"""Explicit open-sheet geometry, in mm, for cold-formed section analysis.

External dimensions retain the existing family conventions. Straight plates
and circular mean-line bends are constructed from their common tangencies;
no pairing of independently sampled outline faces is involved.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from math import atan2, ceil, cos, hypot, isfinite, pi, sin, sqrt, tan

import numpy as np


@dataclass(frozen=True)
class WallPiece:
    start: tuple[float, float]
    end: tuple[float, float]
    role: str
    plate: int
    center: tuple[float, float] | None = None
    turn: float = 0.

    @property
    def length(self):
        if self.center is None:
            return hypot(self.end[0]-self.start[0], self.end[1]-self.start[1])
        return abs(self.turn)*hypot(self.start[0]-self.center[0], self.start[1]-self.center[1])

    def point(self, fraction):
        a, b = np.asarray(self.start), np.asarray(self.end)
        if self.center is None:
            return a + fraction*(b-a)
        center = np.asarray(self.center)
        radius = np.linalg.norm(a-center)
        angle = atan2(a[1]-center[1], a[0]-center[0])+fraction*self.turn
        return center+radius*np.array((cos(angle), sin(angle)))

    def tangent(self, fraction):
        if self.center is None:
            vector = np.asarray(self.end)-self.start
            return vector/np.linalg.norm(vector)
        radial = self.point(fraction)-self.center
        side = 1 if self.turn > 0 else -1
        return side*np.array((-radial[1], radial[0]))/np.linalg.norm(radial)


@dataclass(frozen=True)
class OpenSheet:
    vertices: tuple[tuple[float, float], ...]
    pieces: tuple[WallPiece, ...]
    thickness: float
    radius: float
    roles: tuple[str, ...]

    @property
    def distortional_dimension(self):
        # Unbranched open plate assemblage: longitudinal main-node degrees
        # minus the four global GBT modes (extension, two flexures, torsion).
        # Straight plate subdivision does not create new main nodes.
        return max(0, len(self.vertices)-4)

    def mesh(self, divisions=8, bend_divisions=4):
        """Keep every flat/bend junction and both free edges in the mesh."""
        width = max(p.length for p in self.pieces if p.center is None)
        points, plates, junctions = [], [], []
        for piece in self.pieces:
            count = (max(2, ceil(abs(piece.turn)/(pi/2)*bend_divisions)) if piece.center is not None
                     else max(1, ceil(divisions*piece.length/width)))
            if piece.center is not None and count % 2:
                count += 1
            if not points:
                points.append(piece.point(0.))
            begin = len(points)-1
            for index in range(1, count+1):
                points.append(piece.point(index/count))
                plates.append(piece.plate)
            if piece.center is not None:
                junctions.append(begin+count//2)
        return np.asarray(points), tuple(plates), tuple(junctions)

    def quadrature(self, order=8, *, sharp=False):
        """Return positions and area weights; arcs use exact arc length."""
        xi, wi = np.polynomial.legendre.leggauss(order)
        points, weights = [], []
        if sharp:
            pieces = [WallPiece(a, b, role, i) for i, (a, b, role) in enumerate(
                zip(self.vertices, self.vertices[1:], self.roles, strict=False))]
        else:
            pieces = self.pieces
        for piece in pieces:
            for fraction, weight in zip((xi+1)/2, wi/2, strict=True):
                points.append(piece.point(fraction))
                weights.append(weight*piece.length*self.thickness)
        return np.asarray(points), np.asarray(weights)


def open_sheet(family, geometry, *, mirror=False):
    d, bf, t = (float(geometry[key]) for key in ("d", "bf", "t"))
    c = float(geometry.get("c", 0.))
    r = float(geometry.get("r", t))
    if not all(isfinite(v) and v > 0 for v in (d, bf, t, r)):
        raise ValueError("Dimensões e raio da linha média devem ser finitos e positivos.")
    if family not in {"Z45 Formado", "Z90 Formado"} and not np.isclose(r, t, rtol=1e-10, atol=0):
        raise ValueError("A convenção legada desta família exige raio interno r=t.")
    top, bottom = -(d-t)/2, (d-t)/2
    left, right = -(bf-t)/2, (bf-t)/2
    if family == "U Formado":
        vertices = [(bf/2, top), (left, top), (left, bottom), (bf/2, bottom)]
        roles = ("flange", "web", "flange")
    elif family == "C Formado":
        vertices = [(right, top+c+t/2), (right, top), (left, top),
                    (left, bottom), (right, bottom), (right, bottom-c-t/2)]
        roles = ("lip", "flange", "web", "flange", "lip")
    elif family == "Z Formado":
        vertices = [(-bf-t/2, top), (0., top), (0., bottom), (bf+t/2, bottom)]
        roles = ("flange", "web", "flange")
    elif family in {"Z45 Formado", "Z90 Formado"}:
        alpha = pi/4 if family == "Z45 Formado" else pi/2
        bm = bf-(t/sqrt(2) if family == "Z45 Formado" else t)
        cm = c-((sqrt(2)-1)*t/2 if family == "Z45 Formado" else t/2)
        dx, dz = cm*cos(alpha), cm*sin(alpha)
        vertices = [(-bm-dx, top+dz), (-bm, top), (0., top),
                    (0., bottom), (bm, bottom), (bm+dx, bottom-dz)]
        roles = ("lip", "flange", "web", "flange", "lip")
    elif family == "L Formado":
        vertices = [(left, -d/2), (left, bottom), (bf/2, bottom)]
        roles = ("outstand", "outstand")
    elif family == "Cartola Formado":
        vertices = [(-bf/2-c, bottom), (left, bottom), (left, top),
                    (right, top), (right, bottom), (bf/2+c, bottom)]
        roles = ("outstand", "web", "flange", "web", "outstand")
    else:
        raise ValueError("Família sem linha média de parede aberta.")
    if family in {"C Formado", "Z45 Formado", "Z90 Formado", "Cartola Formado"} and (not isfinite(c) or c <= 0):
        raise ValueError("Dimensão do enrijecedor/aba deve ser positiva.")
    vertices = np.asarray(vertices, dtype=float)
    if mirror:
        vertices[:, 0] *= -1
    vectors = np.diff(vertices, axis=0)
    lengths = np.linalg.norm(vectors, axis=1)
    if np.any(lengths <= 0):
        raise ValueError("Trecho da linha média com comprimento nulo.")
    directions = vectors/lengths[:, None]
    turns = [atan2(np.linalg.det(np.stack((a, b))), float(a@b)) for a, b in itertools.pairwise(directions)]
    radius = r+t/2
    cuts = np.array([0., *(radius*tan(abs(turn)/2) for turn in turns), 0.])
    if np.any(lengths < cuts[:-1]+cuts[1:]-1e-9):
        raise ValueError("As dimensões não comportam as dobras da linha média.")
    pieces = []
    for i, (a, b, direction, role) in enumerate(zip(vertices, vertices[1:], directions, roles, strict=False)):
        start, end = a+direction*cuts[i], b-direction*cuts[i+1]
        if np.linalg.norm(end-start) > 1e-9:
            pieces.append(WallPiece(tuple(start), tuple(end), role, i))
        if i < len(turns):
            side = 1 if turns[i] > 0 else -1
            center = end+side*radius*np.array((-direction[1], direction[0]))
            following = b+directions[i+1]*cuts[i+1]
            pieces.append(WallPiece(tuple(end), tuple(following), "bend", i,
                                    tuple(center), turns[i]))
    return OpenSheet(tuple(map(tuple, vertices)), tuple(pieces), t, r, roles)


def sectorial_properties(sheet):
    """Principal sectorial coordinates with sharp folds (NBR 6355 Annex A).

    Remove the affine component of the sectorial area by area orthogonality;
    its two linear coefficients locate the shear centre. All units are mm.
    """
    points, weights = sheet.quadrature(sharp=True)
    vertices = np.asarray(sheet.vertices)
    omega_nodes = np.r_[0., np.cumsum(vertices[:-1, 0]*vertices[1:, 1]-vertices[:-1, 1]*vertices[1:, 0])]
    xi, _ = np.polynomial.legendre.leggauss(8)
    omega = np.concatenate([a+(xi+1)/2*(b-a) for a, b in itertools.pairwise(omega_nodes)])
    basis = np.column_stack((np.ones(len(points)), points))
    matrix = basis.T@(weights[:, None]*basis)
    coeff = np.linalg.solve(matrix, basis.T@(weights*omega))
    principal = omega-basis@coeff
    cy, cz = np.sum(weights[:, None]*points, axis=0)/sum(weights)
    return {"Cw_mm6": float(weights@(principal**2)),
            "shear_center_y_mm": float(coeff[2]), "shear_center_z_mm": float(-coeff[1]),
            "sharp_centroid_y_mm": float(cy), "sharp_centroid_z_mm": float(cz),
            "omega_mm2": omega_nodes-np.column_stack((np.ones(len(vertices)), vertices))@coeff}


@dataclass(frozen=True)
class SectorialField:
    """Continuous principal sectorial field on the actual mean-line pieces.

    Unlike ``sectorial_properties`` (the sharp-fold approximation), circular
    bends contribute their exact sectorial area. Values use the same area
    measure as the normal mean-line properties; no rescaling of Cw is used.
    """
    sheet: OpenSheet
    origins_mm2: tuple[float, ...]
    affine: tuple[float, float, float]
    cw_mm6: float
    centroid_mm: tuple[float, float]
    reference_origin_mm: tuple[float, float] | None = None

    @property
    def origin_mm(self):
        return self.centroid_mm if self.reference_origin_mm is None else self.reference_origin_mm

    @property
    def shear_center_mm(self):
        return self.affine[2], -self.affine[1]

    def omega(self, piece_index, fraction):
        if not isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError('Posição setorial fora do trecho de parede.')
        piece = self.sheet.pieces[piece_index]
        point = piece.point(fraction)
        return float(self.origins_mm2[piece_index]+_sectorial_increment(piece, fraction)-
                     np.array((1., *point))@self.affine)

    def derivative(self, piece_index, fraction):
        piece = self.sheet.pieces[piece_index]
        point, tangent = piece.point(fraction), piece.tangent(fraction)
        return float(point[0]*tangent[1]-point[1]*tangent[0]-np.asarray(self.affine[1:])@tangent)

    def basis(self, piece_index, fraction):
        point = self.sheet.pieces[piece_index].point(fraction)-self.origin_mm
        return np.array((1., point[1], -point[0], self.omega(piece_index, fraction)))

    def quadrature(self, intervals=None, order=8):
        """Four normal basis functions and retained mean-line area weights.

        Flat intervals are fractions of each actual flat piece; bends remain
        effective, matching the existing effective-width geometry convention.
        """
        xi, wi = np.polynomial.legendre.leggauss(order)
        basis, weights = [], []
        for index, piece in enumerate(self.sheet.pieces):
            portions = (((0., 1.),) if piece.center is not None or intervals is None
                        else intervals[piece.plate])
            for a, b in portions:
                for fraction, weight in zip(a+(xi+1)/2*(b-a), wi*(b-a)/2, strict=True):
                    basis.append(self.basis(index, fraction))
                    weights.append(weight*piece.length*self.sheet.thickness)
        return np.asarray(basis), np.asarray(weights)


def _sectorial_increment(piece, fraction):
    start, point = np.asarray(piece.start), piece.point(fraction)
    if piece.center is None:
        return float(start[0]*point[1]-start[1]*point[0])
    center = np.asarray(piece.center)
    delta = point-start
    radius_squared = float((start-center)@(start-center))
    return float(center[0]*delta[1]-center[1]*delta[0]+radius_squared*piece.turn*fraction)


def rounded_sectorial_field(sheet, *, normal_origin=None):
    """Integrate omega=integral(y dz-z dy), then remove its affine part.

    The three orthogonality conditions locate the principal pole and datum.
    This is a mean-line Vlasov field; finite-thickness warping and local bend
    stress concentrations remain outside the thin-wall model.
    """
    if normal_origin is not None:
        normal_origin = tuple(float(value) for value in normal_origin)
        if len(normal_origin) != 2 or not all(isfinite(value) for value in normal_origin):
            raise ValueError('Origem dos esforços normais inválida.')
    origins, raw, points, weights = [], [], [], []
    previous = 0.
    xi, wi = np.polynomial.legendre.leggauss(8)
    for piece in sheet.pieces:
        origins.append(previous)
        for fraction, weight in zip((xi+1)/2, wi/2, strict=True):
            points.append(piece.point(fraction))
            raw.append(previous+_sectorial_increment(piece, fraction))
            weights.append(weight*piece.length*sheet.thickness)
        previous += _sectorial_increment(piece, 1.)
    points, weights, raw = np.asarray(points), np.asarray(weights), np.asarray(raw)
    centroid = np.sum(weights[:, None]*points, axis=0)/sum(weights)
    # Centre/scale the projection to avoid dependence on a distant datum.
    radius = max(np.linalg.norm(points-centroid, axis=1))
    affine_basis = np.column_stack((np.ones(len(points)), (points-centroid)/radius))
    coefficients = np.linalg.solve(affine_basis.T@(weights[:, None]*affine_basis), affine_basis.T@(weights*raw))
    slopes = coefficients[1:]/radius
    affine = np.r_[coefficients[0]-slopes@centroid, slopes]
    principal = raw-affine_basis@coefficients
    return SectorialField(sheet, tuple(origins), tuple(affine), float(weights@(principal**2)), tuple(centroid), normal_origin)



def effective_shear_center(field, intervals=None):
    """Principal pole of the retained section, without changing the datum.

    Reprojecting the gross omega on [1,z,-y] only changes its affine part.
    This is also the shear-centre construction for the three-normal-field
    Saint-Venant approximation; it does not add a sectorial kinematic mode.
    """
    basis, weights = field.quadrature(intervals)
    normal = basis[:, :3]
    gram = normal.T@(weights[:, None]*normal)
    projection = np.linalg.solve(gram, normal.T@(weights*basis[:, 3]))
    return tuple(np.asarray(field.shear_center_mm)+projection[1:3])
