"""Casos de uso expostos pelo MCP local.

Esta camada mantém o protocolo MCP separado da janela Qt. Ela reutiliza os
serviços e a sessão de comandos do aplicativo para que uma chamada de IA
altere o mesmo modelo que está aberto na interface.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from math import isfinite
from typing import Any

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.data import CatalogLoader
from osa.domain import (
    ActionDefinition,
    ActionGroup,
    LoadCombination,
    ReferenceAxis,
    StructuralModel,
)
from osa.services import ActionService, ModelService, ResultService
from osa.services.section_property_service import SectionPropertyService

ANALYSIS_DIAGRAMS = (
    "Normal", "Cortante Y", "Cortante Z", "Torsor", "Fletor Y", "Fletor Z",
    "Reações de apoio", "Deformação X", "Deformação Y", "Deformação Z", "Deformação XYZ",
)
ANALYSIS_LIMIT_STATES = ("CAR", "ELU", "ELS")
APPLICATION_SESSIONS = ("Geometria", "Ações", "Análise")


class McpApplication:
    """Fachada thread-safe no nível da aplicação para o servidor MCP."""

    def __init__(
        self,
        model: StructuralModel,
        model_service: ModelService,
        *,
        action_service: ActionService | None = None,
        analysis_engine=None,
        on_model_changed: Callable[[], None] | None = None,
        on_view_changed: Callable[[str, bool], None] | None = None,
        get_view_state: Callable[[], dict[str, bool]] | None = None,
        on_active_action_changed: Callable[[str], None] | None = None,
        get_active_action: Callable[[], str | None] | None = None,
        on_analysis_view_changed: Callable[[str, str], None] | None = None,
        get_analysis_view_state: Callable[[], dict[str, Any]] | None = None,
        on_analysis_diagrams_changed: Callable[[bool], None] | None = None,
        on_session_changed: Callable[[str], None] | None = None,
        get_session: Callable[[], str | None] | None = None,
    ) -> None:
        self.model = model
        self.model_service = model_service
        self.action_service = action_service or ActionService(model)
        self._analysis_engine = analysis_engine or PyniteAdapter()
        self._on_model_changed = on_model_changed
        self._on_view_changed = on_view_changed
        self._get_view_state = get_view_state
        self._on_active_action_changed = on_active_action_changed
        self._get_active_action = get_active_action
        self._on_analysis_view_changed = on_analysis_view_changed
        self._get_analysis_view_state = get_analysis_view_state
        self._on_analysis_diagrams_changed = on_analysis_diagrams_changed
        self._on_session_changed = on_session_changed
        self._get_session = get_session
        self._session = "Geometria"
        self._analysis_view = {
            "selected_combination": None,
            "selected_diagram": "Normal",
            "result_diagrams_visible": True,
        }
        self._result_service = ResultService(model)
        self._section_properties = SectionPropertyService()
        self._catalog = CatalogLoader()

    def get_session_state(self) -> dict[str, Any]:
        """Retorna a sessão visual atualmente aberta no OpenSA."""
        active_session = self._get_session() if self._get_session is not None else self._session
        return {
            "active_session": active_session,
            "available_sessions": list(APPLICATION_SESSIONS),
        }

    def set_session(self, session: str) -> dict[str, Any]:
        """Abre uma sessão visual da aplicação."""
        normalized = str(session).strip()
        if normalized not in APPLICATION_SESSIONS:
            raise ValueError(
                "Sessão desconhecida. Use Geometria, Ações ou Análise."
            )
        if self._on_session_changed is None:
            raise ValueError("A navegação visual do OpenSA não está disponível.")
        self._session = normalized
        self._on_session_changed(normalized)
        state = self.get_session_state()
        state["active_session"] = normalized
        return state

    def get_project_summary(self) -> dict[str, Any]:
        """Retorna um resumo pequeno e estável do modelo aberto."""
        return {
            "revision": self.model.revision,
            "nodes": len(self.model.nodes),
            "members": len(self.model.bars),
            "rigid_bars": len(self.model.rigid_bars),
            "actions": len(self.model.actions),
            "load_cases": len(self.model.load_cases),
            "load_combinations": len(self.model.load_combinations),
            "analysis_results": len(self.model.analysis_results),
            "materials": len(self.model.materials),
        }

    def list_materials(self) -> dict[str, Any]:
        """Retorna os materiais disponíveis no catálogo do projeto."""
        return {
            "materials": [
                {
                    "name": name,
                    "type": self.model.material_types.get(name, "Indefinido"),
                    "elastic_modulus_kn_m2": values[0],
                    "shear_modulus_kn_m2": values[1],
                    "poisson_ratio": values[2],
                    "unit_weight_kn_m3": values[3],
                }
                for name, values in self.model.materials.items()
            ],
        }

    def list_sections(self, material: str | None = None) -> dict[str, Any]:
        """Retorna famílias e perfis compatíveis com um material."""
        material_type = None
        if material is not None:
            material_type = self.model.material_types.get(material, material)
            if material_type not in self.model.sections:
                raise ValueError(f"Material ou tipo de material '{material}' não encontrado.")
        material_types = (material_type,) if material_type else tuple(self.model.sections)
        return {
            "sections": [
                {
                    "material_type": material_kind,
                    "families": [
                        {
                            "name": family,
                            "profiles": list(self._catalog.profiles(material_kind, family)),
                        }
                        for family in self.model.sections.get(material_kind, ())
                    ],
                }
                for material_kind in material_types
            ],
        }

    def list_action_groups(self) -> dict[str, Any]:
        """Retorna grupos de ações e suas ações disponíveis."""
        groups = []
        templates = self.action_service.templates()
        for name in self.action_service.action_group_names():
            group = self.model.action_groups.get(name) or templates[name]
            groups.append(self._action_group_payload(group, name in self.model.action_groups))
        return {
            "selected_group": self.model.selected_action_group,
            "groups": groups,
        }

    def list_actions(self, load_case: str | None = None, target: str | None = None) -> dict[str, Any]:
        """Retorna carregamentos aplicados, opcionalmente filtrados."""
        actions = [
            self._action_payload(action)
            for action in self.model.actions.values()
            if (load_case is None or action.load_case == load_case)
            and (target is None or action.target == target)
        ]
        return {
            "revision": self.model.revision,
            "active_action": self._get_active_action() if self._get_active_action else None,
            "actions": actions,
        }

    def get_action_state(self) -> dict[str, Any]:
        """Retorna o grupo e a ação atualmente selecionados na interface."""
        return {
            "selected_group": self.model.selected_action_group,
            "active_action": self._get_active_action() if self._get_active_action else None,
            "available_actions": [
                action.name for action in (self.action_service.selected_group() or ActionGroup("", ())).actions
            ],
        }

    def set_action_group(self, group_name: str) -> dict[str, Any]:
        """Seleciona um grupo de ações existente ou um modelo padrão."""
        if group_name not in self.action_service.action_group_names():
            raise ValueError(f"Grupo de ações '{group_name}' não encontrado.")
        self.action_service.select_action_group(group_name)
        self._notify_model_changed()
        return self.get_action_state()

    def set_active_action(self, action_name: str) -> dict[str, Any]:
        """Seleciona a ação ativa na interface sem alterar os carregamentos."""
        group = self.action_service.selected_group()
        if group is None or action_name not in {action.name for action in group.actions}:
            raise ValueError(f"Ação '{action_name}' não está disponível no grupo selecionado.")
        if self._on_active_action_changed is None:
            raise ValueError("A seleção visual da ação não está disponível.")
        self._on_active_action_changed(action_name)
        state = self.get_action_state()
        state["active_action"] = action_name
        return state

    def create_action_group(
        self,
        name: str,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Cria um grupo personalizado de ações."""
        group = self._action_group_from_payload(name, actions)
        created = self.action_service.add_action_group(group)
        self._notify_model_changed()
        return {"group": self._action_group_payload(created, True)}

    def update_action_group(
        self,
        old_name: str,
        name: str,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Atualiza um grupo personalizado de ações."""
        if old_name not in self.model.action_groups:
            raise ValueError(f"Grupo personalizado '{old_name}' não encontrado.")
        group = self._action_group_from_payload(name, actions)
        updated = self.action_service.update_action_group(old_name, group)
        self._notify_model_changed()
        return {"group": self._action_group_payload(updated, True)}

    def delete_action_group(self, name: str) -> dict[str, Any]:
        """Exclui um grupo personalizado de ações."""
        if name not in self.model.action_groups:
            raise ValueError("Somente grupos personalizados podem ser excluídos.")
        self.action_service.remove_action_group(name)
        self._notify_model_changed()
        return {"deleted_group": name, "selected_group": self.model.selected_action_group}

    def list_load_combinations(self) -> dict[str, Any]:
        """Retorna as combinações configuradas no projeto."""
        return {
            "revision": self.model.revision,
            "selected_group": self.model.selected_action_group,
            "combinations": [
                self._load_combination_payload(combination)
                for combination in self.model.load_combinations.values()
            ],
        }

    def create_load_combination(
        self,
        name: str,
        factors: dict[str, float] | None = None,
        factors_2: dict[str, float] | None = None,
        factors_3: dict[str, float] | None = None,
        active_actions: list[str] | None = None,
        action_group: str | None = None,
        limit_state: str = "CAR",
    ) -> dict[str, Any]:
        """Cria uma combinação de carregamento."""
        combination = self._combination_from_values(
            name, factors, factors_2, factors_3, active_actions, action_group, limit_state,
        )
        if combination.name in self.model.load_combinations:
            raise ValueError(f"Já existe uma combinação chamada '{combination.name}'.")
        self.action_service.set_combination(combination)
        self._notify_model_changed()
        return {"revision": self.model.revision, "combination": self._load_combination_payload(combination)}

    def update_load_combination(
        self,
        old_name: str,
        name: str | None = None,
        factors: dict[str, float] | None = None,
        factors_2: dict[str, float] | None = None,
        factors_3: dict[str, float] | None = None,
        active_actions: list[str] | None = None,
        action_group: str | None = None,
        limit_state: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza uma combinação preservando os campos não informados."""
        current = self.model.load_combinations.get(old_name)
        if current is None:
            raise ValueError(f"Combinação '{old_name}' não encontrada.")
        updated = self._combination_from_values(
            current.name if name is None else name,
            self._factor_dict(current.factors) if factors is None else factors,
            self._factor_dict(current.factors_2) if factors_2 is None else factors_2,
            self._factor_dict(current.factors_3) if factors_3 is None else factors_3,
            list(current.active_actions) if active_actions is None and current.active_actions is not None else active_actions,
            current.action_group if action_group is None else action_group,
            current.limit_state if limit_state is None else limit_state,
        )
        if updated.name != old_name and updated.name in self.model.load_combinations:
            raise ValueError(f"Já existe uma combinação chamada '{updated.name}'.")
        del self.model.load_combinations[old_name]
        self.action_service.set_combination(updated)
        self._notify_model_changed()
        return {"revision": self.model.revision, "combination": self._load_combination_payload(updated)}

    def delete_load_combination(self, name: str) -> dict[str, Any]:
        """Exclui uma combinação de carregamento."""
        if name not in self.model.load_combinations:
            raise ValueError(f"Combinação '{name}' não encontrada.")
        self.action_service.remove_combination(name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_combination": name}

    def get_analysis_state(self) -> dict[str, Any]:
        """Retorna o estado da análise e da visualização de resultados."""
        current_results = self._result_service.current()
        view = self._analysis_view_state()
        return {
            "revision": self.model.revision,
            "results_revision": current_results[0].model_revision if current_results else None,
            "ready": bool(current_results),
            "available_combinations": list(self.model.load_combinations),
            "result_combinations": [result.load_reference for result in current_results],
            "selected_combination": view["selected_combination"],
            "selected_diagram": view["selected_diagram"],
            "result_diagrams_visible": view["result_diagrams_visible"],
        }

    def run_analysis(self, combinations: list[str] | None = None) -> dict[str, Any]:
        """Executa a análise sobre uma cópia do modelo e publica os resultados."""
        orphaned_actions = self.model.remove_orphaned_actions()
        if orphaned_actions:
            self._notify_model_changed()
        if self.action_service.ensure_default_combinations():
            self._notify_model_changed()
        requested = tuple(combinations or ())
        unknown = set(requested) - set(self.model.load_combinations)
        if unknown:
            raise ValueError(
                "Combinações não encontradas para análise: " + ", ".join(sorted(unknown)) + "."
            )
        source_revision = self.model.revision
        snapshot = copy.deepcopy(self.model)
        results = self._analysis_engine.run(snapshot, AnalysisRequest(requested))
        if self.model.revision != source_revision:
            raise ValueError("O modelo foi alterado durante a análise. Execute o processamento novamente.")
        self.model.analysis_results = list(results)
        self._notify_model_changed()
        self._analysis_view["selected_combination"] = results[0].load_reference if results else None
        self._analysis_view["selected_diagram"] = "Normal"
        return {
            "revision": self.model.revision,
            "status": "completed",
            "processed_combinations": [result.load_reference for result in results],
            "result_count": len(results),
            "orphaned_actions_removed": list(orphaned_actions),
        }

    def list_analysis_results(self) -> dict[str, Any]:
        """Lista os resultados válidos da análise atual."""
        results = self._result_service.current()
        return {
            "revision": self.model.revision,
            "results": [
                {
                    "combination": result.load_reference,
                    "model_revision": result.model_revision,
                    "nodes": len(result.node_results),
                    "members": len(result.member_results),
                }
                for result in results
            ],
        }

    def get_node_analysis_results(
        self,
        combination: str,
        node_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retorna deslocamentos, rotações e reações dos nós."""
        result = self._analysis_result(combination)
        names = tuple(node_names) if node_names is not None else tuple(result.node_results)
        unknown = set(names) - set(result.node_results)
        if unknown:
            raise ValueError("Nós sem resultado: " + ", ".join(sorted(unknown)) + ".")
        return {
            "revision": self.model.revision,
            "combination": combination,
            "nodes": [{"name": name, **result.node_results[name]} for name in names],
        }

    def get_member_analysis_results(
        self,
        combination: str,
        member_names: list[str] | None = None,
        include_samples: bool = False,
    ) -> dict[str, Any]:
        """Retorna esforços e deslocamentos dos membros."""
        result = self._analysis_result(combination)
        names = tuple(member_names) if member_names is not None else tuple(result.member_results)
        unknown = set(names) - set(result.member_results)
        if unknown:
            raise ValueError("Membros sem resultado: " + ", ".join(sorted(unknown)) + ".")
        members = []
        for name in names:
            values = dict(result.member_results[name])
            if not include_samples:
                values.pop("samples", None)
            members.append({"name": name, **values})
        return {"revision": self.model.revision, "combination": combination, "members": members}

    def get_support_reactions(
        self,
        combination: str,
        node_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retorna as reações nos nós apoiados."""
        result = self._analysis_result(combination)
        names = tuple(node_names) if node_names is not None else tuple(self.model.nodes)
        unknown = set(names) - set(result.node_results)
        if unknown:
            raise ValueError("Nós sem resultado: " + ", ".join(sorted(unknown)) + ".")
        reaction_keys = ("RXN_FX", "RXN_FY", "RXN_FZ", "RXN_MX", "RXN_MY", "RXN_MZ")
        reactions = []
        for name in names:
            node = self.model.nodes[name]
            if not any(node.supports) and not any(float(value) > 0.0 for value in node.support_stiffness):
                continue
            values = result.node_results[name]
            reactions.append({"name": name, **{key: values.get(key, 0.0) for key in reaction_keys}})
        return {"revision": self.model.revision, "combination": combination, "reactions": reactions}

    def set_analysis_view(
        self,
        combination: str | None = None,
        diagram: str | None = None,
    ) -> dict[str, Any]:
        """Seleciona a combinação e o tipo de diagrama exibido na interface."""
        current_results = self._result_service.current()
        selected_combination = combination
        if (
            selected_combination is not None
            and selected_combination not in {result.load_reference for result in current_results}
        ):
            raise ValueError(f"Não há resultado válido para a combinação '{selected_combination}'.")
        selected_diagram = self._analysis_view["selected_diagram"] if diagram is None else diagram
        if selected_diagram not in ANALYSIS_DIAGRAMS:
            raise ValueError(f"Diagrama desconhecido: '{selected_diagram}'.")
        self._analysis_view.update({
            "selected_combination": selected_combination,
            "selected_diagram": selected_diagram,
        })
        if self._on_analysis_view_changed is None:
            raise ValueError("A visualização da análise não está disponível.")
        self._on_analysis_view_changed(selected_combination or "", selected_diagram)
        state = self.get_analysis_state()
        state["selected_combination"] = selected_combination
        state["selected_diagram"] = selected_diagram
        return state

    def set_analysis_diagrams_visible(self, visible: bool) -> dict[str, Any]:
        """Mostra ou oculta os diagramas de resultados na cena."""
        if not isinstance(visible, bool):
            raise TypeError("visible deve ser booleano.")
        if self._on_analysis_diagrams_changed is None:
            raise ValueError("A visualização da análise não está disponível.")
        self._analysis_view["result_diagrams_visible"] = visible
        self._on_analysis_diagrams_changed(visible)
        state = self.get_analysis_state()
        state["result_diagrams_visible"] = visible
        return state

    def _analysis_result(self, combination: str):
        result = next(
            (item for item in self._result_service.current() if item.load_reference == combination),
            None,
        )
        if result is None:
            raise ValueError(f"Não há resultado válido para a combinação '{combination}'.")
        return result

    def add_node_force(self, node_name: str, direction: str, value: float, load_case: str) -> dict[str, Any]:
        self._validate_load_target(node_name, "node", load_case)
        self._validate_direction(direction)
        self._ensure_load_case_accepts_loads(load_case)
        action = self.action_service.add_node_force(node_name, direction, float(value), load_case)
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action) if action else None}

    def add_node_moment(self, node_name: str, direction: str, value: float, load_case: str) -> dict[str, Any]:
        self._validate_load_target(node_name, "node", load_case)
        self._validate_direction(direction)
        self._ensure_load_case_accepts_loads(load_case)
        action = self.action_service.add_node_moment(node_name, direction, float(value), load_case)
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action) if action else None}

    def add_member_distributed_load(
        self,
        member_name: str,
        direction: str,
        initial: float,
        final: float,
        load_case: str,
        reference: str = "global",
    ) -> dict[str, Any]:
        self._validate_load_target(member_name, "bar", load_case)
        self._validate_direction(direction)
        self._ensure_load_case_accepts_loads(load_case)
        action = self.action_service.add_member_distributed_force(
            member_name, direction, float(initial), float(final), load_case, reference,
        )
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action)}

    def add_member_moment(
        self,
        member_name: str,
        direction: str,
        value: float,
        load_case: str,
    ) -> dict[str, Any]:
        self._validate_load_target(member_name, "bar", load_case)
        self._validate_direction(direction)
        self._ensure_load_case_accepts_loads(load_case)
        action = self.action_service.add_member_moment(member_name, direction, float(value), load_case)
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action)}

    def update_applied_load(
        self,
        action_name: str,
        *,
        target: str | None = None,
        direction: str | None = None,
        initial: float | None = None,
        final: float | None = None,
        value: float | None = None,
        load_case: str | None = None,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza uma carga aplicada preservando o nome automático da ação."""
        current = self.model.actions.get(action_name)
        if current is None:
            raise ValueError(f"Ação '{action_name}' não encontrada.")
        if current.kind == "member_distributed_force_selfweight_Z":
            raise ValueError("O peso próprio deve ser alterado por apply_selfweight ou remove_selfweight.")
        if all(value is None for value in (target, direction, initial, final, value, load_case, reference)):
            raise ValueError("Informe pelo menos um parâmetro para atualizar a ação.")

        updated_target = current.target if target is None else str(target)
        updated_load_case = current.load_case if load_case is None else str(load_case)
        self._validate_load_case(updated_load_case)
        self._ensure_load_case_accepts_loads(updated_load_case)

        kind = current.kind
        if kind.startswith("node_force_"):
            target_kind = "node"
            prefix = "node_force_"
        elif kind.startswith("node_moment_"):
            target_kind = "node"
            prefix = "node_moment_"
        elif kind.startswith("member_moment_"):
            target_kind = "bar"
            prefix = "member_moment_"
        elif kind.startswith("member_distributed_force_"):
            target_kind = "bar"
            prefix = "member_distributed_force_"
        else:
            raise ValueError(f"O tipo de ação '{kind}' não pode ser atualizado pelo MCP.")
        self._validate_load_target(updated_target, target_kind, updated_load_case)

        if kind.startswith("member_distributed_force_"):
            current_reference = "local" if kind.startswith("member_distributed_force_local_") else "global"
            updated_reference = current_reference if reference is None else reference.casefold()
            if updated_reference not in {"global", "local"}:
                raise ValueError("O sistema de direção deve ser Global ou Local.")
            current_direction = kind.rsplit("_", 1)[-1]
            updated_direction = current_direction if direction is None else direction.upper()
            self._validate_direction(updated_direction)
            if value is not None:
                raise ValueError("Cargas distribuídas devem usar initial e final, não value.")
            if (initial is None) != (final is None):
                raise ValueError("Informe initial e final juntos para atualizar uma carga distribuída.")
            components = current.components if initial is None else (
                self._finite_load_value(initial, "initial"),
                self._finite_load_value(final, "final"),
            )
            kind = f"{prefix}{'local_' if updated_reference == 'local' else ''}{updated_direction}"
        else:
            if initial is not None or final is not None or reference is not None:
                raise ValueError("Esta ação concentrada deve ser atualizada usando apenas value.")
            current_direction = kind.rsplit("_", 1)[-1]
            updated_direction = current_direction if direction is None else direction.upper()
            self._validate_direction(updated_direction)
            updated_value = current.components[0] if value is None else self._finite_load_value(value, "value")
            components = (updated_value,)
            kind = f"{prefix}{updated_direction}"

        action = self.action_service.update_action(
            action_name,
            kind=kind,
            target=updated_target,
            components=tuple(components),
            load_case=updated_load_case,
        )
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action)}

    def apply_selfweight(
        self,
        load_case: str,
        materials: list[str] | None = None,
    ) -> dict[str, Any]:
        """Substitui as cargas do caso pelo peso próprio dos materiais selecionados."""
        self._validate_load_case(load_case)
        selected_materials = tuple(materials) if materials is not None else tuple(self.model.materials)
        unknown = next((material for material in selected_materials if material not in self.model.materials), None)
        if unknown is not None:
            raise ValueError(f"Material '{unknown}' não encontrado.")
        weights: list[tuple[str, float]] = []
        for material in selected_materials:
            weights.extend(self.model_service.member_selfweights(material))
        if not weights:
            raise ValueError("Não há membros com propriedades para aplicar o peso próprio.")
        actions = self.action_service.replace_action_with_selfweight(load_case, tuple(weights))
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "load_case": load_case,
            "actions": [self._action_payload(action) for action in actions],
        }

    def remove_selfweight(self, load_case: str) -> dict[str, Any]:
        self._validate_load_case(load_case)
        self.action_service.remove_selfweight(load_case)
        self._notify_model_changed()
        return {"revision": self.model.revision, "load_case": load_case, "selfweight": False}

    def delete_action(self, action_name: str) -> dict[str, Any]:
        action = self.action_service.remove_action(action_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_action": self._action_payload(action)}

    def clear_actions(
        self,
        *,
        load_case: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        if load_case is None and target is None:
            raise ValueError("Informe load_case, target ou ambos para limpar ações.")
        if load_case is not None:
            self._validate_load_case(load_case)
        names = self.action_service.remove_actions(target=target, load_case=load_case)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_actions": list(names)}

    def _validate_load_case(self, load_case: str) -> None:
        group = self.action_service.selected_group()
        if group is None or load_case not in {action.name for action in group.actions}:
            raise ValueError(f"Ação '{load_case}' não está disponível no grupo selecionado.")

    def _validate_load_target(self, name: str, kind: str, load_case: str) -> None:
        self._validate_load_case(load_case)
        if kind == "node" and name not in self.model.nodes:
            raise ValueError(f"Nó '{name}' não encontrado.")
        if kind == "bar" and name not in self.model.bars:
            raise ValueError(f"Membro '{name}' não encontrado.")

    def _ensure_load_case_accepts_loads(self, load_case: str) -> None:
        if self.action_service.has_selfweight(load_case):
            raise ValueError(
                f"A ação '{load_case}' está restrita ao peso próprio; remova-o antes de lançar outras cargas."
            )

    @staticmethod
    def _finite_load_value(value: float, parameter: str) -> float:
        result = float(value)
        if not isfinite(result):
            raise ValueError(f"O parâmetro '{parameter}' deve ser um número finito.")
        return result

    @staticmethod
    def _validate_direction(direction: str) -> None:
        if direction.upper() not in {"X", "Y", "Z"}:
            raise ValueError("A direção deve ser X, Y ou Z.")

    @staticmethod
    def _action_payload(action) -> dict[str, Any]:
        return {
            "name": action.name,
            "kind": action.kind,
            "target": action.target,
            "components": list(action.components),
            "load_case": action.load_case,
        }

    @staticmethod
    def _factor_dict(factors: tuple[tuple[str, float], ...]) -> dict[str, float]:
        return {name: value for name, value in factors}

    @classmethod
    def _load_combination_payload(cls, combination: LoadCombination) -> dict[str, Any]:
        return {
            "name": combination.name,
            "factors": cls._factor_dict(combination.factors),
            "factors_2": cls._factor_dict(combination.factors_2),
            "factors_3": cls._factor_dict(combination.factors_3),
            "active_actions": None if combination.active_actions is None else list(combination.active_actions),
            "action_group": combination.action_group,
            "limit_state": combination.limit_state,
        }

    def _combination_from_values(
        self,
        name: str,
        factors: dict[str, float] | None,
        factors_2: dict[str, float] | None,
        factors_3: dict[str, float] | None,
        active_actions: list[str] | None,
        action_group: str | None,
        limit_state: str,
    ) -> LoadCombination:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("Informe o nome da combinação.")
        if limit_state not in ANALYSIS_LIMIT_STATES:
            raise ValueError("O estado limite deve ser CAR, ELU ou ELS.")
        selected_group = action_group or self.model.selected_action_group
        if action_group is not None and action_group not in self.action_service.action_group_names():
            raise ValueError(f"Grupo de ações '{action_group}' não encontrado.")
        group = self.model.action_groups.get(selected_group)
        if group is None:
            group = self.action_service.templates().get(selected_group)
        abbreviations = tuple(action.abbreviation for action in group.actions) if group else ()
        normalized_factors = self._normalize_factors(factors, abbreviations)
        normalized_factors_2 = self._normalize_factors(factors_2, abbreviations)
        normalized_factors_3 = self._normalize_factors(factors_3, abbreviations)
        normalized_active = None if active_actions is None else tuple(str(item) for item in active_actions)
        unknown_active = set(normalized_active or ()) - set(abbreviations)
        if unknown_active:
            raise ValueError("Ações ativas desconhecidas: " + ", ".join(sorted(unknown_active)) + ".")
        return LoadCombination(
            normalized_name,
            tuple(normalized_factors.items()),
            tuple(normalized_factors_2.items()),
            tuple(normalized_factors_3.items()),
            normalized_active,
            selected_group if selected_group else None,
            limit_state,
        )

    @staticmethod
    def _normalize_factors(
        factors: dict[str, float] | None,
        abbreviations: tuple[str, ...],
    ) -> dict[str, float]:
        values = {abbreviation: 1.0 for abbreviation in abbreviations} if factors is None else dict(factors)
        unknown = set(values) - set(abbreviations)
        if unknown and abbreviations:
            raise ValueError("Siglas de ação desconhecidas: " + ", ".join(sorted(unknown)) + ".")
        normalized = {}
        for name, value in values.items():
            numeric = float(value)
            if not isfinite(numeric):
                raise ValueError(f"O fator '{name}' deve ser um número finito.")
            normalized[str(name)] = numeric
        return normalized

    @staticmethod
    def _action_group_payload(group: ActionGroup, custom: bool) -> dict[str, Any]:
        return {
            "name": group.name,
            "custom": custom,
            "actions": [
                {"name": action.name, "abbreviation": action.abbreviation}
                for action in group.actions
            ],
        }

    @staticmethod
    def _action_group_from_payload(
        name: str,
        actions: list[dict[str, str]],
    ) -> ActionGroup:
        definitions = []
        for item in actions:
            if not isinstance(item, dict) or "name" not in item or "abbreviation" not in item:
                raise ValueError("Cada ação deve possuir name e abbreviation.")
            definitions.append(ActionDefinition(str(item["name"]), str(item["abbreviation"])))
        return ActionGroup(name, tuple(definitions))

    def list_nodes(self) -> dict[str, Any]:
        """Retorna os nós do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "nodes": [
                {
                    "name": node.name,
                    "x": node.x,
                    "y": node.y,
                    "z": node.z,
                    "supports": list(node.supports),
                    "support_stiffness": list(node.support_stiffness),
                }
                for node in self.model.nodes.values()
            ],
        }

    def list_members(self) -> dict[str, Any]:
        """Retorna os membros do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "members": [
                {
                    "name": member.name,
                    "start_node": member.start_node,
                    "end_node": member.end_node,
                    "material": member.material,
                    "section": member.section,
                    "profile": member.profile,
                    "geometry": member.geometry_dict(),
                }
                for member in self.model.bars.values()
            ],
        }

    def list_rigid_bars(self) -> dict[str, Any]:
        """Retorna as barras rígidas do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "rigid_bars": [
                {
                    "name": rigid.name,
                    "start_node": rigid.start_node,
                    "end_node": rigid.end_node,
                }
                for rigid in self.model.rigid_bars.values()
            ],
        }

    def get_view_options(self) -> dict[str, Any]:
        """Retorna as opções visuais da cena conectada ao MCP."""
        if self._get_view_state is None:
            raise ValueError("A cena visual do OpenSA não está disponível.")
        return {"view": self._get_view_state()}

    def set_view_options(self, options: dict[str, bool]) -> dict[str, Any]:
        """Atualiza opções visuais sem alterar o modelo estrutural."""
        available = {
            "grid_visible",
            "reference_axes_visible",
            "node_labels_visible",
            "member_labels_visible",
            "local_axes_visible",
            "nodes_visible",
            "solid_members_visible",
            "member_releases_visible",
            "semirigid_links_visible",
            "node_supports_visible",
            "snap_enabled",
            "node_forces_visible",
            "node_moments_visible",
            "member_forces_visible",
            "member_moments_visible",
        }
        unknown = set(options) - available
        if unknown:
            raise ValueError(f"Opção visual desconhecida: {sorted(unknown)[0]}")
        if not options:
            raise ValueError("Informe pelo menos uma opção visual.")
        if any(not isinstance(value, bool) for value in options.values()):
            raise ValueError("As opções visuais devem ser booleanas.")
        if self._on_view_changed is None or self._get_view_state is None:
            raise ValueError("A cena visual do OpenSA não está disponível.")
        view = dict(self._get_view_state())
        for option, visible in options.items():
            self._on_view_changed(option, visible)
            view[option] = visible
        return {"view": view}

    def list_reference_axes(self) -> dict[str, Any]:
        """Retorna os eixos de referência configurados no projeto."""
        return {
            "revision": self.model.revision,
            "axes": self._axes_payload(),
        }

    def set_reference_axes(self, axes: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """Substitui os eixos de referência por uma configuração serializável."""
        directions = {"X", "Y", "Z"}
        unknown = set(axes) - directions
        if unknown:
            raise ValueError(
                "As direções dos eixos devem ser somente X, Y ou Z."
            )
        normalized: dict[str, tuple[ReferenceAxis, ...]] = {}
        for direction in ("X", "Y", "Z"):
            entries: list[ReferenceAxis] = []
            for item in axes.get(direction, []):
                if not isinstance(item, dict) or "label" not in item or "value" not in item:
                    raise ValueError("Cada eixo deve possuir 'label' e 'value'.")
                try:
                    entries.append(ReferenceAxis(str(item["label"]), float(item["value"])))
                except (TypeError, ValueError) as error:
                    raise ValueError("O valor de cada eixo deve ser numérico.") from error
            normalized[direction] = tuple(entries)
        self.model_service.set_reference_axes(normalized)
        self._notify_model_changed()
        return {"revision": self.model.revision, "axes": self._axes_payload()}

    def create_node(self, x: float, y: float, z: float) -> dict[str, Any]:
        """Cria um nó usando a identidade sequencial padrão do OpenSA."""
        node = self.model_service.create_node(x, y, z)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "node": self._node_payload(node),
        }

    def set_node_supports(
        self,
        node_name: str,
        dx: bool,
        dy: bool,
        dz: bool,
        rx: bool = False,
        ry: bool = False,
        rz: bool = False,
    ) -> dict[str, Any]:
        """Aplica restrições aos seis graus de liberdade de um nó."""
        node = self.model_service.update_supports(node_name, (dx, dy, dz, rx, ry, rz))
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "node": self._node_payload(node),
        }

    def update_node_properties(
        self,
        node_name: str,
        *,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        supports: list[bool] | None = None,
        support_stiffness: list[float] | None = None,
    ) -> dict[str, Any]:
        """Atualiza propriedades de um nó sem permitir alterar sua identidade."""
        node = self.model.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Nó '{node_name}' não encontrado.")
        coordinates = (x, y, z)
        if any(value is not None for value in coordinates) and not all(
            value is not None for value in coordinates
        ):
            raise ValueError("Informe x, y e z juntos para alterar as coordenadas.")
        normalized_coordinates: tuple[float, float, float] | None = None
        if all(value is not None for value in coordinates):
            try:
                normalized_coordinates = tuple(float(value) for value in coordinates)  # type: ignore[arg-type]
            except (TypeError, ValueError) as error:
                raise ValueError("As coordenadas devem ser numéricas.") from error
            if any(not isfinite(value) for value in normalized_coordinates):
                raise ValueError("As coordenadas devem ser números finitos.")

        normalized_supports = self._normalize_bool_values(supports, 6, "apoios")
        normalized_stiffness = self._normalize_nonnegative_values(
            support_stiffness, 6, "rigidezes de mola",
        )
        if (
            normalized_coordinates is None
            and normalized_supports is None
            and normalized_stiffness is None
        ):
            raise ValueError("Informe pelo menos uma propriedade do nó para alterar.")

        if normalized_coordinates is not None:
            node = self.model_service.update_node(node_name, *normalized_coordinates)
        if normalized_supports is not None:
            node = self.model_service.update_supports(node_name, normalized_supports)
        if normalized_stiffness is not None:
            node = self.model_service.update_support_stiffness(node_name, normalized_stiffness)
        self._notify_model_changed()
        return {"revision": self.model.revision, "node": self._node_payload(node)}

    def create_member(
        self,
        start_node: str,
        end_node: str,
        material: str | None = None,
        section: str | None = None,
        geometry: dict[str, float] | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Cria um membro entre dois nós existentes."""
        if any(value is not None for value in (material, section, geometry, profile)):
            if material is None or section is None or geometry is None:
                raise ValueError("Material, seção e geometria devem ser informados juntos.")
            self._validate_member_properties(material, section, geometry)
        member = self.model_service.create_member(start_node, end_node)
        if material is not None and section is not None and geometry is not None:
            member = self._apply_member_properties(member.name, material, section, geometry, profile)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def set_member_rectangular_section(
        self,
        member_names: list[str],
        width_mm: float,
        height_mm: float,
        material: str = "Concreto Estrutural",
    ) -> dict[str, Any]:
        """Aplica uma seção retangular com dimensões explícitas em milímetros."""
        return self.set_member_properties(
            member_names,
            material,
            "Retangular",
            {"b": width_mm, "h": height_mm},
        )

    def delete_node(self, node_name: str) -> dict[str, Any]:
        """Exclui um nó, respeitando as regras de integridade do modelo."""
        if node_name not in self.model.nodes:
            raise ValueError(f"Nó '{node_name}' não encontrado.")
        self.model_service.remove_node(node_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_node": node_name}

    def delete_member(self, member_name: str) -> dict[str, Any]:
        """Exclui um membro e suas ações associadas."""
        if member_name not in self.model.bars:
            raise ValueError(f"Membro '{member_name}' não encontrado.")
        self.model_service.remove_member(member_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_member": member_name}

    def delete_elements(
        self,
        *,
        nodes: list[str] | None = None,
        members: list[str] | None = None,
        rigid_bars: list[str] | None = None,
        cascade: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Exclui vários elementos estruturais em uma operação validada."""
        result = self.model_service.remove_elements(
            node_names=tuple(nodes or ()),
            member_names=tuple(members or ()),
            rigid_bar_names=tuple(rigid_bars or ()),
            cascade=cascade,
            dry_run=dry_run,
        )
        if result["status"] == "deleted":
            self._notify_model_changed()
        return {"revision": self.model.revision, **result}

    def update_member_endpoints(
        self,
        member_name: str,
        start_node: str,
        end_node: str,
    ) -> dict[str, Any]:
        """Altera os nós inicial e final de um membro sem alterar sua identidade."""
        member = self.model_service.update_member_nodes(member_name, start_node, end_node)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def delete_rigid_bar(self, rigid_bar_name: str) -> dict[str, Any]:
        """Exclui uma barra rígida pelo nome atual."""
        if rigid_bar_name not in self.model.rigid_bars:
            raise ValueError(f"Barra rígida '{rigid_bar_name}' não encontrada.")
        self.model_service.remove_rigid_bar(rigid_bar_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_rigid_bar": rigid_bar_name}

    def update_rigid_bar_endpoints(
        self,
        rigid_bar_name: str,
        start_node: str,
        end_node: str,
    ) -> dict[str, Any]:
        """Altera os nós de uma barra rígida; o nome acompanha os novos nós."""
        rigid = self.model_service.update_rigid_bar_nodes(rigid_bar_name, start_node, end_node)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "rigid_bar": {
                "name": rigid.name,
                "start_node": rigid.start_node,
                "end_node": rigid.end_node,
            },
        }

    def split_member(self, member_name: str, parts: int) -> dict[str, Any]:
        """Divide um membro em partes iguais, criando nós intermediários."""
        node_names, member_names = self.model_service.split_member(member_name, parts)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "source_member": member_name,
            "created_nodes": list(node_names),
            "created_members": list(member_names),
            "members": [self._member_payload(self.model.bars[name]) for name in member_names],
        }

    def join_members(self, first_member: str, second_member: str) -> dict[str, Any]:
        """Une dois membros adjacentes e colineares."""
        joined = self.model_service.join_members(first_member, second_member)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "deleted_member": second_member,
            "member": self._member_payload(joined),
        }

    def reverse_member(self, member_name: str) -> dict[str, Any]:
        """Inverte os nós inicial e final de um membro."""
        member = self.model_service.reverse_member(member_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def create_rigid_bar(self, start_node: str, end_node: str) -> dict[str, Any]:
        """Cria uma barra rígida entre dois nós existentes."""
        rigid = self.model_service.create_rigid_bar(start_node, end_node)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "rigid_bar": {
                "name": rigid.name,
                "start_node": rigid.start_node,
                "end_node": rigid.end_node,
            },
        }

    def copy_elements(
        self,
        node_names: list[str] | None,
        member_names: list[str] | None,
        offset: tuple[float, float, float],
    ) -> dict[str, Any]:
        """Copia nós e membros por translação, preservando suas propriedades."""
        copied_nodes, copied_members = self.model_service.copy_elements(
            tuple(node_names or ()),
            tuple(member_names or ()),
            offset,
        )
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "created_nodes": list(copied_nodes),
            "created_members": list(copied_members),
            "members": [self._member_payload(self.model.bars[name]) for name in copied_members],
        }

    def copy_member_properties(
        self,
        source_member: str,
        target_member: str,
        properties: list[str] | None = None,
    ) -> dict[str, Any]:
        """Copia propriedades selecionadas de um membro para outro."""
        available = {"color", "material", "section", "rotation", "offsets", "releases"}
        selected = frozenset(available if properties is None else properties)
        member = self.model_service.copy_member_properties(source_member, target_member, selected)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def set_member_properties(
        self,
        member_names: list[str],
        material: str,
        section: str,
        geometry: dict[str, float],
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Atribui material e seção paramétrica a vários membros."""
        if not member_names:
            raise ValueError("Informe pelo menos um membro.")
        self._validate_member_properties(material, section, geometry)
        names = tuple(dict.fromkeys(member_names))
        if any(name not in self.model.bars for name in names):
            missing = next(name for name in names if name not in self.model.bars)
            raise ValueError(f"Membro '{missing}' não encontrado.")
        members = [
            self._apply_member_properties(name, material, section, geometry, profile)
            for name in names
        ]
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "members": [self._member_payload(member) for member in members],
        }

    def update_member_properties(
        self,
        member_names: list[str],
        *,
        material: str | None = None,
        section: str | None = None,
        geometry: dict[str, float] | None = None,
        profile: str | None = None,
        rotation: int | None = None,
        releases: list[bool] | None = None,
        rotation_flexibility_percent: list[int] | None = None,
        solid_face_offsets_mm: list[float] | None = None,
        solid_section_offsets_mm: list[float] | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza qualquer combinação de propriedades editáveis dos membros."""
        if not member_names:
            raise ValueError("Informe pelo menos um membro.")
        names = tuple(dict.fromkeys(member_names))
        missing = next((name for name in names if name not in self.model.bars), None)
        if missing is not None:
            raise ValueError(f"Membro '{missing}' não encontrado.")

        if rotation is not None and (isinstance(rotation, bool) or not isinstance(rotation, int)):
            raise ValueError("A rotação deve ser um número inteiro em graus.")
        normalized_releases = self._normalize_bool_values(releases, 12, "vinculações")
        normalized_flexibility = self._normalize_int_values(
            rotation_flexibility_percent, 6, 0, 99, "percentuais de semirrígidez",
        )
        face_offsets = self._normalize_offsets(solid_face_offsets_mm, "offsets das faces")
        section_offsets = self._normalize_offsets(solid_section_offsets_mm, "offsets da seção")

        if material is not None and material not in self.model.materials:
            raise ValueError(f"Material '{material}' não encontrado.")
        if color is not None:
            self._validate_color(color)

        for name in names:
            member = self.model.bars[name]
            target_material = material or member.material
            target_section = section if section is not None else member.section
            if section is not None:
                material_type = self.model.material_types.get(target_material)
                if section not in self.model.sections.get(material_type, ()):
                    raise ValueError(
                        f"A seção '{section}' não é compatível com o material '{target_material}'."
                    )
            if geometry is not None:
                if target_material not in self.model.materials or not target_section:
                    raise ValueError(
                        "Para alterar a geometria, informe material e seção válidos "
                        "ou mantenha essas propriedades já definidas no membro."
                    )
                self._validate_member_properties(target_material, target_section, geometry)
            elif material is not None and member.section:
                material_type = self.model.material_types.get(material)
                if member.section not in self.model.sections.get(material_type, ()):
                    raise ValueError(
                        "A troca de material tornaria a seção atual incompatível; "
                        "informe também uma seção compatível."
                    )
            if profile is not None and geometry is None and not member.geometry_dict():
                raise ValueError(
                    "Para alterar o perfil sem informar geometria, o membro precisa "
                    "já possuir uma geometria de seção."
                )

        for name in names:
            member = self.model.bars[name]
            if geometry is not None:
                member = self._apply_member_properties(
                    name,
                    material or member.material,
                    section or member.section,
                    geometry,
                    profile,
                )
            else:
                if material is not None:
                    member = self.model_service.assign_material(name, material)
                if section is not None:
                    member = self.model_service.assign_section(name, section)
                if profile is not None:
                    member = self.model_service.assign_profile(
                        name, profile, member.geometry_dict(),
                    )
            if rotation is not None:
                member = self.model_service.update_member_rotation(name, rotation)
            if normalized_releases is not None:
                member = self.model_service.update_member_releases(name, normalized_releases)
            if normalized_flexibility is not None:
                member = self.model_service.update_member_rotation_flexibility_percent(
                    name, normalized_flexibility,
                )
            if face_offsets is not None:
                member = self.model_service.update_member_solid_face_offsets(name, face_offsets)
            if section_offsets is not None:
                member = self.model_service.update_member_solid_section_offsets(
                    name, section_offsets,
                )
            if color is not None:
                member = self.model_service.update_member_color(name, color)

        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "members": [self._member_payload(self.model.bars[name]) for name in names],
        }

    def _validate_member_properties(
        self,
        material: str,
        section: str,
        geometry: dict[str, float],
    ) -> None:
        values = self.model.materials.get(material)
        if values is None:
            raise ValueError(f"Material '{material}' não encontrado.")
        material_type = self.model.material_types.get(material)
        if section not in self.model.sections.get(material_type, ()):
            raise ValueError(f"A seção '{section}' não é compatível com o material '{material}'.")
        normalized_geometry = {str(key): float(value) for key, value in geometry.items()}
        if not normalized_geometry or any(not isfinite(value) or value <= 0.0 for value in normalized_geometry.values()):
            raise ValueError("As dimensões da seção devem ser números positivos.")
        self._section_properties.calculate(section, normalized_geometry, values[3] / 9.80665e-3)

    def _apply_member_properties(
        self,
        name: str,
        material: str,
        section: str,
        geometry: dict[str, float],
        profile: str | None,
    ):
        self.model_service.assign_material(name, material)
        self.model_service.assign_section(name, section)
        geometry = {str(key): float(value) for key, value in geometry.items()}
        profile_name = profile or self._default_profile_name(section, geometry)
        return self.model_service.assign_profile(name, profile_name, geometry)

    @staticmethod
    def _default_profile_name(section: str, geometry: dict[str, float]) -> str:
        if section == "Retangular" and {"b", "h"} <= geometry.keys():
            return f"R {geometry['b']:g} x {geometry['h']:g}"
        return section

    @staticmethod
    def _member_payload(member) -> dict[str, Any]:
        return {
            "name": member.name,
            "start_node": member.start_node,
            "end_node": member.end_node,
            "material": member.material,
            "section": member.section,
            "profile": member.profile,
            "geometry": member.geometry_dict(),
            "rotation": member.rotation,
            "releases": list(member.releases),
            "rotation_flexibility_percent": list(member.rotation_flexibility_percent),
            "solid_face_offsets_mm": [value * 1000.0 for value in member.solid_face_offsets],
            "solid_section_offsets_mm": [value * 1000.0 for value in member.solid_section_offsets],
            "color": member.color,
        }

    @staticmethod
    def _node_payload(node) -> dict[str, Any]:
        return {
            "name": node.name,
            "x": node.x,
            "y": node.y,
            "z": node.z,
            "supports": list(node.supports),
            "support_stiffness": list(node.support_stiffness),
        }

    @staticmethod
    def _normalize_bool_values(
        values: list[bool] | None,
        expected: int,
        label: str,
    ) -> tuple[bool, ...] | None:
        if values is None:
            return None
        if len(values) != expected or any(not isinstance(value, bool) for value in values):
            raise ValueError(f"As {label} devem possuir exatamente {expected} valores booleanos.")
        return tuple(values)

    @staticmethod
    def _normalize_int_values(
        values: list[int] | None,
        expected: int,
        minimum: int,
        maximum: int,
        label: str,
    ) -> tuple[int, ...] | None:
        if values is None:
            return None
        if (
            len(values) != expected
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
                for value in values
            )
        ):
            raise ValueError(
                f"Os {label} devem possuir {expected} inteiros entre {minimum} e {maximum}."
            )
        return tuple(values)

    @staticmethod
    def _normalize_nonnegative_values(
        values: list[float] | None,
        expected: int,
        label: str,
    ) -> tuple[float, ...] | None:
        if values is None:
            return None
        if len(values) != expected:
            raise ValueError(f"As {label} devem possuir exatamente {expected} valores.")
        try:
            normalized = tuple(float(value) for value in values)
        except (TypeError, ValueError) as error:
            raise ValueError(f"As {label} devem ser numéricas.") from error
        if any(not isfinite(value) or value < 0.0 for value in normalized):
            raise ValueError(f"As {label} devem ser números não negativos.")
        return normalized

    @staticmethod
    def _normalize_offsets(
        values: list[float] | None,
        label: str,
    ) -> tuple[float, float] | None:
        if values is None:
            return None
        if len(values) != 2:
            raise ValueError(f"Os {label} devem possuir exatamente dois valores em milímetros.")
        normalized = tuple(float(value) / 1000.0 for value in values)
        if any(not isfinite(value) for value in normalized):
            raise ValueError(f"Os {label} devem ser números finitos.")
        return normalized  # type: ignore[return-value]

    @staticmethod
    def _validate_color(color: str) -> None:
        if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
            raise ValueError("A cor deve estar no formato hexadecimal #RRGGBB.")
        try:
            int(color[1:], 16)
        except ValueError as error:
            raise ValueError("A cor deve estar no formato hexadecimal #RRGGBB.") from error

    def _axes_payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            direction: [
                {"label": axis.label, "value": axis.value}
                for axis in self.model.axes.get(direction, ())
            ]
            for direction in ("X", "Y", "Z")
        }

    def _analysis_view_state(self) -> dict[str, Any]:
        state = dict(self._analysis_view)
        if self._get_analysis_view_state is not None:
            state.update(self._get_analysis_view_state())
        return state

    def _notify_model_changed(self) -> None:
        if self._on_model_changed is not None:
            self._on_model_changed()
