"""One cached GPU actor per reference, with O(1) placement and visibility edits."""

import numpy as np
import pyvista as pv
from vtkmodules.vtkCommonMath import vtkMatrix4x4


class DrawingReferenceRenderer:
    def __init__(self):
        self._meshes = {}
        self.actors = {}
        self.selected_id = None
        self.origin_actor = None
        self._local_snaps = {}
        self._world_snap_key = None
        self._world_snaps = (np.empty((0, 3)), np.empty((0, 3)))
        self._world_snap_segments_key = None
        self._world_snap_segments = (np.empty((0, 3)), np.empty((0, 3)))

    @staticmethod
    def build(geometry):
        lines = np.frombuffer(geometry.lines, dtype="<f8").reshape(-1, 2)
        faces = np.frombuffer(geometry.triangles, dtype="<f8").reshape(-1, 2)
        points = np.zeros((len(lines) + len(faces), 3))
        points[:, :2] = np.concatenate((lines, faces))
        line_cells = np.empty((len(lines) // 2, 3), dtype=np.int64)
        line_cells[:, 0] = 2
        line_cells[:, 1:] = np.arange(len(lines)).reshape(-1, 2)
        face_cells = np.empty((len(faces) // 3, 4), dtype=np.int64)
        face_cells[:, 0] = 3
        face_cells[:, 1:] = np.arange(len(lines), len(points)).reshape(-1, 3)
        return pv.PolyData(points, lines=line_cells.ravel(), faces=face_cells.ravel())

    @staticmethod
    def matrix(reference):
        basis = {
            "XY": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            "XZ": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "YZ": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
        }[reference.plane]
        matrix = vtkMatrix4x4()
        for col, vector in enumerate(basis):
            for row, value in enumerate(vector):
                matrix.SetElement(row, col, value)
        for row, value in enumerate(reference.origin):
            matrix.SetElement(row, 3, value)
        return matrix

    def sync(self, plotter, references, *, cleared=False):
        if cleared:
            self.actors.clear()
            self.origin_actor = None
        for reference_id in set(self._meshes) - references.keys():
            actor = self.actors.pop(reference_id, None)
            if actor is not None:
                plotter.remove_actor(actor, reset_camera=False, render=False)
            del self._meshes[reference_id]
            self._local_snaps.pop(reference_id, None)
        for reference_id, reference in references.items():
            cached = self._meshes.get(reference_id)
            if cached is None or cached[0] is not reference.geometry:
                self._local_snaps.pop(reference_id, None)
                mesh = self.build(reference.geometry)
                self._meshes[reference_id] = (reference.geometry, mesh)
                actor = self.actors.pop(reference_id, None)
                if actor is not None:
                    plotter.remove_actor(actor, reset_camera=False, render=False)
            else:
                mesh = cached[1]
            actor = self.actors.get(reference_id)
            if actor is None:
                actor = plotter.add_mesh(
                    mesh, color="#8c959f", line_width=1, lighting=False,
                    pickable=False, reset_camera=False, render=False,
                    name=f"drawing-reference-{reference_id}",
                )
                self.actors[reference_id] = actor
            actor.SetUserMatrix(self.matrix(reference))
            actor.SetVisibility(reference.visible)
        if self._world_snap_key is not None and self._world_snap_key != self._snap_key(references):
            self._world_snap_key = None
            self._world_snaps = (np.empty((0, 3)), np.empty((0, 3)))
        if self._world_snap_segments_key is not None and self._world_snap_segments_key != self._snap_key(references):
            self._world_snap_segments_key = None
            self._world_snap_segments = (np.empty((0, 3)), np.empty((0, 3)))
        self._update_selection(plotter, references)

    def set_selected(self, plotter, references, reference_id):
        self.selected_id = reference_id if reference_id in references else None
        self._update_selection(plotter, references)

    def _update_selection(self, plotter, references):
        if self.selected_id not in references:
            self.selected_id = None
        for reference_id, actor in self.actors.items():
            selected = reference_id == self.selected_id
            actor.GetProperty().SetColor(*pv.Color("#0969da" if selected else "#8c959f").float_rgb)
            actor.GetProperty().SetLineWidth(1.75 if selected else 1.0)
        reference = references.get(self.selected_id)
        if reference is None or not reference.visible:
            if self.origin_actor is not None:
                self.origin_actor.SetVisibility(False)
            return
        if self.origin_actor is None:
            self.origin_actor = plotter.add_mesh(
                pv.Sphere(radius=0.05, theta_resolution=20, phi_resolution=12),
                color="#0969da", pickable=False, reset_camera=False, render=False,
                name="drawing-reference-origin",
            )
        self.origin_actor.SetPosition(reference.origin)
        self.origin_actor.SetVisibility(True)

    @staticmethod
    def _world_points(reference, xy):
        points = np.zeros((len(xy), 3), dtype=float)
        first, second = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}[reference.plane]
        points[:, first] = xy[:, 0]
        points[:, second] = xy[:, 1]
        points += reference.origin
        return points

    @staticmethod
    def _snap_key(references):
        return tuple(
            (reference.id, reference.geometry, reference.origin, reference.plane)
            for reference in references.values() if reference.visible
        )

    def snap_points(self, references):
        """Cache true CAD features separately from dash, hatch and tessellation vertices."""
        key = self._snap_key(references)
        if key == self._world_snap_key:
            return self._world_snaps
        endpoint_groups, center_groups = [], []
        for reference in references.values():
            if not reference.visible:
                continue
            geometry = reference.geometry
            cached = self._local_snaps.get(reference.id)
            if cached is None or cached[0] is not geometry:
                segments = np.frombuffer(geometry.lines, dtype="<f8").reshape(-1, 2, 2)
                # Older OSA files contain only rendered primitives. Preserve
                # their usability with segment features until reimported.
                endpoints = (
                    np.unique(segments.reshape(-1, 2), axis=0) if geometry.snap_endpoints is None
                    else np.frombuffer(geometry.snap_endpoints, dtype="<f8").reshape(-1, 2)
                )
                centers = (
                    np.unique(segments.mean(axis=1), axis=0) if geometry.snap_centers is None
                    else np.frombuffer(geometry.snap_centers, dtype="<f8").reshape(-1, 2)
                )
                cached = self._local_snaps[reference.id] = (geometry, endpoints, centers)
            endpoint_groups.append(self._world_points(reference, cached[1]))
            center_groups.append(self._world_points(reference, cached[2]))
        self._world_snap_key = key
        self._world_snaps = (
            np.concatenate(endpoint_groups) if endpoint_groups else np.empty((0, 3)),
            np.concatenate(center_groups) if center_groups else np.empty((0, 3)),
        )
        return self._world_snaps

    def snap_segments(self, references):
        """Return visible reference line segments in world coordinates, cached by placement."""
        key = self._snap_key(references)
        if key == self._world_snap_segments_key:
            return self._world_snap_segments
        starts, ends = [], []
        for reference in references.values():
            if not reference.visible or not reference.geometry.lines:
                continue
            local = np.frombuffer(reference.geometry.lines, dtype="<f8").reshape(-1, 2, 2)
            world = self._world_points(reference, local.reshape(-1, 2)).reshape(-1, 2, 3)
            starts.append(world[:, 0])
            ends.append(world[:, 1])
        self._world_snap_segments_key = key
        self._world_snap_segments = (
            np.concatenate(starts) if starts else np.empty((0, 3)),
            np.concatenate(ends) if ends else np.empty((0, 3)),
        )
        return self._world_snap_segments
