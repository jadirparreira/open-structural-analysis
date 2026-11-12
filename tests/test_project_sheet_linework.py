import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

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
