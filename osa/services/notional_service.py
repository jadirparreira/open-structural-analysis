"""Materialize inspectable notional actions and ELU combinations.

NBR 14762:2010 8.1 / NBR 8800:2024 4.10.7: 0.3% of declared design
floor gravity contributions, independently in global ±X and ±Y. Gravity
inputs are contributions APPLIED at the level, not accumulated column axial
forces. Cases are added even to wind combinations (no lateral-load waiver).
"""
from dataclasses import replace

from osa.domain import Action, ActionGroup, LoadCombination
from osa.domain.notional_inputs import NotionalPlan, NotionalStation
from osa.domain.stability_inputs import stability_signature

GROUP = '__OSA_NOCIONAIS__'
PREFIX = '__OSA_N0__'


def base_ultimate_combinations(model):
    generated = set(model.notional_plan.combinations) if model.notional_plan else set()
    return {name: combo for name, combo in model.load_combinations.items()
            if combo.limit_state.upper() == 'ELU' and name not in generated}


def generate_notionals(model, stations, *, allow_large_displacement=False):
    """Generate all four signs for every base ELU, atomically after validation."""
    from osa.analysis.pynite.combination_builder import CombinationBuilder

    stability_signature(model)  # reject malformed physical data before any mutation
    _assert_no_dependents(model)
    stations = tuple(stations)
    if not stations or any(not isinstance(station, NotionalStation) for station in stations):
        raise ValueError('Cadastre ao menos um par de nós por nível resistente.')
    if len({station.upper_node for station in stations}) != len(stations):
        raise ValueError('Cada nó superior deve aparecer apenas uma vez no cadastro.')
    base = base_ultimate_combinations(model)
    if not base:
        raise ValueError('Cadastre combinações ELU antes de gerar as forças nocionais.')
    for station in stations:
        if station.upper_node not in model.nodes or station.base_node not in model.nodes:
            raise ValueError('Nós de controle de nível inexistentes.')
        if model.nodes[station.upper_node].z <= model.nodes[station.base_node].z+1e-9:
            raise ValueError('O nó do nível deve estar acima do nó de referência na base no eixo global Z.')
        if set(dict(station.gravity_kn)) != set(base):
            raise ValueError('Informe a contribuição gravitacional de cada nó/nível em todas as combinações ELU base.')
    for combo in base:
        if sum(dict(station.gravity_kn)[combo] for station in stations) <= 0:
            raise ValueError('A soma das forças gravitacionais deve ser positiva em cada ELU base.')
    old = model.notional_plan
    old_actions, old_combos = (set(old.actions), set(old.combinations)) if old else (set(), set())
    if GROUP in model.action_groups and (not old or model.action_groups[GROUP].actions):
        raise ValueError('O nome reservado do grupo nocional já está em uso.')
    factors = {name: CombinationBuilder._factors_for(combo, model) for name, combo in base.items()}
    actions, combinations = {}, {}
    for index, (name, combo) in enumerate(base.items(), 1):
        for direction, sign in (('X', 1), ('X', -1), ('Y', 1), ('Y', -1)):
            suffix = ('+' if sign > 0 else '−')+direction
            case = f'{PREFIX}{index}_{direction}_{sign}'
            generated_name = f'{name} [N{suffix}]'
            if generated_name in model.load_combinations and generated_name not in old_combos:
                raise ValueError('Nome de combinação nocional já utilizado: '+generated_name)
            if any(action.load_case == case and action.name not in old_actions for action in model.actions.values()):
                raise ValueError('Caso de carga nocional reservado já utilizado.')
            for node_index, station in enumerate(stations, 1):
                force = .003*dict(station.gravity_kn)[name]*sign
                action_name = f'{case}::{node_index}'
                if action_name in model.actions and action_name not in old_actions:
                    raise ValueError('Identificação de ação nocional já utilizada.')
                actions[action_name] = Action(action_name, 'node_force_'+direction,
                                              station.upper_node, (force,), case)
            resolved = {**factors[name], case: 1.}
            combinations[generated_name] = LoadCombination(generated_name, tuple(resolved.items()),
                active_actions=tuple(resolved), action_group=GROUP, limit_state='ELU')
    # Creating this object also validates the explicit responsible-engineer
    # choice before making any mutation to the project.
    plan = NotionalPlan(stations, tuple(actions), tuple(combinations), None, allow_large_displacement)
    model.actions = {**{name: item for name, item in model.actions.items() if name not in old_actions}, **actions}
    model.load_combinations = {**{name: item for name, item in model.load_combinations.items() if name not in old_combos}, **combinations}
    model.action_groups[GROUP] = ActionGroup(GROUP, ())
    model.notional_plan = plan
    model._touch()
    model.notional_plan = replace(plan, basis=stability_signature(model))
    # Use the medium-displacement procedure conservatively also for small
    # structures. The large-displacement option is a separate declaration.
    model.update_analysis_options(second_order=True, stiffness_factor=.8)
    model.notional_plan = replace(plan, basis=stability_signature(model))
    return model.notional_plan


def notional_plan_current(model):
    return bool(model.notional_plan and model.notional_plan.basis == stability_signature(model))


def remove_notionals(model):
    """Remove only the cases recorded as generated by this plan."""
    plan = model.notional_plan
    _assert_no_dependents(model)
    if not plan:
        return
    model.actions = {name: action for name, action in model.actions.items() if name not in plan.actions}
    model.load_combinations = {name: combo for name, combo in model.load_combinations.items() if name not in plan.combinations}
    if not any(combo.action_group == GROUP for combo in model.load_combinations.values()):
        model.action_groups.pop(GROUP, None)
    model.notional_plan = None
    model._touch()


def _assert_no_dependents(model):
    from osa.analysis.pynite.combination_builder import CombinationBuilder

    plan = model.notional_plan
    if not plan:
        return
    cases = {model.actions[name].load_case for name in plan.actions if name in model.actions}
    for name, combination in model.load_combinations.items():
        if name not in plan.combinations and cases.intersection(CombinationBuilder._factors_for(combination, model)):
            raise ValueError('A combinação '+name+' depende de casos nocionais gerados. Remova essa dependência antes de substituir/excluir o plano.')
