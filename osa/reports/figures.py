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
    "top": View(-90.0, 90.0),
    "front": View(-90.0, 0.0),
    "side": View(0.0, 0.0),
}


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
) -> Path:
    """Desenha o modelo indeformado; opcionalmente colore as barras pela situação no ELU."""
    import matplotlib
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D

    view = view or default_view(model)
    polylines = _member_polylines(model)
    plates = _plate_polygons(model)
    points = np.vstack([line for _, line, _ in polylines] + [line for line, _ in plates] or [np.zeros((1, 3))])
    projected_all = view.project(points)
    span = np.ptp(projected_all, axis=0)
    aspect = float(span[1] / span[0]) if span[0] > 0 else 0.6
    with matplotlib.rc_context(_RC):
        figure = _figure(aspect, max_height_cm)
        axes = _setup_axes(figure, projected_all, colorbar=False, bottom=0.08 if member_status else None)
        from matplotlib.patches import Polygon

        for line, _ in plates:
            axes.add_patch(Polygon(
                view.project(line[:-1]), closed=True, facecolor="#d0d7de", edgecolor="#8c959f",
                linewidth=0.4, alpha=0.6, zorder=0,
            ))
        segments, colors = [], []
        for name, line, _ in polylines:
            projected = view.project(line[[0, -1]])
            segments.append(projected)
            status = (member_status or {}).get(name, "none" if member_status else "")
            colors.append(STATUS_COLORS.get(status, "#24292f"))
        if segments:
            axes.add_collection(LineCollection(segments, colors=colors, linewidths=0.75, capstyle="round"))
        _draw_supports(axes, model, view)
        if member_status:
            present = [key for key in ("ok", "fail", "none") if key in set(member_status.values()) or (
                key == "none" and len(member_status) < len(model.bars)
            )]
            labels = {"ok": "Atende ao ELU", "fail": "Não atende ao ELU", "none": "Sem verificação"}
            axes.legend(
                handles=[Line2D([0], [0], color=STATUS_COLORS[key], lw=1.5) for key in present],
                labels=[labels[key] for key in present], loc="upper center", bbox_to_anchor=(0.5, 0.0),
                ncol=len(present), fontsize=7, frameon=False,
            )
        if view.elevation < 89.0:
            _draw_triad(figure, view)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, format=destination.suffix.lstrip(".") or "pdf")
    return destination
