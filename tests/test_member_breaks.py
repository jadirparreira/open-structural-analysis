"""Break symbols remain local to sheet views and replace the selected cap."""

import copy
import json
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from osa.model import StructuralModel
from osa.rendering.member_breaks import member_break_linework
from osa.ui.project_sheet import ProjectSheetWorkspace


def rectangle():
    corners = ((0.0, -0.1), (1.0, -0.1), (1.0, 0.1), (0.0, 0.1))
    return tuple(zip(corners, (*corners[1:], corners[0])))


@pytest.mark.parametrize("end", (0, 1))
@pytest.mark.parametrize("angle", (0, 35, 90, 170))
def test_break_removes_only_nearest_cap_and_rotates_with_member(end, angle):
    theta = math.radians(angle)
    axis = math.cos(theta), math.sin(theta)

    def rotate(p):
        return p[0] * axis[0] - p[1] * axis[1], p[0] * axis[1] + p[1] * axis[0]

    original = tuple(tuple(rotate(p) for p in line) for line in rectangle())
    unrelated = ((10, 10), (11, 11))
    segments = (*original, unrelated)
    owners = ("bar:B",) * 4 + ("plate:P",)
    marked, sources = member_break_linework(segments, owners, [{"owner": "bar:B", "end": end, "axis": axis}])
    assert unrelated in marked
    assert original[3 if end == 0 else 1] not in marked
    assert original[1 if end == 0 else 3] in marked
    assert len(marked) == len(sources)
    assert len([source for source in sources if source == "plate:P"]) == 1
    assert len(rectangle()) == 4


def test_both_ends_and_json_round_trip():
    marks = [{"owner": "bar:B", "end": end, "axis": [1, 0]} for end in (0, 1)]
    segments, owners = rectangle(), ("bar:B",) * 4
    marked, sources = member_break_linework(segments, owners, json.loads(json.dumps(marks)))
    assert segments[1] not in marked and segments[3] not in marked
    assert len(marked) == len(sources)
    assert member_break_linework(segments, owners, []) == (segments, owners)


@pytest.mark.parametrize("plane", ("XY", "custom"))
@pytest.mark.parametrize("owner", ("bar:B", "B"))
def test_sheet_click_flow_detail_view_toggle_and_fixed_position(plane, owner):
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.model = StructuralModel()
    window.model.add_node("A", 0, 0, 0)
    window.model.add_node("B", 1, 0, 0)
    window.model.add_bar("B", "A", "B")
    sheet = ProjectSheetWorkspace(window)
    sheet.resize(1100, 800)
    view = {"name": "Detalhe", "segments": rectangle(), "segment_owners": (owner,) * 4,
            "projection": {"plane": plane, "coordinate": ((0, 0, 0), (1, 0, 0), (0, 1, 0))},
            "scale_denominator": 5.0,
            "component_detail_group": {"id": "detail-A", "title": "DET A", "view_count": 1}}
    other = copy.deepcopy(view)
    other.pop("component_detail_group")
    other["position"] = (0.8, 0.2)
    sheet.set_sheet_views([view, other])
    changes = []
    sheet.layout_changed.connect(lambda: changes.append(True))

    def paint():
        image = QImage(sheet.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        sheet.render(painter, QPoint())
        painter.end()
        app.processEvents()
        return image

    def screen(x, y):
        cx, cy, tx, ty, scale = sheet._view_draw_data[0]
        return QPointF(tx + (x - cx) * scale, ty - (y - cy) * scale)

    try:
        paint()
        original_position = sheet._view_draw_data[0]
        sheet.select_view(0)
        sheet.set_member_break_mode(True)
        assert sheet._selected_view_index is None
        # The face is farther than the old edge-only picking tolerance.
        assert sheet._element_at(screen(0.90, 0.0), view_index=0) is None
        # First click selects the detail view even when directly on a bar.
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=screen(0.90, 0.0).toPoint())
        assert sheet._member_break_view_index == 0
        assert not view.get("member_breaks")
        QTest.keyClick(sheet, Qt.Key.Key_Return)
        assert sheet._member_break_mode
        assert sheet._member_break_view_index == 0
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=screen(0.90, 0.0).toPoint())
        assert view["member_breaks"][0]["end"] == 1
        assert len(changes) == 1
        paint()
        assert sheet._view_draw_data[0] == original_position
        assert sheet._display_linework(other)[0] == rectangle()
        assert view["segments"] == rectangle()
        assert len(sheet._segment_grid_for_view(0).segments) > 4
        # Removing the mark restores all original lines.
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=screen(0.90, 0.0).toPoint())
        assert view["member_breaks"] == []
        paint()
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=screen(0.10, 0.0).toPoint())
        assert view["member_breaks"][0]["end"] == 0
        QTest.keyClick(sheet, Qt.Key.Key_Escape)
        assert not sheet._member_break_mode
        assert view["member_breaks"]  # Escape preserves placed symbols.
        # Serialized view data restores the same decorated geometry.
        expected = sheet._display_linework(view)
        restored = json.loads(json.dumps(view))
        sheet.set_sheet_views([restored])
        assert sheet._display_linework(restored) == expected
    finally:
        sheet.close()
        window.close()


def test_main_window_button_starts_and_cancels_break_command():
    from osa.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._detailing_project_mode = True
        assert window.project_sheets_palette.sheet_selector.currentText()
        button = window.project_sheets_palette.member_break_button
        assert not button.icon().isNull()
        button.click()
        assert window._command_mode == "project_sheet_member_break"
        assert window.project_sheet_workspace._member_break_mode
        # Enter does nothing, even when focus is outside the sheet.
        QTest.keyClick(window.command_bar.input, Qt.Key.Key_Return)
        assert window._command_mode == "project_sheet_member_break"
        QTest.keyClick(window.command_bar.input, Qt.Key.Key_Escape)
        assert window._command_mode is None
        button.click()
        QTest.keyClick(button, Qt.Key.Key_Escape)
        assert window._command_mode is None
        assert not window.project_sheet_workspace._member_break_mode
    finally:
        window._saved_revision = window.model.revision
        window._saved_view_revision = window.model.view_revision
        window.scene.plotter.close()
        window.close()
        app.processEvents()


def test_face_click_in_generated_base_plate_detail():
    from osa.ui.dialogs import ComponentDetailsDialog

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    model = window.model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 2)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", "Tubular Quadrado")
    model.update_member_profile("B1", "TQ100x3", {"b": 100.0, "t": 3.0})
    generated = ComponentDetailsDialog._build_group_views(model, 0.05, {"parameters": {}, "nodes": ["A"]})
    data = generated["west"]
    assert "B1" in data["segment_owners"]
    view = {"name": "DET A - Oeste", "segments": data["segments"],
            "segment_owners": data["segment_owners"], "scale_denominator": 5.0,
            "projection": {"plane": "custom", "coordinate": data["coordinate"]}}
    sheet = ProjectSheetWorkspace(window)
    sheet.resize(1100, 800)
    sheet._settings["title_block_visible"] = False
    sheet.set_sheet_views([view])
    try:
        image = QImage(sheet.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        sheet.render(painter, QPoint())
        painter.end()
        app.processEvents()
        axis = sheet._member_break_axis(view, "B1")
        normal = -axis[1], axis[0]
        points = [p for line, owner in zip(data["segments"], data["segment_owners"]) if owner == "B1" for p in line]
        stations = [sum(p[i] * axis[i] for i in range(2)) for p in points]
        offsets = [sum(p[i] * normal[i] for i in range(2)) for p in points]
        station = max(stations) - 0.04
        offset = (min(offsets) + max(offsets)) / 2
        x, y = (axis[i] * station + normal[i] * offset for i in range(2))
        cx, cy, tx, ty, scale = sheet._view_draw_data[0]
        face = QPointF(tx + (x - cx) * scale, ty - (y - cy) * scale)
        assert sheet._element_at(face, view_index=0) is None
        sheet.set_member_break_mode(True)
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=face.toPoint())
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=face.toPoint())
        assert view["member_breaks"] == [{"owner": "B1", "axis": list(axis), "end": 1}]
        assert sheet._display_linework(view)[0] != data["segments"]
    finally:
        sheet.close()
        window.close()


def test_red_symbol_selection_axis_drag_save_and_escape():
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    model = window.model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 1, 0, 0)
    model.add_bar("B", "A", "B")
    sheet = ProjectSheetWorkspace(window)
    sheet.resize(1000, 700)
    view = {"segments": rectangle(), "segment_owners": ("bar:B",) * 4,
            "projection": {"plane": "XY"}, "scale_denominator": 5,
            "member_breaks": [{"owner": "bar:B", "axis": [1, 0], "end": 1}]}
    sheet.set_sheet_views([view])
    changes = []
    sheet.layout_changed.connect(lambda: changes.append(True))

    def paint():
        image = QImage(sheet.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        sheet.render(painter, QPoint())
        painter.end()
        app.processEvents()
        return image

    def screen(point):
        cx, cy, tx, ty, scale = sheet._view_draw_data[0]
        return QPointF(tx + (point[0] - cx) * scale, ty - (point[1] - cy) * scale)

    def move(point):
        event = QMouseEvent(QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(sheet, event)

    try:
        image = paint()
        line = sheet._member_break_symbols(view)[0][0]
        point = screen(tuple((a + b) / 2 for a, b in zip(*line)))
        assert any(image.pixelColor(x, y).red() > 180 and image.pixelColor(x, y).green() < 100
                   for x in range(round(point.x()) - 2, round(point.x()) + 3)
                   for y in range(round(point.y()) - 2, round(point.y()) + 3))
        QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=point.toPoint())
        assert sheet._selected_member_break == (0, 0)
        before = sheet._member_break_symbols(view)[0]
        # A diagonal mouse motion moves the symbol only along the member axis.
        destination = point + QPointF(-100, 70)
        move(destination)
        after = sheet._member_break_symbols(view)[0]
        assert [p[1] for segment in before for p in segment] == pytest.approx(
            [p[1] for segment in after for p in segment])
        assert after[0][0][0] < before[0][0][0]
        QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=destination.toPoint())
        assert len(changes) == 1
        saved = json.loads(json.dumps(view))
        assert saved["member_breaks"][0]["position"] == view["member_breaks"][0]["position"]
        original = dict(view["member_breaks"][0])
        paint()
        line = after[0]
        point = screen(tuple((a + b) / 2 for a, b in zip(*line)))
        QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=point.toPoint())
        move(point + QPointF(-70, 20))
        QTest.keyClick(sheet, Qt.Key.Key_Escape)
        assert view["member_breaks"][0] == original
        assert sheet._drag_member_break is None
    finally:
        sheet.close()
        window.close()
