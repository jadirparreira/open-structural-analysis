"""Passive camera-orientation cube rendered over the main scene."""

from __future__ import annotations

from itertools import combinations, product

import numpy as np
import vtk
from PySide6.QtCore import QTimer


class NavigationWidget:
    @staticmethod
    def create(plotter):
        return CameraCubeWidget(plotter)


class CameraCubeWidget:
    """A generic cube that follows the orientation of the main camera."""

    # The navigation controls use fixed Qt dimensions. Keep the cube's visual
    # footprint in the same logical-pixel system instead of scaling it with
    # the full viewport: a normalized viewport gets much smaller and drifts
    # into the controls when the frameless window is restored.
    _VIEWPORT_WIDTH = 176.0
    _VIEWPORT_HEIGHT = 110.0
    _VIEWPORT_LEFT = 34.0
    _VIEWPORT_BOTTOM = 46.0
    _FALLBACK_VIEWPORT = (0.0, 0.045, 0.128, 0.183)
    _CUBE_HALF_SIZE = 1.0
    _EDGE_CHAMFER = 0.22
    _CORNER_CHAMFER = 0.80

    def __init__(self, plotter) -> None:
        self.plotter = plotter
        self._interactor = plotter.iren.interactor
        self._render_window = plotter.render_window
        self._parent_renderer = plotter.renderer

        self._renderer = vtk.vtkRenderer()
        self._renderer.SetLayer(1)
        self._renderer.SetInteractive(False)
        # Layer 1 is an opaque viewport. Besides placing the cube above the
        # scene, clearing its depth buffer prevents model geometry from being
        # composited through the cube itself.
        self._renderer.SetBackground(1.0, 1.0, 1.0)
        self._renderer.SetBackgroundAlpha(1.0)
        self._renderer.SetErase(True)
        self._renderer.SetPreserveDepthBuffer(False)

        if self._render_window.GetNumberOfLayers() < 2:
            self._render_window.SetNumberOfLayers(2)
        self._render_window.AddRenderer(self._renderer)
        self._set_viewport()

        overlay_camera = vtk.vtkCamera()
        overlay_camera.SetPosition(0.12, 0.0, 8.0)
        overlay_camera.SetFocalPoint(0.12, 0.0, 0.0)
        overlay_camera.SetViewUp(0.0, 1.0, 0.0)
        overlay_camera.ParallelProjectionOn()
        overlay_camera.SetParallelScale(1.6)
        self._renderer.SetActiveCamera(overlay_camera)

        self._oriented_props: list[vtk.vtkProp3D] = []
        self._face_actor: vtk.vtkActor | None = None
        self._hover_actor: vtk.vtkActor | None = None
        self._hover_poly_data = vtk.vtkPolyData()
        self._hover_cell_id: int | None = None
        self._face_picker = vtk.vtkCellPicker()
        self._face_picker.SetTolerance(0.01)
        self._qt_pointer_position: tuple[float, float] | None = None
        self._camera_animation = QTimer()
        self._camera_animation.setInterval(16)
        self._camera_animation.timeout.connect(self._animate_camera)
        self._animation_start: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._animation_end: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._animation_elapsed = 0.0
        self._animation_duration = 0.24
        self._build_cube()
        self._install_interaction_handlers()
        self.sync_from_camera()

    def resize(self) -> None:
        self._set_viewport()
        self._renderer.ResetCameraClippingRange()

    @classmethod
    def _viewport_for_render_size(
        cls, render_size: tuple[int, int], device_pixel_ratio: float,
    ) -> tuple[float, float, float, float]:
        """Return a lower-left viewport with a fixed logical-pixel footprint."""
        render_width, render_height = render_size
        if render_width <= 0 or render_height <= 0:
            return 0.0, 0.0, 1.0, 1.0
        scale = max(float(device_pixel_ratio), 1.0)
        width = min(cls._VIEWPORT_WIDTH * scale, float(render_width))
        height = min(cls._VIEWPORT_HEIGHT * scale, float(render_height))
        left = min(cls._VIEWPORT_LEFT * scale, float(render_width) - width)
        bottom = min(cls._VIEWPORT_BOTTOM * scale, float(render_height) - height)
        return (
            left / float(render_width),
            bottom / float(render_height),
            (left + width) / float(render_width),
            (bottom + height) / float(render_height),
        )

    def _set_viewport(self) -> None:
        if not self.plotter.isVisible():
            self._renderer.SetViewport(*self._FALLBACK_VIEWPORT)
            return
        self._renderer.SetViewport(*self._viewport_for_render_size(
            tuple(self._render_window.GetSize()), self.plotter.devicePixelRatioF(),
        ))

    def _build_cube(self) -> None:
        self._bevel_hull = self._create_beveled_cube()

        face_mapper = vtk.vtkPolyDataMapper()
        face_mapper.SetInputConnection(self._bevel_hull.GetOutputPort())
        face_mapper.ScalarVisibilityOff()
        face_actor = vtk.vtkActor()
        face_actor.SetMapper(face_mapper)
        face_actor.GetProperty().SetColor(0.9490, 0.9608, 0.9725)  # #f2f5f8
        face_actor.GetProperty().LightingOff()
        face_actor.GetProperty().SetAmbient(1.0)
        face_actor.GetProperty().SetDiffuse(0.0)
        face_actor.GetProperty().SetSpecular(0.0)
        self._renderer.AddActor(face_actor)
        self._oriented_props.append(face_actor)
        self._face_actor = face_actor

        hover_mapper = vtk.vtkPolyDataMapper()
        hover_mapper.SetInputData(self._hover_poly_data)
        hover_mapper.ScalarVisibilityOff()
        hover_actor = vtk.vtkActor()
        hover_actor.SetMapper(hover_mapper)
        hover_actor.GetProperty().SetColor(0.90, 0.92, 0.94)
        hover_actor.GetProperty().LightingOff()
        hover_actor.GetProperty().SetAmbient(1.0)
        hover_actor.GetProperty().SetDiffuse(0.0)
        hover_actor.GetProperty().SetSpecular(0.0)
        hover_actor.PickableOff()
        hover_actor.VisibilityOff()
        self._renderer.AddActor(hover_actor)
        self._oriented_props.append(hover_actor)
        self._hover_actor = hover_actor

        self._edge_filter = vtk.vtkFeatureEdges()
        self._edge_filter.SetInputConnection(self._bevel_hull.GetOutputPort())
        self._edge_filter.BoundaryEdgesOn()
        self._edge_filter.FeatureEdgesOn()
        self._edge_filter.ManifoldEdgesOff()
        self._edge_filter.NonManifoldEdgesOn()
        self._edge_filter.SetFeatureAngle(30.0)
        edge_mapper = vtk.vtkPolyDataMapper()
        edge_mapper.SetInputConnection(self._edge_filter.GetOutputPort())
        edge_mapper.ScalarVisibilityOff()
        edge_actor = vtk.vtkActor()
        edge_actor.SetMapper(edge_mapper)
        edge_actor.GetProperty().SetRepresentationToWireframe()
        edge_actor.GetProperty().SetColor(0.7843, 0.8157, 0.8471)  # #c8d0d8
        edge_actor.GetProperty().SetLineWidth(1.0)
        edge_actor.GetProperty().LightingOff()
        edge_actor.PickableOff()
        self._renderer.AddActor(edge_actor)
        self._oriented_props.append(edge_actor)

    def _install_interaction_handlers(self) -> None:
        self._interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 1.0)
        self._interactor.AddObserver("LeftButtonPressEvent", self._on_left_press, 1.0)

    def set_qt_pointer_position(self, x: float, y: float) -> None:
        """Store the source Qt coordinates before VTK applies its DPI mapping."""
        self._qt_pointer_position = float(x), float(y)

    def is_pointer_over(self, x: int, y: int) -> bool:
        """Return whether the pointer is over a clickable cube face."""
        return self._pick_face_normal(*self._picker_position(x, y)) is not None

    def _on_mouse_move(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        self._update_hover(*self._picker_position(x, y))

    def _picker_position(self, vtk_x: int, vtk_y: int) -> tuple[float, float]:
        """Use the Qt position normalized to the current VTK render buffer."""
        if self._qt_pointer_position is None:
            return float(vtk_x), float(vtk_y)
        widget_width, widget_height = self.plotter.width(), self.plotter.height()
        render_width, render_height = self._render_window.GetSize()
        if widget_width <= 1 or widget_height <= 1:
            return float(vtk_x), float(vtk_y)
        pointer_x = min(max(self._qt_pointer_position[0], 0.0), float(widget_width - 1))
        pointer_y = min(max(self._qt_pointer_position[1], 0.0), float(widget_height - 1))
        return (
            pointer_x * float(max(render_width - 1, 0)) / float(widget_width - 1),
            (float(widget_height - 1) - pointer_y)
            * float(max(render_height - 1, 0)) / float(widget_height - 1),
        )

    def _set_navigation_style_enabled(self, enabled: bool) -> None:
        style = self._interactor.GetInteractorStyle()
        if style is not None:
            style.SetEnabled(enabled)

    def _pick_face_normal(self, x: int, y: int) -> np.ndarray | None:
        cell_id = self._pick_face_cell(x, y)
        if cell_id is None:
            return None
        poly_data = self._bevel_hull.GetOutput()
        normal, _centroid = self._cell_normal_and_centroid(poly_data, cell_id)
        return normal

    @staticmethod
    def _cell_normal_and_centroid(
        poly_data: vtk.vtkPolyData,
        cell_id: int,
    ) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
        cell = poly_data.GetCell(cell_id)
        if cell is None or cell.GetNumberOfPoints() < 3:
            return None, None

        p0 = np.asarray(poly_data.GetPoint(cell.GetPointId(0)), dtype=float)
        p1 = np.asarray(poly_data.GetPoint(cell.GetPointId(1)), dtype=float)
        p2 = np.asarray(poly_data.GetPoint(cell.GetPointId(2)), dtype=float)
        normal = np.cross(p1 - p0, p2 - p0)
        normal_length = float(np.linalg.norm(normal))
        if normal_length <= 1e-12:
            return None, None
        normal /= normal_length

        centroid = np.mean(
            np.asarray(
                [poly_data.GetPoint(cell.GetPointId(index)) for index in range(cell.GetNumberOfPoints())],
                dtype=float,
            ),
            axis=0,
        )
        if float(np.dot(normal, centroid)) < 0.0:
            normal = -normal
        return normal, centroid

    def _pick_face_cell(self, x: int, y: int) -> int | None:
        if self._face_actor is None:
            return None
        self._face_picker.Pick(x, y, 0.0, self._renderer)
        if self._face_picker.GetActor() != self._face_actor:
            return None
        cell_id = self._face_picker.GetCellId()
        poly_data = self._bevel_hull.GetOutput()
        if cell_id < 0 or cell_id >= poly_data.GetNumberOfCells():
            return None
        return cell_id

    def _update_hover(self, x: int, y: int) -> None:
        cell_id = self._pick_face_cell(x, y)
        if cell_id == self._hover_cell_id:
            return

        self._hover_cell_id = cell_id
        if cell_id is None:
            if self._hover_actor is not None:
                self._hover_actor.VisibilityOff()
            self.plotter.render()
            return

        poly_data = self._bevel_hull.GetOutput()
        selected_normal, selected_centroid = self._cell_normal_and_centroid(poly_data, cell_id)
        if selected_normal is None or selected_centroid is None:
            return

        points = vtk.vtkPoints()
        polygons = vtk.vtkCellArray()
        selected_plane = float(np.dot(selected_normal, selected_centroid))
        coplanar_cell_count = 0
        for candidate_id in range(poly_data.GetNumberOfCells()):
            candidate_normal, candidate_centroid = self._cell_normal_and_centroid(poly_data, candidate_id)
            if candidate_normal is None or candidate_centroid is None:
                continue
            if float(np.dot(candidate_normal, selected_normal)) < 1.0 - 1e-6:
                continue
            if abs(float(np.dot(candidate_normal, candidate_centroid)) - selected_plane) > 1e-6:
                continue

            cell = poly_data.GetCell(candidate_id)
            point_ids = vtk.vtkIdList()
            point_ids.SetNumberOfIds(cell.GetNumberOfPoints())
            for index in range(cell.GetNumberOfPoints()):
                point_ids.SetId(index, points.InsertNextPoint(poly_data.GetPoint(cell.GetPointId(index))))
            polygons.InsertNextCell(point_ids)
            coplanar_cell_count += 1

        if coplanar_cell_count == 0:
            return
        self._hover_poly_data.SetPoints(points)
        self._hover_poly_data.SetPolys(polygons)
        self._hover_poly_data.Modified()
        if self._hover_actor is not None:
            self._hover_actor.VisibilityOn()
        self.plotter.render()

    def _on_left_press(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        normal = self._pick_face_normal(*self._picker_position(x, y))
        if normal is None:
            return
        self._camera_animation.stop()
        self._set_navigation_style_enabled(False)
        self._orient_camera_to_normal(normal)
        QTimer.singleShot(0, lambda: self._set_navigation_style_enabled(True))

    def _orient_camera_to_normal(self, normal: np.ndarray) -> None:
        camera = self._parent_renderer.GetActiveCamera()
        focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
        position = np.asarray(camera.GetPosition(), dtype=float)
        distance = float(np.linalg.norm(position - focal_point))
        if distance <= 1e-9:
            distance = 10.0

        target_position = focal_point + normal * distance
        world_up = np.asarray((0.0, 0.0, 1.0), dtype=float)
        target_up = world_up - float(np.dot(world_up, normal)) * normal
        if float(np.linalg.norm(target_up)) <= 1e-9:
            target_up = np.asarray((0.0, 1.0, 0.0), dtype=float)
        target_up /= float(np.linalg.norm(target_up))

        self._animation_start = (
            position,
            focal_point,
            np.asarray(camera.GetViewUp(), dtype=float),
        )
        self._animation_end = (target_position, focal_point, target_up)
        self._animation_elapsed = 0.0
        self._camera_animation.start()

    def animate_camera_roll(self, *, clockwise: bool) -> None:
        """Animate a 90-degree roll around the camera viewing direction."""
        camera = self._parent_renderer.GetActiveCamera()
        direction = np.asarray(camera.GetDirectionOfProjection(), dtype=float)
        view_up = np.asarray(camera.GetViewUp(), dtype=float)
        direction_norm = np.linalg.norm(direction)
        if direction_norm <= 1e-12:
            return
        direction /= direction_norm
        view_up -= direction * np.dot(view_up, direction)
        up_norm = np.linalg.norm(view_up)
        if up_norm <= 1e-12:
            return
        view_up /= up_norm
        right = np.cross(direction, view_up)
        right_norm = np.linalg.norm(right)
        if right_norm <= 1e-12:
            return
        right /= right_norm
        # The visual clockwise direction corresponds to -right in the
        # camera's world-up representation.
        target_up = -right if clockwise else right
        self._camera_animation.stop()
        self._set_navigation_style_enabled(False)
        self._animation_start = (
            np.asarray(camera.GetPosition(), dtype=float),
            np.asarray(camera.GetFocalPoint(), dtype=float),
            view_up,
        )
        self._animation_end = (
            self._animation_start[0].copy(),
            self._animation_start[1].copy(),
            target_up,
        )
        self._animation_elapsed = 0.0
        self._camera_animation.start()

    def _animate_camera(self) -> None:
        if self._animation_start is None or self._animation_end is None:
            self._camera_animation.stop()
            return

        self._animation_elapsed += self._camera_animation.interval() / 1000.0
        progress = min(1.0, self._animation_elapsed / self._animation_duration)
        eased = 0.5 - 0.5 * np.cos(np.pi * progress)
        start_position, start_focal, start_up = self._animation_start
        end_position, end_focal, end_up = self._animation_end

        camera = self._parent_renderer.GetActiveCamera()
        camera.SetPosition(*((1.0 - eased) * start_position + eased * end_position))
        camera.SetFocalPoint(*((1.0 - eased) * start_focal + eased * end_focal))
        camera.SetViewUp(*((1.0 - eased) * start_up + eased * end_up))
        camera.OrthogonalizeViewUp()
        self.sync_from_camera()
        self.plotter.render()

        if progress >= 1.0:
            self._camera_animation.stop()
            self._animation_start = None
            self._animation_end = None
            self._set_navigation_style_enabled(True)

    def _create_beveled_cube(self) -> vtk.vtkConvexHull:
        """Create a convex cube whose twelve original edges are chamfered."""
        half = self._CUBE_HALF_SIZE
        bevel = self._EDGE_CHAMFER
        planes: list[tuple[np.ndarray, float]] = []

        # Six original cube faces: +/-x, +/-y and +/-z.
        for axis in range(3):
            for sign in (-1.0, 1.0):
                normal = np.zeros(3)
                normal[axis] = sign
                planes.append((normal, half))

        # Twelve planes parallel to the original edges. They remove a strip
        # from each edge while retaining the six large planar faces.
        for first_axis, second_axis in ((0, 1), (0, 2), (1, 2)):
            for first_sign, second_sign in product((-1.0, 1.0), repeat=2):
                normal = np.zeros(3)
                normal[first_axis] = first_sign
                normal[second_axis] = second_sign
                planes.append((normal, 2.0 * half - bevel))

        # Eight corner planes create the polygonal caps where three chamfered
        # edges meet, instead of leaving a sharp point at each cube corner.
        # A cut deeper than twice the edge bevel intersects each adjacent
        # edge strip twice. The resulting corner cap is a visible hexagon,
        # matching the navigation-cube reference instead of a tiny triangle.
        corner_limit = 3.0 * half - self._CORNER_CHAMFER
        for signs in product((-1.0, 1.0), repeat=3):
            planes.append((np.asarray(signs), corner_limit))

        points: list[np.ndarray] = []
        for first, second, third in combinations(planes, 3):
            matrix = np.vstack((first[0], second[0], third[0]))
            if abs(float(np.linalg.det(matrix))) <= 1e-9:
                continue
            point = np.linalg.solve(matrix, np.array((first[1], second[1], third[1])))
            if not all(float(np.dot(normal, point)) <= limit + 1e-7 for normal, limit in planes):
                continue
            if not any(float(np.linalg.norm(point - existing)) <= 1e-7 for existing in points):
                points.append(point)

        vtk_points = vtk.vtkPoints()
        for point in points:
            vtk_points.InsertNextPoint(*point)
        point_cloud = vtk.vtkPolyData()
        point_cloud.SetPoints(vtk_points)

        hull = vtk.vtkConvexHull()
        hull.SetInputData(point_cloud)
        hull.GeneratePolyDataOn()
        return hull

    def sync_from_camera(self) -> None:
        """Apply the main camera's rotation to the overlay cube."""
        camera = self._parent_renderer.GetActiveCamera()
        position = np.asarray(camera.GetPosition(), dtype=float)
        focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
        view_direction = focal_point - position
        direction_length = float(np.linalg.norm(view_direction))
        if direction_length <= 1e-12:
            return
        view_direction /= direction_length

        view_up = np.asarray(camera.GetViewUp(), dtype=float)
        right = np.cross(view_direction, view_up)
        right_length = float(np.linalg.norm(right))
        if right_length <= 1e-12:
            return
        right /= right_length
        corrected_up = np.cross(right, view_direction)
        corrected_up /= max(float(np.linalg.norm(corrected_up)), 1e-12)

        matrix = vtk.vtkMatrix4x4()
        rows = (right, corrected_up, -view_direction)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                matrix.SetElement(row, column, float(value))
        matrix.SetElement(3, 3, 1.0)

        for prop in self._oriented_props:
            prop.SetUserMatrix(matrix)
        self._renderer.ResetCameraClippingRange()
