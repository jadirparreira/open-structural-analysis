"""Current model features exposed through the MCP application facade."""

from __future__ import annotations

import copy
import inspect
from dataclasses import asdict
from typing import Any

from osa.domain import NodeComponentAssignment
from osa.domain.node_components import node_component_definition, node_components
from osa.rendering.analysis_diagrams import BAR_DIAGRAMS, PLATE_DIAGRAMS
from osa.rendering.plate_result_display import PLATE_RESULT_DISPLAY_MODES


class CurrentFeatures:
    def get_capabilities(self) -> dict[str, Any]:
        """Descobre sessões, diagramas, unidades e recursos suportados nesta versão."""
        from .application import APPLICATION_SESSIONS

        return {
            "api_version": "5.0",
            "sessions": list(APPLICATION_SESSIONS),
            "tools": [
                name for name, _method in inspect.getmembers(type(self), inspect.isfunction) if not name.startswith("_")
            ],
            "units": {
                "coordinates": "m",
                "section_geometry": "mm",
                "forces": "kN",
                "moments": "kN·m",
                "plate_moments": "kN·m/m",
                "plate_shear": "kN/m",
                "plate_membrane_stress": "kN/m²",
                "plate_von_mises": "MPa",
                "display_displacements": "mm",
            },
            "analysis_diagrams": {
                kind: [{"label": label, "key": key} for label, key in options]
                for kind, options in (("bar", BAR_DIAGRAMS), ("plate", PLATE_DIAGRAMS))
            },
            "plate_result_display_modes": dict(PLATE_RESULT_DISPLAY_MODES),
            "plate_postprocessing": self._plate_postprocessing_info(),
            "deprecated_options": {
                "snap_enabled": "Removida: a captura permanece ativa; use os controles de tipo na interface."
            },
            "verification": "Mesmas rotinas e limitações da interface; resultados não verificados são preservados.",
        }

    @staticmethod
    def _plate_postprocessing_info():
        from osa.analysis.plate_postprocessing import POSTPROCESSING_INFO
        return copy.deepcopy(POSTPROCESSING_INFO)

    def list_profiles(self, material_type: str, section_family: str) -> dict[str, Any]:
        """Consulta perfis e dimensões dos catálogos. Tipos Aço/Concreto/Madeira; use list_sections para famílias."""
        families = self._catalog.section_families(material_type)
        if section_family not in {family["name"] for family in families}:
            raise ValueError("Família de seção desconhecida para esse tipo de material.")
        return {
            "material_type": material_type,
            "section_family": section_family,
            "profiles": list(self._catalog.profiles(material_type, section_family)),
        }

    def list_plates(self) -> dict[str, Any]:
        """Lista placas, contornos, espessuras, apoios e restrições distribuídas."""
        return {
            "revision": self.model.revision,
            "plates": [self._plate_payload(plate) for plate in self.model.plates.values()],
        }

    def _plate_payload(self, plate) -> dict[str, Any]:
        return {**asdict(plate), "display_name": self.model.plate_display_names.get(plate.name, "")}

    def create_plate(
        self,
        contour: list[list[float]],
        thickness_mm: float = 100.0,
        material: str | None = None,
        supports: list[list[str]] | None = None,
        restrictions: list[bool] | None = None,
        restriction_stiffness: list[float] | None = None,
        restriction_directions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Cria placa de concreto com contorno em m, espessura em mm e molas distribuídas em kN/m³."""
        kwargs = {
            key: value
            for key, value in {
                "restrictions": restrictions,
                "restriction_stiffness": restriction_stiffness,
                "restriction_directions": restriction_directions,
            }.items()
            if value is not None
        }
        plate = self.model.add_plate(
            contour, thickness_mm=thickness_mm, material=material, supports=supports or (), **kwargs
        )
        self._notify_model_changed()
        return {"revision": self.model.revision, "plate": self._plate_payload(plate)}

    def update_plate_properties(
        self,
        plate_name: str,
        thickness_mm: float | None = None,
        material: str | None = None,
        color: str | None = None,
        positioning_displacement: float | None = None,
        edge_positioning: list[list[Any]] | None = None,
        restrictions: list[bool] | None = None,
        restriction_stiffness: list[float] | None = None,
        restriction_directions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Atualiza placa: espessura em mm; deslocamento visual em m; molas em kN/m³; arestas [barra, mm, graus]."""
        if plate_name not in self.model.plates:
            raise ValueError(f"Placa '{plate_name}' não encontrada.")
        self.model.update_plate(
            plate_name,
            thickness_mm=thickness_mm,
            material=material,
            color=color,
            positioning_displacement=positioning_displacement,
            edge_positioning=edge_positioning,
            restrictions=restrictions,
            restriction_stiffness=restriction_stiffness,
            restriction_directions=restriction_directions,
        )
        self._notify_model_changed()
        return {"revision": self.model.revision, "plate": self._plate_payload(self.model.plates[plate_name])}

    def delete_plate(self, plate_name: str) -> dict[str, Any]:
        """Exclui placa e suas cargas, limpando nós órfãos como na interface."""
        self.model.remove_plate(plate_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_plate": plate_name}

    def split_plate(self, plate_name: str, first_point: list[float], second_point: list[float]) -> dict[str, Any]:
        """Divide placa por segmento entre dois pontos do contorno em coordenadas globais (m)."""
        plates = self.model.split_plate(plate_name, first_point, second_point)
        self._notify_model_changed()
        return {"revision": self.model.revision, "plates": [self._plate_payload(p) for p in plates]}

    def join_plates(self, first_plate: str, second_plate: str) -> dict[str, Any]:
        """Une placas compatíveis que compartilham uma borda."""
        plate = self.model.join_plates(first_plate, second_plate)
        self._notify_model_changed()
        return {"revision": self.model.revision, "plate": self._plate_payload(plate)}

    def move_elements(self, targets: list[list[str]], offset: list[float]) -> dict[str, Any]:
        """Move [tipo, nome] por [dx,dy,dz] em m; tipos node/bar/rigid_bar/plate. Nós compartilhados movem uma vez."""
        if not targets:
            raise ValueError("Selecione pelo menos um elemento para mover.")
        moved = self.model.move_elements(targets, offset)
        self._notify_model_changed()
        return {"revision": self.model.revision, "moved_nodes": list(moved)}

    def set_element_display_name(self, kind: str, name: str, display_name: str) -> dict[str, Any]:
        """Altera nome de exibição de node ou plate; preserva sua identidade estrutural."""
        if kind == "node":
            self.model.set_node_display_name(name, display_name)
        elif kind == "plate":
            self.model.set_plate_display_name(name, display_name)
        else:
            raise ValueError("Use node ou plate; para barras, set_verification_element_name.")
        self._notify_model_changed()
        return {"kind": kind, "name": name, "display_name": display_name}

    def list_node_components(self) -> dict[str, Any]:
        """Lista tipos, parâmetros padrão e instâncias dos componentes visuais dos nós."""
        return {
            "definitions": [asdict(item) for item in node_components()],
            "assignments": {
                name: asdict(node.component) for name, node in self.model.nodes.items() if node.component is not None
            },
        }

    def set_node_component(
        self,
        node_name: str,
        component_id: str | None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atribui base_plate/stair_plate ou remove com null. Parâmetros dimensionais em mm; componente só visual."""
        assignment = None
        if component_id is not None:
            definition = node_component_definition(component_id)
            if definition is None:
                raise ValueError("Tipo de componente desconhecido; consulte list_node_components.")
            values = dict(definition.parameters)
            # The domain also supports optional parameters (e.g. per-anchor hook headings).
            values.update(parameters or {})
            assignment = NodeComponentAssignment(component_id, tuple(values.items()))
        self.model.update_node_component(node_name, assignment)
        self._notify_model_changed()
        return {"node": self._node_payload(self.model.nodes[node_name])}

    def add_plate_pressure_profiles(
        self,
        plate_name: str,
        load_case: str,
        x_initial: float,
        x_final: float,
        y_initial: float,
        y_final: float,
    ) -> dict[str, Any]:
        """Aplica perfis independentes de pressão X/Y locais em kN/m², como no painel de ações da placa."""
        self._validate_load_target(plate_name, "plate", load_case)
        values = [self._finite_load_value(value, "pressão") for value in (x_initial, x_final, y_initial, y_final)]
        action = self.action_service.add_plate_surface_pressure_profiles(plate_name, *values, load_case)
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action)}

    def add_plate_edge_load(
        self,
        plate_name: str,
        edge_index: int,
        load_case: str,
        action_type: str,
        direction: str,
        initial: float,
        final: float | None = None,
        reference: str = "global",
    ) -> dict[str, Any]:
        """Aplica força (kN/m) ou momento (kN·m/m) na aresta, índice desde zero. Momento usa referência local."""
        self._validate_load_target(plate_name, "plate", load_case)
        initial = self._finite_load_value(initial, "initial")
        final = initial if final is None else self._finite_load_value(final, "final")
        action = self.action_service.add_plate_edge_action(
            plate_name,
            edge_index,
            action_type,
            direction,
            initial,
            final,
            load_case,
            reference,
        )
        self._notify_model_changed()
        return {"revision": self.model.revision, "action": self._action_payload(action)}

    def ungroup_verification_elements(self, member_name: str) -> dict[str, Any]:
        """Desfaz o grupo de verificação que contém a barra."""
        group = self.model.ungroup_verification_elements(member_name)
        self._notify_model_changed()
        return {"group": group}

    def set_member_calculation_properties(
        self,
        member_name: str,
        properties: dict[str, float | None],
    ) -> dict[str, Any]:
        """Define Ly/Lz/Lt/Lb em m e Ct/Cb adimensionais; null restaura cálculo automático sem invalidar análise."""
        if member_name not in self.model.bars or not properties:
            raise ValueError("Informe uma barra existente e pelo menos uma propriedade.")
        for key, value in properties.items():
            if key not in {"Ly", "Lz", "Lt", "Lb", "Ct", "Cb"}:
                raise ValueError(f"Propriedade de cálculo desconhecida: {key}")
            if value is not None:
                self.model._calculation_property_value(key, value)
        for key, value in properties.items():
            self.model.update_bar_calculation_property(member_name, key, value)
        self._notify_model_changed()
        return {"member": self._member_payload(self.model.bars[member_name])}

    def get_verification_state(self) -> dict[str, Any]:
        """Consulta grupos, resultados e se a análise permite executar as verificações."""
        return {
            "revision": self.model.revision,
            "analysis_ready": bool(self._result_service.current()),
            "groups": copy.deepcopy(self.model.verification_element_groups),
            "result_count": len(self.model.verification_results),
            "calculation_properties_revision": self.model.calculation_properties_revision,
        }

    def get_verification_results(self, element_keys: list[str] | None = None) -> dict[str, Any]:
        """Retorna verificações por chave bar:N ou group:N|N, preservando status/limitações e todos os checks."""
        results = self.model.verification_results
        keys = tuple(results) if element_keys is None else tuple(element_keys)
        if set(keys) - set(results):
            raise ValueError("Há elementos sem resultado de verificação; execute run_verification.")
        return {"revision": self.model.revision, "results": {key: copy.deepcopy(results[key]) for key in keys}}

    def _verification_signature(self):
        return (
            self.model.revision,
            self.model.verification_group_revision,
            self.model.calculation_properties_revision,
            tuple(id(r) for r in self.model.analysis_results),
        )

    def _prepare_verification(self, member_names):
        if not self._result_service.current():
            raise ValueError("Execute a análise antes da verificação.")
        names = None if member_names is None else tuple(dict.fromkeys(member_names))
        if names is not None:
            if not names or set(names) - set(self.model.bars):
                raise ValueError("Informe barras existentes para verificar.")
            if len(names) > 1:
                group = self.model.verification_group_for(names[0])
                if group is None or set(group["members"]) != set(names):
                    raise ValueError("Informe uma barra ou os membros de um grupo completo.")
        signature = self._verification_signature()
        cache = self.model._restraint_lengths_cache
        self.model._restraint_lengths_cache = None
        try:
            return signature, copy.deepcopy(self.model), names
        finally:
            self.model._restraint_lengths_cache = cache

    def _publish_verification(self, signature, payload, names):
        if self._verification_signature() != signature:
            raise ValueError("Modelo ou resultados alterados durante a verificação. Execute novamente.")
        if names is None:
            self.model.verification_results = payload["results"]
        else:
            self.model.verification_results.update(payload["results"])
        self._notify_model_changed()
        return {"revision": self.model.revision, "status": "completed", **copy.deepcopy(payload)}

    def run_verification(self, member_names: list[str] | None = None) -> dict[str, Any]:
        """Executa as mesmas verificações da interface em cópia privada; mantém overrides e recusa publicar resultados obsoletos."""
        from osa.verification.runner import verify_model

        executor = self._execute_on_model_thread
        if executor is None:
            signature, snapshot, names = self._prepare_verification(member_names)
            return self._publish_verification(signature, verify_model(snapshot, names), names)
        signature, snapshot, names = executor(self._prepare_verification, member_names)
        payload = verify_model(snapshot, names)
        return executor(self._publish_verification, signature, payload, names)

    def set_detail_subtractions(self, target_kind: str, target_name: str, cutters: list[list[str]]) -> dict[str, Any]:
        """Define sólidos subtraídos no detalhamento (bar/plate); não muda o modelo analítico."""
        self.model.update_detail_subtractions(target_kind, target_name, cutters)
        self._notify_model_changed()
        return {"target_kind": target_kind, "target_name": target_name, "cutters": cutters}

    def set_member_end_cuts(self, member_name: str, cuts: list[dict[str, Any]]) -> dict[str, Any]:
        """Define cortes visuais por planos: identifier, point (m), normal, reference_label e planes opcionais; [] remove cortes."""
        self.model.update_detail_end_cuts(member_name, cuts)
        self._notify_model_changed()
        return {"member": self._member_payload(self.model.bars[member_name])}

    def copy_element_properties(
        self,
        kind: str,
        source_name: str,
        target_name: str,
        properties: list[str],
    ) -> dict[str, Any]:
        """Copia categorias: node component/restrictions; bar color/material/section/rotation/releases; plate color/material/section/restrictions."""
        self.model.copy_element_properties(kind, source_name, target_name, frozenset(properties))
        self._notify_model_changed()
        return {"kind": kind, "source": source_name, "target": target_name, "properties": properties}


FEATURE_TOOLS = tuple(
    name for name, value in CurrentFeatures.__dict__.items() if not name.startswith("_") and callable(value)
)
READ_TOOLS = {
    "get_capabilities",
    "list_profiles",
    "list_plates",
    "list_node_components",
    "get_verification_state",
    "get_verification_results",
}


def register_feature_tools(server, application, read_only, write, destructive):
    """Keep exact, typed schemas while calls still pass through Qt/locking dispatch."""
    for name in FEATURE_TOOLS:
        method = getattr(CurrentFeatures, name)

        def call(*args, _name=name, **kwargs):
            return getattr(application, _name)(*args, **kwargs)

        signature = inspect.signature(method, eval_str=True)
        call.__signature__ = signature.replace(
            parameters=[p for p in signature.parameters.values() if p.name != "self"]
        )
        call.__name__ = name
        call.__annotations__ = {p.name: p.annotation for p in call.__signature__.parameters.values()}
        call.__annotations__["return"] = signature.return_annotation
        server.add_tool(
            call,
            name=name,
            description=method.__doc__,
            annotations=(read_only if name in READ_TOOLS else destructive if name == "delete_plate" else write),
        )
