import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from osa.ui.project_sheet import ProjectSheetWorkspace


def test_sheet_linework_updates_after_replacing_views_and_segment_data():
    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    widget.resize(800, 600)
    view = {"segments": (((0, 0), (2, 1)), ((10, 10), (10, 10)))}
    widget.set_sheet_views([view])
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)

    def paint():
        painter = QPainter(image)
        widget.render(painter, QPoint())
        painter.end()
        app.processEvents()

    paint()
    assert widget._view_linework[0][3] == (0.0, 10.0, 0.0, 10.0)
    assert len(widget._view_linework[0][2]) == 1
    view["segments"] = (((-4, -3), (3, 2)),)
    paint()
    assert widget._view_linework[0][3] == (-4.0, 3.0, -3.0, 2.0)
    widget.set_sheet_views([{"segments": (((1, 1), (2, 2)),)}])
    paint()
    assert widget._view_linework[0][3] == (1.0, 2.0, 1.0, 2.0)
    widget.close()


def test_grouped_member_interface_filters_only_shared_end_edges():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import numpy as np
    import pyvista as pv

    from osa.rendering.scene_batched import StructureScene

    # Two adjacent members have coincident end edges at x=1; longitudinal
    # edges and an edge from an unrelated member must remain visible.
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [2, 0, 0], [2, 1, 0]], dtype=float)
    mesh = pv.PolyData(points, lines=np.array([2, 1, 2, 2, 0, 1, 2, 1, 2, 2, 3, 4]))
    mesh.cell_data['element_index'] = np.array([0, 0, 1, 2])
    nodes = {str(x): SimpleNamespace(x=x, y=0, z=0) for x in (0, 1, 2)}
    bars = {'a': SimpleNamespace(start_node='0', end_node='1'),
            'b': SimpleNamespace(start_node='1', end_node='2')}
    actor = MagicMock()
    scene = SimpleNamespace(
        _member_batch=SimpleNamespace(edges=mesh, names=('a', 'b', 'c')),
        _member_edge_actor=MagicMock(), _solid_members_visible=True,
        _analysis_visible=False, _verification_palette_visible=True,
        _detailing_session_active=False, _verification_group_edge_actor=None,
        _model=SimpleNamespace(verification_element_groups=[{'members': ['a', 'b']}], bars=bars, nodes=nodes),
        plotter=MagicMock(), _add_colored_mesh=MagicMock(return_value=actor),
    )
    StructureScene._refresh_verification_group_edges(scene)
    filtered = scene._add_colored_mesh.call_args.args[0]
    assert filtered.n_cells == 2
    assert filtered.cell_data['element_index'].tolist() == [0, 2]
    assert filtered.lines.tolist() == [2, 0, 1, 2, 3, 4]


def test_grouped_member_interface_filters_edges_stored_as_polylines():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import numpy as np
    import pyvista as pv

    from osa.rendering.scene_batched import StructureScene

    points = np.array([
        [1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1],
        [0, 0, 0], [2, 0, 0], [3, 0, 0], [4, 0, 0],
    ], dtype=float)
    mesh = pv.PolyData(points, lines=np.array([
        5, 0, 1, 2, 3, 0,  # first member's shared end contour
        2, 4, 0,           # first member's longitudinal profile edge
        5, 0, 1, 2, 3, 0,  # second member's shared start contour
        2, 0, 5,           # second member's longitudinal profile edge
        2, 6, 7,           # unrelated member edge
    ]))
    mesh.cell_data['element_index'] = np.array([0, 0, 1, 1, 2])
    nodes = {str(x): SimpleNamespace(x=x, y=0, z=0) for x in (0, 1, 2)}
    bars = {
        'a': SimpleNamespace(start_node='0', end_node='1'),
        'b': SimpleNamespace(start_node='1', end_node='2'),
    }
    scene = SimpleNamespace(
        _member_batch=SimpleNamespace(edges=mesh, names=('a', 'b', 'c')),
        _member_edge_actor=MagicMock(), _solid_members_visible=True,
        _analysis_visible=False, _verification_palette_visible=True,
        _detailing_session_active=False, _verification_group_edge_actor=None,
        _model=SimpleNamespace(verification_element_groups=[{'members': ['a', 'b']}], bars=bars, nodes=nodes),
        plotter=MagicMock(), _add_colored_mesh=MagicMock(return_value=MagicMock()),
    )

    StructureScene._refresh_verification_group_edges(scene)

    filtered = scene._add_colored_mesh.call_args.args[0]
    assert filtered.n_cells == 3
    assert filtered.cell_data['element_index'].tolist() == [0, 1, 2]


def test_grouped_member_interface_filters_cut_edges_with_boolean_tolerance():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import numpy as np
    import pyvista as pv

    from osa.rendering.scene_batched import StructureScene

    # Boolean subtraction can perturb points on the shared section plane by a
    # fraction of a micron. Those cut boundary segments still belong to the
    # interface and must not reappear as a seam in the grouped profile.
    points = np.array([
        [1.0000002, 0, 0], [1.0000002, 1, 0],
        [0, 0, 0], [2, 0, 0], [3, 0, 0],
    ], dtype=float)
    mesh = pv.PolyData(points, lines=np.array([
        2, 0, 1,  # first member's nearly coplanar cut edge
        2, 2, 0,  # first member's longitudinal edge
        2, 0, 1,  # second member's coincident interface edge
        2, 1, 3,  # second member's longitudinal edge
        2, 3, 4,  # unrelated member edge
    ]))
    mesh.cell_data['element_index'] = np.array([0, 0, 1, 1, 2])
    nodes = {str(x): SimpleNamespace(x=x, y=0, z=0) for x in (0, 1, 2)}
    bars = {
        'a': SimpleNamespace(start_node='0', end_node='1'),
        'b': SimpleNamespace(start_node='1', end_node='2'),
    }
    scene = SimpleNamespace(
        _member_batch=SimpleNamespace(edges=mesh, names=('a', 'b', 'c')),
        _member_edge_actor=MagicMock(), _solid_members_visible=True,
        _analysis_visible=False, _verification_palette_visible=True,
        _detailing_session_active=False, _verification_group_edge_actor=None,
        _model=SimpleNamespace(verification_element_groups=[{'members': ['a', 'b']}], bars=bars, nodes=nodes),
        plotter=MagicMock(), _add_colored_mesh=MagicMock(return_value=MagicMock()),
    )

    StructureScene._refresh_verification_group_edges(scene)

    filtered = scene._add_colored_mesh.call_args.args[0]
    assert filtered.n_cells == 3
    assert filtered.cell_data['element_index'].tolist() == [0, 1, 2]


def test_release_loop_matches_original_geometry():
    from math import cos, pi, sin

    import numpy as np

    from osa.rendering.release_symbols import release_symbol_polylines

    basis = tuple(np.eye(3))
    endpoint = np.array([2., 3., 4.])
    radius = 0.2
    releases = (False, False, False, False, False, False, True, False, True, False, True, False)
    loops = release_symbol_polylines(endpoint, basis[0], releases, radius, basis, end=0, longitudinal_offset=0.1)
    center = endpoint + basis[0] * 0.1
    for axis, loop in enumerate(loops):
        first, second = basis[(axis + 1) % 3], basis[(axis + 2) % 3]
        expected = np.array([center + radius * (1.05 + 0.25 * axis) *
                             (first * cos(angle) + second * sin(angle))
                             for angle in np.linspace(0, 2 * pi, 40)])
        np.testing.assert_allclose(loop, expected, atol=1e-14)


def test_pan_cache_preserves_visible_content_and_refreshes_hit_targets():
    import numpy as np
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    widget.resize(800, 600)
    widget.set_sheet_views([{"segments": (((0, 0), (10, 10)), ((20, 20), (10, 10)))}])
    widget.show()
    app.processEvents()

    def render():
        image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        widget.render(painter, QPoint())
        painter.end()
        return np.frombuffer(image.bits(), dtype=np.uint8).copy()

    # The translation exceeds the overscan margin, exercising the exposed area.
    widget._begin_navigation()
    widget._pan_offset = QPointF(300, 70)
    cached = render()
    widget._finish_navigation()
    precise = render()
    np.testing.assert_array_equal(cached, precise)

    widget._begin_navigation()
    widget._pan_offset += QPointF(-100, -20)
    render()
    # The idle timer may have fired before Qt processes its pending repaint.
    widget._finish_navigation()
    # A click must refresh the hit rectangles before selection.
    old_center = widget._view_hit_rects[0].center()
    new_center = old_center + QPointF(-100, -20)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=new_center.toPoint())
    assert widget._selected_view_index == 0
    widget.close()


def test_project_axis_geometry_is_reused_and_tracks_model_changes():
    from PySide6.QtWidgets import QWidget

    from osa.domain.entities import ReferenceAxis
    from osa.model import StructuralModel

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.model = StructuralModel()
    parent.model.add_node("A", 0, 0, 0)
    parent.model.add_node("B", 10, 10, 0)
    parent.model.set_reference_axes({"X": (ReferenceAxis("A", 5),)})
    widget = ProjectSheetWorkspace(parent)
    widget.resize(800, 600)
    widget.set_sheet_views([{
        "segments": (((0, 0), (10, 10)),),
        "axes_visible": True,
        "projection": {"plane": "XY", "coordinate": 0},
    }])
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)

    def render():
        painter = QPainter(image)
        widget.render(painter, QPoint())
        painter.end()

    render()
    first = widget._view_axis_geometry[0]
    widget.update()
    render()
    assert widget._view_axis_geometry[0] is first
    parent.model.set_reference_axes({"X": (ReferenceAxis("B", 6),)})
    render()
    assert widget._view_axis_geometry[0] is not first
    assert [axis[1] for axis in widget._view_axis_geometry[0][1]] == ["B"]
    widget.close()
    parent.close()
    app.processEvents()


def test_zoom_draws_vector_picture_even_if_raster_cache_is_empty():
    import numpy as np
    from PySide6.QtCore import QPointF, Qt

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    widget.resize(800, 600)
    widget.set_sheet_views([{"segments": (((0, 0), (10, 10)), ((0, 10), (10, 0)))}])
    widget.show()
    app.processEvents()

    def render():
        image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        widget.render(painter, QPoint())
        painter.end()
        return np.frombuffer(image.bits(), dtype=np.uint8).copy()

    widget._begin_navigation()
    widget._zoom_factor = 1.2
    widget._pan_offset = QPointF(15, 10)
    expected = render()
    widget._navigation_pixmap.fill(Qt.GlobalColor.transparent)
    actual = render()
    np.testing.assert_array_equal(actual, expected)
    widget._finish_navigation()
    widget.close()


def test_axis_geometry_is_updated_during_zoom_before_idle():
    from PySide6.QtWidgets import QWidget

    from osa.domain.entities import ReferenceAxis
    from osa.model import StructuralModel

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.model = StructuralModel()
    parent.model.add_node("A", 0, 0, 0)
    parent.model.add_node("B", 10, 10, 0)
    parent.model.set_reference_axes({"X": (ReferenceAxis("A", 5),)})
    widget = ProjectSheetWorkspace(parent)
    widget.resize(800, 600)
    widget.set_sheet_views([{"segments": (((0, 0), (10, 10)),), "axes_visible": True,
                             "projection": {"plane": "XY", "coordinate": 0}}])
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)

    def render():
        painter = QPainter(image)
        widget.render(painter, QPoint())
        painter.end()

    render()
    old_scale = widget._sheet_pixels_per_mm
    widget._begin_navigation()
    widget._zoom_factor *= 1.7
    render()
    zoomed_scale = widget._sheet_pixels_per_mm
    zoomed_rects = dict(widget._axis_endpoint_hit_rects)
    assert zoomed_scale == old_scale * 1.7
    assert zoomed_rects
    widget._finish_navigation()
    render()
    assert widget._sheet_pixels_per_mm == zoomed_scale
    assert widget._axis_endpoint_hit_rects == zoomed_rects
    widget.close()
    parent.close()
    app.processEvents()


def test_dimension_and_identifier_picking_only_test_nearby_segments(monkeypatch):
    from PySide6.QtWidgets import QWidget

    from osa.model import StructuralModel

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.model = StructuralModel()
    count = 1000
    segments = tuple(
        ((index * 10.0, 0.0), (index * 10.0 + 1.0, 0.0))
        for index in range(count)
    )
    owners = tuple(f"fixture:item-{index}" for index in range(count))
    widget = ProjectSheetWorkspace(parent)
    widget.resize(1000, 700)
    widget.set_sheet_views([{"segments": segments, "segment_owners": owners}])
    widget.show()
    app.processEvents()
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    widget.render(painter, QPoint())
    painter.end()

    point = widget._screen_point(0, segments[count // 2][0])
    assert point is not None
    intersections = 0
    original_intersection = ProjectSheetWorkspace._segment_intersection

    def count_intersections(first, second):
        nonlocal intersections
        intersections += 1
        return original_intersection(first, second)

    monkeypatch.setattr(
        ProjectSheetWorkspace, "_segment_intersection", staticmethod(count_intersections),
    )
    snap = widget._dimension_snap_at(point, 0)
    assert snap is not None
    assert snap[4] == "endpoint"
    assert intersections < 1000  # A full pairwise pass would perform ~500,000 tests.

    distance_checks = 0
    original_distance = ProjectSheetWorkspace._distance_to_segment

    def count_distances(position, start, end):
        nonlocal distance_checks
        distance_checks += 1
        return original_distance(position, start, end)

    monkeypatch.setattr(
        ProjectSheetWorkspace, "_distance_to_segment", staticmethod(count_distances),
    )
    target = widget._element_at(point)
    assert target is not None
    assert target[2] == owners[count // 2]
    assert distance_checks < 100
    widget.close()
    parent.close()
    app.processEvents()


def test_project_axis_dash_rhythm_is_fixed_in_screen_space():
    from osa.ui.project_sheet import PROJECT_AXIS_DASH_PATTERN

    assert PROJECT_AXIS_DASH_PATTERN == (6.0, 2.0, 1.0, 2.0)


def test_annotation_movement_invalidates_only_the_old_and_new_area(monkeypatch):
    from PySide6.QtCore import QPoint, QRectF

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    widget.resize(800, 600)
    updates = []
    monkeypatch.setattr(QWidget, "update", lambda _self, region: updates.append(region))

    widget._update_annotation_regions(
        QRectF(10.0, 20.0, 30.0, 40.0),
        QRectF(100.0, 120.0, 30.0, 40.0),
    )

    assert len(updates) == 1
    bounds = updates[0].boundingRect()
    assert bounds.x() == 5
    assert bounds.y() == 15
    assert bounds.right() == 134
    assert bounds.bottom() == 164
    assert not updates[0].contains(QPoint(70, 90))
    assert widget._annotation_partial_repaint
    widget.close()
    app.processEvents()


def test_dimension_drag_keeps_the_last_painted_bounds_when_mouse_events_coalesce(monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF, QRectF, Qt

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    dimension = {"start": (0.0, 0.0), "end": (100.0, 0.0), "offset": (0.0, 0.0)}
    widget._sheet_views = ({"dimensions": [dimension]},)
    widget._view_draw_data = {0: (0.0, 0.0, 200.0, 200.0, 1.0)}
    widget._drag_dimension_index = (0, 0)
    widget._drag_position = QPointF(0.0, 0.0)
    initial_bounds = QRectF(100.0, 100.0, 100.0, 30.0)
    widget._drag_dimension_current_bounds = QRectF(initial_bounds)
    widget._drag_dimension_painted_bounds = QRectF(initial_bounds)
    invalidations = []
    monkeypatch.setattr(
        widget, "_update_annotation_regions",
        lambda *regions: invalidations.append(regions),
    )

    for position in (QPointF(0.0, 10.0), QPointF(0.0, 20.0)):
        event = SimpleNamespace(
            buttons=lambda: Qt.MouseButton.LeftButton,
            position=lambda position=position: position,
            accept=lambda: None,
        )
        widget.mouseMoveEvent(event)

    assert len(invalidations) == 2
    assert invalidations[-1][0] == initial_bounds
    assert invalidations[-1][1].top() == 120.0
    assert dimension["offset"][1] == -20.0
    widget.close()
    app.processEvents()


def test_view_axis_and_title_drags_use_partial_invalidation(monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF, QRectF, Qt

    app = QApplication.instance() or QApplication([])
    event_at = lambda x, y: SimpleNamespace(
        buttons=lambda: Qt.MouseButton.LeftButton,
        position=lambda: QPointF(x, y),
        accept=lambda: None,
    )

    axis_widget = ProjectSheetWorkspace()
    axis_key = "X:A:0.000000"
    endpoint_key = f"{axis_key}:start"
    axis_widget._sheet_views = ({"axis_label_positions": {}},)
    axis_widget._view_draw_data = {0: (0.0, 0.0, 200.0, 200.0, 1.0)}
    axis_widget._view_axis_geometry = {
        0: (None, [(axis_key, "A", (0.0, 0.0), (100.0, 0.0))]),
    }
    axis_widget._selected_view_index = 0
    axis_widget._drawing_area = QRectF(0.0, 0.0, 500.0, 500.0)
    axis_widget._view_geometry_bounds[0] = QRectF(100.0, 100.0, 100.0, 100.0)
    axis_widget._view_content_bounds[0] = QRectF(100.0, 100.0, 300.0, 150.0)
    axis_widget._view_hit_rects[0] = QRectF(100.0, 100.0, 300.0, 250.0)
    axis_widget._axis_line_bounds[(0, axis_key)] = QRectF(200.0, 190.0, 100.0, 20.0)
    axis_widget._view_title_hit_rects[0] = QRectF(150.0, 255.0, 100.0, 30.0)
    axis_widget._drag_axis_endpoints = ((0, endpoint_key),)
    axis_widget._axis_endpoint_drag_data = {(0, endpoint_key): (1.0, 0.0, 100.0)}
    axis_widget._drag_position = QPointF(0.0, 0.0)
    axis_bounds = QRectF(200.0, 190.0, 100.0, 20.0)
    axis_widget._drag_axis_current_bounds[(0, axis_key)] = QRectF(axis_bounds)
    axis_widget._drag_axis_painted_bounds[(0, axis_key)] = QRectF(axis_bounds)
    axis_updates = []
    monkeypatch.setattr(axis_widget, "_update_annotation_regions", lambda *items: axis_updates.append(items))
    axis_widget.mouseMoveEvent(event_at(10.0, 0.0))
    assert axis_widget._sheet_views[0]["axis_label_positions"][endpoint_key] == 0.1
    assert axis_updates and axis_updates[-1][0] == axis_bounds
    assert any(
        isinstance(region, QRectF) and region.top() <= 100.0 <= region.bottom()
        for region in axis_updates[-1][2:]
    )

    title_widget = ProjectSheetWorkspace()
    title_widget._sheet_views = ({"label_offset_mm": (0.0, 0.0)},)
    title_widget._sheet_pixels_per_mm = 1.0
    title_widget._drag_view_title_index = 0
    title_widget._selected_view_index = 0
    title_widget._drawing_area = QRectF(0.0, 0.0, 500.0, 500.0)
    title_widget._view_geometry_bounds[0] = QRectF(100.0, 100.0, 200.0, 100.0)
    title_widget._view_content_bounds[0] = QRectF(100.0, 100.0, 200.0, 100.0)
    title_widget._view_hit_rects[0] = QRectF(95.0, 95.0, 300.0, 200.0)
    title_widget._drag_position = QPointF(0.0, 0.0)
    title_bounds = QRectF(20.0, 30.0, 100.0, 20.0)
    title_widget._drag_title_current_bounds = QRectF(title_bounds)
    title_widget._drag_title_painted_bounds = QRectF(title_bounds)
    title_updates = []
    monkeypatch.setattr(title_widget, "_update_annotation_regions", lambda *items: title_updates.append(items))
    title_widget.mouseMoveEvent(event_at(8.0, 6.0))
    assert title_widget._sheet_views[0]["label_offset_mm"] == (8.0, 6.0)
    assert title_updates and title_updates[-1][1] == title_bounds.translated(8.0, 6.0)
    assert any(
        isinstance(region, QRectF) and region.top() <= 95.0 <= region.bottom()
        for region in title_updates[-1][2:]
    )

    view_widget = ProjectSheetWorkspace()
    view_widget._sheet_views = ({"position": (0.5, 0.5)},)
    view_widget._selected_view_index = 0
    view_widget._drag_view_index = 0
    view_widget._drag_position = QPointF(0.0, 0.0)
    view_widget._drawing_area = QRectF(0.0, 0.0, 100.0, 100.0)
    view_bounds = QRectF(100.0, 100.0, 200.0, 100.0)
    view_widget._drag_view_current_bounds = QRectF(view_bounds)
    view_widget._drag_view_painted_bounds = QRectF(view_bounds)
    view_updates = []
    monkeypatch.setattr(view_widget, "_update_annotation_regions", lambda *items: view_updates.append(items))
    view_widget.mouseMoveEvent(event_at(10.0, 20.0))
    assert view_widget._sheet_views[0]["position"] == (0.6, 0.7)
    assert view_updates and view_updates[-1][1] == view_bounds.translated(10.0, 20.0)

    axis_widget.close()
    title_widget.close()
    view_widget.close()
    app.processEvents()


def test_identification_drag_invalidates_auto_moved_title_and_view_outline(monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF, QRectF, Qt

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    widget._sheet_views = ({"identifications": [{"projected_point": (0.0, 0.0)}]},)
    widget._selected_view_index = 0
    widget._view_draw_data = {0: (0.0, 0.0, 200.0, 200.0, 1.0)}
    widget._drawing_area = QRectF(0.0, 0.0, 600.0, 600.0)
    widget._view_geometry_bounds[0] = QRectF(100.0, 100.0, 200.0, 100.0)
    widget._view_content_bounds[0] = QRectF(100.0, 100.0, 200.0, 100.0)
    widget._view_hit_rects[0] = QRectF(95.0, 95.0, 300.0, 200.0)
    widget._view_title_hit_rects[0] = QRectF(100.0, 205.0, 100.0, 30.0)
    initial_label = QRectF(150.0, 150.0, 30.0, 10.0)
    widget._identification_hit_rects[(0, 0)] = initial_label
    widget._drag_identification_index = 0
    widget._drag_identification_indices = (0,)
    widget._drag_identification_current_bounds = {0: QRectF(initial_label)}
    widget._drag_identification_painted_bounds = {0: QRectF(initial_label)}
    widget._drag_position = QPointF(0.0, 0.0)
    updates = []
    monkeypatch.setattr(widget, "_update_annotation_regions", lambda *regions: updates.append(regions))

    event = SimpleNamespace(
        buttons=lambda: Qt.MouseButton.LeftButton,
        position=lambda: QPointF(0.0, 200.0),
        accept=lambda: None,
    )
    widget.mouseMoveEvent(event)

    assert widget._sheet_views[0]["identifications"][0]["projected_point"] == (0.0, -200.0)
    assert updates
    regions = updates[-1]
    assert any(isinstance(region, QRectF) and region == QRectF(100.0, 362.0, 100.0, 30.0) for region in regions)
    assert len(regions) > 4  # Old and new frame edges are included with the moved label/title.
    widget.close()
    app.processEvents()


def test_dimension_must_be_selected_after_its_view(monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF, QRectF, Qt

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    widget._sheet_views = ({"dimensions": [{"start": (0.0, 0.0), "end": (100.0, 0.0), "offset": (0.0, 10.0)}]},)
    dimension_key = (0, 0)
    widget._dimension_text_hit_rects[dimension_key] = QRectF(100.0, 100.0, 30.0, 20.0)
    event = SimpleNamespace(
        button=lambda: Qt.MouseButton.LeftButton,
        position=lambda: QPointF(110.0, 110.0),
        modifiers=lambda: Qt.KeyboardModifier.NoModifier,
        accept=lambda: None,
    )

    widget.mousePressEvent(event)
    assert widget._selected_view_index == 0
    assert widget._selected_dimension is None
    assert widget._drag_dimension_index is None

    widget.mousePressEvent(event)
    assert widget._selected_dimension == dimension_key
    assert widget._drag_dimension_index == dimension_key
    widget.close()
    app.processEvents()


def test_dimension_drag_invalidates_auto_moved_title_and_view_outline(monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPointF, QRectF, Qt

    app = QApplication.instance() or QApplication([])
    widget = ProjectSheetWorkspace()
    dimension = {"start": (0.0, 0.0), "end": (100.0, 0.0), "offset": (0.0, 10.0)}
    widget._sheet_views = ({"dimensions": [dimension]},)
    widget._selected_view_index = 0
    widget._view_draw_data = {0: (0.0, 0.0, 200.0, 200.0, 1.0)}
    widget._drawing_area = QRectF(0.0, 0.0, 600.0, 600.0)
    widget._view_geometry_bounds[0] = QRectF(100.0, 100.0, 100.0, 80.0)
    widget._view_content_bounds[0] = QRectF(100.0, 100.0, 200.0, 100.0)
    widget._view_dimension_bounds[(0, 0)] = QRectF(190.0, 180.0, 110.0, 20.0)
    widget._dimension_bounds[(0, 0)] = QRectF(188.0, 178.0, 114.0, 24.0)
    widget._view_title_hit_rects[0] = QRectF(100.0, 205.0, 100.0, 30.0)
    widget._view_hit_rects[0] = QRectF(95.0, 95.0, 300.0, 150.0)
    widget._drag_dimension_index = (0, 0)
    widget._drag_dimension_current_bounds = QRectF(188.0, 178.0, 114.0, 24.0)
    widget._drag_dimension_painted_bounds = QRectF(widget._drag_dimension_current_bounds)
    widget._drag_dimension_content_current_bounds = QRectF(190.0, 180.0, 110.0, 20.0)
    widget._drag_position = QPointF(0.0, 0.0)
    widget._align_dimension_to_existing = lambda _view_index, value: value
    updates = []
    monkeypatch.setattr(widget, "_update_annotation_regions", lambda *regions: updates.append(regions))

    event = SimpleNamespace(
        buttons=lambda: Qt.MouseButton.LeftButton,
        position=lambda: QPointF(0.0, 10.0),
        accept=lambda: None,
    )
    widget.mouseMoveEvent(event)

    assert dimension["offset"] == (0.0, 0.0)
    assert updates
    assert any(isinstance(region, QRectF) and region == QRectF(100.0, 215.0, 100.0, 30.0) for region in updates[-1])
    assert len(updates[-1]) > 4
    widget.close()
    app.processEvents()
