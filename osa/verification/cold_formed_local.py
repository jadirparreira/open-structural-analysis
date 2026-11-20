"""NBR 14762:2010 web shear and concentrated transverse bearing (Annex D).

The caller supplies the physical load arrangement and bearing dimensions.
No connection, transverse stiffener or bearing length is inferred from nodes.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite, sqrt


def web_shear_resistance(h, t, E, fy, *, stiffener_spacing=None):
    """9.8.3; mm, N/mm² -> N, including qualified transverse stiffeners.

    A supplied spacing asserts that the stiffeners satisfy 9.5. It is not a
    substitute for checking the stiffeners and their connections themselves.
    """
    if not all(isfinite(v) and v > 0 for v in (h, t, E, fy)):
        raise ValueError("Geometria e propriedades da alma devem ser positivas e finitas.")
    if stiffener_spacing is not None and (not isfinite(stiffener_spacing) or stiffener_spacing <= 0):
        raise ValueError("O espaçamento dos enrijecedores deve ser positivo e finito.")
    kv = 5. if stiffener_spacing is None or stiffener_spacing/h > 3 else 5.+5./(stiffener_spacing/h)**2
    slenderness = h/t
    if slenderness <= 1.08*sqrt(E*kv/fy):
        capacity, branch = .6*fy*h*t/1.1, "yield"
    elif slenderness <= 1.4*sqrt(E*kv/fy):
        capacity, branch = .65*t*t*sqrt(kv*fy*E)/1.1, "inelastic"
    else:
        capacity, branch = .905*E*kv*t**3/h/1.1, "elastic"
    return capacity, {"kv": kv, "h_over_t": slenderness, "branch": branch}


@dataclass(frozen=True)
class WebShearShare:
    plate: int
    flat_height_mm: float
    vertical_per_shear_y: float
    vertical_per_shear_z: float


@lru_cache(maxsize=256)
def web_shear_shares(family, geometry, mirror=False):
    """Vertical resultant per straight longitudinal web under unit Vy/Vz.

    Integrate the thin-wall flow over the full sharp-fold web, assigning its
    bend-zone resultant to the flat web checked by 9.8.3. Its resistance uses
    only the actual flat width. Loads are at the principal shear centre;
    additional nonuniform torsion must be superposed separately.
    """
    import numpy as np
    from scipy.integrate import simpson

    from osa.sections.thin_walled import open_sheet
    from osa.verification.cold_formed_torsion import thin_wall_stresses

    sheet = open_sheet(family, dict(geometry), mirror=mirror)
    # q is quadratic along each sharp straight wall: Simpson with three
    # points gives its resultant exactly, rather than a mesh approximation.
    fy = thin_wall_stresses(sheet, shear_y=1., divisions=2)
    fz = thin_wall_stresses(sheet, shear_z=1., divisions=2)
    flats = {piece.plate: piece.length for piece in sheet.pieces if piece.center is None}
    shares = []
    for index, role in enumerate(sheet.roles):
        if role != 'web':
            continue
        a, b = np.asarray(sheet.vertices[index]), np.asarray(sheet.vertices[index+1])
        vector = b-a
        length = float(np.linalg.norm(vector))
        interval = slice(3*index, 3*(index+1))
        coordinate = np.linspace(0., length, 3)
        tangent_z = vector[1]/length
        y = float(simpson(fy.shear_flow_n_mm[interval], x=coordinate)*tangent_z)
        z = float(simpson(fz.shear_flow_n_mm[interval], x=coordinate)*tangent_z)
        shares.append(WebShearShare(index, flats[index], y, z))
    return tuple(shares)


# Entries: family group, stiffened edge, connected flange, one/two flanges,
# end/interior loading -> (alpha, alpha_r, alpha_c, alpha_h, maximum ri/t).
# Product dimensions and scope are checked before using these table entries.
_BEARING = {
    ("U", True, True, 1, True): (4.6, .14, .35, .02, 9.),
    ("U", True, True, 1, False): (15.8, .23, .14, .01, 5.),
    ("U", True, True, 2, True): (8.6, .08, .12, .048, 12.),
    ("U", True, True, 2, False): (23., .10, .08, .031, 12.),
    ("U", True, False, 1, True): (4.3, .14, .35, .02, 5.),
    ("U", True, False, 1, False): (15.8, .23, .14, .01, 5.),
    ("U", True, False, 2, True): (15.8, .32, .05, .04, 3.),
    ("U", True, False, 2, False): (25.9, .52, .15, .001, 3.),
    ("U", False, False, 1, True): (4.6, .40, .60, .03, 2.),
    ("U", False, False, 1, False): (14.9, .32, .10, .01, 1.),
    ("U", False, False, 2, True): (2., .11, .37, .01, 1.),
    ("U", False, False, 2, False): (14., .47, .25, .04, 1.),
    ("Z", True, True, 1, True): (4.6, .14, .35, .02, 9.),
    ("Z", True, True, 1, False): (15.8, .23, .14, .01, 5.5),
    ("Z", True, True, 2, True): (10.3, .05, .16, .052, 12.),
    ("Z", True, True, 2, False): (25.9, .07, .07, .04, 12.),
    ("Z", True, False, 1, True): (5.7, .09, .02, .001, 5.),
    ("Z", True, False, 1, False): (15.8, .23, .14, .01, 5.),
    ("Z", True, False, 2, True): (15.8, .32, .05, .04, 3.),
    ("Z", True, False, 2, False): (25.9, .52, .15, .001, 3.),
    ("Z", False, False, 1, True): (4.6, .40, .60, .03, 2.),
    ("Z", False, False, 1, False): (14.9, .32, .10, .01, 1.),
    ("Z", False, False, 2, True): (2., .11, .37, .01, 1.),
    ("Z", False, False, 2, False): (14., .47, .25, .04, 1.),
    ("Cartola", False, True, 1, True): (4., .25, .68, .04, 5.),
    ("Cartola", False, True, 1, False): (19.5, .13, .13, .04, 10.),
    ("Cartola", False, True, 2, True): (10.3, .10, .07, .03, 10.),
    ("Cartola", False, True, 2, False): (11.5, .14, .22, .02, 10.),
    ("Cartola", False, False, 1, True): (4., .25, .68, .04, 4.),
    ("Cartola", False, False, 1, False): (19.5, .13, .13, .04, 4.),
}


@dataclass(frozen=True)
class BearingResistance:
    per_web_n: float
    coefficients: tuple[float, float, float, float]
    table: str
    end_loading: bool
    loaded_flanges: int


def bearing_resistance(family, *, h, t, ri, c, fy, edge_distance,
                       connected=False, loaded_flanges=1, angle=90.):
    """Annex D per web, dimensions mm, fy N/mm²; capacity N.

    edge_distance is the clear distance from bearing to member end. Flange
    connectivity means rotational restraint by the load/support connection,
    not merely a connected analysis node. Tables D.2–D.4 require theta=90°.
    """
    if not all(isfinite(v) and v > 0 for v in (h, t, ri, c, fy)) or not isfinite(edge_distance) or edge_distance < 0:
        raise ValueError("Dimensões da região de apoio inválidas.")
    if angle != 90.:
        raise ValueError("As Tabelas D.2–D.4 implementadas exigem θ=90°.")
    if loaded_flanges not in (1, 2):
        raise ValueError("Informe uma ou duas mesas carregadas.")
    if c < 20 or h/t > 200:
        raise ValueError("Anexo D: exige c≥20 mm e h/t≤200; fora disso é necessário outro dispositivo de transmissão da força.")
    if family in {"U Formado", "C Formado"}:
        group, stiffened, table = "U", family == "C Formado", "D.2"
    elif family in {"Z Formado", "Z45 Formado", "Z90 Formado"}:
        group, stiffened, table = "Z", family != "Z Formado", "D.3"
    elif family == "Cartola Formado":
        group, stiffened, table = "Cartola", False, "D.4"
    else:
        raise ValueError("Família não abrangida pelas Tabelas D.2–D.4.")
    if c/t > (200 if group == "Cartola" else 210) or c/h > 2:
        raise ValueError("Dimensões de apoio fora dos limites c/t e c/h da Tabela "+table+".")
    end_loading = edge_distance <= 1.5*h
    key = group, stiffened, bool(connected), loaded_flanges, end_loading
    if key not in _BEARING:
        raise ValueError("Condição de mesa/força não prevista na Tabela "+table+".")
    alpha, ar, ac, ah, max_radius = _BEARING[key]
    if ri/t > max_radius:
        raise ValueError("ri/t supera o domínio da linha aplicável da Tabela "+table+".")
    if group in {"U", "Z"} and connected and loaded_flanges == 2 and not end_loading and edge_distance <= 2.5*h:
        raise ValueError("Força interna nas duas mesas conectadas exige distância à extremidade superior a 2,5h.")
    capacity = alpha*t*t*fy*(1-ar*sqrt(ri/t))*(1+ac*sqrt(c/t))*(1-ah*sqrt(h/t))/1.35
    if capacity <= 0:
        raise ValueError("Resistência de apoio não positiva no domínio informado.")
    return BearingResistance(capacity, (alpha, ar, ac, ah), table, end_loading, loaded_flanges)


def bearing_checks(element, model, fy):
    """Check declared design force per web; never assume equal load sharing."""
    from osa.domain.stability_inputs import stability_signature
    from osa.verification.structured_checks import check, number, step

    reference = 'ABNT NBR 14762:2010, Anexo D'
    output = {}
    basis = stability_signature(model)
    for name in element.member_names:
        member = model.bars[name]
        key = 'bearing_'+name
        base = {'critical_check': 'Forças concentradas — '+name, 'reference': reference,
                'parameters': {}, 'steps': []}
        if member.bearing_basis != basis:
            output[key] = {**base, 'status': 'not_checked', 'detail':
                'Revise as regiões de contato e forças de cálculo por alma. O cadastro está ausente ou foi invalidado por alterações físicas/cargas. Inclua apoios e forças aplicadas; não se presume transmissão direta à alma.'}
            continue
        if not member.bearing_regions:
            output[key] = {**base, 'status': 'not_applicable', 'detail':
                'Declarada a ausência de compressão localizada de alma neste modelo: forças concentradas inexistentes ou transmitidas diretamente à alma por dispositivo verificado separadamente.'}
            continue
        geometry = member.geometry_dict()
        radius = geometry.get('r', geometry['t'])
        h = geometry['d']-2*(radius+geometry['t'])
        for region in member.bearing_regions:
            error, capacity, steps, params = None, None, [], {'region': region.name,
                'contact_mm': region.contact_mm, 'edge_distance_mm': region.edge_distance_mm,
                'connected': region.connected, 'loaded_flanges': region.loaded_flanges,
                'force_source': 'força de cálculo informada por alma; envoltória de todas as combinações ELU',
                'assumptions': 'Inclui apoios e forças aplicadas. A distribuição entre almas e o dispositivo de transmissão são responsabilidade do cadastro físico.'}
            try:
                if model.load_combinations and region.combination not in model.load_combinations:
                    raise ValueError('Combinação de cálculo da região não cadastrada.')
                if (region.combination in model.load_combinations and
                        not model.load_combinations[region.combination].limit_state.upper().startswith('ELU')):
                    raise ValueError('A força de apoio deve corresponder a uma combinação ELU.')
                resistance = bearing_resistance(member.section, h=h, t=geometry['t'], ri=radius,
                    c=region.contact_mm, fy=fy, edge_distance=region.edge_distance_mm,
                    connected=region.connected, loaded_flanges=region.loaded_flanges)
                capacity = resistance.per_web_n/1000
                alpha, ar, ac, ah = resistance.coefficients
                params.update(h_mm=h, t_mm=geometry['t'], ri_mm=radius, fy_mpa=fy,
                              coefficients=resistance.coefficients, table=resistance.table)
                steps = [step('F_{Rd}', r'\alpha t^2f_y(1-\alpha_r\sqrt{r_i/t})(1+\alpha_c\sqrt{c/t})(1-\alpha_h\sqrt{h/t})/1{,}35',
                              f'α={number(alpha)}; αr={number(ar)}; αc={number(ac)}; αh={number(ah)}',
                              capacity, 'kN por alma', 'D.2 / Tabela '+resistance.table)]
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                error = str(exc)
            sample = {'x': region.position_m, 'bearing_force': region.force_per_web_kn}
            item = check('shear_z', [(region.combination, name, sample)], lambda row: row['bearing_force'],
                         capacity, params, steps, reference, error)
            item['critical_check'] = 'Esmagamento da alma — '+name+' / '+region.name
            output[key+'_'+region.name] = item
    return output
