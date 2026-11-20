"""Seven-DOF open-section Euler–Bernoulli/Vlasov beam element.

Units: N, mm, radians. Nodal order is [uC,vC,wC,theta,ry,rz,theta'];
warping is an independent slope DOF. The axial reference is the centroid;
transverse bending is referred to the principal sectorial shear centre.
Elastic energy and initial-normal-stress energy are integrated directly.
This element is a kernel; it does not itself assert an ultimate resistance.
"""
from dataclasses import dataclass
from math import isfinite

import numpy as np

VLASOV_ALGORITHM = 'vlasov-7gl-3'


@dataclass(frozen=True)
class VlasovSection:
    area: float
    iy: float
    iz: float
    iyz: float
    j: float
    cw: float
    ysc: float = 0.
    zsc: float = 0.
    wagner_y: float = 0.
    wagner_z: float = 0.
    wagner_w: float = 0.
    initial_r0_squared: float | None = None
    normal_matrix: tuple[tuple[float, ...], ...] | None = None

    def __post_init__(self):
        if not all(isfinite(value) for value in (self.area, self.iy, self.iz, self.iyz, self.j, self.cw,
            self.ysc, self.zsc, self.wagner_y, self.wagner_z, self.wagner_w)):
            raise ValueError('Propriedades de Vlasov não finitas.')
        if self.initial_r0_squared is not None and (not isfinite(self.initial_r0_squared) or self.initial_r0_squared <= 0):
            raise ValueError('Raio polar geométrico inválido.')
        if min(self.area, self.iy, self.iz, self.j) <= 0 or self.cw < 0 or self.iy*self.iz <= self.iyz**2:
            raise ValueError('Área, inércias ou constante de empenamento inválidas.')

        if self.normal_matrix is not None:
            matrix = np.asarray(self.normal_matrix, dtype=float)
            if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
                raise ValueError('Matriz normal/setorial inválida.')
            symmetry_scale = np.sqrt(np.maximum(abs(np.diag(matrix)), 1e-30))
            if np.max(abs(matrix-matrix.T)/np.outer(symmetry_scale, symmetry_scale)) > 1e-12:
                raise ValueError('Matriz normal/setorial assimétrica.')
            matrix = (matrix+matrix.T)/2
            active = 3 if matrix[3, 3] == 0 else 4
            if active == 3 and np.any(matrix[3, :] != 0):
                raise ValueError('Acoplamento setorial sem rigidez de empenamento.')
            diagonal = np.diag(matrix)[:active]
            if np.any(diagonal <= 0):
                raise ValueError('Matriz normal/setorial não positiva.')
            scaling = np.sqrt(diagonal)
            if min(np.linalg.eigvalsh(matrix[:active, :active]/np.outer(scaling, scaling))) <= 1e-12:
                raise ValueError('Matriz normal/setorial não positiva ou singular.')
            object.__setattr__(self, 'normal_matrix', tuple(tuple(float(value) for value in row) for row in matrix))

    @property
    def normal_gram(self):
        if self.normal_matrix is not None:
            return np.asarray(self.normal_matrix, dtype=float)
        return np.array(((self.area, 0., 0., 0.), (0., self.iy, -self.iyz, 0.),
                         (0., -self.iyz, self.iz, 0.), (0., 0., 0., self.cw)))

    @property
    def r0_squared(self):
        if self.initial_r0_squared is not None:
            return self.initial_r0_squared
        return (self.iy+self.iz)/self.area+self.ysc**2+self.zsc**2

    @property
    def transform(self):
        matrix = np.eye(14)
        for offset in (0, 7):
            matrix[offset+1, offset+3] = -self.zsc
            matrix[offset+2, offset+3] = self.ysc
        return matrix


def section_from_sheet(family, geometry, mirror=False):
    """Actual rounded normal properties, principal sectorial Cw/shear centre."""
    from osa.sections.properties import calculate_section_properties
    from osa.sections.thin_walled import open_sheet, sectorial_properties

    sheet = open_sheet(family, geometry, mirror=mirror)
    props = calculate_section_properties(family, geometry, mirror_z=mirror)
    sector = sectorial_properties(sheet)
    sc = np.array((sector['shear_center_y_mm'], sector['shear_center_z_mm']))
    points, weights = sheet.quadrature()
    centroid = np.sum(points*weights[:, None], axis=0)/sum(weights)
    centered = points-centroid
    basis = np.column_stack((np.ones(len(points)), centered[:, 1], -centered[:, 0]))
    matrix = basis.T@(weights[:, None]*basis)
    polar = np.sum((points-sc)**2, axis=1)
    wagner = polar@(weights[:, None]*(basis@np.linalg.solve(matrix, np.eye(3)[:, 1:])))
    sharp, sharp_weights = sheet.quadrature(sharp=True)
    xi, _weights = np.polynomial.legendre.leggauss(8)
    omega = np.concatenate([a+(xi+1)/2*(b-a) for a, b in zip(sector['omega_mm2'][:-1], sector['omega_mm2'][1:], strict=True)])
    cw = sector['Cw_mm6']
    beta_w = float(sharp_weights@(np.sum((sharp-sc)**2, axis=1)*omega)/cw) if cw > 1e-12 else 0.
    return VlasovSection(props.area_mm2, props.iy_mm4, props.iz_mm4, props.iyz_mm4,
                         props.j_mm4, cw, sc[0]-props.centroid_y_mm, sc[1]-props.centroid_z_mm,
                         float(wagner[0]), float(wagner[1]), beta_w)



def rounded_section_from_sheet(family, geometry, mirror=False, *, sectorial_mode=True):
    """Continuous rounded mean-line section at the program's nodal datum.

    Nodes retain the existing gross-section centroid. The complete normal
    Gram matrix carries any offset to the mean-line centroid explicitly;
    omega, Cw, pole and normal properties use the same mean-line measure.
    Saint-Venant J retains the existing thin-wall section convention.
    """
    from osa.sections.properties import calculate_section_properties
    from osa.sections.thin_walled import open_sheet, rounded_sectorial_field

    props = calculate_section_properties(family, geometry, mirror_z=mirror)
    origin = (props.centroid_y_mm, props.centroid_z_mm)
    sheet = open_sheet(family, geometry, mirror=mirror)
    field = rounded_sectorial_field(sheet, normal_origin=origin)
    basis, weights = field.quadrature()
    matrix = basis.T@(weights[:, None]*basis)
    points, _weights = sheet.quadrature()
    sc = np.asarray(field.shear_center_mm)
    polar = np.sum((points-sc)**2, axis=1)
    wagner = polar@(weights[:, None]*(basis@np.linalg.solve(matrix, np.eye(4)[:, 1:])))
    r0 = float(weights@polar/sum(weights))
    if not sectorial_mode:
        matrix[3, :] = matrix[:, 3] = 0.
        wagner[2] = 0.
    return VlasovSection(float(matrix[0, 0]), float(matrix[1, 1]), float(matrix[2, 2]),
        float(-matrix[1, 2]), props.j_mm4, field.cw_mm6 if sectorial_mode else 0., sc[0]-origin[0], sc[1]-origin[1],
        *map(float, wagner), initial_r0_squared=r0, normal_matrix=tuple(map(tuple, matrix)))


def shapes(length, fraction):
    """Local interpolation rows and first/second/third derivatives at x/L."""
    if not isfinite(length) or length <= 0 or not isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError('Comprimento ou posição de integração inválidos.')
    s, L = fraction, length
    hermite = np.array((1-3*s*s+2*s**3, L*(s-2*s*s+s**3), 3*s*s-2*s**3, L*(-s*s+s**3)))
    first = np.array(((-6*s+6*s*s)/L, 1-4*s+3*s*s, (6*s-6*s*s)/L, -2*s+3*s*s))
    second = np.array(((-6+12*s)/L**2, (-4+6*s)/L, (6-12*s)/L**2, (-2+6*s)/L))
    third = np.array((12/L**3, 6/L**2, -12/L**3, 6/L**2))
    output = {}
    for name, ids, signs in (('v', (1, 5, 8, 12), (1, 1, 1, 1)),
                            ('w', (2, 4, 9, 11), (1, -1, 1, -1)),
                            ('theta', (3, 6, 10, 13), (1, 1, 1, 1))):
        for suffix, values in (('', hermite), ('1', first), ('2', second), ('3', third)):
            row = np.zeros(14)
            row[list(ids)] = values*np.asarray(signs)
            output[name+suffix] = row
    output['u'] = np.zeros(14)
    output['u'][[0, 7]] = 1-s, s
    output['u1'] = np.zeros(14)
    output['u1'][[0, 7]] = -1/L, 1/L
    return output


def element_matrices(length, section, E, G, *, compression=0., moment_y=0., moment_z=0., bimoment=0.):
    """Elastic K and destabilizing G (positive compression); tangent=K-G.

    Initial bending/warping stresses enter the polar stress resultant and
    the bending–twist couplings. The resultants are constant over this
    element; a global analysis must resolve their variation with its mesh.
    """
    if not all(isfinite(value) and value > 0 for value in (E, G)) or not all(isfinite(value) for value in (compression, moment_y, moment_z, bimoment)):
        raise ValueError('Módulos ou esforços iniciais inválidos.')
    matrix, geometric = np.zeros((14, 14)), np.zeros((14, 14))
    polar = compression*section.r0_squared+moment_y*section.wagner_y+moment_z*section.wagner_z+bimoment*section.wagner_w
    stress = np.array(((compression, 0., -moment_y+section.zsc*compression),
                       (0., compression, -moment_z-section.ysc*compression),
                       (-moment_y+section.zsc*compression, -moment_z-section.ysc*compression, polar)))
    transform = section.transform
    xi, wi = np.polynomial.legendre.leggauss(4)
    for fraction, weight in zip((xi+1)/2, wi*length/2, strict=True):
        shape = shapes(length, fraction)
        u, v2, w2, t1, t2 = (shape[key] for key in ('u1', 'v2', 'w2', 'theta1', 'theta2'))
        normal_strain = np.stack((-u, w2, -v2, t2))
        matrix += weight*(E*normal_strain.T@section.normal_gram@normal_strain+G*section.j*np.outer(t1, t1))
        gradient = np.stack((shape['v1'], shape['w1'], t1))
        geometric += weight*(gradient.T@stress@gradient+compression*np.outer(u, u))
    return transform.T@matrix@transform, transform.T@geometric@transform


def consistent_load(length, section, *, axial=(0., 0.), force_y=(0., 0.), force_z=(0., 0.), torque=(0., 0.)):
    """Consistent 14-DOF forces for linear densities applied at the centroid.

    Force densities are N/mm; torque densities N mm/mm. The warping DOF is
    conjugate to a bimoment (N mm²). Eccentricity to SC is included in work.
    """
    if any(len(values) != 2 or not all(isfinite(value) for value in values) for values in (axial, force_y, force_z, torque)):
        raise ValueError('Densidades de carga inválidas.')
    result = np.zeros(14)
    xi, wi = np.polynomial.legendre.leggauss(4)
    for fraction, weight in zip((xi+1)/2, wi*length/2, strict=True):
        shape = shapes(length, fraction)
        qx, qy, qz, qt = (start+(end-start)*fraction for start, end in (axial, force_y, force_z, torque))
        sc_torque = qt+section.zsc*qy-section.ysc*qz
        result += weight*(qx*shape['u']+qy*shape['v']+qz*shape['w']+sc_torque*shape['theta'])
    return section.transform.T@result


def recover(length, section, E, G, displacements, fraction):
    """Recover centroidal displacement and elastic stress resultants.

    Normal resultants follow tension-positive sigma=N/A+My*z/Iy-Mz*y/Iz;
    B=-ECw*theta''. Transverse loads/torques are about SC for stress recovery.
    """
    d = np.asarray(displacements, dtype=float)
    if d.shape != (14,) or not np.all(np.isfinite(d)):
        raise ValueError('Deslocamentos de Vlasov inválidos.')
    rows = shapes(length, fraction)
    sc = section.transform@d
    v, w, theta, theta1, theta2, theta3 = (float(rows[key]@sc) for key in ('v', 'w', 'theta', 'theta1', 'theta2', 'theta3'))
    v2, w2 = float(rows['v2']@sc), float(rows['w2']@sc)
    saint_venant = G*section.j*theta1
    normal = E*section.normal_gram@np.array((-float(rows['u1']@sc), w2, -v2, theta2))
    derivative = np.array((0., float(rows['w3']@sc), -float(rows['v3']@sc), theta3))
    warping = float(-E*section.normal_gram[3]@derivative)
    return {'uC_mm': float(rows['u']@sc), 'vC_mm': v+section.zsc*theta,
            'wC_mm': w-section.ysc*theta, 'twist_rad': theta, 'twist_rate_per_mm': theta1,
            'axial_tension_N': float(-normal[0]),
            'moment_y_Nmm': float(-normal[1]),
            'moment_z_Nmm': float(-normal[2]),
            'bimoment_Nmm2': float(-normal[3]),
            'saint_venant_torque_Nmm': saint_venant, 'warping_torque_Nmm': warping,
            'total_torque_Nmm': saint_venant+warping}
