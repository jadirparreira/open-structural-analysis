"""Elastic Vlasov torsion and thin-wall stress recovery.

Internal units: N, mm, radians. This analysis does not supply an ultimate
buckling resistance. A prescribed torque diagram must be statically
admissible with the real torsional/warping restraints; a six-DOF analysis
of an indeterminate system cannot establish that diagram with gross GJ.

Convention: B=-ECw*theta'', Tw=B', T=GJ*theta'+Tw. Sectorial area has
omega'=y*z'-z*y' around the principal shear centre. Thus sigma_w=B*omega/Cw
and q_w=-Tw*S_omega/Cw recover a positive torque about local x.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import factorial, isfinite, sqrt

import numpy as np
from scipy.linalg import solve_banded

from osa.sections.thin_walled import sectorial_properties


def _ratios(a, u):
    """sinh(u)/sinh(a) and cosh(u)/sinh(a), stable for a >> 1."""
    denominator = -np.expm1(-2*a)
    first = np.exp(u-a)
    second = np.exp(-u-a)
    return (first-second)/denominator, (first+second)/denominator


@dataclass(frozen=True)
class TorsionState:
    x_mm: np.ndarray
    torque_nmm: np.ndarray
    bimoment_nmm2: np.ndarray
    warping_torque_nmm: np.ndarray
    saint_venant_torque_nmm: np.ndarray
    twist_rad: np.ndarray
    twist_rate_per_mm: np.ndarray


def prescribed_torque(x, torque, *, E, G, J, Cw, warping_start='free', warping_end='free', positions=None):
    """Exact piecewise-linear-T solution, free B=0 / blocked theta'=0.

    Endpoint torque and distributed torque follow the supplied continuous
    diagram. A concentrated torque inside the bar must be represented by
    distinct connected segments with its equilibrium jump and compatible
    rotation/warping, rather than smearing a discontinuity over this model.
    No torsional rotational support is inferred from a warping restraint.
    theta(0)=0 only sets the reference rotation.
    """
    x, torque = np.asarray(x, dtype=float), np.asarray(torque, dtype=float)
    if x.ndim != 1 or len(x) < 2 or torque.shape != x.shape or not np.all(np.isfinite(x)) or not np.all(np.isfinite(torque)):
        raise ValueError('Diagrama de torção incompleto ou não finito.')
    if x[0] != 0 or np.any(np.diff(x) <= 0):
        raise ValueError('O diagrama deve iniciar em zero e ter posições crescentes.')
    if not all(isfinite(value) and value > 0 for value in (E, G, J, Cw)):
        raise ValueError('Rigidezes e constante de empenamento devem ser positivas e finitas.')
    if any(value not in ('free', 'blocked') for value in (warping_start, warping_end)):
        raise ValueError('Declare empenamento livre ou impedido em cada extremidade.')
    xp = np.asarray(positions if positions is not None else x, dtype=float)
    if xp.ndim != 1 or not np.all(np.isfinite(xp)) or np.any(xp < 0) or np.any(xp > x[-1]):
        raise ValueError('Posições de recuperação fora da barra.')
    k = sqrt(G*J/(E*Cw))
    a = k*np.diff(x)
    csch, coth = _ratios(a, np.zeros_like(a))[1], _ratios(a, a)[1]
    particular = -np.diff(torque)/np.diff(x)/k**2
    # Exact dynamic stiffness of B''-k²B=T', assembled as a tridiagonal
    # positive system; no hyperbolic overflow for very long members.
    matrix = np.zeros((3, len(x)))
    rhs = np.zeros(len(x))
    for i in range(len(x)-1):
        diagonal, cross = k*coth[i], -k*csch[i]
        matrix[1, i] += diagonal
        matrix[1, i+1] += diagonal
        matrix[0, i+1] = cross
        matrix[2, i] = cross
        rhs[i:i+2] += k*np.tanh(a[i]/2)*particular[i]
    if warping_start == 'free':
        matrix[1, 0], matrix[0, 1], rhs[0] = 1., 0., 0.
    else:
        rhs[0] -= torque[0]
    if warping_end == 'free':
        matrix[1, -1], matrix[2, -2], rhs[-1] = 1., 0., 0.
    else:
        rhs[-1] += torque[-1]
    nodes = solve_banded((1, 1), matrix, rhs)
    interval = np.minimum(np.searchsorted(x, xp, side='right')-1, len(x)-2)
    u = k*(xp-x[interval])
    left_s, left_c = _ratios(a[interval], a[interval]-u)
    right_s, right_c = _ratios(a[interval], u)
    left, right = nodes[interval]-particular[interval], nodes[interval+1]-particular[interval]
    B = particular[interval]+left*left_s+right*right_s
    Tw = k*(-left*left_c+right*right_c)
    T = np.interp(xp, x, torque)
    Tsv = T-Tw
    slopes = np.diff(torque)/np.diff(x)
    integral = np.r_[0., np.cumsum((torque[1:]+torque[:-1])*np.diff(x)/2)]
    distance = xp-x[interval]
    integral_at = integral[interval]+torque[interval]*distance+.5*slopes[interval]*distance**2
    theta = (integral_at-(B-nodes[0]))/(G*J)
    return TorsionState(xp, T, B, Tw, Tsv, theta, Tsv/(G*J))


@dataclass(frozen=True)
class ThinWallStresses:
    positions_mm: np.ndarray
    omega_mm2: np.ndarray
    sectorial_first_mm4: np.ndarray
    normal_mpa: np.ndarray
    shear_flow_n_mm: np.ndarray
    saint_venant_surface_mpa: float
    t_mm: float

    @property
    def maximum_shear_mpa(self):
        return float(np.max(abs(self.shear_flow_n_mm))/self.t_mm+abs(self.saint_venant_surface_mpa))

    @property
    def maximum_von_mises_mpa(self):
        shear = abs(self.shear_flow_n_mm)/self.t_mm+abs(self.saint_venant_surface_mpa)
        return float(np.max(np.sqrt(self.normal_mpa**2+3*shear**2)))


def thin_wall_stresses(sheet, *, axial=0., moment_y=0., moment_z=0., shear_y=0., shear_z=0.,
                       bimoment=0., warping_torque=0., saint_venant_torque=0., J=None, divisions=40):
    """Sharp-fold stress field and shear flow; positive axial stress is tension.

    Shear resultants and torque are recovered by contour equilibrium. Bending
    resultants use [1,z,-y], consistent with the section verifier. The two
    opposite Saint-Venant surface values are enveloped at each contour point.
    The membrane/sectorial stresses are constant through thickness (thin wall
    approximation); local stress concentrations at bends are outside this model.
    """
    if not all(isfinite(value) for value in (axial, moment_y, moment_z, shear_y, shear_z, bimoment, warping_torque, saint_venant_torque)):
        raise ValueError('Esforços não finitos na recuperação de tensões.')
    if type(divisions) is not int or divisions < 2:
        raise ValueError('A discretização deve conter ao menos duas divisões por parede.')
    vertices = np.asarray(sheet.vertices)
    t = sheet.thickness
    sectorial = sectorial_properties(sheet)
    omega_nodes, cw = sectorial['omega_mm2'], sectorial['Cw_mm6']
    points, weights = sheet.quadrature(sharp=True)
    centroid = np.sum(points*weights[:, None], axis=0)/sum(weights)
    relative = points-centroid
    basis = np.column_stack((np.ones(len(points)), relative[:, 1], -relative[:, 0]))
    gram = basis.T@(weights[:, None]*basis)
    coefficients = np.linalg.solve(gram, (axial, moment_y, moment_z))
    inertia = relative.T@(weights[:, None]*relative)
    flow_coefficients = np.linalg.solve(inertia, (-shear_y, -shear_z))
    if cw <= 1e-16*sum(weights)*max(np.linalg.norm(vertices, axis=1))**4:
        if abs(bimoment)+abs(warping_torque) > 1e-12:
            raise ValueError('Seção sem grau de liberdade setorial no modelo de parede fina.')
        cw = 1.
    positions, omegas, firsts, q, normal = [], [], [], [], []
    first_yz, first_omega = np.zeros(2), 0.
    for i, (start, end) in enumerate(pairwise(vertices)):
        length = np.linalg.norm(end-start)
        fraction = np.linspace(0., 1., divisions+1)
        local = start+fraction[:, None]*(end-start)
        omega = omega_nodes[i]+fraction*(omega_nodes[i+1]-omega_nodes[i])
        yz = first_yz+t*length*(fraction[:, None]*(start-centroid)+.5*fraction[:, None]**2*(end-start))
        sw = first_omega+t*length*(fraction*omega_nodes[i]+.5*fraction**2*(omega_nodes[i+1]-omega_nodes[i]))
        stress_basis = np.column_stack((np.ones(len(local)), local[:, 1]-centroid[1], -(local[:, 0]-centroid[0])))
        positions.extend(local)
        omegas.extend(omega)
        firsts.extend(sw)
        q.extend(yz@flow_coefficients-warping_torque*sw/cw)
        normal.extend(stress_basis@coefficients+bimoment*omega/cw)
        first_yz, first_omega = yz[-1], sw[-1]
    if J is None:
        J = sum(np.linalg.norm(np.diff(vertices, axis=0), axis=1))*t**3/3
    if not isfinite(J) or J <= 0:
        raise ValueError('Constante de torção inválida.')
    return ThinWallStresses(np.asarray(positions), np.asarray(omegas), np.asarray(firsts),
                           np.asarray(normal), np.asarray(q), saint_venant_torque*t/J, t)


@dataclass(frozen=True)
class TorsionEndModel:
    """Condensed exact end-rotation stiffness with independent end warping.

    Warping is declared free or blocked at each physical member end. A
    continuous warping degree of freedom shared by multiple members cannot
    be condensed independently with this model. This object supplies elastic
    stiffness and consistent loading, not an ultimate resistance.
    """
    length_mm: float
    E: float
    G: float
    J_mm4: float
    Cw_mm6: float
    warping_start: str = 'free'
    warping_end: str = 'free'

    def __post_init__(self):
        if not all(isfinite(value) and value > 0 for value in (self.length_mm, self.E, self.G, self.J_mm4)) or not isfinite(self.Cw_mm6) or self.Cw_mm6 < 0:
            raise ValueError('Comprimento e rigidezes de torção inválidos.')
        if any(value not in ('free', 'blocked') for value in (self.warping_start, self.warping_end)):
            raise ValueError('Declare empenamento livre ou impedido em cada extremidade.')

    @property
    def compliance_rad_nmm(self):
        if self.Cw_mm6 == 0 or (self.warping_start, self.warping_end) == ('free', 'free'):
            return self.length_mm/(self.G*self.J_mm4)
        a = sqrt(self.G*self.J_mm4/(self.E*self.Cw_mm6))*self.length_mm
        if self.warping_start == self.warping_end:
            a /= 2
        # 1-tanh(a)/a loses all significant digits for short members or
        # dominant warping stiffness. Its series retains the cubic limit.
        if a < .01:
            factor = a*a*(1/3+a*a*(-2/15+a*a*(17/315-62*a*a/2835)))
        else:
            factor = 1-np.tanh(a)/a
        return self.length_mm/(self.G*self.J_mm4)*factor

    @property
    def stiffness_nmm(self):
        return np.array(((1., -1.), (-1., 1.)))/self.compliance_rad_nmm

    def end_rotation_shape(self, positions):
        """theta(x) for theta(0)=0, theta(L)=1, with declared warping BC."""
        x = np.asarray(positions, dtype=float)
        if not np.all(np.isfinite(x)) or np.any(x < 0) or np.any(x > self.length_mm):
            raise ValueError('Posições de torção fora da barra.')
        s = x/self.length_mm
        if self.Cw_mm6 == 0 or (self.warping_start, self.warping_end) == ('free', 'free'):
            return s
        k = sqrt(self.G*self.J_mm4/(self.E*self.Cw_mm6))
        a = k*self.length_mm
        if a < .1:
            # Expand the cancellation-prone quotient itself, cancelling a²
            # analytically. Terms through a^12 keep relative error <1e-11
            # on this interval, including the pure-warping cubic limit.
            if self.warping_start == 'free':
                return 1-self._short_shape(1-s, a, both=False)
            return self._short_shape(s, a/2 if self.warping_start == self.warping_end else a,
                                     both=self.warping_start == self.warping_end)
        def sinh_cosh_ratio(u, denominator):
            return (np.exp(u-denominator)-np.exp(-u-denominator))/(1+np.exp(-2*denominator))
        if self.warping_start == self.warping_end:
            B = sinh_cosh_ratio(k*x-a/2, a/2)/k
            B0 = -np.tanh(a/2)/k
        elif self.warping_start == 'blocked':
            B = -sinh_cosh_ratio(a-k*x, a)/k
            B0 = -np.tanh(a)/k
        else:
            B = sinh_cosh_ratio(k*x, a)/k
            B0 = 0.
        return (x-(B-B0))/(self.G*self.J_mm4*self.compliance_rad_nmm)

    @staticmethod
    def _short_shape(s, a, *, both):
        sech = (1., -.5, 5/24, -61/720, 1385/40320, -50521/3628800, 2702765/479001600)
        r = 2*s-1 if both else 1-s
        numerator, denominator = np.zeros_like(s, dtype=float), 0.
        for n in range(1, len(sech)):
            coefficient, end_coefficient = np.zeros_like(s, dtype=float), 0.
            for i in range(n+1):
                j = n-i
                value = (1+r**(2*j+1))/2 if both else 1-r**(2*j+1)
                coefficient -= sech[i]*value/factorial(2*j+1)
                end_coefficient -= sech[i]/factorial(2*j+1)
            numerator += coefficient*a**(2*(n-1))
            denominator += end_coefficient*a**(2*(n-1))
        return numerator/denominator

    def consistent_torque_load(self, start_mm, end_mm, initial_n, final_n):
        """Equivalent end torques for a linear distributed torque (N mm/mm).

        Exact homogeneous virtual-rotation shapes ensure consistent work for
        the condensed end rotations. They include the restraint of warping;
        using the Saint-Venant linear shape would give incorrect end torques
        when one end is warping restrained and the other is free.
        """
        from scipy.integrate import quad

        if not all(isfinite(value) for value in (start_mm, end_mm, initial_n, final_n)) or not 0 <= start_mm < end_mm <= self.length_mm:
            raise ValueError('Trecho de momento distribuído inválido.')
        span = end_mm-start_mm
        total = span*(initial_n+final_n)/2
        def integrand(x):
            torque = initial_n+(final_n-initial_n)*(x-start_mm)/span
            return float(torque*self.end_rotation_shape(x))
        end_torque = quad(integrand, start_mm, end_mm, epsabs=max(1., abs(total))*1e-10, epsrel=1e-10, limit=100)[0]
        return np.array((total-end_torque, end_torque))


def centroid_to_shear_center_transform(y_sc_mm, z_sc_mm):
    """Local 12-DOF transverse kinematic transform, C -> SC reference.

    The axial reference remains the centroid, so axial displacement and the
    two bending rotations are unchanged. At each end: vSC=vC-zSC*theta,
    wSC=wC+ySC*theta. Force transformation preserves virtual work and yields
    TSC=TC+zSC*Vy-ySC*Vz. All translational DOFs/offsets use mm.
    """
    if not isfinite(y_sc_mm) or not isfinite(z_sc_mm):
        raise ValueError('Centro de torção não finito.')
    matrix = np.eye(12)
    for offset in (0, 6):
        matrix[offset+1, offset+3] = -z_sc_mm
        matrix[offset+2, offset+3] = y_sc_mm
    return matrix
