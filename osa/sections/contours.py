"""Contornos paramétricos para seções laminadas e formadas.

Os contornos são construídos diretamente a partir das dimensões geométricas,
com raios de dobra e detalhes próprios de cada família de seção.
"""

from __future__ import annotations

from math import cos, pi, sin, tan


Point = tuple[float, float]


def rounded_rect_svg_path(
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> str:
    """Return one rounded-rectangle subpath for an SVG compound contour."""
    width, height, radius = map(float, (width, height, radius))
    if width <= 0.0 or height <= 0.0:
        raise ValueError("As dimensões do retângulo devem ser maiores que zero.")
    radius = min(max(0.0, radius), width / 2.0, height / 2.0)
    x2, y2 = x + width, y + height
    if radius == 0.0:
        return f"M {x:.2f},{y:.2f} H {x2:.2f} V {y2:.2f} H {x:.2f} Z"
    return (
        f"M {x + radius:.2f},{y:.2f} H {x2 - radius:.2f} "
        f"A {radius:.2f},{radius:.2f} 0 0 1 {x2:.2f},{y + radius:.2f} "
        f"V {y2 - radius:.2f} "
        f"A {radius:.2f},{radius:.2f} 0 0 1 {x2 - radius:.2f},{y2:.2f} "
        f"H {x + radius:.2f} "
        f"A {radius:.2f},{radius:.2f} 0 0 1 {x:.2f},{y2 - radius:.2f} "
        f"V {y + radius:.2f} "
        f"A {radius:.2f},{radius:.2f} 0 0 1 {x + radius:.2f},{y:.2f} Z"
    )


def _rect_svg_path(x: float, y: float, width: float, height: float) -> str:
    return f"M {x:.2f},{y:.2f} H {x + width:.2f} V {y + height:.2f} H {x:.2f} Z"


def concrete_rectangular_svg_path(b: float, h: float, cx: float = 0.0, cy: float = 0.0) -> str:
    return _rect_svg_path(cx - b / 2.0, cy - h / 2.0, b, h)


def concrete_circular_svg_path(d: float, cx: float = 0.0, cy: float = 0.0) -> str:
    r = float(d) / 2.0
    return (
        f"M {cx + r:.2f},{cy:.2f} A {r:.2f},{r:.2f} 0 1 1 {cx - r:.2f},{cy:.2f} "
        f"A {r:.2f},{r:.2f} 0 1 1 {cx + r:.2f},{cy:.2f} Z"
    )


def concrete_l_svg_path(
    b: float,
    h: float,
    t: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the idealized right-angle concrete L outline."""
    x0, y0 = cx - b / 2.0, cy - h / 2.0
    x1, y1 = x0 + b, y0 + h
    return (
        f"M {x0:.2f},{y0:.2f} H {x0 + t:.2f} V {y1 - t:.2f} "
        f"H {x1:.2f} V {y1:.2f} H {x0:.2f} Z"
    )


def concrete_t_svg_path(b: float, h: float, t: float, cx: float = 0.0, cy: float = 0.0) -> str:
    x0, y0 = cx - b / 2.0, cy - h / 2.0
    x1, y1 = x0 + b, y0 + h
    xw0, xw1 = cx - t / 2.0, cx + t / 2.0
    return (
        f"M {x0:.2f},{y0:.2f} H {x1:.2f} V {y0 + t:.2f} "
        f"H {xw1:.2f} V {y1:.2f} H {xw0:.2f} V {y0 + t:.2f} H {x0:.2f} Z"
    )


def concrete_i_svg_path(b: float, h: float, t: float, cx: float = 0.0, cy: float = 0.0) -> str:
    x0, y0 = cx - b / 2.0, cy - h / 2.0
    x1, y1 = x0 + b, y0 + h
    xw0, xw1 = cx - t / 2.0, cx + t / 2.0
    return (
        f"M {x0:.2f},{y0:.2f} H {x1:.2f} V {y0 + t:.2f} "
        f"H {xw1:.2f} V {y1 - t:.2f} H {x1:.2f} V {y1:.2f} "
        f"H {x0:.2f} V {y1 - t:.2f} H {xw0:.2f} V {y0 + t:.2f} H {x0:.2f} Z"
    )


def concrete_u_svg_path(b: float, h: float, t: float, cx: float = 0.0, cy: float = 0.0) -> str:
    x0, y0 = cx - b / 2.0, cy - h / 2.0
    x1, y1 = x0 + b, y0 + h
    return (
        f"M {x0:.2f},{y0:.2f} H {x0 + t:.2f} V {y1 - t:.2f} "
        f"H {x1 - t:.2f} V {y0:.2f} H {x1:.2f} V {y1:.2f} "
        f"H {x0:.2f} Z"
    )


def concrete_plus_svg_path(b: float, h: float, t: float, cx: float = 0.0, cy: float = 0.0) -> str:
    x0, x1 = cx - b / 2.0, cx + b / 2.0
    y0, y1 = cy - h / 2.0, cy + h / 2.0
    xv0, xv1 = cx - t / 2.0, cx + t / 2.0
    yh0, yh1 = cy - t / 2.0, cy + t / 2.0
    return (
        f"M {xv0:.2f},{y0:.2f} H {xv1:.2f} V {yh0:.2f} H {x1:.2f} "
        f"V {yh1:.2f} H {xv1:.2f} V {y1:.2f} H {xv0:.2f} V {yh1:.2f} "
        f"H {x0:.2f} V {yh0:.2f} H {xv0:.2f} Z"
    )


def concrete_rectangular_hollow_svg_path(b: float, h: float, t: float, cx: float = 0.0, cy: float = 0.0) -> str:
    outer = _rect_svg_path(cx - b / 2.0, cy - h / 2.0, b, h)
    inner = _rect_svg_path(cx - b / 2.0 + t, cy - h / 2.0 + t, b - 2.0 * t, h - 2.0 * t)
    return f"{outer} {inner}"


def concrete_circular_hollow_svg_path(de: float, di: float, cx: float = 0.0, cy: float = 0.0) -> str:
    return f"{concrete_circular_svg_path(de, cx, cy)} {concrete_circular_svg_path(di, cx, cy)}"


def _w_radius(geometry: dict[str, float]) -> float:
    """Return the W-profile fillet radius, preserving old catalog records."""
    value = geometry.get("r", geometry.get("r_mm", 10.0))
    radius = float(value)
    if radius <= 0.0:
        raise ValueError("O raio de concordância do perfil W deve ser maior que zero.")
    return radius


def _w_dimensions(d: float, bf: float, tw: float, tf: float, r: float) -> None:
    if min(d, bf, tw, tf, r) <= 0.0:
        raise ValueError("As dimensões do perfil W devem ser maiores que zero.")
    if d <= 2.0 * tf:
        raise ValueError("A altura do perfil W deve ser maior que duas vezes tf.")
    if bf <= tw + 2.0 * r:
        raise ValueError("A mesa do perfil W não comporta o raio informado.")
    if d <= 2.0 * (tf + r):
        raise ValueError("O raio informado não comporta a altura livre da alma.")


def w_svg_path(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the closed, fully-parametric SVG outline of a W section."""
    d, bf, tw, tf, r = map(float, (d, bf, tw, tf, r))
    _w_dimensions(d, bf, tw, tf, r)

    half_d = d / 2.0
    half_bf = bf / 2.0
    half_tw = tw / 2.0
    y_top = cy - half_d
    y_top_inner = y_top + tf
    y_bottom_inner = cy + half_d - tf
    y_bottom = cy + half_d
    x_left = cx - half_bf
    x_right = cx + half_bf
    x_web_left = cx - half_tw
    x_web_right = cx + half_tw

    return (
        f"M {x_left:.2f},{y_top:.2f} "
        f"H {x_right:.2f} V {y_top_inner:.2f} "
        f"H {x_web_right + r:.2f} "
        f"A {r:.2f},{r:.2f} 0 0 0 {x_web_right:.2f},{y_top_inner + r:.2f} "
        f"V {y_bottom_inner - r:.2f} "
        f"A {r:.2f},{r:.2f} 0 0 0 {x_web_right + r:.2f},{y_bottom_inner:.2f} "
        f"H {x_right:.2f} V {y_bottom:.2f} H {x_left:.2f} "
        f"V {y_bottom_inner:.2f} H {x_web_left - r:.2f} "
        f"A {r:.2f},{r:.2f} 0 0 0 {x_web_left:.2f},{y_bottom_inner - r:.2f} "
        f"V {y_top_inner + r:.2f} "
        f"A {r:.2f},{r:.2f} 0 0 0 {x_web_left - r:.2f},{y_top_inner:.2f} "
        f"H {x_left:.2f} Z"
    )


def gerar_perfil_w_svg(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float,
    cx: float = 0.0,
    cy: float = 0.0,
    padding: float = 20.0,
    stroke_color: str = "#0F172A",
    stroke_width: float = 2.0,
) -> str:
    """Return a standalone SVG for a fully-parametric W profile."""
    view_w = float(bf) + 2.0 * float(padding)
    view_h = float(d) + 2.0 * float(padding)
    path_d = w_svg_path(d, bf, tw, tf, r, cx=cx, cy=cy)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {view_w:.1f} {view_h:.1f}" '
        f'width="{view_w:.0f}" height="{view_h:.0f}">'
        f'<path d="{path_d}" fill="none" stroke="{stroke_color}" '
        f'stroke-width="{float(stroke_width):g}" stroke-linejoin="round" '
        'stroke-linecap="round" />'
        '</svg>'
    )


def _arc_points(center: Point, start_angle: float, end_angle: float, radius: float, steps: int) -> list[Point]:
    return [
        (center[0] + radius * cos(start_angle + (end_angle - start_angle) * index / steps),
         center[1] + radius * sin(start_angle + (end_angle - start_angle) * index / steps))
        for index in range(1, steps + 1)
    ]


def w_contour_points(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float,
    arc_steps: int = 16,
) -> tuple[Point, ...]:
    """Return the same parametric W contour as sampled polygon points."""
    d, bf, tw, tf, r = map(float, (d, bf, tw, tf, r))
    _w_dimensions(d, bf, tw, tf, r)
    h_d, h_bf, h_tw = d / 2.0, bf / 2.0, tw / 2.0
    top_inner, bottom_inner = h_d - tf, -h_d + tf
    points: list[Point] = [
        (-h_bf, h_d), (h_bf, h_d), (h_bf, top_inner),
        (h_tw + r, top_inner),
    ]
    points.extend(_arc_points((h_tw + r, top_inner - r), pi / 2.0, pi, r, arc_steps))
    points.append((h_tw, bottom_inner + r))
    points.extend(_arc_points((h_tw + r, bottom_inner + r), pi, 1.5 * pi, r, arc_steps))
    points.extend(((h_bf, bottom_inner), (h_bf, -h_d), (-h_bf, -h_d), (-h_bf, bottom_inner)))
    points.append((-h_tw - r, bottom_inner))
    points.extend(_arc_points((-h_tw - r, bottom_inner + r), -pi / 2.0, 0.0, r, arc_steps))
    points.append((-h_tw, top_inner - r))
    points.extend(_arc_points((-h_tw - r, top_inner - r), 0.0, pi / 2.0, r, arc_steps))
    points.append((-h_bf, top_inner))
    return tuple(points)


def _u_defaults(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float | None,
    r1: float | None,
    flange_angle_deg: float,
) -> tuple[float, float, float]:
    d, bf, tw, tf = map(float, (d, bf, tw, tf))
    radius = float(r) if r is not None else max(2.0, 1.5 * tf)
    tip_radius = float(r1) if r1 is not None else max(1.5, min(tf, 0.8 * tf))
    if min(d, bf, tw, tf, radius, tip_radius) <= 0.0:
        raise ValueError("As dimensões do perfil U devem ser maiores que zero.")
    if d <= 2.0 * tf:
        raise ValueError("A altura do perfil U deve ser maior que duas vezes tf.")
    if bf <= tw + radius + tip_radius:
        raise ValueError("A largura do perfil U não comporta os raios informados.")
    if d <= 2.0 * (tf + radius):
        raise ValueError("Os raios informados não comportam a altura livre da alma.")
    return radius, tip_radius, float(flange_angle_deg)


def u_svg_path(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float | None = None,
    r1: float | None = None,
    flange_angle_deg: float = 2.0,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the closed, parametric SVG outline of a rolled U section."""
    d, bf, tw, tf = map(float, (d, bf, tw, tf))
    radius, tip_radius, angle_deg = _u_defaults(
        d, bf, tw, tf, r, r1, flange_angle_deg
    )
    half_d = d / 2.0
    x_outer = cx - bf / 2.0
    x_inner = x_outer + tw
    x_tip = x_outer + bf
    y_top = cy - half_d
    y_bottom = cy + half_d
    free_width = bf - tw - radius - tip_radius
    rise = free_width * tan(angle_deg * pi / 180.0)
    y_top_inner_at_web = y_top + tf + rise
    y_bottom_inner_at_web = y_bottom - tf - rise

    return (
        f"M {x_outer:.2f},{y_top:.2f} "
        f"H {x_tip:.2f} "
        f"A {tip_radius:.2f},{tip_radius:.2f} 0 0 1 "
        f"{x_tip - tip_radius:.2f},{y_top + tip_radius:.2f} "
        f"L {x_inner + radius:.2f},{y_top_inner_at_web:.2f} "
        f"Q {x_inner:.2f},{y_top_inner_at_web:.2f} "
        f"{x_inner:.2f},{y_top_inner_at_web + radius:.2f} "
        f"V {y_bottom_inner_at_web - radius:.2f} "
        f"Q {x_inner:.2f},{y_bottom_inner_at_web:.2f} "
        f"{x_inner + radius:.2f},{y_bottom_inner_at_web:.2f} "
        f"L {x_tip - tip_radius:.2f},{y_bottom - tip_radius:.2f} "
        f"A {tip_radius:.2f},{tip_radius:.2f} 0 0 1 "
        f"{x_tip:.2f},{y_bottom:.2f} "
        f"H {x_outer:.2f} V {y_top:.2f} Z"
    )


def gerar_perfil_u_svg(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float | None = None,
    r1: float | None = None,
    flange_angle_deg: float = 2.0,
    cx: float = 0.0,
    cy: float = 0.0,
    padding: float = 20.0,
    stroke_color: str = "#0F172A",
    stroke_width: float = 2.0,
) -> str:
    """Return a standalone SVG for a fully-parametric U profile."""
    view_w = float(bf) + 2.0 * float(padding)
    view_h = float(d) + 2.0 * float(padding)
    path_d = u_svg_path(
        d, bf, tw, tf, r, r1, flange_angle_deg, cx=cx, cy=cy
    )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {view_w:.1f} {view_h:.1f}" '
        f'width="{view_w:.0f}" height="{view_h:.0f}">'
        f'<path d="{path_d}" fill="none" stroke="{stroke_color}" '
        f'stroke-width="{float(stroke_width):g}" stroke-linejoin="round" '
        'stroke-linecap="round" />'
        '</svg>'
    )


def _formed_radius(t: float, d: float, bf: float) -> float:
    """Return a compact bend radius for cold-formed sheet profiles."""
    thickness = float(t)
    if min(thickness, float(d), float(bf)) <= 0.0:
        raise ValueError("As dimensões da seção formada devem ser maiores que zero.")
    return max(0.8 * thickness, min(1.8 * thickness, 0.08 * min(float(d), float(bf))))


def u_formed_svg_path(
    d: float,
    bf: float,
    t: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the rounded, open U cold-formed section outline.

    The bend radii follow the sheet convention used by the section sketch:
    the inside radius is ``t`` and the outside radius is ``2t``.
    """
    d, bf, t = map(float, (d, bf, t))
    _formed_radius(t, d, bf)
    if d <= 4.0 * t or bf <= 2.0 * t:
        raise ValueError("A seção U formada requer d > 4t e bf > 2t.")
    x0, x1, x2 = cx - bf / 2.0, cx - bf / 2.0 + t, cx + bf / 2.0
    y0, y1, y2, y3 = cy - d / 2.0, cy - d / 2.0 + t, cy + d / 2.0 - t, cy + d / 2.0
    r_inner = t
    r_outer = 2.0 * t
    return (
        f"M {x0 + r_outer:.2f},{y0:.2f} H {x2:.2f} V {y1:.2f} "
        f"H {x1 + r_inner:.2f} Q {x1:.2f},{y1:.2f} {x1:.2f},{y1 + r_inner:.2f} "
        f"V {y2 - r_inner:.2f} Q {x1:.2f},{y2:.2f} {x1 + r_inner:.2f},{y2:.2f} "
        f"H {x2:.2f} V {y3:.2f} H {x0 + r_outer:.2f} "
        f"Q {x0:.2f},{y3:.2f} {x0:.2f},{y3 - r_outer:.2f} V {y0 + r_outer:.2f} "
        f"Q {x0:.2f},{y0:.2f} {x0 + r_outer:.2f},{y0:.2f} Z"
    )


def c_formed_svg_path(
    d: float,
    bf: float,
    c: float,
    t: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the rounded C cold-formed section with two inward lips.

    The inside bends use ``t`` and the outside bends use ``2t`` at the web,
    flange and lip transitions.
    """
    d, bf, c, t = map(float, (d, bf, c, t))
    radius = _formed_radius(t, d, bf)
    if d <= 2.0 * (t + c) or bf <= t + radius or c <= 0.0:
        raise ValueError("A seção C formada requer d > 2(t + c), bf > t + r e c > 0.")
    x0, x1, x2 = cx - bf / 2.0, cx - bf / 2.0 + t, cx + bf / 2.0
    y0, y1, y2, y3 = cy - d / 2.0, cy - d / 2.0 + t, cy + d / 2.0 - t, cy + d / 2.0
    r_inner = t
    r_outer = 2.0 * t
    return (
        f"M {x0 + r_outer:.2f},{y0:.2f} H {x2 - r_outer:.2f} "
        f"Q {x2:.2f},{y0:.2f} {x2:.2f},{y0 + r_outer:.2f} "
        f"V {y1 + c:.2f} H {x2 - t:.2f} "
        f"V {y1 + r_inner:.2f} Q {x2 - t:.2f},{y1:.2f} {x2 - t - r_inner:.2f},{y1:.2f} "
        f"H {x1 + r_inner:.2f} Q {x1:.2f},{y1:.2f} {x1:.2f},{y1 + r_inner:.2f} "
        f"V {y2 - r_inner:.2f} Q {x1:.2f},{y2:.2f} {x1 + r_inner:.2f},{y2:.2f} "
        f"H {x2 - t - r_inner:.2f} Q {x2 - t:.2f},{y2:.2f} {x2 - t:.2f},{y2 - r_inner:.2f} "
        f"V {y2 - c:.2f} H {x2:.2f} "
        f"V {y3 - r_outer:.2f} Q {x2:.2f},{y3:.2f} {x2 - r_outer:.2f},{y3:.2f} "
        f"H {x0 + r_outer:.2f} Q {x0:.2f},{y3:.2f} {x0:.2f},{y3 - r_outer:.2f} "
        f"V {y0 + r_outer:.2f} Q {x0:.2f},{y0:.2f} {x0 + r_outer:.2f},{y0:.2f} Z"
    )


def z_formed_svg_path(
    d: float,
    bf: float,
    t: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the rounded Z cold-formed section outline."""
    d, bf, t = map(float, (d, bf, t))
    _formed_radius(t, d, bf)
    if d <= 4.0 * t or bf <= 2.0 * t:
        raise ValueError("A seção Z formada requer d > 4t e bf > 2t.")
    # Sequência do contorno: 1-2-3-4-5-6-7-8-9-10-11-12.
    # A mesa superior sai para a esquerda e a inferior para a direita.
    x_left, x_right = cx - t / 2.0, cx + t / 2.0
    y0, y1, y2, y3 = cy - d / 2.0, cy - d / 2.0 + t, cy + d / 2.0 - t, cy + d / 2.0
    r_inner = t
    r_outer = 2.0 * t
    return (
        # 1 -> 2 -> 3: mesa superior e dobra externa de raio 2t
        f"M {x_left - bf:.2f},{y0:.2f} H {x_right - r_outer:.2f} "
        f"A {r_outer:.2f},{r_outer:.2f} 0 0 1 {x_right:.2f},{y0 + r_outer:.2f} "
        # 3 -> 4: face externa da alma
        f"V {y2 - r_inner:.2f} "
        # 4 -> 5: dobra interna inferior de raio t
        f"A {r_inner:.2f},{r_inner:.2f} 0 0 0 {x_right + r_inner:.2f},{y2:.2f} "
        # 5 -> 6 -> 7: mesa inferior e ponta reta
        f"H {x_right + bf:.2f} V {y3:.2f} "
        # 7 -> 8 -> 9: face inferior e dobra externa de raio 2t
        f"H {x_left + r_outer:.2f} "
        f"A {r_outer:.2f},{r_outer:.2f} 0 0 1 {x_left:.2f},{y3 - r_outer:.2f} "
        # 9 -> 10: face interna da alma
        f"V {y1 + r_inner:.2f} "
        # 10 -> 11: dobra interna superior de raio t
        f"A {r_inner:.2f},{r_inner:.2f} 0 0 0 {x_left - r_inner:.2f},{y1:.2f} "
        # 11 -> 12 -> 1: mesa superior interna e ponta reta
        f"H {x_left - bf:.2f} V {y0:.2f} Z"
    )


def l_formed_svg_path(
    d: float,
    bf: float,
    t: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the rounded unequal-angle L cold-formed section outline."""
    d, bf, t = map(float, (d, bf, t))
    _formed_radius(t, d, bf)
    if d <= t or bf <= t:
        raise ValueError("A seção L formada requer d > t e bf > t.")
    x0, x1, x2 = cx - bf / 2.0, cx - bf / 2.0 + t, cx + bf / 2.0
    y0, y1 = cy - d / 2.0, cy + d / 2.0
    r_inner = t
    r_outer = 2.0 * t
    return (
        f"M {x0:.2f},{y0:.2f} H {x1:.2f} V {y1 - t - r_inner:.2f} "
        f"Q {x1:.2f},{y1 - t:.2f} {x1 + r_inner:.2f},{y1 - t:.2f} "
        f"H {x2:.2f} V {y1:.2f} H {x0 + r_outer:.2f} "
        f"Q {x0:.2f},{y1:.2f} {x0:.2f},{y1 - r_outer:.2f} V {y0:.2f} Z"
    )


def cartola_formed_svg_path(
    d: float,
    bf: float,
    c: float,
    t: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the rounded hat (Cartola) cold-formed section outline."""
    d, bf, c, t = map(float, (d, bf, c, t))
    _formed_radius(t, d, bf)
    if d <= 4.0 * t or bf <= 5.0 * t or c <= 0.0:
        raise ValueError("A seção Cartola requer d > 4t, bf > 5t e c > 0.")
    xl, xr = cx - bf / 2.0, cx + bf / 2.0
    y0, y3 = cy - d / 2.0, cy + d / 2.0
    r_inner = t
    r_outer = 2.0 * t
    y1 = y0 + t
    y2 = y3 - t
    return (
        # 1 -> 2: aba inferior esquerda, face interna
        f"M {xl - c:.2f},{y2:.2f} H {xl - t:.2f} "
        # 2 -> 3: arco interno de raio t, subindo
        f"A {r_inner:.2f},{r_inner:.2f} 0 0 0 {xl:.2f},{y2 - t:.2f} "
        # 3 -> 4: alma esquerda, face externa
        f"V {y0 + r_outer:.2f} "
        # 4 -> 5: arco externo superior esquerdo de raio 2t
        f"A {r_outer:.2f},{r_outer:.2f} 0 0 1 {xl + 2.0 * t:.2f},{y0:.2f} "
        # 5 -> 6: mesa superior externa
        f"H {xr - r_outer:.2f} "
        # 6 -> 7: arco externo superior direito de raio 2t
        f"A {r_outer:.2f},{r_outer:.2f} 0 0 1 {xr:.2f},{y0 + r_outer:.2f} "
        # 7 -> 8: alma direita, face externa
        f"V {y2 - t:.2f} "
        # 8 -> 9: arco interno inferior direito de raio t
        f"A {r_inner:.2f},{r_inner:.2f} 0 0 0 {xr + t:.2f},{y2:.2f} "
        # 9 -> 10 -> 11: aba direita e ponta reta
        f"H {xr + c:.2f} V {y3:.2f} "
        # 11 -> 12: face externa da aba inferior direita
        f"H {xr + t:.2f} "
        # 12 -> 13: arco externo inferior direito de raio 2t
        f"A {r_outer:.2f},{r_outer:.2f} 0 0 1 {xr - t:.2f},{y3 - r_outer:.2f} "
        # 13 -> 14: alma direita, face interna
        f"V {y1 + t:.2f} "
        # 14 -> 15: arco interno superior direito de raio t
        f"A {r_inner:.2f},{r_inner:.2f} 0 0 0 {xr - 2.0 * t:.2f},{y1:.2f} "
        # 15 -> 16: mesa superior interna
        f"H {xl + 2.0 * t:.2f} "
        # 16 -> 17: arco interno superior esquerdo de raio t, descendo
        f"A {r_inner:.2f},{r_inner:.2f} 0 0 0 {xl + t:.2f},{y1 + t:.2f} "
        # 17 -> 18: alma esquerda, face interna
        f"V {y3 - r_outer:.2f} "
        # 18 -> 19: arco externo inferior esquerdo de raio 2t
        f"A {r_outer:.2f},{r_outer:.2f} 0 0 1 {xl - t:.2f},{y3:.2f} "
        # 19 -> 20 -> 1: aba esquerda e fechamento pela ponta reta
        f"H {xl - c:.2f} V {y2:.2f} Z"
    )


def u_contour_points(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r: float | None = None,
    r1: float | None = None,
    flange_angle_deg: float = 2.0,
    arc_steps: int = 16,
) -> tuple[Point, ...]:
    """Return sampled points from the same parametric U contour."""
    d, bf, tw, tf = map(float, (d, bf, tw, tf))
    radius, tip_radius, angle_deg = _u_defaults(
        d, bf, tw, tf, r, r1, flange_angle_deg
    )
    x_outer = -bf / 2.0
    x_inner = x_outer + tw
    x_tip = x_outer + bf
    half_d = d / 2.0
    y_top = half_d
    y_bottom = -half_d
    free_width = bf - tw - radius - tip_radius
    rise = free_width * tan(angle_deg * pi / 180.0)
    top_inner = half_d - tf - rise
    bottom_inner = -half_d + tf + rise

    points: list[Point] = [
        (x_outer, y_top),
        (x_tip, y_top),
    ]
    points.extend(_arc_points((x_tip - tip_radius, y_top), 0.0, -pi / 2.0, tip_radius, arc_steps))
    points.append((x_inner + radius, top_inner))
    points.extend(_arc_points((x_inner + radius, top_inner - radius), pi / 2.0, pi, radius, arc_steps))
    points.append((x_inner, bottom_inner + radius))
    points.extend(_arc_points((x_inner + radius, bottom_inner + radius), pi, 1.5 * pi, radius, arc_steps))
    points.append((x_tip - tip_radius, -half_d + tip_radius))
    points.extend(_arc_points((x_tip - tip_radius, -half_d), pi / 2.0, 0.0, tip_radius, arc_steps))
    points.extend(((x_outer, -half_d), (x_outer, half_d)))
    return tuple(points)


def _l_defaults(t: float, r1: float | None, r2: float | None) -> tuple[float, float]:
    thickness = float(t)
    inner_radius = float(r1) if r1 is not None else thickness
    tip_radius = float(r2) if r2 is not None else max(0.75, 0.8 * thickness)
    if min(thickness, inner_radius, tip_radius) <= 0.0:
        raise ValueError("As dimensões e os raios do perfil L devem ser maiores que zero.")
    return inner_radius, tip_radius


def l_svg_path(
    b: float,
    t: float,
    r1: float | None = None,
    r2: float | None = None,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the closed, parametric SVG outline of an equal-leg L section."""
    b, t = map(float, (b, t))
    inner_radius, tip_radius = _l_defaults(t, r1, r2)
    if b <= t + inner_radius or b <= t:
        raise ValueError("A largura do perfil L deve comportar a espessura e o raio interno.")

    x_left = cx - b / 2.0
    x_web = x_left + t
    x_right = x_left + b
    y_top = cy - b / 2.0
    y_bottom = cy + b / 2.0
    return (
        f"M {x_left:.2f},{y_top:.2f} "
        f"H {x_web - tip_radius:.2f} "
        f"A {tip_radius:.2f},{t:.2f} 0 0 1 {x_web:.2f},{y_top + t:.2f} "
        f"V {y_bottom - t - inner_radius:.2f} "
        f"A {inner_radius:.2f},{inner_radius:.2f} 0 0 0 "
        f"{x_web + inner_radius:.2f},{y_bottom - t:.2f} "
        f"H {x_right - tip_radius:.2f} "
        f"A {tip_radius:.2f},{t:.2f} 0 0 1 {x_right:.2f},{y_bottom:.2f} "
        f"H {x_left:.2f} V {y_top:.2f} Z"
    )


def gerar_perfil_l_svg(
    b: float,
    t: float,
    r1: float | None = None,
    r2: float | None = None,
    cx: float = 0.0,
    cy: float = 0.0,
    padding: float = 20.0,
    stroke_color: str = "#0F172A",
    stroke_width: float = 2.0,
) -> str:
    """Return a standalone SVG for a fully-parametric L profile."""
    view_w = float(b) + 2.0 * float(padding)
    view_h = float(b) + 2.0 * float(padding)
    path_d = l_svg_path(b, t, r1, r2, cx=cx, cy=cy)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {view_w:.1f} {view_h:.1f}" '
        f'width="{view_w:.0f}" height="{view_h:.0f}">'
        f'<path d="{path_d}" fill="none" stroke="{stroke_color}" '
        f'stroke-width="{float(stroke_width):g}" stroke-linejoin="round" '
        'stroke-linecap="round" />'
        '</svg>'
    )


def _ellipse_arc_points(
    center: Point,
    start_angle: float,
    end_angle: float,
    rx: float,
    ry: float,
    steps: int,
) -> list[Point]:
    return [
        (center[0] + rx * cos(start_angle + (end_angle - start_angle) * index / steps),
         center[1] + ry * sin(start_angle + (end_angle - start_angle) * index / steps))
        for index in range(1, steps + 1)
    ]


def l_contour_points(
    b: float,
    t: float,
    r1: float | None = None,
    r2: float | None = None,
    arc_steps: int = 16,
) -> tuple[Point, ...]:
    """Return sampled points from the same parametric L contour."""
    b, t = map(float, (b, t))
    inner_radius, tip_radius = _l_defaults(t, r1, r2)
    if b <= t + inner_radius or b <= t:
        raise ValueError("A largura do perfil L deve comportar a espessura e o raio interno.")
    x_left = -b / 2.0
    x_web = x_left + t
    x_right = x_left + b
    y_top = b / 2.0
    y_bottom = -b / 2.0
    points: list[Point] = [
        (x_left, y_top),
        (x_web - tip_radius, y_top),
    ]
    points.extend(_ellipse_arc_points((x_web - tip_radius, y_top - t), pi / 2.0, 0.0, tip_radius, t, arc_steps))
    points.append((x_web, y_bottom + t + inner_radius))
    points.extend(_arc_points((x_web + inner_radius, y_bottom + t + inner_radius), pi, 1.5 * pi, inner_radius, arc_steps))
    points.append((x_right - tip_radius, y_bottom + t))
    points.extend(_ellipse_arc_points((x_right - tip_radius, y_bottom), pi / 2.0, 0.0, tip_radius, t, arc_steps))
    points.extend(((x_right, y_bottom), (x_left, y_bottom), (x_left, y_top)))
    return tuple(points)


def _t_defaults(tf: float, r1: float | None, r2: float | None) -> tuple[float, float]:
    flange_thickness = float(tf)
    inner_radius = float(r1) if r1 is not None else flange_thickness
    tip_radius = float(r2) if r2 is not None else max(0.75, 0.8 * flange_thickness)
    if min(flange_thickness, inner_radius, tip_radius) <= 0.0:
        raise ValueError("As dimensões e os raios do perfil T devem ser maiores que zero.")
    return inner_radius, tip_radius


def t_svg_path(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r1: float | None = None,
    r2: float | None = None,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the closed SVG outline of an inverted, rounded T section."""
    d, bf, tw, tf = map(float, (d, bf, tw, tf))
    inner_radius, tip_radius = _t_defaults(tf, r1, r2)
    if d <= tf or bf <= tw + 2.0 * inner_radius:
        raise ValueError("A geometria do perfil T não comporta as dimensões informadas.")

    x_left = cx - bf / 2.0
    x_right = cx + bf / 2.0
    x_web_left = cx - tw / 2.0
    x_web_right = cx + tw / 2.0
    y_top = cy - d / 2.0
    y_bottom = cy + d / 2.0
    y_flange = y_bottom - tf
    return (
        f"M {x_web_left:.2f},{y_top:.2f} "
        f"H {x_web_right:.2f} "
        f"V {y_flange - inner_radius:.2f} "
        f"A {inner_radius:.2f},{inner_radius:.2f} 0 0 0 "
        f"{x_web_right + inner_radius:.2f},{y_flange:.2f} "
        f"H {x_right - tip_radius:.2f} "
        f"A {tip_radius:.2f},{tf:.2f} 0 0 1 "
        f"{x_right:.2f},{y_bottom:.2f} "
        f"H {x_left:.2f} "
        f"A {tip_radius:.2f},{tf:.2f} 0 0 1 "
        f"{x_left + tip_radius:.2f},{y_flange:.2f} "
        f"H {x_web_left - inner_radius:.2f} "
        f"A {inner_radius:.2f},{inner_radius:.2f} 0 0 0 "
        f"{x_web_left:.2f},{y_flange - inner_radius:.2f} "
        f"V {y_top:.2f} Z"
    )


def gerar_perfil_t_svg(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r1: float | None = None,
    r2: float | None = None,
    cx: float = 0.0,
    cy: float = 0.0,
    padding: float = 20.0,
    stroke_color: str = "#0F172A",
    stroke_width: float = 2.0,
) -> str:
    """Return a standalone SVG for a fully-parametric inverted T profile."""
    view_w = float(bf) + 2.0 * float(padding)
    view_h = float(d) + 2.0 * float(padding)
    path_d = t_svg_path(d, bf, tw, tf, r1, r2, cx=cx, cy=cy)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {view_w:.1f} {view_h:.1f}" '
        f'width="{view_w:.0f}" height="{view_h:.0f}">'
        f'<path d="{path_d}" fill="none" stroke="{stroke_color}" '
        f'stroke-width="{float(stroke_width):g}" stroke-linejoin="round" '
        'stroke-linecap="round" />'
        '</svg>'
    )


def _i_defaults(tf: float, r1: float | None, r2: float | None) -> tuple[float, float]:
    flange_thickness = float(tf)
    inner_radius = float(r1) if r1 is not None else flange_thickness
    tip_radius = float(r2) if r2 is not None else max(0.75, 0.8 * flange_thickness)
    if min(flange_thickness, inner_radius, tip_radius) <= 0.0:
        raise ValueError("As dimensões e os raios do perfil I devem ser maiores que zero.")
    return inner_radius, tip_radius


def i_svg_path(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r1: float | None = None,
    r2: float | None = None,
    flange_angle_deg: float = 2.0,
    cx: float = 0.0,
    cy: float = 0.0,
) -> str:
    """Build the closed SVG outline of an American I section with sloped flanges."""
    d, bf, tw, tf = map(float, (d, bf, tw, tf))
    inner_radius, tip_radius = _i_defaults(tf, r1, r2)
    if d <= 2.0 * tf or bf <= tw + 2.0 * inner_radius:
        raise ValueError("A geometria do perfil I não comporta as dimensões informadas.")
    x_left, x_right = cx - bf / 2.0, cx + bf / 2.0
    x_web_left, x_web_right = cx - tw / 2.0, cx + tw / 2.0
    y_top, y_bottom = cy - d / 2.0, cy + d / 2.0
    free_half = bf / 2.0 - tw / 2.0 - inner_radius - tip_radius
    rise = free_half * tan(flange_angle_deg * pi / 180.0)
    top_inner = y_top + tf + rise
    bottom_inner = y_bottom - tf - rise
    return (
        f"M {x_left:.2f},{y_top:.2f} H {x_right:.2f} "
        f"A {tip_radius:.2f},{tip_radius:.2f} 0 0 1 "
        f"{x_right - tip_radius:.2f},{y_top + tip_radius:.2f} "
        f"L {x_web_right + inner_radius:.2f},{top_inner:.2f} "
        f"Q {x_web_right:.2f},{top_inner:.2f} {x_web_right:.2f},{top_inner + inner_radius:.2f} "
        f"V {bottom_inner - inner_radius:.2f} "
        f"Q {x_web_right:.2f},{bottom_inner:.2f} {x_web_right + inner_radius:.2f},{bottom_inner:.2f} "
        f"L {x_right - tip_radius:.2f},{y_bottom - tip_radius:.2f} "
        f"A {tip_radius:.2f},{tip_radius:.2f} 0 0 1 {x_right:.2f},{y_bottom:.2f} "
        f"H {x_left:.2f} "
        f"A {tip_radius:.2f},{tip_radius:.2f} 0 0 1 {x_left + tip_radius:.2f},{y_bottom - tip_radius:.2f} "
        f"L {x_web_left - inner_radius:.2f},{bottom_inner:.2f} "
        f"Q {x_web_left:.2f},{bottom_inner:.2f} {x_web_left:.2f},{bottom_inner - inner_radius:.2f} "
        f"V {top_inner + inner_radius:.2f} "
        f"Q {x_web_left:.2f},{top_inner:.2f} {x_web_left - inner_radius:.2f},{top_inner:.2f} "
        f"L {x_left + tip_radius:.2f},{y_top + tip_radius:.2f} "
        f"A {tip_radius:.2f},{tip_radius:.2f} 0 0 1 {x_left:.2f},{y_top:.2f} Z"
    )


def gerar_perfil_i_svg(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r1: float | None = None,
    r2: float | None = None,
    flange_angle_deg: float = 2.0,
    cx: float = 0.0,
    cy: float = 0.0,
    padding: float = 20.0,
    stroke_color: str = "#0F172A",
    stroke_width: float = 2.0,
) -> str:
    """Return a standalone SVG for a fully-parametric I profile."""
    view_w = float(bf) + 2.0 * float(padding)
    view_h = float(d) + 2.0 * float(padding)
    path_d = i_svg_path(d, bf, tw, tf, r1, r2, flange_angle_deg, cx=cx, cy=cy)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {view_w:.1f} {view_h:.1f}" '
        f'width="{view_w:.0f}" height="{view_h:.0f}">'
        f'<path d="{path_d}" fill="none" stroke="{stroke_color}" '
        f'stroke-width="{float(stroke_width):g}" stroke-linejoin="round" '
        'stroke-linecap="round" />'
        '</svg>'
    )


def i_contour_points(
    d: float,
    bf: float,
    tw: float,
    tf: float,
    r1: float | None = None,
    r2: float | None = None,
    flange_angle_deg: float = 2.0,
    arc_steps: int = 16,
) -> tuple[Point, ...]:
    """Return sampled points from the same parametric I contour."""
    d, bf, tw, tf = map(float, (d, bf, tw, tf))
    inner_radius, tip_radius = _i_defaults(tf, r1, r2)
    if d <= 2.0 * tf or bf <= tw + 2.0 * inner_radius:
        raise ValueError("A geometria do perfil I não comporta as dimensões informadas.")
    half_d, half_bf, half_tw = d / 2.0, bf / 2.0, tw / 2.0
    free_half = half_bf - half_tw - inner_radius - tip_radius
    rise = free_half * tan(flange_angle_deg * pi / 180.0)
    top_inner = half_d - tf - rise
    bottom_inner = -half_d + tf + rise
    points: list[Point] = [(-half_bf, half_d), (half_bf, half_d)]
    points.extend(_arc_points((half_bf - tip_radius, half_d), 0.0, -pi / 2.0, tip_radius, arc_steps))
    points.append((half_tw + inner_radius, top_inner))
    points.extend(_arc_points((half_tw + inner_radius, top_inner - inner_radius), pi / 2.0, pi, inner_radius, arc_steps))
    points.append((half_tw, bottom_inner + inner_radius))
    points.extend(_arc_points((half_tw + inner_radius, bottom_inner + inner_radius), pi, 1.5 * pi, inner_radius, arc_steps))
    points.append((half_bf - tip_radius, -half_d + tip_radius))
    points.extend(_arc_points((half_bf - tip_radius, -half_d), pi / 2.0, 0.0, tip_radius, arc_steps))
    points.append((-half_bf, -half_d))
    points.extend(_arc_points((-half_bf + tip_radius, -half_d), pi, pi / 2.0, tip_radius, arc_steps))
    points.append((-half_tw - inner_radius, bottom_inner))
    points.extend(_arc_points((-half_tw - inner_radius, bottom_inner + inner_radius), -pi / 2.0, 0.0, inner_radius, arc_steps))
    points.append((-half_tw, top_inner - inner_radius))
    points.extend(_arc_points((-half_tw - inner_radius, top_inner - inner_radius), 0.0, pi / 2.0, inner_radius, arc_steps))
    points.append((-half_bf + tip_radius, half_d - tip_radius))
    points.extend(_arc_points((-half_bf + tip_radius, half_d), -pi / 2.0, -pi, tip_radius, arc_steps))
    return tuple(points)


def contour_points(family: str, geometry: dict[str, float], arc_steps: int = 12) -> tuple[Point, ...] | None:
    """Return a scaled reference contour for a supported laminated family."""
    if family == "W Laminado":
        return w_contour_points(
            float(geometry["d"]),
            float(geometry["bf"]),
            float(geometry.get("tw", 6.0)),
            float(geometry.get("tf", 8.0)),
            _w_radius(geometry),
            arc_steps,
        )
    if family in {"U Laminado", "U Inclinado Laminado"}:
        return u_contour_points(
            float(geometry["d"]),
            float(geometry["bf"]),
            float(geometry["tw"]),
            float(geometry["tf"]),
            geometry.get("r", geometry.get("r_mm")),
            geometry.get("r1", geometry.get("r1_mm")),
            float(geometry.get("flange_angle_deg", 2.0)),
            arc_steps,
        )
    if family == "L Laminado":
        return l_contour_points(
            float(geometry["b"]),
            float(geometry["t"]),
            geometry.get("r1", geometry.get("r1_mm")),
            geometry.get("r2", geometry.get("r2_mm")),
            arc_steps,
        )
    if family == "I Laminado":
        return i_contour_points(
            float(geometry["d"]),
            float(geometry["bf"]),
            float(geometry["tw"]),
            float(geometry["tf"]),
            geometry.get("r1", geometry.get("r1_mm")),
            geometry.get("r2", geometry.get("r2_mm")),
            float(geometry.get("flange_angle_deg", 2.0)),
            arc_steps,
        )
    return None


def polygon_properties(points: tuple[Point, ...]) -> tuple[float, float, float, float, float, float]:
    """Return area, centroid, Iy, Iz and Iyz for a sampled contour."""
    if len(points) < 3:
        raise ValueError("O contorno precisa possuir pelo menos três pontos.")
    cross = tuple(
        x0 * z1 - x1 * z0
        for (x0, z0), (x1, z1) in zip(points, points[1:] + points[:1])
    )
    signed_twice_area = sum(cross)
    if abs(signed_twice_area) < 1e-12:
        raise ValueError("O contorno possui área nula.")
    area = signed_twice_area / 2.0
    cy = sum((x0 + x1) * value for value, ((x0, z0), (x1, z1)) in zip(cross, zip(points, points[1:] + points[:1]))) / (3.0 * signed_twice_area)
    cz = sum((z0 + z1) * value for value, ((x0, z0), (x1, z1)) in zip(cross, zip(points, points[1:] + points[:1]))) / (3.0 * signed_twice_area)
    iz_origin = sum(value * (x0 * x0 + x0 * x1 + x1 * x1) for value, ((x0, z0), (x1, z1)) in zip(cross, zip(points, points[1:] + points[:1]))) / 12.0
    iy_origin = sum(value * (z0 * z0 + z0 * z1 + z1 * z1) for value, ((x0, z0), (x1, z1)) in zip(cross, zip(points, points[1:] + points[:1]))) / 12.0
    iyz_origin = sum(value * (2.0 * x0 * z1 + x0 * z0 + x1 * z0 + 2.0 * x1 * z1) for value, ((x0, z0), (x1, z1)) in zip(cross, zip(points, points[1:] + points[:1]))) / 24.0
    iy = abs(iy_origin - area * cz * cz)
    iz = abs(iz_origin - area * cy * cy)
    iyz = iyz_origin - area * cy * cz
    return abs(area), cy, cz, iy, iz, iyz
