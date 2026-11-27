"""Figuras vetoriais do laudo geradas diretamente dos dados do modelo.

As deformadas e vistas do modelo são desenhadas com matplotlib (backend
sem janela) a partir das coordenadas dos nós e dos deslocamentos amostrados
ao longo das barras, em vez de capturas de tela da interface. O resultado é
um PDF vetorial que o LaTeX inclui com qualidade de impressão.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import cos, radians, sin
from pathlib import Path

import numpy as np

# Escala de cores semelhante à usada por programas de cálculo estrutural:
# roxo/azul para deslocamentos pequenos, verde no meio e vermelho no máximo.
_DISPLACEMENT_COLORS = (
    "#4b1f7a", "#2b3fc4", "#1c8fe0", "#19c3d6", "#17a589",
    "#1e8449", "#a9c41c", "#f1c40f", "#f39c12", "#e74c3c", "#7b1010",
)
STATUS_COLORS = {"ok": "#1E8449", "fail": "#C0392B", "none": "#8c959f"}
_TEXT_WIDTH_CM = 16.6
_CM = 1.0 / 2.54

_RC = {
    "font.family": "serif",
    # O cmr10 do matplotlib não tem acentos; o STIX (incluído no matplotlib)
    # é a alternativa com Unicode completo quando não há Latin Modern/CMU.
    "font.serif": ["Latin Modern Roman", "CMU Serif", "STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "axes.unicode_minus": False,
    "font.size": 8,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
}


@dataclass(frozen=True)
class View:
    """Projeção ortográfica definida por azimute e elevação da câmera (graus)."""

    azimuth: float = -55.0
    elevation: float = 28.0

    def axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        az, el = radians(self.azimuth), radians(self.elevation)
        towards_camera = np.array((cos(el) * cos(az), cos(el) * sin(az), sin(el)))
        forward = -towards_camera
        up_reference = np.array((0.0, 0.0, 1.0)) if abs(sin(el)) < 0.999 else np.array((0.0, 1.0, 0.0))
        right = np.cross(forward, up_reference)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return right, up, forward

    def project(self, points: np.ndarray) -> np.ndarray:
        right, up, _ = self.axes()
        return np.column_stack((points @ right, points @ up))


VIEWS = {
    "iso": View(-55.0, 28.0),
    "iso_se": View(-45.0, 35.26438968),
    "top": View(-90.0, 90.0),
    "front": View(-90.0, 0.0),
    "side": View(0.0, 0.0),
}


def cover_view(direction: str) -> View:
    """Camera matching one of the four detailing isometric directions."""
    return {
        "ISO-SE": View(-45.0, 35.26438968),
        "ISO-NE": View(45.0, 35.26438968),
        "ISO-NW": View(135.0, 35.26438968),
        "ISO-SW": View(-135.0, 35.26438968),
    }.get(str(direction), VIEWS["iso_se"])


def _model_points(model) -> np.ndarray:
    points = [(node.x, node.y, node.z) for node in model.nodes.values()]
    for plate in getattr(model, "plates", {}).values():
        points.extend(plate.contour)
    return np.array(points, dtype=float).reshape(-1, 3)


def default_view(model) -> View:
    """Escolhe a vista: isométrica, ou a elevação quando o modelo é plano."""
    coordinates = _model_points(model)
    if len(coordinates) == 0:
        return VIEWS["iso"]
    extent = np.ptp(coordinates, axis=0)
    size = float(extent.max()) or 1.0
    if extent[1] <= 1e-6 * size and extent[2] > 1e-6 * size:
        return VIEWS["front"]
    if extent[0] <= 1e-6 * size and extent[2] > 1e-6 * size:
        return VIEWS["side"]
    return VIEWS["iso"]


def _figure(aspect: float, max_height_cm: float = 11.5):
    from matplotlib.figure import Figure

    width = _TEXT_WIDTH_CM
    height = min(max(width * aspect, 5.0), max_height_cm)
    figure = Figure(figsize=(width * _CM, height * _CM))
    return figure


def _member_polylines(model, member_results: Mapping | None = None, scale: float = 0.0):
    """Retorna, por barra, os pontos (indeformados ou deformados) e |u| em cada ponto."""
    lines = []
    for name, bar in model.bars.items():
        start, end = model.nodes.get(bar.start_node), model.nodes.get(bar.end_node)
        if start is None or end is None:
            continue
        p0 = np.array((start.x, start.y, start.z), dtype=float)
        p1 = np.array((end.x, end.y, end.z), dtype=float)
        length = float(np.linalg.norm(p1 - p0)) or 1.0
        result = (member_results or {}).get(name)
        samples = (result or {}).get("samples") or ()
        if samples:
            fractions = np.array([float(item.get("x", 0.0)) / length for item in samples])
            displacement = np.array([
                (item.get("deflection_x", 0.0), item.get("deflection_y", 0.0), item.get("deflection_z", 0.0))
                for item in samples
            ], dtype=float)
        else:
            fractions = np.array((0.0, 1.0))
            displacement = np.zeros((2, 3))
        base = p0 + np.outer(np.clip(fractions, 0.0, 1.0), p1 - p0)
        lines.append((name, base + scale * displacement, np.linalg.norm(displacement, axis=1)))
    return lines


def _plate_polygons(model, result=None, scale: float = 0.0):
    """Contornos das placas (indeformados) ou elementos da malha deformados, com |u| por vértice."""
    polygons = []
    plate_results = getattr(result, "plate_results", None) or {} if result is not None else {}
    if result is None:
        for plate in getattr(model, "plates", {}).values():
            contour = np.array(plate.contour, dtype=float)
            if len(contour) >= 3:
                polygons.append((np.vstack((contour, contour[:1])), np.zeros(len(contour) + 1)))
        return polygons
    for plate_result in plate_results.values():
        nodes = plate_result.get("nodes", {})
        for element in plate_result.get("elements", {}).values():
            names = [name for name in element.get("nodes", ()) if name in nodes]
            if len(names) < 3:
                continue
            base = np.array([nodes[name]["coordinates"] for name in names], dtype=float)
            displacement = np.array(
                [(nodes[name].get("DX", 0.0), nodes[name].get("DY", 0.0), nodes[name].get("DZ", 0.0)) for name in names],
                dtype=float,
            )
            points = base + scale * displacement
            magnitudes = np.linalg.norm(displacement, axis=1)
            polygons.append((np.vstack((points, points[:1])), np.append(magnitudes, magnitudes[0])))
    return polygons


def _node_displacements(model, node_results: Mapping) -> dict[str, np.ndarray]:
    return {
        name: np.array((values.get("DX", 0.0), values.get("DY", 0.0), values.get("DZ", 0.0)), dtype=float)
        for name, values in node_results.items() if name in model.nodes
    }


def displacement_peak(model, result) -> tuple[float, str | None, np.ndarray | None, np.ndarray | None]:
    """Maior deslocamento total (m), onde ocorre (nó ou barra), ponto original e vetor deslocamento."""
    best, label, base, vector = 0.0, None, None, None
    for name, displacement in _node_displacements(model, result.node_results).items():
        magnitude = float(np.linalg.norm(displacement))
        if magnitude > best:
            node = model.nodes[name]
            best, label = magnitude, f"nó {name}"
            base, vector = np.array((node.x, node.y, node.z), dtype=float), displacement
    for name, points, magnitudes in _member_polylines(model, result.member_results, 1.0):
        if len(magnitudes) and float(magnitudes.max()) > best * (1.0 + 1e-9):
            index = int(magnitudes.argmax())
            start, end = model.nodes[model.bars[name].start_node], model.nodes[model.bars[name].end_node]
            fraction = index / max(len(magnitudes) - 1, 1)
            origin = np.array((start.x, start.y, start.z)) + fraction * (
                np.array((end.x, end.y, end.z)) - np.array((start.x, start.y, start.z))
            )
            best, label = float(magnitudes[index]), f"barra {name}"
            base, vector = origin, points[index] - origin
    for points, magnitudes in _plate_polygons(model, result, 1.0):
        if len(magnitudes) and float(magnitudes.max()) > best * (1.0 + 1e-9):
            best, label, base, vector = float(magnitudes.max()), "placa", None, None
    return best, label, base, vector


def max_displacement(model, result) -> tuple[float, str | None]:
    """Maior deslocamento total (m) e onde ocorre."""
    value, label, *_ = displacement_peak(model, result)
    return value, label


def nice_scale_factor(model, max_displacement_m: float, target_ratio: float = 0.06) -> float:
    """Fator de escala "redondo" para o maior deslocamento ocupar ~6 % do modelo."""
    coordinates = _model_points(model)
    size = float(np.ptp(coordinates, axis=0).max()) if len(coordinates) else 1.0
    if max_displacement_m <= 0.0 or size <= 0.0:
        return 1.0
    raw = target_ratio * size / max_displacement_m
    magnitude = 10.0 ** np.floor(np.log10(raw))
    for step in (1.0, 2.0, 5.0, 10.0):
        if raw <= step * magnitude * 1.5:
            return float(step * magnitude)
    return float(10.0 * magnitude)


def _decimal(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _setup_axes(figure, projected: np.ndarray, colorbar: bool, bottom: float | None = None):
    bottom = bottom if bottom is not None else 0.17 if colorbar else 0.02
    axes = figure.add_axes((0.01, bottom, 0.98, 0.98 - bottom))
    axes.set_axis_off()
    axes.set_aspect("equal", adjustable="datalim")
    if len(projected):
        # Com aspecto igual, só os limites de dados são informados; o
        # matplotlib ajusta o outro eixo sem avisos de limites conflitantes.
        low, high = projected.min(axis=0), projected.max(axis=0)
        margin = 0.04 * float(np.maximum(high - low, 1e-6).max())
        axes.update_datalim(np.array((low - margin, high + margin)))
        axes.autoscale_view()
    return axes


def _draw_triad(figure, view: View) -> None:
    """Pequeno sistema de eixos globais no canto inferior esquerdo."""
    triad = figure.add_axes((0.005, 0.005, 0.07, 0.12))
    triad.set_axis_off()
    triad.set_aspect("equal")
    triad.set_xlim(-1.3, 1.3)
    triad.set_ylim(-1.3, 1.3)
    origin = np.zeros(2)
    for vector, label, color in (
        ((1.0, 0.0, 0.0), "X", "#C0392B"), ((0.0, 1.0, 0.0), "Y", "#1E8449"), ((0.0, 0.0, 1.0), "Z", "#2b3fc4"),
    ):
        tip = view.project(np.array([vector], dtype=float))[0]
        if np.linalg.norm(tip) < 0.15:
            triad.plot([0], [0], marker="o", markersize=2.5, color=color)
            triad.text(0.15, 0.15, label, color=color, fontsize=6)
            continue
        triad.annotate(
            "", xy=tip, xytext=origin,
            arrowprops={"arrowstyle": "-|>", "color": color, "lw": 0.8, "mutation_scale": 6},
        )
        triad.text(*(tip * 1.25), label, color=color, fontsize=6, ha="center", va="center")


def _draw_supports(axes, model, view: View) -> None:
    supported = [
        (node.x, node.y, node.z) for node in model.nodes.values()
        if any(node.supports) or any(value > 0.0 for value in getattr(node, "support_stiffness", ()))
    ]
    if supported:
        projected = view.project(np.array(supported, dtype=float))
        axes.scatter(
            projected[:, 0], projected[:, 1], marker="^", s=9, facecolors="none",
            edgecolors="#57606a", linewidths=0.5, zorder=4,
        )


def render_deformed_shape(
    model,
    result,
    destination: str | Path,
    *,
    scale: float | None = None,
    view: View | None = None,
) -> dict[str, float | str | None]:
    """Desenha a deformada de uma combinação colorida pelo deslocamento total (mm)."""
    import matplotlib
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    view = view or default_view(model)
    maximum_m, maximum_label, peak_base, peak_vector = displacement_peak(model, result)
    scale = float(scale) if scale else nice_scale_factor(model, maximum_m)
    undeformed = _member_polylines(model) + [("", points, values) for points, values in _plate_polygons(model)]
    deformed = _member_polylines(model, result.member_results, scale) + [
        ("", points, values) for points, values in _plate_polygons(model, result, scale)
    ]
    all_points = np.vstack([points for _, points, _ in undeformed + deformed] or [np.zeros((1, 3))])
    projected_all = view.project(all_points)
    span = np.ptp(projected_all, axis=0)
    aspect = float(span[1] / span[0]) if span[0] > 0 else 0.6

    maximum_mm = maximum_m * 1000.0
    colormap = LinearSegmentedColormap.from_list("osa_deslocamentos", _DISPLACEMENT_COLORS)
    norm = Normalize(vmin=0.0, vmax=maximum_mm if maximum_mm > 0 else 1.0)

    with matplotlib.rc_context(_RC):
        figure = _figure(aspect * 0.83 + 0.17)
        axes = _setup_axes(figure, projected_all, colorbar=True)
        base_segments = [
            np.column_stack((view.project(points)[:-1], view.project(points)[1:])).reshape(-1, 2, 2)
            for _, points, _ in undeformed
        ]
        if base_segments:
            axes.add_collection(LineCollection(
                np.concatenate(base_segments), colors="#c9d1d9", linewidths=0.35, zorder=1,
            ))
        segments, values = [], []
        for _, points, magnitudes in deformed:
            projected = view.project(points)
            segments.append(np.stack((projected[:-1], projected[1:]), axis=1))
            values.append(0.5 * (magnitudes[:-1] + magnitudes[1:]) * 1000.0)
        if segments:
            collection = LineCollection(
                np.concatenate(segments), cmap=colormap, norm=norm, linewidths=0.8, zorder=2,
                capstyle="round",
            )
            collection.set_array(np.concatenate(values))
            axes.add_collection(collection)
        _draw_supports(axes, model, view)
        if peak_base is not None and maximum_mm > 0:
            position = view.project(np.array([peak_base + scale * peak_vector]))[0]
            axes.scatter([position[0]], [position[1]], s=10, color="#24292f", zorder=5)
            axes.annotate(
                f"máx. {_decimal(maximum_mm, 2)} mm", xy=position, xytext=(6, 6),
                textcoords="offset points", fontsize=7, color="#24292f", zorder=6,
            )
        colorbar_axes = figure.add_axes((0.12, 0.075, 0.82, 0.035))
        from matplotlib.cm import ScalarMappable

        mappable = ScalarMappable(norm=norm, cmap=colormap)
        colorbar = figure.colorbar(mappable, cax=colorbar_axes, orientation="horizontal")
        ticks = np.linspace(0.0, norm.vmax, 9)
        decimals = 2 if norm.vmax < 10 else 1
        colorbar.set_ticks(ticks, labels=[_decimal(value, decimals) for value in ticks])
        colorbar.ax.tick_params(labelsize=6.5, length=2, width=0.4)
        colorbar.outline.set_linewidth(0.4)
        colorbar.set_label("Deslocamento total (mm)", fontsize=7, labelpad=2)
        _draw_triad(figure, view)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, format=destination.suffix.lstrip(".") or "pdf")
    return {"max_mm": maximum_mm, "location": maximum_label, "scale": scale}


def render_model_view(
    model,
    destination: str | Path,
    *,
    view: View | None = None,
    member_status: Mapping[str, str] | None = None,
    max_height_cm: float = 11.5,
    model_mode: str = "analytic",
    show_global_axes: bool = True,
    cover_rendering: bool = False,
    support_mesh=None,
    cover_model_image: str | Path | None = None,
) -> Path:
    """Desenha o modelo da capa com cores dos elementos, sem indicação de verificação."""
    destination = Path(destination)
    if (
        cover_rendering and model_mode == "executive"
        and cover_model_image is not None and Path(cover_model_image).is_file()
    ):
        from matplotlib.figure import Figure
        from matplotlib.image import imread

        figure = Figure(figsize=(15.0 * _CM, 10.0 * _CM), dpi=300)
        axes = figure.add_axes((0.0, 0.0, 1.0, 1.0))
        axes.imshow(imread(cover_model_image))
        axes.set_axis_off()
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, format=destination.suffix.lstrip(".") or "pdf")
        return destination
    import matplotlib
    from matplotlib.collections import LineCollection
    from matplotlib.collections import PolyCollection

    view = view or default_view(model)
    polylines = _member_polylines(model)
    plates = _plate_polygons(model)
    components = (
        _cover_component_meshes(
            model,
            include_stair_components=True,
            support_mesh=support_mesh,
        )
        if cover_rendering and model_mode == "executive" else []
    )
    groups = [line for _, line, _ in polylines] + [line for line, _ in plates]
    groups.extend(mesh.points for mesh, _ in components if mesh.n_points)
    projected_groups = [view.project(points) for points in groups if len(points)]
    projected_all = np.vstack(projected_groups or [np.zeros((1, 2))])
    span = np.ptp(projected_all, axis=0)
    aspect = float(span[1] / span[0]) if span[0] > 0 else 0.6
    with matplotlib.rc_context(_RC):
        figure = _figure(aspect, max_height_cm)
        axes = _setup_axes(figure, projected_all, colorbar=False, bottom=0.08 if member_status else None)
        from matplotlib.patches import Polygon

        for index, (line, _values) in enumerate(plates):
            plate_color = (
                list(getattr(model, "plates", {}).values())[index].color
                if cover_rendering else "#d0d7de"
            )
            axes.add_patch(Polygon(
                view.project(line[:-1]), closed=True, facecolor=plate_color, edgecolor="#8c959f",
                linewidth=0.4, alpha=0.6, zorder=0,
            ))
        segments, colors = [], []
        for name, line, _ in polylines:
            segments.append(view.project(line[[0, -1]]))
            if member_status:
                colors.append(STATUS_COLORS.get(member_status.get(name, "none"), "#24292f"))
            else:
                colors.append(
                    getattr(model.bars.get(name), "color", "#24292f")
                    if cover_rendering else "#24292f"
                )
        if segments:
            axes.add_collection(LineCollection(segments, colors=colors, linewidths=1.0, capstyle="round"))
        if cover_rendering:
            _draw_projected_meshes(axes, components, view, PolyCollection, zorder=3)
        else:
            _draw_supports(axes, model, view)
        if member_status:
            from matplotlib.lines import Line2D

            present = [key for key in ("ok", "fail", "none") if key in set(member_status.values()) or (
                key == "none" and len(member_status) < len(model.bars)
            )]
            labels = {"ok": "Atende ao ELU", "fail": "Não atende ao ELU", "none": "Sem verificação"}
            axes.legend(
                handles=[Line2D([0], [0], color=STATUS_COLORS[key], lw=1.5) for key in present],
                labels=[labels[key] for key in present], loc="upper center", bbox_to_anchor=(0.5, 0.0),
                ncol=len(present), fontsize=7, frameon=False,
            )
        if show_global_axes and view.elevation < 89.0:
            _draw_triad(figure, view)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, format=destination.suffix.lstrip(".") or "pdf")
    return destination


def render_executive_model_image(
    model, direction: str, destination: str | Path, *, support_mesh=None,
) -> Path:
    """Render one cover direction with the same solid colors and depth buffer as the model view."""
    from types import SimpleNamespace

    import pyvista as pv

    from osa.rendering.batched_renderer import (
        BatchedRigidBarRenderer, BatchedMemberRenderer,
    )
    from osa.rendering.node_component_renderer import (
        STAIR_WOOD_COLOR, STAIR_WOOD_EDGE_COLOR, stair_wood_edge_mesh,
    )
    from osa.rendering.solid_member_renderer import SolidMemberRenderer
    from osa.ui.detailing_viewport import _DetachedDetailingScene

    directions = {
        "ISO-SE": (1.0, -1.0, 1.0),
        "ISO-NE": (1.0, 1.0, 1.0),
        "ISO-NW": (-1.0, 1.0, 1.0),
        "ISO-SW": (-1.0, -1.0, 1.0),
    }
    direction = str(direction) if str(direction) in directions else "ISO-SE"
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)

    detail_scene = _DetachedDetailingScene(
        SimpleNamespace(_marker_radius_current=0.05)
    )
    solids = list(detail_scene.detailing_view_solid_meshes(model))
    # The executive cover shows physical components. Analytical restraint
    # glyphs overlap the anchors below base plates and look like protrusions
    # on their bends. Never overlay them on the physical detailing solids.

    plotter = pv.Plotter(off_screen=True, window_size=(1500, 1000))
    plotter.set_background("white")
    points_for_bounds = []
    face_groups: dict[str, list] = {}
    edge_groups: dict[str, list] = {}
    silhouettes = []

    def add_face(mesh, color):
        if mesh is not None and mesh.n_points and mesh.n_cells:
            face_groups.setdefault(str(color), []).append(mesh)
            points_for_bounds.append(np.asarray(mesh.points, dtype=float))

    def add_edges(mesh, color, *, silhouette=False):
        if mesh is None or not mesh.n_points or not mesh.n_cells:
            return
        if not isinstance(color, str):
            channels = np.clip(np.asarray(color, dtype=float), 0.0, 1.0)
            color = "#" + "".join(f"{round(channel * 255):02x}" for channel in channels[:3])
        edges = mesh.extract_feature_edges(
            boundary_edges=True, feature_edges=True,
            manifold_edges=False, non_manifold_edges=False, feature_angle=25.0,
        )
        if edges.n_lines:
            edge_groups.setdefault(str(color), []).append(edges)
        if silhouette:
            silhouettes.append((mesh, str(color)))

    edge_color = SolidMemberRenderer.edge_color
    for name, mesh in solids:
        if not mesh.n_points or not mesh.n_cells:
            continue
        if name.startswith("plate:"):
            owner = getattr(model, "plates", {}).get(name.partition(":")[2])
            color = getattr(owner, "color", "#8c959f")
            add_face(mesh, color)
            add_edges(mesh, "#6e7781")
        elif name.startswith("component:"):
            color = STAIR_WOOD_COLOR if name.endswith(":wood") else "#8c959f"
            add_face(mesh, color)
            if name.endswith(":wood"):
                node_name = name.split(":", 2)[1]
                node = model.nodes.get(node_name)
                if node is not None and getattr(node, "component", None) is not None:
                    wood_edges = stair_wood_edge_mesh(
                        dict(node.component.parameters), (node.x, node.y, node.z),
                    )
                    if wood_edges.n_lines:
                        edge_groups.setdefault(STAIR_WOOD_EDGE_COLOR, []).append(wood_edges)
            elif ":rod:" in name:
                add_edges(mesh, "#57606a", silhouette=True)
            else:
                add_edges(mesh, "#57606a")
        else:
            owner = getattr(model, "bars", {}).get(name)
            color = getattr(owner, "color", "#24292f")
            add_face(mesh, color)
            add_edges(
                mesh,
                edge_color(color),
                silhouette=bool(owner and owner.section in BatchedMemberRenderer._silhouette_sections),
            )
    if getattr(model, "rigid_bars", None):
        _names, rigid_lines = BatchedRigidBarRenderer().build(model)
        if rigid_lines.n_cells:
            points_for_bounds.append(np.asarray(rigid_lines.points, dtype=float))
            plotter.add_mesh(
                rigid_lines, color=BatchedRigidBarRenderer.COLOR, line_width=1.2,
                lighting=False, pickable=False, reset_camera=False, render=False,
            )
    if points_for_bounds:
        bounds_points = np.vstack(points_for_bounds)
        low, high = bounds_points.min(axis=0), bounds_points.max(axis=0)
        center = (low + high) / 2.0
        span = max(float(np.ptp(bounds_points, axis=0).max()), 1e-3)
    else:
        center, span = np.zeros(3), 1.0
    camera_direction = np.asarray(directions[direction], dtype=float)
    camera_direction /= np.linalg.norm(camera_direction)
    plotter.camera_position = (
        center + camera_direction * span * 4.0,
        center,
        (0.0, 0.0, 1.0),
    )
    plotter.camera.parallel_projection = True
    plotter.camera.parallel_scale = span * 0.50
    camera = plotter.renderer.GetActiveCamera()
    for mesh, color in silhouettes:
        silhouette = SolidMemberRenderer.silhouette_for(mesh, camera)
        if silhouette.n_lines:
            edge_groups.setdefault(color, []).append(silhouette)
    for color, meshes in face_groups.items():
        combined = pv.merge(meshes, merge_points=False) if len(meshes) > 1 else meshes[0]
        plotter.add_mesh(
            combined, color=color, lighting=False, smooth_shading=False,
            ambient=0.25, diffuse=0.75, specular=0.12,
            pickable=False, reset_camera=False, render=False,
        )
    for color, meshes in edge_groups.items():
        combined = pv.merge(meshes, merge_points=False) if len(meshes) > 1 else meshes[0]
        actor = plotter.add_mesh(
            combined, color=color, line_width=1.0, lighting=False,
            pickable=False, reset_camera=False, render=False,
        )
        mapper = actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
    # Faces are added after the camera is placed. Recompute depth clipping
    # from the complete scene, including when no support glyph actors exist.
    plotter.reset_camera_clipping_range()
    try:
        plotter.show(
            auto_close=False, interactive=False, screenshot=str(target),
            window_size=(1500, 1000),
        )
    finally:
        plotter.close()
    return target


def _cover_component_meshes(model, *, include_stair_components: bool, support_mesh=None):
    """Build assigned 3D node components for the memorial cover."""
    from osa.rendering.batched_renderer import BatchedNodeRenderer
    from osa.rendering.node_component_renderer import (
        STAIR_WOOD_COLOR, _orient_base_plate_mesh, stair_plate_mesh, stair_wood_mesh,
    )
    import pyvista as pv

    meshes = []
    if support_mesh is None:
        support_mesh = BatchedNodeRenderer(glyphs=True).build_supports(model, 0.05)
    if support_mesh.n_cells:
        # The live support glyphs are intentionally detailed for close-up
        # interaction. At cover scale, most of those facets are sub-pixel and
        # make vector PDF export needlessly expensive; retain their 3D shape
        # while reducing the mesh before projecting it.
        support_mesh = support_mesh.triangulate().decimate_pro(0.9)
        meshes.append((support_mesh, "#a8b0b9"))
    for node in model.nodes.values():
        assignment = getattr(node, "component", None)
        if assignment is None:
            continue
        parameters = dict(assignment.parameters)
        origin = (node.x, node.y, node.z)
        try:
            if assignment.component_id == "base_plate":
                width = float(parameters.get("largura_mm", 300.0)) / 1000.0
                length = float(parameters.get("comprimento_mm", 300.0)) / 1000.0
                thickness = float(parameters.get("espessura_mm", 20.0)) / 1000.0
                rotation = float(parameters.get("rotacao_deg", 0.0))
                displacement_a = float(parameters.get("deslocamento_a_mm", 0.0)) / 1000.0
                displacement_b = float(parameters.get("deslocamento_b_mm", 0.0)) / 1000.0
                cosine, sine = np.cos(np.radians(rotation)), np.sin(np.radians(rotation))
                center_x = node.x + displacement_a * cosine - displacement_b * sine
                center_y = node.y + displacement_a * sine + displacement_b * cosine
                plate = pv.Cube(
                    center=(center_x, center_y, node.z + thickness / 2.0),
                    x_length=width, y_length=length, z_length=thickness,
                )
                if rotation:
                    plate.rotate_z(rotation, point=(center_x, center_y, node.z), inplace=True)
                _orient_base_plate_mesh(plate, origin, str(parameters.get("plano", "XY+")))
                meshes.append((plate, "#8c959f"))
            elif include_stair_components and assignment.component_id == "stair_plate":
                meshes.append((stair_plate_mesh(parameters, origin), "#8c959f"))
                wood = stair_wood_mesh(parameters, origin)
                if wood.n_points:
                    meshes.append((wood, STAIR_WOOD_COLOR))
        except (TypeError, ValueError, OverflowError):
            continue
    return meshes


def _draw_projected_meshes(axes, meshes, view, collection_type, *, zorder=2):
    polygons, colors, depths = [], [], []
    towards_camera = view.axes()[2]
    for mesh, color in meshes:
        cells = np.asarray(mesh.faces, dtype=np.int64)
        if not len(cells):
            continue
        points = np.asarray(mesh.points, dtype=float)
        projected_points = view.project(points)
        cursor = 0
        while cursor < len(cells):
            count = int(cells[cursor])
            ids = cells[cursor + 1:cursor + count + 1]
            cursor += count + 1
            polygons.append(projected_points[ids])
            colors.append(color)
            depths.append(float(np.mean(points[ids] @ towards_camera)))
    if not polygons:
        return
    order = np.argsort(depths)
    axes.add_collection(collection_type(
        [polygons[index] for index in order],
        facecolors=[colors[index] for index in order],
        edgecolors="#57606a", linewidths=0.12, zorder=zorder,
    ))
