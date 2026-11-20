"""Sparse seven-DOF cold-member assembly alongside the PyNite model.

Original nodes retain their six physical DOFs. Internal mesh coordinates and
warping DOFs are private to this solve; a continuous warping DOF is shared
only when explicitly declared and geometrically compatible. Other members,
plates and support springs retain the existing six-DOF elastic formulation.
"""
import itertools
from dataclasses import dataclass, replace
from math import ceil, cos, radians, sin, sqrt

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import splu

from osa.analysis.vlasov import (
    VLASOV_ALGORITHM,
    VlasovSection,
    element_matrices,
    recover,
    rounded_section_from_sheet,
    shapes,
)
from osa.sections.thin_walled import open_sheet, rounded_sectorial_field

COLD = {'U Formado', 'C Formado', 'Z Formado', 'Z45 Formado', 'Z90 Formado', 'L Formado', 'Cartola Formado'}
FIELDS = ('DX', 'DY', 'DZ', 'RX', 'RY', 'RZ')
REACTIONS = ('RxnFX', 'RxnFY', 'RxnFZ', 'RxnMX', 'RxnMY', 'RxnMZ')


@dataclass
class Element:
    owner: str
    member: object
    start_m: float
    end_m: float
    offset_m: float
    section: VlasovSection
    E: float
    G: float
    rotation: np.ndarray
    angle: float
    indices: np.ndarray
    transform: np.ndarray
    elastic: np.ndarray

    @property
    def length(self):
        return (self.end_m-self.start_m)*1000


def _local_vector(direction, value, rotation):
    vector = np.zeros(6)
    axis = 'XYZ'.index(direction[-1].upper())
    if direction[0] == 'M':
        axis += 3
    vector[axis] = value
    if direction[-1].isupper():
        vector[:3] = rotation@vector[:3]
        vector[3:] = rotation@vector[3:]
    return vector


def _work_row(length, section, fraction, vector):
    row = shapes(length, fraction)
    fx, fy, fz, tx, my, mz = vector
    sc = (fx*row['u']+fy*row['v']+fz*row['w']+
          (tx+section.zsc*fy-section.ysc*fz)*row['theta']-my*row['w1']+mz*row['v1'])
    return section.transform.T@sc


def _loads(element, reference):
    factors = element.member.model.load_combos[reference].factors
    lines, points = [], []
    a, b = element.start_m, element.end_m
    for load in element.member.DistLoads:
        direction, start, end, lo, hi, case = load[:6]
        factor = factors.get(case, 0.)
        if not factor or hi <= a or lo >= b:
            continue
        left, right = max(a, lo), min(b, hi)
        q0, q1 = start+(end-start)*(left-lo)/(hi-lo), start+(end-start)*(right-lo)/(hi-lo)
        # kN/m = N/mm. PyNite distributed loads here contain forces only.
        lines.append(((left-a)*1000, (right-a)*1000,
                      _local_vector(direction, q0*factor, element.rotation),
                      _local_vector(direction, q1*factor, element.rotation)))
    continuous = [item for item in getattr(element.member.model, '_osa_continuous_moments', ()) if item[0] == element.owner]
    continuous_cases = {item[3] for item in continuous}
    for _owner, axis, density, case in continuous:
        factor = factors.get(case, 0.)
        if not factor:
            continue
        vector = np.zeros(6)
        value = density*factor*1000  # kN m/m -> N mm/mm
        c, s = cos(element.angle), sin(element.angle)
        if axis == 'X':
            vector[3] = value
        elif axis == 'Y':
            vector[4:6] = c*value, -s*value
        else:
            vector[4:6] = s*value, c*value
        lines.append((0., element.length, vector, vector))
    for load in element.member.PtLoads:
        direction, value, position, case = load[:4]
        if direction.startswith('M') and case in continuous_cases:
            continue
        factor = factors.get(case, 0.)
        last = abs(b-element.member.L()) < 1e-10
        if factor and position >= a-1e-10 and (position < b-1e-10 or last and position <= b+1e-10):
            scale = 1e6 if direction[0] == 'M' else 1000.
            points.append((max(0., min(element.length, (position-a)*1000)),
                           _local_vector(direction, value*factor*scale, element.rotation)))
    return lines, points


def _load_vector(element, loads):
    result = np.zeros(14)
    xi, wi = np.polynomial.legendre.leggauss(4)
    for a, b, q0, q1 in loads[0]:
        for x, weight in zip(a+(xi+1)/2*(b-a), wi*(b-a)/2, strict=True):
            vector = q0+(q1-q0)*(x-a)/(b-a)
            result += weight*_work_row(element.length, element.section, x/element.length, vector)
    for x, vector in loads[1]:
        result += _work_row(element.length, element.section, x/element.length, vector)
    return result


def _axial_integral(loads, x):
    value = 0.
    for a, b, q0, q1 in loads[0]:
        stop = min(x, b)
        if stop > a:
            span = stop-a
            value += q0[0]*span+(q1[0]-q0[0])*span**2/(2*(b-a))
    return value+sum(vector[0] for position, vector in loads[1] if position <= x+1e-9)


def _minimum_normal(initial, loads, length):
    candidates = {0., length}
    for a, b, q0, q1 in loads[0]:
        candidates.update((a, b))
        if q1[0] != q0[0]:
            zero = a-q0[0]*(b-a)/(q1[0]-q0[0])
            if a < zero < b:
                candidates.add(zero)
    candidates.update(position for position, _vector in loads[1])
    minimum = min(initial+_axial_integral(loads, x) for x in candidates)
    jumps = {}
    for position, vector in loads[1]:
        jumps[position] = jumps.get(position, 0.)+vector[0]
    for position, jump in jumps.items():
        # The left limit precedes all coincident point-force jumps.
        minimum = min(minimum, initial+_axial_integral(loads, position)-jump)
    return minimum


def _normal_geometric(element, initial, loads):
    """Initial axial stress only; small-strain axial DOFs remain linear.

    N(x) follows exact axial-load equilibrium. The transverse/twist energy
    is that of the Vlasov kernel, including centroid/shear-centre offsets.
    Initial bending/bimoment prestress is not a nonlinear material model.
    """
    section = element.section
    stress = np.array(((1., 0., section.zsc), (0., 1., -section.ysc),
                       (section.zsc, -section.ysc, section.r0_squared)))
    geometric = np.zeros((14, 14))
    xi, wi = np.polynomial.legendre.leggauss(4)
    for fraction, weight in zip((xi+1)/2, wi*element.length/2, strict=True):
        row = shapes(element.length, fraction)
        gradient = np.stack((row['v1'], row['w1'], row['theta1']))@section.transform
        geometric += weight*(initial+_axial_integral(loads, fraction*element.length))*(gradient.T@stress@gradient)
    return geometric



def _centroid_slopes(rows, section, local):
    sc = section.transform@local
    twist = float(rows['theta1']@sc)
    return (float(rows['v1']@sc)+section.zsc*twist,
            float(rows['w1']@sc)-section.ysc*twist, twist)

def _equilibrated(element, d, force, loads, x, *, initial_normal=None):
    data = recover(element.length, element.section, element.E, element.G, d, x/element.length)
    integral, lever = np.zeros(6), np.zeros(6)
    xi, wi = np.polynomial.legendre.leggauss(3)
    for a, b, q0, q1 in loads[0]:
        stop = min(x, b)
        if stop <= a:
            continue
        for s, weight in zip(a+(xi+1)/2*(stop-a), wi*(stop-a)/2, strict=True):
            value = q0+(q1-q0)*(s-a)/(b-a)
            integral += weight*value
            lever += weight*(x-s)*value
    for s, value in loads[1]:
        if s <= x+1e-9:
            integral += value
            lever += (x-s)*value
    sc_force = np.linalg.solve(element.section.transform.T, force)
    initial_torque = -sc_force[3]
    sc_integral = integral[3]+element.section.zsc*integral[1]-element.section.ysc*integral[2]
    sc_lever = lever[3]+element.section.zsc*lever[1]-element.section.ysc*lever[2]
    theta0 = float(shapes(element.length, 0.)['theta']@(element.section.transform@d))
    torque = initial_torque-sc_integral
    B = sc_force[6]+initial_torque*x-sc_lever-element.G*element.section.j*(data['twist_rad']-theta0)
    correction_my = correction_mz = correction_B = 0.
    material_torque = torque
    if initial_normal is not None:
        # Section moment equilibrium includes P-delta. Generalized torsional
        # force includes the initial-stress contribution; material torque
        # (Saint-Venant + warping) must remove that contribution explicitly.
        for location, weight in zip((xi+1)*x/2, wi*x/2, strict=True):
            rows = shapes(element.length, location/element.length)
            normal = initial_normal+_axial_integral(loads, location)
            v1, w1, t1 = _centroid_slopes(rows, element.section, d)
            correction_my += weight*normal*w1
            correction_mz += weight*normal*v1
            correction_B += weight*normal*(element.section.zsc*v1-element.section.ysc*w1+
                (element.section.r0_squared-element.section.ysc**2-element.section.zsc**2)*t1)
        rows = shapes(element.length, x/element.length)
        normal = initial_normal+_axial_integral(loads, x)
        v1, w1, t1 = _centroid_slopes(rows, element.section, d)
        material_torque += normal*(element.section.zsc*v1-element.section.ysc*w1+
            (element.section.r0_squared-element.section.ysc**2-element.section.zsc**2)*t1)
    if element.section.cw == 0:
        B = correction_B = 0.
        material_torque = data['saint_venant_torque_Nmm']
    v1, w1, _t1 = _centroid_slopes(shapes(element.length, x/element.length), element.section, d)
    return {**data, 'centroid_slope_y': v1, 'centroid_slope_z': w1, 'compression_N': force[0]+integral[0],
            'plot_My_Nmm': -force[4]-force[2]*x-lever[2]-integral[4]+correction_my,
            'plot_Mz_Nmm': force[5]-force[1]*x-lever[1]+integral[5]+correction_mz,
            'Vy_N': force[1]+integral[1], 'Vz_N': force[2]+integral[2],
            'total_torque_Nmm': material_torque, 'generalized_torque_Nmm': torque, 'bimoment_Nmm2': B+correction_B,
            'warping_torque_Nmm': material_torque-data['saint_venant_torque_Nmm']}


def _geometric_normal_matrix(element):
    c, s = cos(element.angle), sin(element.angle)
    rotation = np.eye(4)
    rotation[1:3, 1:3] = ((c, s), (-s, c))
    normal = rotation.T@element.section.normal_gram@rotation
    return (normal[:3, :3] if element.section.cw == 0 else normal).tolist()


def _geometric_shear_center(element):
    c, s = cos(element.angle), sin(element.angle)
    return [float(c*element.section.ysc-s*element.section.zsc),
            float(s*element.section.ysc+c*element.section.zsc)]


class VlasovSystem:
    def __init__(self, target, source, divisions=16, tension_bounds=None):
        from Pynite.Analysis import _partition_D, _prepare_model

        _prepare_model(target)
        self.target, self.source = target, source
        self.mesh_tension_bounds = tension_bounds or {}
        self.tension_bounds = {}
        self.size = 6*len(target.nodes)
        self.original_size = self.size
        _free, fixed, values = _partition_D(target)
        self.known = dict(zip(fixed, np.asarray(values).reshape(-1), strict=True))
        self.elements, self.removed, self.springs = [], [], []
        self.warping, self.end_rows, self.continuities, self.end_phi = {}, {}, {}, {}
        for name, member in source.bars.items():
            if member.section in COLD:
                if member.section != "L Formado" and any(value is None for value in member.warping_restraints):
                    raise ValueError('Declare os vínculos de empenamento A/B da barra '+name+'.')
                self._member(name, member, divisions)
        self._validate_continuities()
        self._assemble()

    def _allocate(self, count=1):
        result = np.arange(self.size, self.size+count)
        self.size += count
        return result

    def _phi(self, name, source_member, node, side, section, rotation, angle):
        boundary = source_member.warping_restraints[side] if side is not None else 'free'
        if section.cw == 0:
            return -1, 1.  # auxiliary slopes are local to each element
        key = (name, node)
        sign = 1.
        if boundary == 'continuous':
            key, sign = self._continuity(name, source_member, node, rotation, angle)
        if key not in self.warping:
            self.warping[key] = int(self._allocate()[0])
        index = self.warping[key]
        if boundary == 'blocked':
            self.known[index] = 0.
        if side is not None:
            self.end_phi[name, side] = (index, sign, section.cw)
        return index, sign

    def _continuity(self, name, source_member, node, rotation, angle):
        from osa.sections.properties import calculate_section_properties

        sheet = open_sheet(source_member.section, source_member.geometry_dict(), mirror=source_member.section_mirrored)
        field = rounded_sectorial_field(sheet)
        coordinates, omegas = [], []
        for index, piece in enumerate(sheet.pieces):
            for fraction in (0., .5, 1.):
                coordinates.append(piece.point(fraction))
                omegas.append(field.omega(index, fraction))
        omega = np.asarray(omegas)
        c, s = cos(angle), sin(angle)
        props = calculate_section_properties(source_member.section, source_member.geometry_dict(), mirror_z=source_member.section_mirrored)
        vertices = np.asarray(coordinates)-np.array((props.centroid_y_mm, props.centroid_z_mm))
        yz = vertices@np.array(((c, -s), (s, c)))
        cloud = yz[:, :1]*rotation[1]+yz[:, 1:]*rotation[2]
        vectors = omega[:, None]*rotation[0]
        order = sorted(range(len(cloud)), key=lambda i: tuple(np.round(cloud[i], 7)))
        cloud, vectors = cloud[order], vectors[order]
        if node not in self.continuities:
            self.continuities[node] = (cloud, vectors, rotation[0], [name])
            return ('continuous', node), 1.
        points, reference, axis, names = self.continuities[node]
        if (cloud.shape != points.shape or not np.allclose(cloud, points, atol=1e-6, rtol=0) or
                abs(abs(axis@rotation[0])-1) > 1e-8):
            raise ValueError('Continuidade de empenamento incompatível no nó '+str(node)+'.')
        sign = float(np.sum(reference*vectors)/np.sum(reference*reference))
        if abs(abs(sign)-1) > 1e-7 or not np.allclose(vectors, sign*reference, atol=1e-5, rtol=1e-7):
            raise ValueError('Funções setoriais incompatíveis no nó '+str(node)+'.')
        names.append(name)
        return ('continuous', node), sign

    def _validate_continuities(self):
        for node, (_points, _vectors, _axis, names) in self.continuities.items():
            if len(names) < 2:
                raise ValueError('Empenamento contínuo no nó '+str(node)+' requer outra extremidade compatível também declarada contínua.')

    def _boundary_rows(self, name, sub, side, rotation):
        key = (name, sub.name, side)
        if key in self.end_rows:
            return self.end_rows[key]
        node = sub.i_node if side == 0 else sub.j_node
        rows = []
        springs = getattr(sub, '_osa_end_springs', {})
        for dof in range(6):
            index = dof+6*side
            base = 6*node.ID+(0 if dof < 3 else 3)
            original = {base+i: value for i, value in enumerate(rotation[dof % 3]) if abs(value) > 1e-14}
            if sub.Releases[index] or index in springs:
                private = int(self._allocate()[0])
                rows.append({private: 1.})
                if index in springs:
                    self.springs.append(({**{i: -value for i, value in original.items()}, private: 1.}, springs[index]))
            else:
                rows.append(original)
        self.end_rows[key] = rows
        return rows

    def _member(self, name, member, divisions):
        from osa.sections.properties import calculate_section_properties

        geometry = member.geometry_dict()
        gross = rounded_section_from_sheet(member.section, geometry, member.section_mirrored,
                                           sectorial_mode=member.section != 'L Formado')
        shape_props = calculate_section_properties(member.section, geometry, mirror_z=member.section_mirrored)
        length = np.linalg.norm(np.array(tuple(getattr(self.source.nodes[member.end_node], key) for key in ('x', 'y', 'z')))-
                                np.array(tuple(getattr(self.source.nodes[member.start_node], key) for key in ('x', 'y', 'z'))))
        for physical_name, start_ratio, _end_ratio in self.target._osa_member_segments.get(name, ((name, 0., 1.),)):
            physical = self.target.members[physical_name]
            angle = radians(getattr(physical, '_osa_principal_angle', 0.))
            c, s = cos(angle), sin(angle)
            rotation = physical.T()[:3, :3]
            section = physical.section
            ei = section.Iy*1e12/shape_props.i_major_mm4
            ea = section.A*1e6/shape_props.area_mm2
            modes = 3 if member.section == 'L Formado' else 4
            normal_rotation = np.eye(modes)
            normal_rotation[1:3, 1:3] = ((c, s), (-s, c))
            supplied = getattr(self.target, '_osa_effective_normal_matrices', {}).get(name)
            if supplied is None:
                scale = np.diag(np.sqrt((ea, *([ei]*(modes-1)))))
                normal = scale@normal_rotation@gross.normal_gram[:modes, :modes]@normal_rotation.T@scale
            else:
                normal = normal_rotation@np.asarray(supplied)@normal_rotation.T
            padded = np.zeros((4, 4))
            padded[:modes, :modes] = normal
            ysc, zsc = gross.ysc, gross.zsc
            if modes == 3:
                supplied_pole = getattr(self.target, '_osa_effective_shear_centers', {}).get(name)
                if supplied_pole is not None:
                    ysc, zsc = np.asarray(supplied_pole)-np.array((shape_props.centroid_y_mm, shape_props.centroid_z_mm))
            mu_y, mu_z = -gross.normal_gram[0, 2]/gross.area, gross.normal_gram[0, 1]/gross.area
            r0_squared = (gross.iy+gross.iz)/gross.area-2*(ysc*mu_y+zsc*mu_z)+ysc**2+zsc**2
            properties = replace(gross, area=float(normal[0, 0]), iy=float(normal[1, 1]), iz=float(normal[2, 2]),
                iyz=float(-normal[1, 2]), j=section.J*1e12, cw=float(padded[3, 3]),
                ysc=c*ysc+s*zsc, zsc=-s*ysc+c*zsc,
                wagner_y=c*gross.wagner_y+s*gross.wagner_z,
                wagner_z=-s*gross.wagner_y+c*gross.wagner_z, initial_r0_squared=r0_squared,
                normal_matrix=tuple(map(tuple, padded)))
            for sub in physical.sub_members.values():
                self.removed.append(sub)
                sub_offset = float((np.array((sub.i_node.X, sub.i_node.Y, sub.i_node.Z))-
                    np.array((physical.i_node.X, physical.i_node.Y, physical.i_node.Z)))@rotation[0])
                knots = np.linspace(0., sub.L(), max(1, ceil(divisions*sub.L()/length))+1).tolist()
                continuous_cases = {item[3] for item in getattr(self.target, '_osa_continuous_moments', ()) if item[0] == name}
                knots += [row[2] for row in sub.PtLoads if not (row[0].startswith('M') and row[3] in continuous_cases)]
                knots += [row[index] for row in sub.DistLoads for index in (3, 4)]
                # Resolve the exponential warping boundary layers without
                # meshing a very long uniform interior at the shortest scale.
                # Loads/discontinuities are additional layer origins.
                if properties.cw > 0:
                    elastic_length = sqrt(physical.material.E/physical.material.G*properties.cw/properties.j)/1000
                    tension = self.mesh_tension_bounds.get(name, 0.)
                    shortest = sqrt(physical.material.E/1000*properties.cw/(
                        physical.material.G/1000*properties.j+tension*properties.r0_squared))/1000
                    anchors = {0., sub.L(), *(row[2] for row in sub.PtLoads
                        if not (row[0].startswith('M') and row[3] in continuous_cases)),
                        *(row[index] for row in sub.DistLoads for index in (3, 4))}
                    distance, spacing = shortest/8, shortest/8
                    while distance < min(sub.L(), 16*elastic_length):
                        for anchor in anchors:
                            for value in (anchor-distance, anchor+distance):
                                if 0 < value < sub.L() and min(abs(value-existing) for existing in knots) >= shortest/16:
                                    knots.append(value)
                        spacing = min(shortest/4, spacing*1.12) if distance < 4*shortest else spacing*1.12
                        distance += spacing
                knots = sorted({round(float(x), 12) for x in knots})
                nodes = []
                for index, x in enumerate(knots):
                    if index in (0, len(knots)-1):
                        side = 0 if index == 0 else 1
                        node = sub.i_node if side == 0 else sub.j_node
                        rows = self._boundary_rows(name, sub, side, rotation)
                        source_side = 0 if node.name == member.start_node else 1 if node.name == member.end_node else None
                        phi = self._phi(name, member, node.name, source_side, properties, rotation, angle)
                    else:
                        private = self._allocate(6)
                        rows = [{int(i): 1.} for i in private]
                        # Internal coordinates use the local frame, so no R.
                        phi = self._phi(name, member, (sub.name, index), None, properties, rotation, angle)
                    nodes.append((rows, phi))
                for index, (a, b) in enumerate(itertools.pairwise(knots)):
                    if properties.cw == 0:
                        phi_a, phi_b = map(int, self._allocate(2))
                        left_phi, right_phi = {phi_a: 1.}, {phi_b: 1.}
                        if sub.i_node.name == member.start_node and abs(a) < 1e-10:
                            self.end_phi[name, 0] = (phi_a, 1., 0.)
                        if sub.j_node.name == member.end_node and abs(b-sub.L()) < 1e-10:
                            self.end_phi[name, 1] = (phi_b, 1., 0.)
                    else:
                        left_phi = {nodes[index][1][0]: nodes[index][1][1]}
                        right_phi = {nodes[index+1][1][0]: nodes[index+1][1][1]}
                    rows = [*nodes[index][0], left_phi, *nodes[index+1][0], right_phi]
                    indices = np.array(sorted({i for row in rows for i in row}))
                    positions = {int(value): i for i, value in enumerate(indices)}
                    transform = np.zeros((14, len(indices)))
                    for row_index, row in enumerate(rows):
                        scale = 1000. if row_index % 7 < 3 else .001 if row_index % 7 == 6 else 1.
                        for column, value in row.items():
                            transform[row_index, positions[column]] = value*scale
                    ke, _kg = element_matrices((b-a)*1000, properties, physical.material.E/1000, physical.material.G/1000)
                    self.elements.append(Element(name, sub, a, b, start_ratio*length+sub_offset+a,
                        properties, physical.material.E/1000, physical.material.G/1000, rotation, angle, indices, transform, ke))

    def _assemble(self):
        first = next(iter(self.target.load_combos))
        base = self.target.Ke(first, check_stability=False, sparse=True).tocoo()
        rows, cols, values = [base.row], [base.col], [base.data]
        def add(indices, matrix):
            rows.append(np.repeat(indices, len(indices)))
            cols.append(np.tile(indices, len(indices)))
            values.append(matrix.reshape(-1))
        for sub in self.removed:
            indices = np.r_[np.arange(6*sub.i_node.ID, 6*sub.i_node.ID+6), np.arange(6*sub.j_node.ID, 6*sub.j_node.ID+6)]
            add(indices, -sub.Ke())
        for element in self.elements:
            add(element.indices, element.transform.T@element.elastic@element.transform*1e-6)
        for row, stiffness in self.springs:
            indices = np.array(tuple(row))
            vector = np.array(tuple(row.values()))
            add(indices, stiffness*np.outer(vector, vector))
        self.matrix = coo_matrix((np.concatenate(values), (np.concatenate(rows), np.concatenate(cols))), shape=(self.size, self.size)).tocsr()
        self.matrix = (self.matrix+self.matrix.T)*.5
        self.matrix.eliminate_zeros()

    def solve(self, reference, *, second_order=False):
        rhs = np.zeros(self.size)
        rhs[:self.original_size] = (self.target.P(reference)-self.target.FER(reference)).reshape(-1)
        for sub in self.removed:
            indices = np.r_[np.arange(6*sub.i_node.ID, 6*sub.i_node.ID+6), np.arange(6*sub.j_node.ID, 6*sub.j_node.ID+6)]
            rhs[indices] += sub.FER(reference).reshape(-1)
        factors = self.target.load_combos[reference].factors
        for name, end, value, case in getattr(self.target, '_osa_bimoment_loads', ()):
            if not factors.get(case, 0.):
                continue
            data = self.end_phi.get((name, 0 if end == 'A' else 1))
            if data is None or data[2] == 0:
                raise ValueError('A ação de bimomento requer um modo setorial representado na barra '+name+'.')
            index, sign, _cw = data
            rhs[index] += sign*value*factors[case]  # kN m² conjugate to theta' [rad/m]
        loads = []
        for element in self.elements:
            local_loads = _loads(element, reference)
            vector = _load_vector(element, local_loads)
            rhs[element.indices] += element.transform.T@vector*1e-6
            loads.append((local_loads, vector))
        known = dict(self.known)
        # Empty original nodal coordinates from released joints are redundant
        # only if they carry no load. No internal rigid-body mode is removed.
        for index in range(self.original_size):
            if self.matrix.getrow(index).nnz == 0 and abs(rhs[index]) < 1e-12:
                known[index] = 0.
        free = np.setdiff1d(np.arange(self.size), tuple(known))
        matrix = self.matrix
        d, residual = self._positive_solve(matrix, rhs, free, known)
        for element, (local_loads, vector) in zip(self.elements, loads, strict=True):
            local = element.transform@d[element.indices]
            initial = float((element.elastic@local-vector)[0])
            minimum = _minimum_normal(initial, local_loads, element.length)
            self.tension_bounds[element.owner] = max(self.tension_bounds.get(element.owner, 0.), -minimum)
        geometric = [np.zeros((14, 14)) for _element in self.elements]
        normals = [None for _element in self.elements]
        iterations = 1
        if second_order:
            for iterations in range(1, 51):
                rows, cols, values = [], [], []
                normals, geometric = [], []
                def add(indices, value, rows=rows, cols=cols, values=values):
                    rows.append(np.repeat(indices, len(indices)))
                    cols.append(np.tile(indices, len(indices)))
                    values.append(value.reshape(-1))
                for element, (local_loads, vector) in zip(self.elements, loads, strict=True):
                    local = element.transform@d[element.indices]
                    initial = float((element.elastic@local-vector)[0])
                    kg = _normal_geometric(element, initial, local_loads)
                    normals.append(initial)
                    geometric.append(kg)
                    add(element.indices, -element.transform.T@kg@element.transform*1e-6)
                removed_ids = {id(sub) for sub in self.removed}
                for physical in self.target.members.values():
                    for sub in physical.sub_members.values():
                        if id(sub) in removed_ids:
                            continue
                        indices = np.r_[np.arange(6*sub.i_node.ID, 6*sub.i_node.ID+6), np.arange(6*sub.j_node.ID, 6*sub.j_node.ID+6)]
                        elastic_force = sub.T()@(sub.Ke()@d[indices]+sub.FER(reference).reshape(-1))
                        tension = .5*(elastic_force[6]-elastic_force[0])
                        # Match the small-strain axial convention used for 7GL.
                        kg = sub.Kg(float(tension))
                        axis = np.zeros(12)
                        axis[:3], axis[6:9] = sub.T()[0, :3], -sub.T()[0, :3]
                        if not (sub.Releases[0] or sub.Releases[6]):
                            kg -= tension/sub.L()*np.outer(axis, axis)
                        add(indices, kg)
                delta = coo_matrix((np.concatenate(values), (np.concatenate(rows), np.concatenate(cols))), shape=self.matrix.shape).tocsr()
                matrix = self.matrix+delta
                updated, residual = self._positive_solve(matrix, rhs, free, known)
                # Dimensionless energy norm does not mix metres and radians.
                difference = updated-d
                error = np.sqrt(abs(difference@(self.matrix@difference))/max(1e-30, abs(updated@(self.matrix@updated))))
                d = updated
                if error < 1e-9:
                    break
            else:
                raise ValueError('P–Delta com empenamento não convergiu em 50 iterações.')
            self.target._osa_tangent_stability[reference] = {'status': 'positive',
                'method': 'Fatoração positiva da rigidez 7GL com tensão inicial axial',
                'free_dofs': len(free), 'iterations': iterations,
                'scope': 'P–Delta/P–delta por força normal; não substitui as verificações de flambagem e resistência sob flexão/bimomento.'}
        self._store(reference, d, residual, loads, geometric, normals, second_order, iterations)

    def _positive_solve(self, matrix, rhs, free, known):
        d = np.zeros(self.size)
        for index, value in known.items():
            d[index] = value
        reduced = matrix[free, :][:, free].tocsc()
        diagonal = reduced.diagonal()
        if np.any(diagonal <= 0) or not np.all(np.isfinite(diagonal)):
            raise ValueError('Modelo com empenamento contém graus de liberdade instáveis.')
        scaling = 1/np.sqrt(diagonal)
        scaled = diags(scaling)@reduced@diags(scaling)
        force = scaling*(rhs[free]-matrix[free, :]@d)
        try:
            if len(free) <= 800:
                factor = cho_factor(scaled.toarray(), lower=True)
                if np.min(np.diag(factor[0])**2, initial=1.) <= 1e-12:
                    raise ValueError('Rigidez tangente numericamente singular.')
                solution = cho_solve(factor, force)
            else:
                factor = splu(scaled.tocsc(), permc_spec='MMD_AT_PLUS_A', diag_pivot_thresh=0., options={'SymmetricMode': True})
                pivots = factor.U.diagonal()
                difference = factor.U-diags(pivots)@factor.L.T
                if (not np.array_equal(factor.perm_r, factor.perm_c) or np.any(pivots <= 1e-12) or
                        np.max(abs(difference.data), initial=0) > 1e-7*np.max(abs(factor.U.data), initial=1)):
                    raise ValueError('Fatoração não comprova energia tangente positiva.')
                solution = factor.solve(force)
            d[free] = scaling*solution
        except (np.linalg.LinAlgError, RuntimeError, ValueError) as exc:
            raise ValueError('A análise com empenamento não encontrou equilíbrio elástico estável.') from exc
        residual = matrix@d-rhs
        if not np.all(np.isfinite(d)) or np.linalg.norm(residual[free]) > 1e-6*max(1e-9, np.linalg.norm(rhs[free])):
            raise ValueError('Equilíbrio da análise com empenamento não convergiu.')
        return d, residual

    def _store(self, reference, d, residual, loads, geometric, normals, second_order, iterations):
        from osa.sections.properties import calculate_section_properties

        self.target._D[reference] = d[:self.original_size, None]
        for node in self.target.nodes.values():
            for dof, (field, reaction) in enumerate(zip(FIELDS, REACTIONS, strict=True)):
                index = 6*node.ID+dof
                getattr(node, field)[reference] = float(d[index])
                value = residual[index] if index in self.known else 0.
                spring = getattr(node, 'spring_'+field)
                if spring[0] is not None and spring[2]:
                    value = -float(spring[0])*d[index]
                getattr(node, reaction)[reference] = float(value)
        result = {}
        for name, member in self.source.bars.items():
            elements = [(element, load) for element, load in zip(self.elements, loads, strict=True) if element.owner == name]
            if not elements:
                continue
            length = max(element.offset_m+element.length/1000 for element, _load in elements)
            positions = sorted({*np.linspace(0., length, 21), *(element.offset_m for element, _load in elements), length})
            samples = []
            for position in positions:
                selected = next(((element, load) for element, load in elements if element.offset_m-1e-10 <= position < element.offset_m+element.length/1000-1e-10), elements[-1])
                element, (local_loads, vector) = selected
                coordinate = max(0., min(element.length, (position-element.offset_m)*1000))
                local = element.transform@d[element.indices]
                index = next(i for i, item in enumerate(self.elements) if item is element)
                state = _equilibrated(element, local, (element.elastic-geometric[index])@local-vector,
                                      local_loads, coordinate, initial_normal=normals[index])
                c, s = cos(element.angle), sin(element.angle)
                global_displacement = element.rotation.T@np.array((state['uC_mm'], state['vC_mm'], state['wC_mm']))/1000
                samples.append({'x': float(position), 'axial': state['compression_N']/1000,
                    'shear_y': (c*state['Vy_N']-s*state['Vz_N'])/1000,
                    'shear_z': (s*state['Vy_N']+c*state['Vz_N'])/1000,
                    'moment_y': (c*state['plot_My_Nmm']+s*state['plot_Mz_Nmm'])/1e6,
                    'moment_z': (-s*state['plot_My_Nmm']+c*state['plot_Mz_Nmm'])/1e6,
                    'centroid_slope_y': c*state['centroid_slope_y']-s*state['centroid_slope_z'],
                    'centroid_slope_z': s*state['centroid_slope_y']+c*state['centroid_slope_z'],
                    'torque': -state['total_torque_Nmm']/1e6,
                    'torque_sc': state['total_torque_Nmm']/1e6,
                    'generalized_torque_sc': state['generalized_torque_Nmm']/1e6,
                    'bimoment': state['bimoment_Nmm2']/1e9,
                    'saint_venant_torque': state['saint_venant_torque_Nmm']/1e6,
                    'warping_torque': state['warping_torque_Nmm']/1e6, 'twist': state['twist_rad'],
                    **dict(zip(('deflection_x', 'deflection_y', 'deflection_z'), map(float, global_displacement), strict=True))})
            samples = [{key: float(value) for key, value in row.items()} for row in samples]
            shape_props = calculate_section_properties(member.section, member.geometry_dict(), mirror_z=member.section_mirrored)
            result[name] = {'length': length, 'samples': samples,
                'start': {key: value for key, value in samples[0].items() if key != 'x'},
                'end': {key: value for key, value in samples[-1].items() if key != 'x'},
                'warping_analysis': {'status': 'solved', 'algorithm': VLASOV_ALGORITHM, 'method': ('Bernoulli–Saint-Venant, Cw=0' if member.section == 'L Formado' else 'Vlasov 7GL')+
                        (', P–Delta por força normal' if second_order else ', análise linear'),
                    'iterations': iterations, 'second_order': bool(second_order),
                    'normal_mode_count': 3 if member.section == 'L Formado' else 4,
                    'geometry_basis': 'rounded-angle-saint-venant-v1' if member.section == 'L Formado' else 'rounded-mean-line-v1',
                    'shear_center_offset_geometric_mm': _geometric_shear_center(elements[0][0]),
                    'normal_origin_section_mm': (shape_props.centroid_y_mm, shape_props.centroid_z_mm),
                    'normal_gram_geometric': _geometric_normal_matrix(elements[0][0]),
                    'elements': len(elements), 'end_restraints': member.warping_restraints,
                    'end_warping_dofs': {end: {'rate_rad_per_m': float(sign*d[index]),
                        'support_reaction_kn_m2': float(sign*residual[index]) if index in self.known else 0.,
                        'sectorial_degree': bool(cw > 0)}
                        for (owner, side), (index, sign, cw) in self.end_phi.items() if owner == name
                        for end in ('A' if side == 0 else 'B',)},
                    'torque_reference': ('centro de torção efetivo; torque=−TSC, TSC=Tsv e B=Tw=0 no modelo Cw=0.' if member.section == 'L Formado' else
                        'polo setorial bruto; torque=−(Tsv+Tw). B usa a matriz normal acoplada; B=−ECwθ″ somente na seção bruta principal desacoplada. generalized_torque_sc inclui a parcela geométrica sob força normal.'),
                    'scope': 'Forças transversais no centroide; excentricidade ao centro de torção incluída. A força axial nodal é resultante distribuída, sem bimomento externo implícito. Transferência axial localizada exige o bimomento correspondente à função setorial do ponto.'}}
        self.target._osa_vlasov_results[reference] = result


def solve_vlasov(target, source, divisions=16, *, second_order=False):
    system = VlasovSystem(target, source, divisions)
    target.solution = 'P-Delta' if second_order else 'Linear'
    target._osa_vlasov_results = {}
    target._osa_tangent_stability = {}
    if second_order:
        # Tension shortens the torsional boundary layer. Obtain its envelope
        # from the initial small-strain equilibrium before the final mesh.
        for reference in target.load_combos:
            system.solve(reference)
        if any(value > 0 for value in system.tension_bounds.values()):
            system = VlasovSystem(target, source, divisions, system.tension_bounds)
            target._osa_vlasov_results = {}
    for reference in target.load_combos:
        system.solve(reference, second_order=second_order)
    target._osa_vlasov_system = system
