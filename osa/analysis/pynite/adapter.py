"""Fachada única para a API do PyNite."""

from collections.abc import Callable
from dataclasses import replace
from math import isfinite

import numpy as np

from osa.analysis.contracts import AnalysisRequest
from osa.analysis.vlasov import VLASOV_ALGORITHM
from osa.domain import StructuralModel
from osa.sections.thin_walled import open_sheet
from osa.transcriptions.contracts import require_import_review
from osa.verification.cold_formed_member import FAMILIES as COLD_FAMILIES
from osa.verification.cold_formed_service import (
    coupled_service_stiffness,
    coupled_service_stress,
    needs_warping_solution,
)
from osa.verification.cold_formed_warping_effective import normal_matrix_change

from .combination_builder import CombinationBuilder
from .load_case_builder import LoadCaseBuilder
from .model_builder import ModelBuilder
from .result_mapper import ResultMapper
from .semirigid import install_semirigid_connections
from .tangent_stability import tangent_stability


class PyniteAdapter:
    def __init__(
        self,
        builder: ModelBuilder | None = None,
        mapper: ResultMapper | None = None,
        load_cases: LoadCaseBuilder | None = None,
        combinations: CombinationBuilder | None = None,
    ) -> None:
        self.builder = builder or ModelBuilder()
        self.mapper = mapper or ResultMapper()
        self.load_cases = load_cases or LoadCaseBuilder()
        self.combinations = combinations or CombinationBuilder()

    def run(
        self,
        model: StructuralModel,
        request: AnalysisRequest,
        progress: Callable[[str], None] | None = None,
    ):
        require_import_review(model)
        from osa.services.notional_service import notional_plan_current

        if model.notional_plan and not notional_plan_current(model):
            raise ValueError("As forças nocionais não correspondem ao modelo/cargas atuais. Revise as forças gravitacionais e gere novamente os casos nocionais.")
        request = replace(request,
            second_order=model.second_order_analysis if request.second_order is None else request.second_order,
            warping=model.warping_analysis if request.warping is None else request.warping,
            stiffness_factor=model.ultimate_stiffness_factor if request.stiffness_factor is None else request.stiffness_factor)
        if not request.warping and any(action.kind.startswith('member_bimoment_') for action in model.actions.values()):
            raise ValueError('Ações de bimomento exigem a análise com empenamento (7GL).')
        if request.second_order and model.plates:
            raise ValueError("A análise P-Delta deste motor não inclui a não linearidade geométrica das placas. Use um modelo de barras ou uma análise externa compatível.")
        self._notify(progress, "model")
        target = self.builder.build(model)
        self._notify(progress, "loads")
        load_cases = self.load_cases.apply(target, model)
        self._notify(progress, "combinations")
        available_references = self.combinations.apply(target, model, load_cases)
        install_semirigid_connections(target, model)
        self._notify(progress, "solve")
        self._solve(target, replace(request, second_order=False), model)
        references = request.load_combinations or available_references
        unknown = set(references) - set(available_references)
        if unknown:
            raise ValueError(f"Combinações não encontradas para análise: {', '.join(sorted(unknown))}.")
        self._notify(progress, "results")
        results = []
        for reference in references:
            story_info = None
            tangent_info = None
            combination = model.load_combinations.get(reference)
            factor = request.stiffness_factor if combination is not None and combination.limit_state.upper().startswith('ELU') else 1.
            if request.second_order or factor != 1.:
                self._notify(progress, "second_order" if request.second_order else "reduced_stiffness")
                local_target = self.builder.build(model)
                cases = self.load_cases.apply(local_target, model)
                self.combinations.apply(local_target, model, cases)
                local_target.load_combos = {reference: local_target.load_combos[reference]}
                install_semirigid_connections(local_target, model)
                for member in model.bars.values():
                    section = local_target.sections[f'section::{member.name}']
                    section.A *= factor
                    section.Iy *= factor
                    section.Iz *= factor
                first_drifts = None
                if model.notional_plan and request.second_order and combination.limit_state.upper() == 'ELU':
                    self._solve(local_target, replace(request, second_order=False), model)
                    first_drifts = self._story_drifts(local_target, model.notional_plan.stations, reference)
                self._solve(local_target, request, model)
                tangent_info = getattr(local_target, "_osa_tangent_stability", {}).get(reference)
                if first_drifts is not None:
                    second_drifts = self._story_drifts(local_target, model.notional_plan.stations, reference)
                    story_info = self._story_amplification(first_drifts, second_drifts, factor)
                result = self.mapper.map(local_target, model.revision, reference)
            else:
                result = self.mapper.map(target, model.revision, reference)
            combination = model.load_combinations.get(reference)
            if (combination is not None and combination.limit_state.upper().startswith('ELS')
                    and any(member.section in COLD_FAMILIES for member in model.bars.values())):
                self._notify(progress, "effective_stiffness")
                result = self._service_result(model, result, request)
            output = {name: {**values, 'structural_analysis': {
                'method': 'P-Delta' if request.second_order else 'primeira ordem',
                'EA_EI_factor': factor,
                'imperfections': 'forças nocionais de 0,3% em casos ELU explícitos' if model.notional_plan and combination is not None and combination.limit_state.upper() == 'ELU' else 'somente as imperfeições/cargas nocionais explicitamente modeladas',
                'notional_basis': model.notional_plan.basis if model.notional_plan else None,
                'storey_amplification': story_info,
                'tangent_stability': tangent_info,
                'scope': 'A convergência numérica não comprova a classificação de deslocabilidade nem a suficiência das imperfeições de 8.1.',
            }} for name, values in result.member_results.items()}
            results.append(replace(result, member_results=output))
        return results

    def _service_result(self, model, initial, request):
        """PFF service checks require the actual normal matrix/pole model."""
        if request.warping:
            return self._warping_service_result(model, initial, request)
        output = {name: dict(values) for name, values in initial.member_results.items()}
        for member in model.bars.values():
            if member.section not in COLD_FAMILIES:
                continue
            eccentric = needs_warping_solution(member, output[member.name].get('samples', ()))
            detail = ('Há torção/cortante excêntrico ao centro de torção. ' if eccentric else '')
            detail += ('O ELS dos formados exige a matriz normal completa e o centro de torção coerente. '
                       'Ative a análise dos formados com torção/empenamento e declare os vínculos A/B quando houver modo setorial. '
                       'A cantoneira usa o modelo Cw=0. Os esforços da análise centroidal permanecem disponíveis para inspeção.')
            output[member.name]['service_stiffness'] = {'status': 'not_checked', 'detail': detail}
        return replace(initial, member_results=output)

    def _warping_service_result(self, model, initial, request):
        """Re-solve with normal matrices and physically compatible poles."""
        members = [member for member in model.bars.values() if member.section in COLD_FAMILIES]
        result, applied, masks, poles, data = initial, {}, {}, {}, {}
        try:
            for member in members:
                info = initial.member_results[member.name].get('warping_analysis', {})
                basis = 'rounded-angle-saint-venant-v1' if member.section == 'L Formado' else 'rounded-mean-line-v1'
                if info.get('geometry_basis') != basis or info.get('algorithm') != VLASOV_ALGORITHM:
                    raise ValueError('A análise e o MLE exigem a mesma linha média/polo; processe novamente.')
                applied[member.name] = np.asarray(info['normal_gram_geometric'], dtype=float)
                poles[member.name] = np.asarray(info['normal_origin_section_mm'])+np.asarray(info['shear_center_offset_geometric_mm'])
                masks[member.name] = {piece.plate: ((0., 1.),) for piece in open_sheet(
                    member.section, member.geometry_dict(), mirror=member.section_mirrored).pieces if piece.center is None}
            for iteration in range(1, 101):
                required, next_masks, required_poles = {}, {}, {}
                error = 0.
                for member in members:
                    samples = result.member_results[member.name].get('samples', ())
                    info = coupled_service_stiffness(member, model.materials[member.material], samples,
                                                    retained_limit=masks[member.name], structural_update=True)
                    normal = np.asarray(info['normal_gram'], dtype=float)
                    pole = np.asarray(info['shear_center_section_mm'], dtype=float)
                    required[member.name], required_poles[member.name] = normal, pole
                    next_masks[member.name] = info['retained_intervals']
                    difference = normal_matrix_change(normal, applied[member.name])
                    pole_error = float(np.max(abs(pole-poles[member.name]))/max(member.geometry_dict()['d'], member.geometry_dict()['bf']))
                    info['normal_matrix_relative_error'], info['shear_center_relative_error'] = difference, pole_error
                    error = max(error, difference, pole_error)
                    data[member.name] = info
                if error <= 1e-6:
                    break
                target = self.builder.build(model)
                load_cases = self.load_cases.apply(target, model)
                self.combinations.apply(target, model, load_cases)
                target.load_combos = {initial.load_reference: target.load_combos[initial.load_reference]}
                install_semirigid_connections(target, model)
                target._osa_effective_normal_matrices = {name: matrix.copy() for name, matrix in required.items()}
                target._osa_effective_shear_centers = {name: pole.copy() for name, pole in required_poles.items()}
                self._solve(target, request, model)
                result = self.mapper.map(target, model.revision, initial.load_reference)
                applied, masks, poles = required, next_masks, required_poles
            else:
                raise ValueError('A análise ELS acoplada não convergiu em 100 iterações.')
            output = {name: dict(values) for name, values in result.member_results.items()}
            for member in members:
                info = {**data[member.name], 'status': 'converged', 'iterations': iteration}
                info['required_normal_gram'] = info['normal_gram']
                info['required_retained_intervals'] = info['retained_intervals']
                info['required_shear_center_section_mm'] = info['shear_center_section_mm']
                info['retained_intervals'] = masks[member.name]
                info['normal_gram'] = applied[member.name].tolist()
                info['shear_center_section_mm'] = poles[member.name].tolist()
                info.update(coupled_service_stress(member, model.materials[member.material],
                    result.member_results[member.name]['samples'], applied[member.name], info['retained_intervals'],
                    second_order=request.second_order, shear_center_section_mm=poles[member.name]))
                output[member.name]['service_stiffness'] = info
            return replace(result, member_results=output)
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            output = {name: dict(values) for name, values in initial.member_results.items()}
            for member in members:
                output[member.name]['service_stiffness'] = {'status': 'not_checked', 'detail': str(exc)}
            return replace(initial, member_results=output)

    @staticmethod
    def _story_drifts(target, stations, reference):
        rows = []
        for station in stations:
            for direction in ('X', 'Y'):
                field = 'D'+direction
                upper = getattr(target.nodes[station.upper_node], field)[reference]
                lower = getattr(target.nodes[station.base_node], field)[reference]
                if not isfinite(upper-lower):
                    raise ValueError('Deslocamento de nível não finito; não se classifica a estabilidade.')
                rows.append({'level': station.level, 'upper_node': station.upper_node,
                             'base_node': station.base_node, 'direction': direction,
                             'drift_m': float(upper-lower)})
        return rows

    @staticmethod
    def _story_amplification(first, second, factor):
        rows, ratios = [], []
        indeterminate = False
        for a, b in zip(first, second, strict=True):
            if abs(a['drift_m']) < 1e-10:
                ratio = 1. if abs(b['drift_m']) < 1e-10 else None
            else:
                ratio = abs(b['drift_m']/a['drift_m'])
            indeterminate |= ratio is None
            if ratio is not None:
                ratios.append(ratio)
            rows.append({**a, 'first_order_m': a['drift_m'], 'second_order_m': b['drift_m'], 'ratio': ratio})
        small, medium = (1.13, 1.55) if abs(factor-.8) < 1e-12 else (1.10, 1.40)
        maximum = max(ratios, default=1.)
        classification = ('indeterminada' if indeterminate else 'pequena' if maximum <= small else
                          'média' if maximum <= medium else 'grande')
        return {'maximum_ratio': maximum, 'classification': classification,
                'measure': 'deslocamento relativo à base da estrutura',
                'algorithm': 'osa-story-base-v1',
                'interpretation': 'Os limites 1,13/1,55 seguem a redação de 4.10.4.5 para imperfeições de material, representadas por EA/EI=0,8 em 4.10.7.1.2. A remissão de 4.10.4.5 a 4.10.3.3 no PDF trata de imperfeições geométricas; esta interpretação é explícita.',
                'small_limit': small, 'medium_limit': medium, 'rows': rows,
                'reference': 'ABNT NBR 8800:2024, 4.10.4.2–4.10.4.5'}

    @staticmethod
    def _solve(target, request, model=None):
        if request.warping:
            from .vlasov_solver import solve_vlasov
            solve_vlasov(target, model, second_order=request.second_order)
        elif request.second_order:
            target.analyze_PDelta(max_iter=50)
            target._osa_tangent_stability = {name: tangent_stability(target, name) for name in target.load_combos}
        else:
            target.analyze()

    @staticmethod
    def _notify(progress: Callable[[str], None] | None, stage: str) -> None:
        if progress is not None:
            progress(stage)
