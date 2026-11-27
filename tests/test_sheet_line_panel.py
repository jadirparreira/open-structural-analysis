"""Individual drawing-line appearance on sheets and inserted views."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.sheet_line_panel import LINE_STYLES, ProjectSheetLinePanel


@pytest.mark.parametrize("view_index", [None, 0])
@pytest.mark.parametrize("style", ["continuous", "dash", "dash_dot"])
def test_line_inspector_updates_and_renders_appearance(monkeypatch, view_index, style):
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(1400, 1000)
    sheet = ProjectSheetWorkspace(window)
    sheet.resize(1000, 800)
    first = {"kind": "line", "points": ((.1, .1), (.3, .3))}
    second = {"kind": "line", "points": ((.2, .1), (.4, .3))}
    sheet.set_sheet_views([{"sheet_lines": [first, second]}] if view_index == 0 else [])
    if view_index is None:
        sheet.set_sheet_annotations([], [first, second])
    key = (view_index if view_index is not None else -1, 0)
    sheet._selected_sheet_line = key
    panel = ProjectSheetLinePanel(window, sheet)
    panel.show_for(key)
    changed = []
    sheet.layout_changed.connect(lambda: changed.append(True))
    try:
        assert panel.style_input.currentData() == "continuous"
        assert panel.color_button.text() == ""
        assert panel.color_button.width() == panel.color_button.height() == 34
        panel.style_input.setCurrentIndex(panel.style_input.findData(style))
        def choose_color(picker):
            picker._set_color("#f40000")
            picker._custom_slot_clicked(0)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr("osa.ui.dialogs._DimensionColorDialog.exec", choose_color)
        panel.color_button.click()
        assert first.get("line_style", "continuous") == style
        assert first["color"] == "#f40000"
        assert sheet._project_settings["sheet_line_custom_colors"][0] == "#f40000"
        assert "color" not in second and "line_style" not in second
        assert "identity" not in first
        assert changed
        restored = json.loads(json.dumps(first))
        sheet._view_draw_data[0] = (0., 0., 200., 200., 1000.)
        sheet._drawing_area.setRect(0., 0., 800., 600.)
        rendered = []
        monkeypatch.setattr(sheet, "_draw_annotation_geometry", lambda painter, *args: rendered.append(
            (painter.pen().color().name(), painter.pen().style())))
        image = QImage(1000, 800, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            sheet._draw_sheet_line(painter, restored, view_index, 0)
            sheet._selected_sheet_line = None
            sheet._draw_sheet_line(painter, restored, view_index, 0)
        finally:
            painter.end()
        assert rendered == [("#f40000", LINE_STYLES[style])] * 2
        sheet._selected_sheet_line = key
        assert sheet.delete_selected_sheet_line()
        assert sheet._line_annotation_collection(view_index) == [second]
    finally:
        window.close()
        app.processEvents()


def test_cancel_color_and_deselect_do_not_change_line(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    sheet = ProjectSheetWorkspace(window)
    line = {"kind": "line", "points": ((.1, .1), (.3, .3))}
    sheet.set_sheet_annotations([], [line])
    sheet._selected_sheet_line = (-1, 0)
    panel = ProjectSheetLinePanel(window, sheet)
    panel.show_for((-1, 0))
    monkeypatch.setattr("osa.ui.dialogs._DimensionColorDialog.exec", lambda self: QDialog.DialogCode.Rejected)
    panel.color_button.click()
    assert "color" not in line
    sheet._selected_sheet_line = None
    panel.style_input.setCurrentIndex(1)
    assert "line_style" not in line
    panel.show_for(None)
    assert panel.isHidden()
    window.close()
    app.processEvents()
