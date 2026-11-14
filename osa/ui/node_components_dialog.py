"""Node component picker, parameter editor, and fixed component preview."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor

from osa.domain import NodeComponentAssignment
from osa.domain.node_components import BASE_PLATE_PLANES, default_hook_headings, node_components
from osa.rendering.batched_renderer import _clip_line_mesh_outside_cutters, _transformed_points
from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.node_component_renderer import (
    STAIR_WOOD_COLOR,
    STAIR_WOOD_EDGE_COLOR,
    append_polydata_meshes,
    base_plate_component_meshes,
    stair_plate_mesh,
    stair_wood_mesh,
)
from osa.rendering.solid_member_renderer import SolidMemberRenderer
from osa.sections import section_shape

from .detailing_viewport import _DetachedDetailingScene
from .property_panel import CompactDoubleSpinBox, PropertyPanel

_PARAMETER_LABELS = {
    "largura_mm": "Dimensão A",
    "comprimento_mm": "Dimensão B",
    "deslocamento_a_mm": "Deslocamento A",
    "deslocamento_b_mm": "Deslocamento B",
    "espessura_mm": "Espessura da chapa",
    "rotacao_deg": "Rotação da chapa",
    "fixador": "Tipo de fixador",
    "distancia_a_mm": "Distância da borda",
    "comprimento_fixador_mm": "Comprimento do fixador",
    "embutimento_mm": "Embutimento do fixador",
    "perna_mm": "Perna do gancho",
    "rotacao_gancho_deg": "Rotação do gancho",
    "diametro_mm": "Diâmetro da barra",
    "fixadores_lado_a": "Fixadores lado A",
    "fixadores_lado_b": "Fixadores lado B",
    "plano": "Plano",
    "madeira_largura_mm": "Dimensão A",
    "madeira_comprimento_mm": "Dimensão B",
    "madeira_deslocamento_a_mm": "Deslocamento A",
    "madeira_deslocamento_b_mm": "Deslocamento B",
    "madeira_espessura_mm": "Espessura da chapa",
}
_FIXADORES = ("Reto", "Gancho")
_NO_HOOK_ROTATION_VALUE = -1_000_000_000.0


def _normalized_hook_rotation(value: float) -> float:
    normalized = round(float(value) % 360.0, 1)
    return 0.0 if normalized >= 360.0 else normalized


class ComponentPreview(QWidget):
    """Interactive PyVista viewport for the pending base-plate component."""

    hook_selected = Signal(int)

    def __init__(self, model, node_name: str, parent=None, *, detailing_scene=None) -> None:
        super().__init__(parent)
        self._model = model
        self._node_name = node_name
        self._detailing_scene = detailing_scene
        self._component_id: str | None = None
        self._parameters: dict[str, object] = {}
        self._camera_initialized = False
        self._solid_member_renderer = SolidMemberRenderer()
        self._rod_silhouette_sources: list[pv.PolyData] = []
        self._hook_silhouette_sources: list[pv.PolyData] = []
        self._rod_silhouette_actors: list[object] = []
        self._selected_hook_silhouette_actor = None
        self._hook_actors: list[object] = []
        self._preview_component_actors: list[object] = []
        self._preview_bar_actors: list[object] = []
        self._preview_bar_cache_key: tuple[object, ...] | None = None
        self._preview_source_bar_cache_key: tuple[object, ...] | None = None
        self._preview_source_bar_meshes: dict[str, pv.PolyData] = {}
        self._preview_bar_silhouette_sources: list[pv.PolyData] = []
        self._empty_label_actor = None
        self._plate_actor = None
        self._wood_actor = None
        self._rod_actor = None
        self._rod_edge_actor = None
        self._hardware_actor = None
        self._hardware_edge_actor = None
        self._hook_cell_ranges: list[tuple[int, int]] = []
        self._hook_silhouette_cell_ranges: list[tuple[int, int]] = []
        self._selected_hook_index: int | None = None
        self._camera_drag_mode: str | None = None
        self._camera_drag_last_position: tuple[int, int] | None = None
        self._left_press_position: tuple[int, int] | None = None
        self._left_press_selectable = False
        self.setAccessibleName("Pré-visualização 3D do componente")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.plotter = QtInteractor(self, multi_samples=4, auto_update=False)
        self.plotter.set_background("#f6f8fa")
        self.plotter.enable_parallel_projection()
        self.plotter.iren.style = vtk.vtkInteractorStyleUser()
        self._camera_render_timer = QTimer(self)
        self._camera_render_timer.setSingleShot(True)
        self._camera_render_timer.setInterval(16)
        self._camera_render_timer.timeout.connect(self._render_camera_navigation)
        self._silhouette_timer = QTimer(self)
        self._silhouette_timer.setSingleShot(True)
        self._silhouette_timer.setInterval(500)
        self._silhouette_timer.timeout.connect(self._refresh_silhouettes_after_navigation)
        interactor = self.plotter.iren.interactor
        self._navigation_observers = (
            interactor.AddObserver("LeftButtonPressEvent", self._left_button_pressed, 1.5),
            interactor.AddObserver("LeftButtonReleaseEvent", self._left_button_released, 1.5),
            interactor.AddObserver("MiddleButtonPressEvent", self._middle_button_pressed, 1.5),
            interactor.AddObserver("MiddleButtonReleaseEvent", self._camera_button_released, 1.5),
            interactor.AddObserver("RightButtonPressEvent", self._right_button_pressed, 1.5),
            interactor.AddObserver("RightButtonReleaseEvent", self._camera_button_released, 1.5),
            interactor.AddObserver("MouseMoveEvent", self._camera_mouse_moved, 1.5),
            interactor.AddObserver("MouseWheelForwardEvent", self._camera_wheel, 1.5),
            interactor.AddObserver("MouseWheelBackwardEvent", self._camera_wheel, 1.5),
        )
        layout.addWidget(self.plotter)

    def set_component(self, component_id: str | None, parameters: dict[str, object]) -> None:
        old_counts = (
            self._parameters.get("fixadores_lado_a", 2),
            self._parameters.get("fixadores_lado_b", 2),
        )
        new_parameters = dict(parameters)
        new_counts = (
            new_parameters.get("fixadores_lado_a", 2),
            new_parameters.get("fixadores_lado_b", 2),
        )
        counts_changed = (
            component_id == self._component_id == "base_plate" and old_counts != new_counts
        )
        self._component_id = component_id
        self._parameters = new_parameters
        if component_id != "base_plate" or counts_changed:
            self._selected_hook_index = None
        self._render_preview()
        if counts_changed:
            self.hook_selected.emit(-1)

    def _render_preview(self) -> None:
        plotter = self.plotter
        for actor in self._preview_component_actors:
            actor.SetVisibility(False)
        self._rod_silhouette_sources.clear()
        self._hook_silhouette_sources.clear()
        self._hook_actors.clear()
        plotter.set_background("#f6f8fa")
        if self._component_id not in {"base_plate", "stair_plate"}:
            for actor in self._preview_bar_actors:
                actor.SetVisibility(False)
            if self._empty_label_actor is None:
                self._empty_label_actor = plotter.add_text(
                    "Selecione um componente", position="upper_left", font_size=11,
                    color="#57606a", name="component-preview-empty",
                )
            plotter.render()
            return
        if self._empty_label_actor is not None:
            plotter.renderer.remove_actor(self._empty_label_actor, render=False)
            self._empty_label_actor = None

        p = self._parameters
        if self._component_id == "stair_plate":
            width = max(
                float(p.get("largura_mm", 200.0)),
                float(p.get("madeira_largura_mm", 280.0)),
            ) / 1000.0
            length = max(
                float(p.get("comprimento_mm", 300.0)),
                float(p.get("madeira_comprimento_mm", 800.0)),
            ) / 1000.0
            self._ensure_preview_bars(width, length, 0.0)
            for actor in self._preview_bar_actors:
                actor.SetVisibility(True)
            plate = stair_plate_mesh(p, (0.0, 0.0, 0.0))
            wood = stair_wood_mesh(p, (0.0, 0.0, 0.0))
            self._plate_actor = self._set_preview_mesh_actor(
                self._plate_actor, plate,
                color="#8c959f", edge_color="#57606a", show_edges=True,
                line_width=1.2, smooth_shading=False, lighting=False, pickable=True,
            )
            self._plate_actor.SetObjectName("component-preview-plate")
            self._wood_actor = self._set_preview_mesh_actor(
                self._wood_actor, wood,
                color=STAIR_WOOD_COLOR, edge_color=STAIR_WOOD_EDGE_COLOR,
                show_edges=True, line_width=1.2, smooth_shading=False,
                lighting=False, pickable=True,
            )
            self._wood_actor.SetObjectName("component-preview-wood")
            if not self._camera_initialized:
                plotter.view_vector((-1.0, -1.0, 1.0), viewup=(0.0, 0.0, 1.0), render=False)
                plotter.reset_camera()
                plotter.camera.zoom(1.12)
                self._camera_initialized = True
            plotter.render()
            return

        if p.get("fixador") != "Gancho":
            self._selected_hook_index = None
        width = float(p.get("largura_mm", 300.0)) / 1000.0
        length = float(p.get("comprimento_mm", 300.0)) / 1000.0
        diameter = float(p.get("diametro_mm", 16.0)) / 1000.0
        self._ensure_preview_bars(width, length, diameter)
        self._rod_silhouette_sources.extend(self._preview_bar_silhouette_sources)
        for actor in self._preview_bar_actors:
            actor.SetVisibility(True)

        plate, rods, washers, nuts = base_plate_component_meshes(p, (0.0, 0.0, 0.0))
        self._plate_actor = self._set_preview_mesh_actor(
            self._plate_actor, plate,
            color="#8c959f", edge_color="#57606a", show_edges=True,
            line_width=1.2, smooth_shading=False, lighting=False, pickable=True,
        )
        self._plate_actor.SetObjectName("component-preview-plate")

        combined_rods = append_polydata_meshes(rods)
        self._rod_actor = self._set_preview_mesh_actor(
            self._rod_actor, combined_rods,
            color="#8c959f", smooth_shading=True, lighting=False,
            pickable=p.get("fixador") == "Gancho",
        )
        self._rod_actor.SetObjectName("component-preview-hooks")
        self._rod_actor.SetPickable(p.get("fixador") == "Gancho")
        self._hook_actors = [self._rod_actor] if p.get("fixador") == "Gancho" else []
        self._rod_silhouette_sources.extend(rods)
        self._hook_silhouette_sources.extend(rods)
        self._hook_cell_ranges = []
        cell_start = 0
        for rod in rods:
            self._hook_cell_ranges.append((cell_start, cell_start + rod.n_cells))
            cell_start += rod.n_cells
        hook_edges = (
            combined_rods.extract_feature_edges(
                feature_angle=25.0, boundary_edges=True, feature_edges=True,
                manifold_edges=False, non_manifold_edges=False,
            )
            if p.get("fixador") == "Gancho" else pv.PolyData()
        )
        if hook_edges.n_cells:
            self._rod_edge_actor = self._set_preview_mesh_actor(
                self._rod_edge_actor, hook_edges,
                color="#57606a", line_width=1.0, lighting=False, pickable=False,
            )
            mapper = self._rod_edge_actor.GetMapper()
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
            mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)

        hardware = append_polydata_meshes((*washers, *nuts))
        self._hardware_actor = self._set_preview_mesh_actor(
            self._hardware_actor, hardware,
            color="#8c959f", smooth_shading=False, lighting=False, pickable=True,
        )
        self._hardware_actor.SetObjectName("component-preview-hardware")
        hardware_edges = hardware.extract_feature_edges(
            feature_angle=25.0, boundary_edges=True, feature_edges=True,
            manifold_edges=False, non_manifold_edges=False,
        )
        if hardware_edges.n_cells:
            self._hardware_edge_actor = self._set_preview_mesh_actor(
                self._hardware_edge_actor, hardware_edges,
                color="#57606a", line_width=0.9, lighting=False, pickable=False,
            )
            mapper = self._hardware_edge_actor.GetMapper()
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
            mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)

        if not self._camera_initialized:
            plotter.view_vector((-1.0, -1.0, 1.0), viewup=(0.0, 0.0, 1.0), render=False)
            plotter.reset_camera()
            plotter.camera.zoom(1.12)
            self._camera_initialized = True
        self._refresh_rod_silhouettes()
        plotter.render()

    def _set_preview_mesh_actor(self, actor, mesh, **style):
        if actor is None:
            actor = self.plotter.add_mesh(
                mesh, reset_camera=False, render=False, **style,
            )
            self._preview_component_actors.append(actor)
        else:
            mapper = actor.GetMapper()
            mapper.SetInputData(mesh)
            mapper.Modified()
        actor.GetProperty().LightingOff()
        actor.SetVisibility(True)
        return actor

    def _ensure_preview_bars(self, width: float, length: float, diameter: float) -> None:
        model_revision = getattr(self._model, "revision", None)
        cache_key = (width, length, diameter, model_revision)
        if cache_key == self._preview_bar_cache_key:
            return
        for actor in self._preview_bar_actors:
            self.plotter.renderer.RemoveActor(actor)
        self._preview_bar_actors.clear()
        self._preview_bar_silhouette_sources.clear()
        self._preview_bar_cache_key = cache_key
        node = self._model.nodes.get(self._node_name)
        if node is None:
            return
        preview_length = max(width, length) * 1.4
        if self._detailing_scene is not None:
            self._ensure_adjusted_preview_bar_sources(model_revision)
            node_origin = np.asarray((node.x, node.y, node.z), dtype=float)
            for bar in self._model.bars.values():
                if bar.start_node != self._node_name and bar.end_node != self._node_name:
                    continue
                other_name = bar.end_node if bar.start_node == self._node_name else bar.start_node
                other = self._model.nodes.get(other_name)
                source = self._preview_source_bar_meshes.get(bar.name)
                if other is None or source is None:
                    continue
                direction = np.asarray((other.x - node.x, other.y - node.y, other.z - node.z))
                norm = float(np.linalg.norm(direction))
                if norm <= 1e-12:
                    continue
                direction /= norm
                # Keep the actual adjusted solid near the component. The
                # Boolean mesh already includes face alignment, end cuts and
                # subtractions; this plane only limits the preview to a short
                # connected segment instead of drawing the entire structure.
                clipped = self._clip_preview_bar_segment(
                    source, direction, node_origin + direction * preview_length,
                )
                if not clipped.n_points or not clipped.n_cells:
                    continue
                clipped.points -= node_origin
                edge_mesh = clipped.extract_feature_edges(
                    boundary_edges=True, feature_edges=True,
                    manifold_edges=False, non_manifold_edges=True,
                    feature_angle=25.0,
                )
                curve_edges = self._preview_bar_curve_edges(
                    bar, node_origin, direction,
                    node_origin + direction * preview_length,
                )
                if curve_edges.n_lines:
                    edge_mesh = pv.merge((edge_mesh, curve_edges), merge_points=False)
                face_actor = self.plotter.add_mesh(
                    clipped, color=bar.color, smooth_shading=False, lighting=False,
                    pickable=True, reset_camera=False, render=False,
                )
                face_actor.SetObjectName(f"component-preview-bar:{bar.name}")
                edge_actor = self.plotter.add_mesh(
                    edge_mesh, color=self._solid_member_renderer.edge_color(bar.color),
                    line_width=1.5, lighting=False, pickable=False,
                    reset_camera=False, render=False,
                )
                edge_actor.SetObjectName(f"component-preview-bar-edge:{bar.name}")
                edge_mapper = edge_actor.GetMapper()
                edge_mapper.SetResolveCoincidentTopologyToPolygonOffset()
                edge_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
                edge_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
                self._preview_bar_actors.extend((face_actor, edge_actor))
                self._preview_bar_silhouette_sources.append(clipped)
            return
        for bar in self._model.bars.values():
            if bar.start_node != self._node_name and bar.end_node != self._node_name:
                continue
            other_name = bar.end_node if bar.start_node == self._node_name else bar.start_node
            other = self._model.nodes.get(other_name)
            if other is None:
                continue
            vector = (other.x - node.x, other.y - node.y, other.z - node.z)
            norm = math.sqrt(sum(value * value for value in vector))
            if norm <= 1e-12:
                continue
            endpoint = tuple(value / norm * preview_length for value in vector)
            start = SimpleNamespace(x=0.0, y=0.0, z=0.0)
            end = SimpleNamespace(x=endpoint[0], y=endpoint[1], z=endpoint[2])
            try:
                visual = self._solid_member_renderer.render(
                    self.plotter, bar, start, end, visible=True,
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                visual = None
            if visual is not None:
                visual.face_actor.GetProperty().LightingOff()
                visual.face_actor.SetPickable(True)
                self._preview_bar_actors.extend((visual.face_actor, visual.edge_actor))
            else:
                line = pv.Line((0.0, 0.0, 0.0), endpoint)
                bar_actor = self.plotter.add_mesh(
                    line.tube(radius=max(diameter * 1.8, 0.006)),
                    color=bar.color, smooth_shading=True, lighting=False, pickable=True,
                    reset_camera=False, render=False,
                )
                bar_actor.SetObjectName(f"component-preview-bar:{bar.name}")
                self._preview_bar_actors.append(bar_actor)

    def _preview_bar_curve_edges(
        self, bar, node_origin: np.ndarray, direction: np.ndarray, clip_origin: np.ndarray,
    ) -> pv.PolyData:
        """Add the section's longitudinal curved-profile edges to the preview."""
        start = self._model.nodes.get(bar.start_node)
        end = self._model.nodes.get(bar.end_node)
        if start is None or end is None:
            return pv.PolyData()
        try:
            shape = section_shape(
                bar.section, bar.geometry_dict(),
                arc_steps=self._solid_member_renderer._arc_steps,
                mirror_z=bar.section_mirrored,
            )
            if shape is None:
                return pv.PolyData()
            local_edges = self._solid_member_renderer._build_curve_transition_mesh(shape)
        except (KeyError, TypeError, ValueError):
            return pv.PolyData()
        if not local_edges.n_lines:
            return pv.PolyData()

        basis = LocalAxesRenderer.basis(start, end, rotation=bar.rotation)
        if basis is None:
            return pv.PolyData()
        start_point = np.asarray((start.x, start.y, start.z), dtype=float)
        end_point = np.asarray((end.x, end.y, end.z), dtype=float)
        face_offsets = getattr(bar, "solid_face_offsets", (0.0, 0.0))
        if len(face_offsets) == 2:
            candidate_start = start_point - basis[0] * float(face_offsets[0])
            candidate_end = end_point + basis[0] * float(face_offsets[1])
            if float(np.dot(candidate_end - candidate_start, basis[0])) > 1e-9:
                start_point, end_point = candidate_start, candidate_end
        transition_points = _transformed_points(
            np.asarray(local_edges.points),
            start_point + LocalAxesRenderer.section_offset(bar, start, end),
            end_point - start_point, basis[1], basis[2],
            getattr(bar, "solid_face_angles", (0.0, 0.0, 0.0, 0.0)),
        )
        transition = pv.PolyData(
            transition_points, lines=np.asarray(local_edges.lines, dtype=np.int64).copy(),
        )
        cutter_map = getattr(self._detailing_scene, "_detailing_view_subtraction_meshes", {})
        cutter_references = (
            *getattr(bar, "detail_subtractions", ()),
            *(('end_cut', cut.identifier) for cut in getattr(bar, "detail_end_cuts", ())),
        )
        cutters = tuple(
            cutter for reference in cutter_references
            if (cutter := cutter_map.get(tuple(reference))) is not None
        )
        if cutters:
            transition = _clip_line_mesh_outside_cutters(transition, cutters)
        transition = transition.clip(normal=direction, origin=clip_origin, invert=True)
        if transition.n_points and transition.n_lines:
            transition.points -= node_origin
            return transition
        return pv.PolyData()

    def _ensure_adjusted_preview_bar_sources(self, model_revision) -> None:
        cache_key = (id(self._model), model_revision, self._node_name)
        if cache_key == self._preview_source_bar_cache_key:
            return
        self._preview_source_bar_cache_key = cache_key
        self._preview_source_bar_meshes.clear()
        connected_names = {
            bar.name for bar in self._model.bars.values()
            if bar.start_node == self._node_name or bar.end_node == self._node_name
        }
        for solid_name, mesh in self._detailing_scene.detailing_view_solid_meshes(self._model):
            bar_name = solid_name.removeprefix("bar:")
            if bar_name in connected_names:
                self._preview_source_bar_meshes[bar_name] = mesh.copy(deep=True)

    @staticmethod
    def _clip_preview_bar_segment(
        source: pv.PolyData, direction: np.ndarray, clip_origin: np.ndarray,
    ) -> pv.PolyData:
        """Trim a local preview segment and cap the section so tube walls stay visible."""
        plane = vtk.vtkPlane()
        plane.SetOrigin(*map(float, clip_origin))
        # vtkClipClosedSurface keeps the positive side of its plane. The
        # component is at the connected node, so keep the side opposite the
        # bar direction and cap the distal end of the preview stub.
        plane.SetNormal(*map(float, -direction))
        planes = vtk.vtkPlaneCollection()
        planes.AddItem(plane)
        clipper = vtk.vtkClipClosedSurface()
        clipper.SetInputData(source)
        clipper.SetClippingPlanes(planes)
        clipper.GenerateFacesOn()
        clipper.GenerateOutlineOn()
        clipper.Update()
        clipped = pv.wrap(clipper.GetOutput()).copy(deep=True)
        if clipped.n_points and clipped.n_cells:
            return clipped
        # Keep a displayable segment when a source is not a closed solid.
        return source.clip(normal=direction, origin=clip_origin, invert=True)

    def _refresh_rod_silhouettes(self, *_args) -> None:
        if not self._rod_silhouette_sources:
            return
        camera = self.plotter.renderer.GetActiveCamera()
        combined = self._solid_member_renderer.silhouette_for(
            append_polydata_meshes(tuple(self._rod_silhouette_sources)), camera,
        )
        if not combined.n_cells:
            if self._rod_silhouette_actors:
                self._rod_silhouette_actors[0].SetVisibility(False)
            return
        actor = self._rod_silhouette_actors[0] if self._rod_silhouette_actors else None
        actor = self._set_preview_mesh_actor(
            actor, combined, color="#57606a", lighting=False,
            pickable=False, line_width=1.5,
        )
        if not self._rod_silhouette_actors:
            self._rod_silhouette_actors.append(actor)
        silhouette_mapper = actor.GetMapper()
        silhouette_mapper.SetResolveCoincidentTopologyToPolygonOffset()
        silhouette_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
        silhouette_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
        self._update_selected_hook_silhouette(camera)

    def _set_selected_hook(self, index: int) -> None:
        self._selected_hook_index = index if index >= 0 else None
        self._update_selected_hook_silhouette(self.plotter.renderer.GetActiveCamera())
        self.plotter.render()
        self.hook_selected.emit(index)

    def _update_selected_hook_silhouette(self, camera) -> None:
        index = self._selected_hook_index
        if index is None or not 0 <= index < len(self._hook_silhouette_sources):
            if self._selected_hook_silhouette_actor is not None:
                self._selected_hook_silhouette_actor.SetVisibility(False)
            return
        silhouette = self._solid_member_renderer.silhouette_for(
            self._hook_silhouette_sources[index], camera,
        )
        if not silhouette.n_cells:
            if self._selected_hook_silhouette_actor is not None:
                self._selected_hook_silhouette_actor.SetVisibility(False)
            return
        self._selected_hook_silhouette_actor = self._set_preview_mesh_actor(
            self._selected_hook_silhouette_actor, silhouette,
            color="#0969da", lighting=False, pickable=False, line_width=2.0,
        )

    @staticmethod
    def _rotate_vector(vector: np.ndarray, axis: np.ndarray, angle_degrees: float) -> np.ndarray:
        axis_length = float(np.linalg.norm(axis))
        if axis_length <= 1e-12 or abs(float(angle_degrees)) <= 1e-12:
            return vector.copy()
        unit_axis = axis / axis_length
        angle = np.deg2rad(float(angle_degrees))
        cosine, sine = float(np.cos(angle)), float(np.sin(angle))
        return (
            vector * cosine + np.cross(unit_axis, vector) * sine
            + unit_axis * float(np.dot(unit_axis, vector)) * (1.0 - cosine)
        )

    def _left_button_pressed(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        self._left_press_position = int(x), int(y)
        self._left_press_selectable = not caller.GetShiftKey()
        self._begin_camera_drag("pan" if caller.GetShiftKey() else "orbit", x, y)

    def _middle_button_pressed(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        self._begin_camera_drag("pan", x, y)

    def _right_button_pressed(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        self._begin_camera_drag("dolly", x, y)

    def _begin_camera_drag(self, mode: str, x: int, y: int) -> None:
        if self._camera_drag_mode is not None:
            return
        self._camera_drag_mode = mode
        self._camera_drag_last_position = int(x), int(y)

    def _camera_mouse_moved(self, caller, _event) -> None:
        if self._camera_drag_mode is None or self._camera_drag_last_position is None:
            return
        x, y = caller.GetEventPosition()
        x, y = int(x), int(y)
        last_x, last_y = self._camera_drag_last_position
        self._camera_drag_last_position = x, y
        if self._camera_drag_mode == "orbit":
            self._orbit_camera(x - last_x, y - last_y)
        elif self._camera_drag_mode == "pan":
            self._pan_camera(last_x, last_y, x, y)
        else:
            self._dolly_camera(last_y, y)
        self._queue_camera_render()

    def _orbit_camera(self, dx: int, dy: int) -> None:
        width, height = self.plotter.render_window.GetSize()
        if width <= 0 or height <= 0 or (dx == 0 and dy == 0):
            return
        azimuth = -float(dx) / float(width) * 180.0
        elevation = -float(dy) / float(height) * 180.0
        camera = self.plotter.renderer.GetActiveCamera()
        focal = np.asarray(camera.GetFocalPoint(), dtype=float)
        offset = np.asarray(camera.GetPosition(), dtype=float) - focal
        if float(np.linalg.norm(offset)) <= 1e-12:
            return
        world_up = np.asarray((0.0, 0.0, 1.0), dtype=float)
        up = np.asarray(camera.GetViewUp(), dtype=float)
        was_at_pole = float(np.linalg.norm(np.cross(world_up, offset))) <= 1e-8
        offset = self._rotate_vector(offset, world_up, azimuth)
        if was_at_pole:
            up = self._rotate_vector(up, world_up, azimuth)
        direction = -offset / max(float(np.linalg.norm(offset)), 1e-12)
        elevation_axis = np.cross(world_up, direction)
        if float(np.linalg.norm(elevation_axis)) <= 1e-8:
            horizontal_up = up.copy()
            horizontal_up[2] = 0.0
            if float(np.linalg.norm(horizontal_up)) <= 1e-8:
                horizontal_up = np.asarray((0.0, 1.0, 0.0), dtype=float)
            elevation_axis = np.cross(horizontal_up, direction)
        offset = self._rotate_vector(offset, elevation_axis, elevation)
        camera.SetPosition(*(focal + offset))
        at_pole = float(np.linalg.norm(np.cross(world_up, offset))) <= 1e-8
        if at_pole:
            up[2] = 0.0
            up_length = float(np.linalg.norm(up))
            up = up / up_length if up_length > 1e-8 else np.asarray((0.0, 1.0, 0.0))
            camera.SetViewUp(*up)
        else:
            camera.SetViewUp(*world_up)

    def _pan_camera(self, last_x: int, last_y: int, x: int, y: int) -> None:
        renderer = self.plotter.renderer
        camera = renderer.GetActiveCamera()
        focal = np.asarray(camera.GetFocalPoint(), dtype=float)
        renderer.SetWorldPoint(*focal, 1.0)
        renderer.WorldToDisplay()
        depth = float(renderer.GetDisplayPoint()[2])

        def display_to_world(px: int, py: int) -> np.ndarray | None:
            renderer.SetDisplayPoint(float(px), float(py), depth)
            renderer.DisplayToWorld()
            world = np.asarray(renderer.GetWorldPoint(), dtype=float)
            if abs(float(world[3])) <= 1e-12:
                return None
            return world[:3] / world[3]

        current = display_to_world(x, y)
        previous = display_to_world(last_x, last_y)
        if current is None or previous is None:
            return
        movement = previous - current
        camera.SetPosition(*(np.asarray(camera.GetPosition(), dtype=float) + movement))
        camera.SetFocalPoint(*(focal + movement))

    def _dolly_camera(self, last_y: int, y: int) -> None:
        center_y = float(self.plotter.renderer.GetCenter()[1])
        if abs(center_y) <= 1e-12:
            return
        factor = 1.1 ** (10.0 * (float(y) - float(last_y)) / center_y)
        camera = self.plotter.renderer.GetActiveCamera()
        camera.SetParallelScale(camera.GetParallelScale() / factor)

    def _camera_wheel(self, _caller, event) -> None:
        factor = 1.0 / 1.05 if event == "MouseWheelForwardEvent" else 1.05
        camera = self.plotter.renderer.GetActiveCamera()
        camera.SetParallelScale(camera.GetParallelScale() * factor)
        self._queue_camera_render()
        self._silhouette_timer.start()

    def _queue_camera_render(self) -> None:
        if not self._camera_render_timer.isActive():
            self._camera_render_timer.start()

    def _render_camera_navigation(self) -> None:
        self.plotter.render()

    def _refresh_silhouettes_after_navigation(self) -> None:
        if self._component_id == "base_plate":
            self._refresh_rod_silhouettes()
            self.plotter.render()

    def _camera_button_released(self, *_args) -> None:
        self._finish_camera_drag()

    def _left_button_released(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        press = self._left_press_position
        self._finish_camera_drag()
        self._left_press_position = None
        if (
            self._left_press_selectable and press is not None
            and np.hypot(x - press[0], y - press[1]) <= 4.0
        ):
            self._select_hook_at_pointer()
        self._left_press_selectable = False

    def _finish_camera_drag(self) -> None:
        self._camera_render_timer.stop()
        self._camera_drag_mode = None
        self._camera_drag_last_position = None
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()
        self._silhouette_timer.start()

    def _select_hook_at_pointer(self, *_args) -> None:
        if not self._hook_actors:
            return
        x, y = self.plotter.iren.get_event_position()
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.01)
        if not picker.Pick(x, y, 0, self.plotter.renderer):
            if self._selected_hook_index is not None:
                self._set_selected_hook(-1)
            return
        actor_name = str(picker.GetActor().GetObjectName() or "")
        if actor_name != "component-preview-hooks":
            if self._selected_hook_index is not None:
                self._set_selected_hook(-1)
            return
        cell_id = picker.GetCellId()
        index = next(
            (hook_index for hook_index, (start, end) in enumerate(self._hook_cell_ranges)
             if start <= cell_id < end),
            None,
        )
        if index is None:
            return
        if index == self._selected_hook_index:
            return
        self._set_selected_hook(index)

    def shutdown(self) -> None:
        self.plotter.close()


class NodeComponentsDialog(QDialog):
    def __init__(self, window, node_name: str, parent=None) -> None:
        super().__init__(parent or window)
        self.window = window
        self.node_name = node_name
        self._definitions = node_components()
        self._current_definition = None
        self._preview_shutdown = False
        self._inputs: dict[str, QWidget] = {}
        self._hook_rotation_unit_label: QLabel | None = None
        current = window.model.nodes[node_name].component
        self._draft_component_id = current.component_id if current else None
        self._draft_parameters = dict(current.parameters) if current else {}
        self.setWindowTitle("Componente do nó")
        self.setObjectName("nodeComponentsDialog")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(1120, 680)
        self.setMinimumSize(1000, 560)
        self.setModal(True)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QListWidget { background: #f6f8fa; border: 0; padding: 8px; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #57606a; }"
            "QListWidget::item:selected { background: #d0d7de; color: #24292f; }"
            "QListWidget:focus { outline: none; border: 0; }"
            "QFrame#componentPreview { background: #f6f8fa; border: 1px solid #d0d7de; "
            "border-radius: 8px; }"
            "QScrollArea#componentParametersScroll { background: transparent; border: 0; }"
            "QScrollArea#componentParametersScroll QWidget#qt_scrollarea_viewport { "
            "background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 12px; "
            "margin: 4px 2px 4px 0; }"
            "QScrollBar::handle:vertical { background: #afb8c1; min-height: 28px; "
            "border-radius: 6px; }"
            "QScrollBar::handle:vertical:hover { background: #8c959f; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { "
            "background: transparent; }"
            "QComboBox#fastenerSelector::drop-down { width: 0px; border: 0; }"
            "QComboBox#fastenerSelector::down-arrow { image: none; }"
            "QLabel#componentParameterName { color: #57606a; font-size: 12px; "
            "font-weight: 600; padding: 0; }"
            "QPushButton#closeProperties { min-height: 34px; padding: 4px 14px; "
            "border: 1px solid #d0d7de; border-radius: 7px; color: #24292f; background: #f6f8fa; }"
            "QPushButton#closeProperties:hover { background: #eaeef2; }"
            "QPushButton#applyComponent { min-height: 34px; padding: 4px 16px; border: 0; "
            "border-radius: 7px; background: #0969da; color: #ffffff; font-weight: 600; }"
            "QPushButton#applyComponent:hover { background: #0550ae; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        titlebar = QFrame()
        titlebar.setObjectName("titleBar")
        titlebar.setFixedHeight(40)
        titlebar_layout = QHBoxLayout(titlebar)
        titlebar_layout.setContentsMargins(12, 6, 8, 6)
        title = QLabel("Componente")
        title.setObjectName("windowTitle")
        titlebar_layout.addWidget(title)
        titlebar_layout.addStretch(1)
        outer.addWidget(titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.component_list = QListWidget()
        self.component_list.setFixedWidth(170)
        self.component_list.setSpacing(8)
        self.component_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.component_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.component_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.component_list.setAccessibleName("Componentes aplicáveis ao nó")
        body.addWidget(self.component_list)

        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(18, 10, 18, 9)
        right_layout.setSpacing(0)
        self.details_title = QLabel(f"Nó {node_name}")
        self.details_title.setObjectName("windowTitle")
        right_layout.addWidget(self.details_title)
        right_layout.addSpacing(10)
        self.details_text = QLabel("Selecione um componente aplicável ao nó.")
        self.details_text.setObjectName("hint")
        self.details_text.setWordWrap(True)
        right_layout.addWidget(self.details_text)
        right_layout.addSpacing(12)

        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(18)
        self.parameters_scroll = QScrollArea()
        self.parameters_scroll.setObjectName("componentParametersScroll")
        self.parameters_scroll.setWidgetResizable(True)
        self.parameters_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.parameters_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.parameters_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.parameters_widget = QWidget()
        self.parameters_layout = QGridLayout(self.parameters_widget)
        self.parameters_layout.setContentsMargins(0, 4, 8, 12)
        self.parameters_layout.setHorizontalSpacing(8)
        self.parameters_layout.setVerticalSpacing(10)
        self.parameters_layout.setColumnStretch(0, 1)
        self.parameters_layout.setColumnStretch(1, 1)
        self.parameters_scroll.setWidget(self.parameters_widget)
        editor_row.addWidget(self.parameters_scroll, 1)

        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("componentPreview")
        self.preview_frame.setFixedWidth(450)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        preview_layout.setSpacing(8)
        preview_title = QLabel("Pré-visualização")
        preview_title.setObjectName("propertySection")
        preview_layout.addWidget(preview_title)
        scene = getattr(window, "scene", None)
        self._preview_detail_scene = (
            _DetachedDetailingScene(scene) if scene is not None else None
        )
        self.preview = ComponentPreview(
            window.model, node_name, detailing_scene=self._preview_detail_scene,
        )
        self.preview.hook_selected.connect(self._preview_hook_selected)
        preview_layout.addWidget(self.preview, 1)
        editor_row.addWidget(self.preview_frame)
        right_layout.addLayout(editor_row, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 10, 0, 0)
        footer.setSpacing(12)
        footer.addStretch(1)
        self.close_button = QPushButton("Fechar")
        self.close_button.setObjectName("closeProperties")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        self.apply_button = QPushButton("Aplicar")
        self.apply_button.setObjectName("applyComponent")
        self.apply_button.clicked.connect(self._apply_component)
        footer.addWidget(self.apply_button)
        right_layout.addLayout(footer)
        body.addWidget(self.right_panel, 1)
        outer.addLayout(body, 1)

        self._add_component_row("Nenhum", None)
        for definition in self._definitions:
            self._add_component_row(definition.name, definition.component_id)
        self.component_list.currentRowChanged.connect(self._component_selected)

        selected_row = next(
            (row for row in range(self.component_list.count())
             if self.component_list.item(row).data(Qt.ItemDataRole.UserRole) == self._draft_component_id),
            0,
        )
        self.component_list.setCurrentRow(selected_row)
        if parent is not None:
            self.move(parent.geometry().center() - self.rect().center())

    def _add_component_row(self, name: str, component_id: str | None) -> None:
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, component_id)
        self.component_list.addItem(item)

    def _component_selected(self, row: int) -> None:
        self._clear_parameter_inputs()

        if row < 0:
            self._draft_component_id = None
            self._draft_parameters = {}
            self.details_title.setText(f"Nó {self.node_name}")
            self.details_text.setText("Selecione um componente aplicável ao nó.")
            self.preview.set_component(None, {})
            return

        item = self.component_list.item(row)
        component_id = item.data(Qt.ItemDataRole.UserRole)
        self._draft_component_id = component_id
        definition = next(
            (entry for entry in self._definitions if entry.component_id == component_id), None,
        )
        if definition is None:
            self._current_definition = None
            self._draft_parameters = {}
            self.details_title.setText("Nenhum componente")
            self.details_text.setText("Este nó não possui um componente aplicado.")
            self.preview.set_component(None, {})
            return

        self._current_definition = definition
        current = self.window.model.nodes[self.node_name].component
        values = dict(current.parameters) if current and current.component_id == component_id else {}
        for key, default in definition.parameters:
            values.setdefault(key, default)
        if component_id == "base_plate":
            if values.get("fixador") == "Químico":
                values["fixador"] = "Reto"
            if values.get("fixador") not in _FIXADORES:
                values["fixador"] = "Reto"
            if values["fixador"] == "Reto":
                values.pop("perna_mm", None)
                values.pop("rotacao_gancho_deg", None)
            else:
                legacy_rotation = float(values.get("rotacao_gancho_deg", 0.0))
                for index, heading in enumerate(default_hook_headings(values)):
                    global_key = f"rotacao_global_gancho_{index}_deg"
                    legacy_key = f"rotacao_gancho_{index}_deg"
                    if global_key not in values:
                        values[global_key] = _normalized_hook_rotation(
                            heading
                            + float(values.get(legacy_key, legacy_rotation)),
                        )
                    values.pop(legacy_key, None)
                values.pop("rotacao_gancho_deg", None)
        self._draft_parameters = values
        self.details_title.setText(definition.name)
        description = (
            "O topo da madeira coincide com o nó; a chapa de aço fica embaixo. "
            "A rotação da chapa de aço também orienta o degrau."
            if component_id == "stair_plate" else
            "Chapa retangular posicionada no plano selecionado no nó."
        )
        self.details_text.setText(
            f"{description} Os parâmetros visuais são aplicados ao nó somente ao clicar em Aplicar."
        )
        self._show_parameters(definition.parameters, values)
        self._update_preview()

    def _show_parameters(self, parameters, values: dict[str, object]) -> None:
        self._clear_parameter_inputs()
        visible_parameters = [
            (key, default) for key, default in parameters
            if key not in {"perna_mm", "rotacao_gancho_deg"}
            or values.get("fixador") == "Gancho"
        ]
        row, column = 0, 0
        active_section = None
        for key, default in visible_parameters:
            section = "Degrau de madeira" if key.startswith("madeira_") else "Chapa de aço"
            if section != active_section:
                if column:
                    row += 1
                    column = 0
                heading = QLabel(section, self.parameters_widget)
                heading.setObjectName("propertySection")
                self.parameters_layout.addWidget(heading, row, 0, 1, 2)
                row += 1
                active_section = section
            field_group = QWidget(self.parameters_widget)
            group_layout = QVBoxLayout(field_group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(1)
            label = QLabel(_PARAMETER_LABELS.get(key, key.replace("_", " ").capitalize()))
            label.setObjectName("componentParameterName")
            label.setAccessibleName(label.text())
            if key == "rotacao_gancho_deg":
                label_row = QWidget(field_group)
                label_layout = QHBoxLayout(label_row)
                label_layout.setContentsMargins(0, 0, 0, 0)
                label_layout.setSpacing(4)
                label_layout.addWidget(label)
                label_layout.addStretch(1)
                info_button = QToolButton(label_row)
                info_button.setObjectName("componentParameterInfo")
                info_button.setIcon(QIcon(str(
                    Path(__file__).parents[1] / "resources" / "icons" / "info.svg"
                )))
                info_button.setIconSize(QSize(14, 14))
                info_button.setFixedSize(18, 18)
                info_button.setAutoRaise(True)
                info_button.setAccessibleName("Informação sobre a rotação do gancho")
                info_button.setToolTip(
                    "Selecione um gancho na pré-visualização para definir a rotação dele."
                )
                label_layout.addWidget(info_button)
                group_layout.addWidget(label_row)
            else:
                group_layout.addWidget(label)
            if key in {"fixador", "plano"}:
                field = QComboBox(field_group)
                field.setObjectName("fastenerSelector" if key == "fixador" else "planeSelector")
                field.addItems(_FIXADORES if key == "fixador" else BASE_PLATE_PLANES)
                field.setCurrentText(str(values.get(key, default)))
                field.setAccessibleName(label.text())
                field.currentTextChanged.connect(
                    self._fixador_changed if key == "fixador" else self._input_changed
                )
                group_layout.addWidget(field)
                self._inputs[key] = field
            else:
                field = CompactDoubleSpinBox(field_group)
                field.setDecimals(1)
                if key in {"fixadores_lado_a", "fixadores_lado_b"}:
                    field.setDecimals(0)
                    field.setRange(2.0, 100.0)
                    field.setSingleStep(1.0)
                elif key == "rotacao_deg":
                    field.setRange(
                        0.0,
                        359.9 if self._current_definition.component_id == "stair_plate" else 259.9,
                    )
                    field.setSingleStep(0.1)
                elif key == "rotacao_gancho_deg":
                    field.setSpecialValueText("Nenhum")
                    field.setRange(_NO_HOOK_ROTATION_VALUE, 1_000_000_000.0)
                    field.setSingleStep(0.1)
                    field.setValue(_NO_HOOK_ROTATION_VALUE)
                elif key in {
                    "deslocamento_a_mm", "deslocamento_b_mm",
                    "madeira_deslocamento_a_mm", "madeira_deslocamento_b_mm",
                }:
                    field.setRange(-100_000.0, 100_000.0)
                    field.setSingleStep(1.0)
                elif key not in {"fixadores_lado_a", "fixadores_lado_b"}:
                    field.setRange(0.1, 100_000.0)
                    field.setSingleStep(1.0)
                field.setKeyboardTracking(False)
                field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                field.setAccessibleName(label.text())
                if key == "rotacao_gancho_deg":
                    field.setEnabled(False)
                    field.setToolTip(
                        "Selecione um gancho na pré-visualização para definir a rotação dele."
                    )
                else:
                    field.setValue(float(values.get(key, default)))
                if key == "distancia_a_mm":
                    field.setToolTip("Distância da borda da chapa ao eixo dos chumbadores.")
                if key == "comprimento_fixador_mm":
                    field.setToolTip("Comprimento total do fixador.")
                if key == "embutimento_mm":
                    field.setToolTip("Distância entre o fundo da chapa e a ponta do fixador.")
                if key == "diametro_mm":
                    field.setToolTip("O diâmetro define também as dimensões da arruela e da porca.")
                field.valueChanged.connect(self._input_changed)
                unit_box = PropertyPanel._editable_unit_box(
                    field,
                    "°" if key in {"rotacao_deg", "rotacao_gancho_deg"}
                    else "" if key in {"fixadores_lado_a", "fixadores_lado_b"}
                    else "mm",
                )
                if key == "rotacao_gancho_deg":
                    self._hook_rotation_unit_label = unit_box.findChild(QLabel)
                    self._hook_rotation_unit_label.hide()
                group_layout.addWidget(unit_box)
                self._inputs[key] = field
            self.parameters_layout.addWidget(field_group, row, column)
            column += 1
            if column == 2:
                row += 1
                column = 0

        self.parameters_layout.activate()
        QTimer.singleShot(0, self._update_parameter_content_minimum_height)

    def _update_parameter_content_minimum_height(self) -> None:
        if self.parameters_layout.count():
            self.parameters_layout.activate()
            self.parameters_widget.setMinimumHeight(self.parameters_layout.sizeHint().height())

    def _clear_parameter_inputs(self) -> None:
        self._inputs.clear()
        self._hook_rotation_unit_label = None
        self.parameters_widget.setMinimumHeight(0)
        while self.parameters_layout.count():
            item = self.parameters_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _input_changed(self, *_args) -> None:
        for key, field in self._inputs.items():
            if isinstance(field, QComboBox):
                self._draft_parameters[key] = field.currentText()
            elif isinstance(field, CompactDoubleSpinBox):
                value = field.value()
                if key == "rotacao_gancho_deg":
                    if self.preview._selected_hook_index is None:
                        continue
                    value = _normalized_hook_rotation(value)
                    previous = field.blockSignals(True)
                    field.setValue(value)
                    field.blockSignals(previous)
                    self._draft_parameters[
                        f"rotacao_global_gancho_{self.preview._selected_hook_index}_deg"
                    ] = value
                else:
                    self._draft_parameters[key] = value
        self._update_preview()

    def _preview_hook_selected(self, index: int) -> None:
        field = self._inputs.get("rotacao_gancho_deg")
        if isinstance(field, CompactDoubleSpinBox):
            previous = field.blockSignals(True)
            if index < 0:
                field.setEnabled(False)
                field.setPrefix("")
                field.setValue(_NO_HOOK_ROTATION_VALUE)
                if self._hook_rotation_unit_label is not None:
                    self._hook_rotation_unit_label.hide()
            else:
                key = f"rotacao_global_gancho_{index}_deg"
                heading = default_hook_headings(self._draft_parameters)[index]
                value = float(self._draft_parameters.get(key, heading))
                field.setEnabled(True)
                field.setPrefix(f"Gancho {index + 1}: ")
                field.setValue(value)
                if self._hook_rotation_unit_label is not None:
                    self._hook_rotation_unit_label.show()
            field.blockSignals(previous)

    def _fixador_changed(self, fixador: str) -> None:
        self._input_changed()
        self._draft_parameters["fixador"] = fixador
        if fixador == "Gancho":
            self._draft_parameters.setdefault("perna_mm", 200.0)
            for index, heading in enumerate(default_hook_headings(self._draft_parameters)):
                self._draft_parameters.setdefault(
                    f"rotacao_global_gancho_{index}_deg",
                    heading,
                )
        else:
            self._draft_parameters.pop("perna_mm", None)
            self._draft_parameters.pop("rotacao_gancho_deg", None)
        if self._current_definition is not None:
            self._show_parameters(self._current_definition.parameters, self._draft_parameters)
        self._update_preview()

    def _update_preview(self) -> None:
        self.preview.set_component(self._draft_component_id, self._draft_parameters)

    def _apply_component(self) -> None:
        if self._draft_component_id is None:
            assignment = None
        else:
            parameters = tuple(
                (key, value) for key, value in self._draft_parameters.items()
                if key != "rotacao_gancho_deg"
                and (
                    key != "perna_mm"
                    and not key.startswith("rotacao_gancho_")
                    and not key.startswith("rotacao_global_gancho_")
                    or self._draft_parameters.get("fixador") == "Gancho"
                )
            )
            assignment = NodeComponentAssignment(self._draft_component_id, parameters)
        current = self.window.model.nodes[self.node_name].component
        if current != assignment:
            try:
                self.window.model.update_node_component(self.node_name, assignment)
            except (TypeError, ValueError) as error:
                QMessageBox.warning(self, "Componente inválido", str(error))
                return
            self.window.refresh_scene()
        self.accept()

    def done(self, result: int) -> None:
        if not self._preview_shutdown:
            self._preview_shutdown = True
            self.preview.shutdown()
        super().done(result)
