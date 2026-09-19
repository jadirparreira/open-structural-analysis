"""Propriedades de seções idealizadas para elementos de barra.

As geometrias são definidas em milímetros. Os resultados permanecem em mm² e
mm⁴ até a conversão explícita feita pelo adaptador do solver.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot, pi
from typing import Mapping

from .contours import contour_points, polygon_properties


@dataclass(frozen=True, slots=True)
class SectionProperties:
    """Propriedades geométricas necessárias ao elemento de barra do PyNite."""

    area_mm2: float
    centroid_y_mm: float
    centroid_z_mm: float
    iy_mm4: float
    iz_mm4: float
    iyz_mm4: float
    i_major_mm4: float
    i_minor_mm4: float
    principal_axis_angle_deg: float
    j_mm4: float
    mass_kg_m: float

    @property
    def area_cm2(self) -> float:
        return self.area_mm2 / 100.0

    @property
    def iy_cm4(self) -> float:
        return self.iy_mm4 / 10_000.0

    @property
    def iz_cm4(self) -> float:
        return self.iz_mm4 / 10_000.0

    @property
    def j_cm4(self) -> float:
        return self.j_mm4 / 10_000.0


@dataclass(frozen=True, slots=True)
class _Rectangle:
    width_mm: float
    height_mm: float
    centroid_y_mm: float
    centroid_z_mm: float

    @property
    def area_mm2(self) -> float:
        return self.width_mm * self.height_mm

    @property
    def iy_mm4(self) -> float:
        return self.width_mm * self.height_mm**3 / 12.0

    @property
    def iz_mm4(self) -> float:
        return self.height_mm * self.width_mm**3 / 12.0


def _positive(parameters: Mapping[str, float], name: str) -> float:
    try:
        value = float(parameters[name])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Informe um valor numérico para '{name}'.") from error
    if value <= 0:
        raise ValueError(f"'{name}' deve ser maior que zero.")
    return value


def _properties_from_rectangles(
    rectangles: tuple[_Rectangle, ...],
    j_mm4: float,
    density_kg_m3: float,
) -> SectionProperties:
    area = sum(item.area_mm2 for item in rectangles)
    centroid_y = sum(item.area_mm2 * item.centroid_y_mm for item in rectangles) / area
    centroid_z = sum(item.area_mm2 * item.centroid_z_mm for item in rectangles) / area
    iy = sum(item.iy_mm4 + item.area_mm2 * (item.centroid_z_mm - centroid_z) ** 2 for item in rectangles)
    iz = sum(item.iz_mm4 + item.area_mm2 * (item.centroid_y_mm - centroid_y) ** 2 for item in rectangles)
    iyz = sum(
        item.area_mm2 * (item.centroid_y_mm - centroid_y) * (item.centroid_z_mm - centroid_z)
        for item in rectangles
    )
    mean = (iy + iz) / 2.0
    radius = hypot((iy - iz) / 2.0, iyz)
    i_major, i_minor = mean + radius, mean - radius
    principal_angle = degrees(0.5 * atan2(-2.0 * iyz, iy - iz))
    mass = area * 1e-6 * density_kg_m3
    return SectionProperties(
        area_mm2=area,
        centroid_y_mm=centroid_y,
        centroid_z_mm=centroid_z,
        iy_mm4=iy,
        iz_mm4=iz,
        iyz_mm4=iyz,
        i_major_mm4=i_major,
        i_minor_mm4=i_minor,
        principal_axis_angle_deg=principal_angle,
        j_mm4=j_mm4,
        mass_kg_m=mass,
    )


def _open_wall_torsion(*segments: tuple[float, float]) -> float:
    """Constante de torção de Saint-Venant para paredes abertas delgadas.

    Cada segmento é informado como ``(comprimento, espessura)`` em mm. A
    aproximação é apropriada às seções idealizadas por chapas retangulares.
    """
    return sum(length * thickness**3 / 3.0 for length, thickness in segments)


def _properties_from_contour(
    family: str,
    geometry: Mapping[str, float],
    j_mm4: float,
    density_kg_m3: float,
) -> SectionProperties:
    points = contour_points(family, dict(geometry), arc_steps=16)
    if points is None:
        raise ValueError(f"Contorno de referência indisponível para '{family}'.")
    area, centroid_y, centroid_z, iy, iz, iyz = polygon_properties(points)
    mean = (iy + iz) / 2.0
    radius = hypot((iy - iz) / 2.0, iyz)
    i_major, i_minor = mean + radius, mean - radius
    principal_angle = degrees(0.5 * atan2(-2.0 * iyz, iy - iz))
    return SectionProperties(
        area_mm2=area,
        centroid_y_mm=centroid_y,
        centroid_z_mm=centroid_z,
        iy_mm4=iy,
        iz_mm4=iz,
        iyz_mm4=iyz,
        i_major_mm4=i_major,
        i_minor_mm4=i_minor,
        principal_axis_angle_deg=principal_angle,
        j_mm4=j_mm4,
        mass_kg_m=area * 1e-6 * density_kg_m3,
    )


def _w(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    tw = _positive(parameters, "tw")
    tf = _positive(parameters, "tf")
    if d <= 2.0 * tf or bf <= tw:
        raise ValueError("A geometria requer d > 2 tf e bf > tw.")
    j = _open_wall_torsion((bf, tf), (d - 2.0 * tf, tw), (bf, tf))
    return _properties_from_contour("W Laminado", parameters, j, density_kg_m3)


def _u(
    parameters: Mapping[str, float],
    density_kg_m3: float,
    family: str = "U Inclinado Laminado",
) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    tw = _positive(parameters, "tw")
    tf = _positive(parameters, "tf")
    if d <= 2.0 * tf or bf <= tw:
        raise ValueError("A geometria requer d > 2 tf e bf > tw.")
    j = _open_wall_torsion((bf, tf), (d - 2.0 * tf, tw), (bf, tf))
    return _properties_from_contour(family, parameters, j, density_kg_m3)


def _i(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    tw = _positive(parameters, "tw")
    tf = _positive(parameters, "tf")
    if d <= 2.0 * tf or bf <= tw:
        raise ValueError("A geometria requer d > 2 tf e bf > tw.")
    j = _open_wall_torsion((bf, tf), (d - 2.0 * tf, tw), (bf, tf))
    return _properties_from_contour("I Laminado", parameters, j, density_kg_m3)


def _t(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf") if "bf" in parameters else d
    tw = _positive(parameters, "tw") if "tw" in parameters else _positive(parameters, "t")
    tf = _positive(parameters, "tf") if "tf" in parameters else tw
    if d <= tf or bf <= tw:
        raise ValueError("A geometria requer d > tf e bf > tw.")
    rectangles = (
        _Rectangle(bf, tf, bf / 2.0, tf / 2.0),
        _Rectangle(tw, d - tf, bf / 2.0, tf + (d - tf) / 2.0),
    )
    j = _open_wall_torsion((bf, tf), (d - tf, tw))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _l(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    b = _positive(parameters, "b")
    t = _positive(parameters, "t")
    if b <= t:
        raise ValueError("A geometria requer b > t.")
    rectangles = (
        _Rectangle(b, t, b / 2.0, t / 2.0),
        _Rectangle(t, b - t, t / 2.0, t + (b - t) / 2.0),
    )
    j = _open_wall_torsion((b, t), (b - t, t))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _l_formed(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    t = _positive(parameters, "t")
    if d <= t or bf <= t:
        raise ValueError("A geometria requer d > t e bf > t.")
    flange = bf - t
    rectangles = (
        _Rectangle(t, d, t / 2.0, d / 2.0),
        _Rectangle(flange, t, t + flange / 2.0, d - t / 2.0),
    )
    j = _open_wall_torsion((d, t), (flange, t))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _u_formed(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    t = _positive(parameters, "t")
    if d <= 4.0 * t or bf <= 2.0 * t:
        raise ValueError("A seção U formada requer d > 4t e bf > 2t.")
    flange = bf - t
    rectangles = (
        _Rectangle(t, d, t / 2.0, d / 2.0),
        _Rectangle(flange, t, t + flange / 2.0, t / 2.0),
        _Rectangle(flange, t, t + flange / 2.0, d - t / 2.0),
    )
    j = _open_wall_torsion((d, t), (flange, t), (flange, t))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _u_stiffened(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    thickness = _positive(parameters, "t")
    tw = tf = thickness
    c = _positive(parameters, "c")
    if d <= 2.0 * (tf + c) or bf <= tw:
        raise ValueError("A seção C formada requer d > 2(t + c) e bf > t.")
    flange = bf - tw
    rectangles = (
        _Rectangle(tw, d, tw / 2.0, d / 2.0),
        _Rectangle(flange, tf, tw + flange / 2.0, tf / 2.0),
        _Rectangle(flange, tf, tw + flange / 2.0, d - tf / 2.0),
        _Rectangle(tf, c, bf - tf / 2.0, tf + c / 2.0),
        _Rectangle(tf, c, bf - tf / 2.0, d - tf - c / 2.0),
    )
    j = _open_wall_torsion(
        (d, tw), (flange, tf), (flange, tf), (c, tf), (c, tf)
    )
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _z(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    thickness = _positive(parameters, "t")
    tw = tf = thickness
    if d <= 4.0 * tf or bf <= 2.0 * tf:
        raise ValueError("A seção Z formada requer d > 4t e bf > 2t.")
    rectangles = (
        _Rectangle(tw, d - 2.0 * tf, tw / 2.0, d / 2.0),
        _Rectangle(bf, tf, -bf / 2.0, tf / 2.0),
        _Rectangle(bf, tf, tw + bf / 2.0, d - tf / 2.0),
    )
    j = _open_wall_torsion((d - 2.0 * tf, tw), (bf, tf), (bf, tf))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _cartola(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    d = _positive(parameters, "d")
    bf = _positive(parameters, "bf")
    thickness = _positive(parameters, "t")
    tw = tf = thickness
    c = _positive(parameters, "c")
    if d <= 4.0 * tf or bf <= 5.0 * tw or c <= 0.0:
        raise ValueError("A seção Cartola requer d > 4t, bf > 5t e c > 0.")
    web_y = bf / 2.0 - tw / 2.0
    rectangles = (
        _Rectangle(bf, tf, 0.0, tf / 2.0),
        _Rectangle(tw, d - 2.0 * tf, -web_y, d / 2.0),
        _Rectangle(tw, d - 2.0 * tf, web_y, d / 2.0),
        _Rectangle(c, tf, -web_y - c / 2.0, d - tf / 2.0),
        _Rectangle(c, tf, web_y + c / 2.0, d - tf / 2.0),
    )
    j = _open_wall_torsion(
        (bf, tf), (d - 2.0 * tf, tw), (d - 2.0 * tf, tw), (c, tf), (c, tf)
    )
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _tube_properties(
    area: float,
    iy: float,
    iz: float,
    j: float,
    density_kg_m3: float,
) -> SectionProperties:
    return SectionProperties(
        area_mm2=area,
        centroid_y_mm=0.0,
        centroid_z_mm=0.0,
        iy_mm4=iy,
        iz_mm4=iz,
        iyz_mm4=0.0,
        i_major_mm4=max(iy, iz),
        i_minor_mm4=min(iy, iz),
        principal_axis_angle_deg=0.0,
        j_mm4=j,
        mass_kg_m=area * 1e-6 * density_kg_m3,
    )


def _closed_rectangular_torsion(width: float, height: float, thickness: float) -> float:
    # Thin-walled closed-section approximation evaluated on the wall
    # centreline. The tube drawings use outer radius 2t and inner radius t,
    # therefore the centreline radius is 1.5t.
    mid_width = width - thickness
    mid_height = height - thickness
    mid_radius = 1.5 * thickness
    mid_area = mid_width * mid_height - (4.0 - pi) * mid_radius**2
    mid_perimeter = 2.0 * (mid_width + mid_height) + (2.0 * pi - 4.0) * mid_radius
    return 4.0 * mid_area**2 / (mid_perimeter / thickness)


def _closed_sharp_rectangular_torsion(width: float, height: float, thickness: float) -> float:
    """Thin-walled closed-section approximation for sharp rectangular walls."""
    mid_width = width - thickness
    mid_height = height - thickness
    mid_area = mid_width * mid_height
    mid_perimeter = 2.0 * (mid_width + mid_height)
    return 4.0 * mid_area**2 / (mid_perimeter / thickness)


def _rounded_rectangle_geometry(
    width: float,
    height: float,
    radius: float,
) -> tuple[float, float, float]:
    """Return area and centroidal inertias of a rounded rectangle.

    The result is exact for a rectangle with four equal quarter-circle
    corners. ``iy`` is about the horizontal centroidal axis and ``iz`` about
    the vertical centroidal axis, matching the convention used by the
    rectangular section calculators above.
    """
    width, height, radius = map(float, (width, height, radius))
    if radius < 0.0 or radius > min(width, height) / 2.0:
        raise ValueError("O raio da seção retangular arredondada é inválido.")
    corner_factor = 4.0 - pi
    area = width * height - corner_factor * radius**2
    vertical_offset = height / 2.0 - radius
    horizontal_offset = width / 2.0 - radius
    removed_y = corner_factor * vertical_offset**2 * radius**2 + (4.0 / 3.0 - pi / 4.0) * radius**4
    removed_z = corner_factor * horizontal_offset**2 * radius**2 + (4.0 / 3.0 - pi / 4.0) * radius**4
    iy = width * height**3 / 12.0 - removed_y
    iz = height * width**3 / 12.0 - removed_z
    return area, iy, iz


def _tubular_circular(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    diameter = _positive(parameters, "D")
    thickness = _positive(parameters, "t")
    inner = diameter - 2.0 * thickness
    if inner <= 0:
        raise ValueError("O diâmetro externo deve ser maior que duas vezes a espessura.")
    outer_area = pi * diameter**2 / 4.0
    inner_area = pi * inner**2 / 4.0
    inertia = pi * (diameter**4 - inner**4) / 64.0
    polar = pi * (diameter**4 - inner**4) / 32.0
    return _tube_properties(outer_area - inner_area, inertia, inertia, polar, density_kg_m3)


def _tubular_square(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    side = _positive(parameters, "b")
    thickness = _positive(parameters, "t")
    inner = side - 2.0 * thickness
    if inner <= 2.0 * thickness:
        raise ValueError("O lado externo deve ser maior que quatro vezes a espessura para os cantos arredondados.")
    outer_area, outer_iy, outer_iz = _rounded_rectangle_geometry(side, side, 2.0 * thickness)
    inner_area, inner_iy, inner_iz = _rounded_rectangle_geometry(inner, inner, thickness)
    area = outer_area - inner_area
    inertia = outer_iy - inner_iy
    j = _closed_rectangular_torsion(side, side, thickness)
    return _tube_properties(area, inertia, inertia, j, density_kg_m3)


def _tubular_rectangular(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    thickness = _positive(parameters, "t")
    if width <= 4.0 * thickness or height <= 4.0 * thickness:
        raise ValueError("As dimensões externas devem ser maiores que quatro vezes a espessura para os cantos arredondados.")
    inner_width, inner_height = width - 2.0 * thickness, height - 2.0 * thickness
    outer_area, outer_iy, outer_iz = _rounded_rectangle_geometry(width, height, 2.0 * thickness)
    inner_area, inner_iy, inner_iz = _rounded_rectangle_geometry(inner_width, inner_height, thickness)
    area = outer_area - inner_area
    iy = outer_iy - inner_iy
    iz = outer_iz - inner_iz
    j = _closed_rectangular_torsion(width, height, thickness)
    return _tube_properties(area, iy, iz, j, density_kg_m3)


def _bar_round(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    diameter = _positive(parameters, "d")
    area = pi * diameter**2 / 4.0
    inertia = pi * diameter**4 / 64.0
    return _tube_properties(area, inertia, inertia, 2.0 * inertia, density_kg_m3)


def _bar_square(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    side = _positive(parameters, "b")
    inertia = side**4 / 12.0
    return _tube_properties(side**2, inertia, inertia, 0.1406 * side**4, density_kg_m3)


def _bar_rectangular(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    area = width * height
    iy = width * height**3 / 12.0
    iz = height * width**3 / 12.0
    long_side, short_side = max(width, height), min(width, height)
    ratio = short_side / long_side
    j = long_side * short_side**3 * (1.0 / 3.0 - 0.21 * ratio * (1.0 - ratio**4 / 12.0))
    return _tube_properties(area, iy, iz, j, density_kg_m3)


def _solid_rectangular_torsion(width: float, height: float) -> float:
    """Saint-Venant torsion approximation for a solid rectangle."""
    long_side, short_side = max(width, height), min(width, height)
    ratio = short_side / long_side
    return long_side * short_side**3 * (
        1.0 / 3.0 - 0.21 * ratio * (1.0 - ratio**4 / 12.0)
    )


def _concrete_rectangular(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    rectangle = (_Rectangle(width, height, width / 2.0, height / 2.0),)
    return _properties_from_rectangles(
        rectangle, _solid_rectangular_torsion(width, height), density_kg_m3
    )


def _concrete_circular(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    diameter = _positive(parameters, "d")
    area = pi * diameter**2 / 4.0
    inertia = pi * diameter**4 / 64.0
    return _tube_properties(area, inertia, inertia, 2.0 * inertia, density_kg_m3)


def _concrete_plus(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    web = flange = _positive(parameters, "t")
    if width <= web or height <= flange:
        raise ValueError("A seção Tipo + requer b > t e h > t.")
    side = (width - web) / 2.0
    rectangles = (
        _Rectangle(web, height, width / 2.0, height / 2.0),
        _Rectangle(side, flange, side / 2.0, height / 2.0),
        _Rectangle(side, flange, width - side / 2.0, height / 2.0),
    )
    j = _open_wall_torsion((height, web), (width - web, flange))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _concrete_l(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    thickness = _positive(parameters, "t")
    if width <= thickness or height <= thickness:
        raise ValueError("A seção Tipo L requer b > t e h > t.")
    rectangles = (
        _Rectangle(thickness, height, thickness / 2.0, height / 2.0),
        _Rectangle(width - thickness, thickness, thickness + (width - thickness) / 2.0, thickness / 2.0),
    )
    j = _open_wall_torsion((height, thickness), (width - thickness, thickness))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _concrete_t(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    web = flange = _positive(parameters, "t")
    if width <= web or height <= flange:
        raise ValueError("A seção Tipo T requer b > t e h > t.")
    rectangles = (
        _Rectangle(web, height - flange, width / 2.0, (height - flange) / 2.0),
        _Rectangle(width, flange, width / 2.0, height - flange / 2.0),
    )
    j = _open_wall_torsion((height - flange, web), (width, flange))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _concrete_u(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    web = base = _positive(parameters, "t")
    if width <= 2.0 * web + 1.0 or height <= base:
        raise ValueError("A seção Tipo U requer b > 2t + 1 e h > t.")
    side_height = height - base
    rectangles = (
        _Rectangle(width, base, width / 2.0, base / 2.0),
        _Rectangle(web, side_height, web / 2.0, base + side_height / 2.0),
        _Rectangle(web, side_height, width - web / 2.0, base + side_height / 2.0),
    )
    j = _open_wall_torsion((width, base), (side_height, web), (side_height, web))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _concrete_i(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    web = flange = _positive(parameters, "t")
    if width <= web or height <= 2.0 * flange + 1.0:
        raise ValueError("A seção Tipo I requer b > t e h > 2t + 1.")
    web_height = height - 2.0 * flange
    rectangles = (
        _Rectangle(width, flange, width / 2.0, flange / 2.0),
        _Rectangle(web, web_height, width / 2.0, flange + web_height / 2.0),
        _Rectangle(width, flange, width / 2.0, height - flange / 2.0),
    )
    j = _open_wall_torsion((2.0 * width, flange), (web_height, web))
    return _properties_from_rectangles(rectangles, j, density_kg_m3)


def _concrete_rectangular_hollow(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    width = _positive(parameters, "b")
    height = _positive(parameters, "h")
    thickness = _positive(parameters, "t")
    if width <= 2.0 * thickness + 1.0 or height <= 2.0 * thickness + 1.0:
        raise ValueError("A seção retangular vazada requer b e h > 2t + 1.")
    inner_width = width - 2.0 * thickness
    inner_height = height - 2.0 * thickness
    rectangles = (
        _Rectangle(width, thickness, width / 2.0, thickness / 2.0),
        _Rectangle(width, thickness, width / 2.0, height - thickness / 2.0),
        _Rectangle(thickness, inner_height, thickness / 2.0, thickness + inner_height / 2.0),
        _Rectangle(thickness, inner_height, width - thickness / 2.0, thickness + inner_height / 2.0),
    )
    return _properties_from_rectangles(
        rectangles, _closed_sharp_rectangular_torsion(width, height, thickness), density_kg_m3
    )


def _concrete_circular_hollow(parameters: Mapping[str, float], density_kg_m3: float) -> SectionProperties:
    # Accept the former De/Di keys while projects are migrated by the UI.
    outer = _positive(parameters, "d") if "d" in parameters else _positive(parameters, "De")
    if "t" in parameters:
        thickness = _positive(parameters, "t")
    else:
        inner = _positive(parameters, "Di")
        thickness = (outer - inner) / 2.0
        if thickness <= 0:
            raise ValueError("O diâmetro interno deve ser menor que o diâmetro externo.")
    if outer <= 2.0 * thickness + 1.0:
        raise ValueError("A seção circular vazada requer d > 2t + 1.")
    inner = outer - 2.0 * thickness
    outer_area = pi * outer**2 / 4.0
    inner_area = pi * inner**2 / 4.0
    inertia = pi * (outer**4 - inner**4) / 64.0
    return _tube_properties(outer_area - inner_area, inertia, inertia, 2.0 * inertia, density_kg_m3)


def calculate_section_properties(
    family: str,
    geometry: Mapping[str, float],
    density_kg_m3: float = 7850.0,
) -> SectionProperties:
    """Calcula propriedades da seção idealizada correspondente à família."""
    if density_kg_m3 <= 0:
        raise ValueError("A densidade do material deve ser maior que zero.")
    calculators = {
        "W Laminado": _w,
        "U Laminado": _u,
        "U Inclinado Laminado": _u,
        "I Laminado": _i,
        "L Laminado": _l,
        "T Laminado": _t,
        "U Formado": _u_formed,
        "C Formado": _u_stiffened,
        "Z Formado": _z,
        "L Formado": _l_formed,
        "Cartola Formado": _cartola,
        "Tubular Circular": _tubular_circular,
        "Tubular Quadrado": _tubular_square,
        "Tubular Retangular": _tubular_rectangular,
        "Barra Circular": _bar_round,
        # Accept the former family name when opening projects created before
        # the catalog nomenclature was standardized.
        "Barra Redonda": _bar_round,
        "Barra Quadrada": _bar_square,
        "Barra Retangular": _bar_rectangular,
        "Quadrada": _bar_square,
        "Retangular": _concrete_rectangular,
        "Circular": _concrete_circular,
        "Tipo +": _concrete_plus,
        "Tipo L": _concrete_l,
        "Tipo T": _concrete_t,
        "Tipo U": _concrete_u,
        "Tipo I": _concrete_i,
        "Retangular Vazado": _concrete_rectangular_hollow,
        "Circular Vazado": _concrete_circular_hollow,
    }
    try:
        calculator = calculators[family]
    except KeyError as error:
        raise ValueError(f"Cálculo paramétrico indisponível para '{family}'.") from error
    return calculator(geometry, float(density_kg_m3))
