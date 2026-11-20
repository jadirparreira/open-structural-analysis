"""Elastic Vlasov member stability and sectorial properties of open sheets.

Compression follows NBR 14762:2010 9.7.2.1–3. Uniform-moment bending uses
fork-supported ends, free warping and loads through the shear centre (C.2).
Lengths and boundary conditions must be supplied; topology does not infer K.
All internal units are N and mm.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, pi, radians, sin, sqrt

import numpy as np
from scipy.linalg import eigh

from osa.sections.properties import calculate_section_properties
from osa.sections.thin_walled import open_sheet, sectorial_properties


@dataclass(frozen=True)
class GlobalSection:
    area: float
    i1: float
    i2: float
    j: float
    cw: float
    u0: float
    v0: float
    r0: float
    angle: float
    # Polar initial-stress moments for unit geometric My and Mz, in mm.
    wagner_y: float
    wagner_z: float


def global_section(family, geometry, *, mirror=False):
    sheet = open_sheet(family, geometry, mirror=mirror)
    props = calculate_section_properties(family, geometry, mirror_z=mirror)
    sector = sectorial_properties(sheet)
    angle = radians(props.principal_axis_angle_deg)
    c, s = cos(angle), sin(angle)
    dy = sector["shear_center_y_mm"]-props.centroid_y_mm
    dz = sector["shear_center_z_mm"]-props.centroid_z_mm
    u0, v0 = c*dy+s*dz, -s*dy+c*dz
    r0 = sqrt((props.iy_mm4+props.iz_mm4)/props.area_mm2+dy*dy+dz*dz)
    points, weights = sheet.quadrature()
    centroid = np.sum(points*weights[:, None], axis=0)/weights.sum()
    centered = points-centroid
    # Exact curved mean-line integration for the bending stress field and
    # its polar moment about the independently determined shear centre.
    basis = np.column_stack((np.ones(len(points)), centered[:, 1], -centered[:, 0]))
    moment_matrix = basis.T@(weights[:, None]*basis)
    polar = np.sum((points-np.array((sector["shear_center_y_mm"], sector["shear_center_z_mm"])))**2, axis=1)
    coeff = np.linalg.solve(moment_matrix, np.eye(3)[:, 1:])
    wagner = polar@(weights[:, None]*(basis@coeff))
    return GlobalSection(props.area_mm2, props.i_major_mm4, props.i_minor_mm4, props.j_mm4,
                         sector["Cw_mm6"], u0, v0, r0, angle, float(wagner[0]), float(wagner[1]))


def _positive(*values):
    if not all(isfinite(v) and v > 0 for v in values):
        raise ValueError("Módulos e comprimentos efetivos devem ser finitos e positivos.")


def compression_critical(section, E, G, kl1, kl2, klt):
    """Smallest positive elastic compression eigenvalue, including coupling.

    The determinant is exactly the cubic in 9.7.2.3; this symmetric definite
    eigenproblem also covers the mono- and doubly-symmetric special cases.
    """
    _positive(E, G, kl1, kl2, klt)
    n1, n2 = pi*pi*E*section.i1/kl1**2, pi*pi*E*section.i2/kl2**2
    torsional = pi*pi*E*section.cw/klt**2+G*section.j
    elastic = np.diag((n1, n2, torsional))
    geometric = np.array(((1., 0., section.u0), (0., 1., section.v0),
                          (section.u0, section.v0, section.r0**2)))
    values = eigh(elastic, geometric, eigvals_only=True)
    return float(values[0]), {"Ne1_N": n1, "Ne2_N": n2,
                             "Net_N": torsional/section.r0**2, "eigenvalues_N": tuple(map(float, values))}


def bending_critical(section, E, G, lb, lt, *, lb2=None, moment_y=1., moment_z=0.):
    """Both signs of uniform bending in one or both geometric directions.

    Return the minimum absolute elastic load multiplier and its sign. For
    a unit moment input it is an elastic moment in N mm. A common lateral
    length lb is used in both principal directions; lt is the twist length.
    """
    lb2 = lb if lb2 is None else lb2
    _positive(E, G, lb, lb2, lt)
    if not all(isfinite(v) for v in (moment_y, moment_z)) or hypot2(moment_y, moment_z) == 0:
        raise ValueError("Informe um vetor de momento finito e não nulo.")
    c, s = cos(section.angle), sin(section.angle)
    m1, m2 = c*moment_y+s*moment_z, -s*moment_y+c*moment_z
    elastic = np.diag((pi*pi*E*section.i1/lb**2, pi*pi*E*section.i2/lb2**2,
                       pi*pi*E*section.cw/lt**2+G*section.j))
    geometric = np.array(((0., 0., -m2), (0., 0., -m1),
                          (-m2, -m1, section.wagner_y*moment_y+section.wagner_z*moment_z)))
    values = eigh(geometric, elastic, eigvals_only=True)
    critical = min((1/abs(v), 1 if v > 0 else -1) for v in values if abs(v) > 1e-30)
    return float(critical[0]), int(critical[1])


def hypot2(a, b):
    return a*a+b*b
