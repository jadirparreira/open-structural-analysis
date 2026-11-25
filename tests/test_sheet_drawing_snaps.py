"""Drawing tools snap to the actual paper, carimbo and table grid."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from osa.ui.project_sheet import ProjectSheetWorkspace


@pytest.fixture
def sheet():
    app = QApplication.instance() or QApplication([])
    workspace = ProjectSheetWorkspace()
    workspace.resize(1500, 1050)
    workspace._settings['tables'] = [dict(kind='accessories', position=(.15, .25))]
    workspace.accessory_rows_provider = lambda:[dict(name='Arruela Lisa Ø 12,5', quantity=4)]
    # Also test sheet references while the drawing is associated with a view.
    workspace.set_sheet_views([dict(segments=(((0., 0.), (.1, .1)),),
                                   scale_denominator=10., position=(.85, .12))])
    workspace.show(); app.processEvents(); workspace.grab()
    yield workspace
    workspace.close(); app.processEvents()


@pytest.mark.parametrize('view_index', [None, 0])
def test_border_and_title_block_grid_snap_even_inside_view(sheet, view_index):
    paper, frame, stamp = sheet._paper_rect, sheet._drawing_area, sheet._stamp_rect
    points = [paper.topLeft(), frame.bottomLeft(), stamp.topLeft(),
              QPointF(stamp.left()+stamp.width()*.78, stamp.top()+50*sheet._sheet_pixels_per_mm)]
    for target in points:
        snap = sheet._line_snap_screen_point(target+QPointF(1, 1), view_index)
        assert snap is not None
        assert (snap[0]-target).manhattanLength() < 1e-5
    target = (frame.topLeft()+frame.topRight())/2
    snap = sheet._line_snap_screen_point(target+QPointF(1, 1), view_index)
    assert snap is not None and snap[1] == 'center'
    assert (snap[0]-target).manhattanLength() < 1e-5


@pytest.mark.parametrize('view_index', [None, 0])
def test_table_corners_midpoints_internal_intersections_and_perpendicular(sheet, view_index):
    bounds = sheet._sheet_table_hit_rects[0]
    layout = sheet._sheet_table_layouts[0][1]
    scale = bounds.width()/layout.width_mm
    x = bounds.left()+layout._widths[0]*scale
    y = bounds.top()+layout._title_height*scale
    targets = [bounds.topLeft(), bounds.bottomRight(),
               QPointF(x, y), QPointF(x, y+layout._rows[0][0]*scale)]
    for target in targets:
        snap = sheet._line_snap_screen_point(target+QPointF(1, 1), view_index)
        assert snap is not None
        assert (snap[0]-target).manhattanLength() < 1e-5
    target = (bounds.topLeft()+bounds.topRight())/2
    assert sheet._line_snap_screen_point(target, view_index)[1] == 'center'
    target = QPointF(bounds.left()+bounds.width()*.31, bounds.top())
    origin = target+QPointF(0, -50)
    snap = sheet._line_snap_screen_point(target+QPointF(0, 1), view_index, origin)
    assert snap[1] == 'perpendicular' and (snap[0]-target).manhattanLength() < 1e-5


@pytest.mark.parametrize('kind', ['line', 'rectangle', 'circle'])
def test_shape_placement_uses_border_and_table_snaps(sheet, kind):
    first = sheet._drawing_area.bottomLeft()
    second = sheet._sheet_table_hit_rects[0].topLeft()
    sheet.set_sheet_line_mode(True, kind)
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=(first+QPointF(1, 1)).toPoint())
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=(second+QPointF(1, 1)).toPoint())
    assert sheet._annotation_mode is None
    annotation = sheet._sheet_lines[-1]
    assert annotation['kind'] == kind
    for saved, expected in zip(annotation['points'], (first, second)):
        actual = sheet._sheet_annotation_screen_point(dict(anchor=saved), None)
        assert (actual-expected).manhattanLength() < 1e-5
