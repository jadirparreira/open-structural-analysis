"""Weld marks use paper dimensions and remain local to their selected view."""
import json
import os
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from osa.model import StructuralModel
from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.weld_symbols import DEFAULTS, WeldTool, draw_weld, symbol_sides, weld_layout


@pytest.mark.parametrize("side,expected", [("arrow", (1,)), ("other", (-1,)), ("both", (1, -1))])
def test_sides_follow_fakury_single_reference_line(side, expected):
    assert symbol_sides({"side": side}) == expected


@pytest.fixture
def scene():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(1400, 950)
    window.model = StructuralModel()
    window._command_mode = None
    window.command_session = SimpleNamespace(cancel=lambda: None)
    window.cancel_member_placement = lambda: window.tool.finish()
    sheet = ProjectSheetWorkspace(window)
    sheet.resize(1100, 800)
    sheet.move(0, 90)
    tool = WeldTool(window, sheet)
    window.project_sheet_workspace = sheet
    window.tool = sheet.weld_tool = tool
    corners = ((0, -.1), (1, -.1), (1, .1), (0, .1))
    view = dict(name="Detalhe", segments=tuple(zip(corners, (*corners[1:], corners[0]))),
                segment_owners=("bar:B",) * 4, scale_denominator=5.,
                projection={"plane": "XY", "coordinate": 0},
                component_detail_group={"id": "detail-A", "title": "DET A", "view_count": 1})
    sheet.set_sheet_views([view])
    window.show()
    app.processEvents()
    def paint():
        sheet.update()
        app.processEvents()
        return sheet.grab().toImage()
    paint()
    yield app, window, sheet, tool, view, paint
    tool.finish()
    window.close()
    app.processEvents()


def test_select_view_then_face_place_edit_drag_delete_and_cancel(scene):
    app, window, sheet, tool, view, paint = scene
    changes = []
    sheet.layout_changed.connect(lambda: changes.append(True))
    point = sheet._screen_point(0, (.8, 0))
    tool.start()
    assert tool.panel.isVisible()
    assert tool.panel.x() > window.width() / 2
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert tool.view_index == 0
    assert not view.get("weld_marks")
    QTest.keyClick(tool.panel.fields["tail"], Qt.Key.Key_Return)
    assert tool.active and not view.get("weld_marks")
    # A face point, with no requirement to hit an edge.
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert len(view["weld_marks"]) == 1
    mark = view["weld_marks"][0]
    assert mark["point"] == pytest.approx(sheet._projected_point_at(0, point.toPoint()))
    assert changes
    QTest.keyClick(tool.panel.fields["tail"], Qt.Key.Key_Escape)
    assert not tool.active and not tool.panel.isVisible()
    paint()
    anchor = sheet._screen_point(0, mark["point"])
    elbow = anchor + QPointF(*mark["offset_mm"]) * sheet._sheet_pixels_per_mm
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=elbow.toPoint())
    assert tool.selected == (0, 0)
    tool.panel.fields["size"].setValue(8)
    assert mark["size"] == 8
    paint()
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=elbow.toPoint())
    QTest.mouseMove(sheet, (elbow + QPointF(20, 10)).toPoint())
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=(elbow + QPointF(20, 10)).toPoint())
    assert mark["offset_mm"][0] > 18
    assert sheet._screen_point(0, mark["point"]) == anchor
    assert json.loads(json.dumps(view))["weld_marks"][0]["size"] == 8
    QTest.keyClick(sheet, Qt.Key.Key_Delete)
    assert view["weld_marks"] == []


def test_cancel_before_view_and_outside_click_and_reset(scene):
    app, window, sheet, tool, view, paint = scene
    tool.start()
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert not tool.active and not view.get("weld_marks")
    tool.start()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))
    assert tool.view_index is None
    point = sheet._screen_point(0, (.5, 0)).toPoint()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))
    assert not view.get("weld_marks")
    sheet.set_sheet_views([])
    assert not tool.active and not tool.hits and not tool.panel.isVisible()


@pytest.mark.parametrize("kind", ["fillet", "square", "bevel", "v"])
def test_symbol_rendering_and_fixed_paper_size(kind):
    app = QApplication.instance() or QApplication([])
    image = QImage(700, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    mark = dict(DEFAULTS, kind=kind, side="both", field=True, all_around=True,
                tail="E7018", length=50, pitch=150, contour="convex")
    hit = draw_weld(painter, QPointF(30, 220), mark, 4)
    painter.end()
    assert hit.contains(QPointF(30, 220))
    assert hit.boundingRect().width() > 200
    assert hit.boundingRect().height() > 70


@pytest.mark.parametrize("kind,geometry", [
    ("fillet", ((0, 0, 0, 4), (0, 4, 4, 0))),
    ("square", ((0, 0, 0, 4), (4, 0, 4, 4))),
    ("bevel", ((0, 0, 0, 4), (0, 0, 6, 4))),
    ("v", ((3, 0, 0, 4), (3, 0, 6, 4))),
])
@pytest.mark.parametrize("side", ["arrow", "other", "both"])
@pytest.mark.parametrize("direction", ["left", "right"])
def test_basic_symbols_match_fakury_1045_1046_and_table_104(kind, geometry, side, direction):
    from PySide6.QtGui import QPainterPath
    app = QApplication.instance() or QApplication([])
    class Spy:
        def __init__(self, painter):
            self.painter, self.paths = painter, []
        def __getattr__(self, name):
            return getattr(self.painter, name)
        def drawPath(self, path):
            self.paths.append(QPainterPath(path))
            self.painter.drawPath(path)
    image = QImage(500, 300, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    spy = Spy(painter)
    mark = dict(DEFAULTS, kind=kind, side=side, direction=direction)
    layout = weld_layout(mark, painter.font())
    draw_weld(spy, QPointF(100, 200), mark, 2)
    painter.end()
    symbol = spy.paths[1]
    left = 136 - (layout['length_mm'] * 2 if direction == 'left' else 0)
    origin_x, origin_y = left + layout['symbol_x_mm'] * 2, 168
    expected = [(origin_x + x1*2, origin_y + y1*2*sign,
                 origin_x + x2*2, origin_y + y2*2*sign)
                for sign in symbol_sides(mark) for x1,y1,x2,y2 in geometry]
    actual = [(symbol.elementAt(i).x, symbol.elementAt(i).y,
               symbol.elementAt(i+1).x, symbol.elementAt(i+1).y)
              for i in range(0, symbol.elementCount(), 2)]
    assert len(actual) == len(expected)
    for line, wanted in zip(actual, expected):
        assert line == pytest.approx(wanted)


def test_drag_reuses_complete_context_and_rebuilds_on_release(scene, monkeypatch):
    import numpy as np
    app, window, sheet, tool, view, paint = scene
    view["weld_marks"] = [dict(DEFAULTS, point=(.8, 0), offset_mm=(18, -16))]
    paint()
    anchor = sheet._screen_point(0, (.8, 0))
    elbow = anchor + QPointF(18, -16) * sheet._sheet_pixels_per_mm
    renders = []
    original = sheet._draw_sheet_views
    def draw(*args):
        renders.append(True)
        return original(*args)
    monkeypatch.setattr(sheet, "_draw_sheet_views", draw)
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=elbow.toPoint())
    app.processEvents()
    assert tool._drag_background is not None
    before = sheet.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    old_bounds = tool.hits[0, 0].boundingRect()
    transforms = dict(sheet._view_draw_data)
    context_frames = dict(sheet._view_hit_rects)
    count = len(renders)
    for distance in (10, 20, 40, 65):
        QTest.mouseMove(sheet, (elbow + QPointF(distance, 25)).toPoint())
        app.processEvents()
    after = sheet.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert len(renders) == count, "Dragging must not traverse/repaint model views"
    assert sheet._view_draw_data == transforms
    assert sheet._view_hit_rects == context_frames
    changed_area = old_bounds.united(tool.hits[0, 0].boundingRect()).adjusted(-8, -8, 8, 8).toAlignedRect()
    mask = np.ones((after.height(), after.width()), dtype=bool)
    area = changed_area.intersected(after.rect())
    mask[area.top():area.bottom()+1, area.left():area.right()+1] = False
    def pixels(image):
        return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4)
    assert np.array_equal(pixels(before)[mask], pixels(after)[mask]), "All context pixels outside the weld must stay intact"
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=(elbow + QPointF(65, 25)).toPoint())
    app.processEvents()
    assert tool._drag_background is None
    assert len(renders) > count
    assert view["weld_marks"][0]["point"] == (.8, 0)


def test_only_weld_panel_visible_with_fixed_height_and_clean_content(scene):
    from PySide6.QtWidgets import QFrame, QLabel
    app, window, sheet, tool, view, paint = scene
    other = QFrame(window)
    other.setObjectName("propertyPanel")
    # Emulate the view inspector appearing in response to the selection signal.
    sheet.selection_changed.connect(lambda *_: other.show())
    other.show()
    tool.start()
    assert not other.isVisible()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.7, 0)).toPoint())
    assert not other.isVisible() and tool.panel.isVisible()
    assert [label.text() for label in tool.panel.findChildren(QLabel) if label.objectName() == "propertyTitle"] == ["Solda"]
    labels = " ".join(label.text() for label in tool.panel.findChildren(QLabel))
    assert "Clique" not in labels and "Convenção" not in labels and "Passo 0" not in labels
    height = tool.panel.height()
    window.resize(1280, 760)
    app.processEvents()
    assert tool.panel.height() == height
    assert tool.panel.x() > window.width() / 2
    assert tool.panel.geometry().bottom() < window.height() - 70
    assert isinstance(tool.panel.preview, QFrame)


def test_escape_rolls_back_cached_drag_and_zoom_invalidates_it(scene):
    app, window, sheet, tool, view, paint = scene
    mark = dict(DEFAULTS, point=(.8, 0), offset_mm=(18, -16))
    view["weld_marks"] = [mark]
    paint()
    elbow = sheet._screen_point(0, mark["point"]) + QPointF(18, -16) * sheet._sheet_pixels_per_mm
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=elbow.toPoint())
    QTest.mouseMove(sheet, (elbow + QPointF(40, 20)).toPoint())
    assert mark["offset_mm"] != (18, -16)
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert tool._drag_background is None and mark["offset_mm"] == (18, -16)
    paint()
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=elbow.toPoint())
    assert tool._drag_background is not None
    sheet._zoom_factor *= 1.2
    paint()
    assert tool._drag_background is None
    assert sheet._view_draw_data[0][4] > 0
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=elbow.toPoint())


@pytest.mark.parametrize("scale", [.8, 2., 5.])
def test_all_weld_texts_are_3mm_and_lines_use_standard_cosmetic_width(scale):
    app = QApplication.instance() or QApplication([])
    class PainterSpy:
        def __init__(self, painter):
            self.painter, self.fonts, self.pens = painter, [], []
        def __getattr__(self, name):
            return getattr(self.painter, name)
        def setFont(self, font):
            self.fonts.append(font.pixelSize())
            self.painter.setFont(font)
        def setPen(self, pen):
            self.pens.append((pen.widthF(), pen.isCosmetic()))
            self.painter.setPen(pen)
    image = QImage(700, 400, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    spy = PainterSpy(painter)
    draw_weld(spy, QPointF(30, 220), dict(DEFAULTS, kind="v", root=2, tail="E7018"), scale)
    painter.end()
    assert spy.fonts and set(spy.fonts) == {max(1, round(3 * scale))}
    assert spy.pens and set(spy.pens) == {(1.0, True)}


@pytest.mark.parametrize("direction", ["right", "left"])
def test_preview_is_centered_even_with_long_tail(scene, direction):
    import numpy as np
    app, window, sheet, tool, view, paint = scene
    tool.start()
    tool.panel.fields["direction"].setCurrentIndex(tool.panel.fields["direction"].findData(direction))
    tool.panel.fields["tail"].setText("SMAW E7018 - OBSERVAÇÃO DA JUNTA")
    app.processEvents()
    preview = tool.panel.preview
    image = preview.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4)
    ys, xs = np.where(np.min(pixels[:, :, :3], axis=2) < 128)
    assert abs((xs.min() + xs.max()) / 2 - preview.width() / 2) < 4
    assert abs((ys.min() + ys.max()) / 2 - preview.height() / 2) < 4
    assert xs.min() > 6 and xs.max() < preview.width() - 6


@pytest.mark.parametrize("kind,point", [("endpoint", (1., .1)), ("center", (.5, -.1)), ("intersection", (.65, .03))])
def test_launch_snaps_hover_and_click_to_visible_view_linework(scene, kind, point):
    app, window, sheet, tool, view, paint = scene
    if kind == "intersection":
        view["segments"] += (((.65, -.1), (.65, .1)), ((.2, .03), (.9, .03)))
        view["segment_owners"] += ("bar:C", "bar:D")
        sheet.invalidate_view_geometry(0)
    paint()
    tool.start()
    # First click still only selects the view.
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.4, 0)).toPoint())
    assert not view.get("weld_marks")
    target = sheet._screen_point(0, point)
    cursor = target + QPointF(3, -2)
    QTest.mouseMove(sheet, cursor.toPoint())
    app.processEvents()
    assert tool.snap is not None and tool.snap[4] == kind
    assert tool.snap[2] == pytest.approx(point)
    assert tool.snap_indicator.isVisible()
    assert abs(tool.snap_indicator.geometry().center().x() - target.x()) < 2
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=cursor.toPoint())
    assert view["weld_marks"][0]["point"] == pytest.approx(point)
    assert not tool.snap_indicator.isVisible()
    # Recompute at the click itself, without relying on previous mouse moves.
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=(target + QPointF(-2, 1)).toPoint())
    assert view["weld_marks"][1]["point"] == pytest.approx(point)
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert tool.snap is None and not tool.snap_indicator.isVisible()


def test_launch_snaps_follow_preferences_and_ignore_hidden_elements(scene):
    app, window, sheet, tool, view, paint = scene
    window.scene = SimpleNamespace(snap_type_enabled=lambda kind: kind != "center")
    paint()
    tool.start()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.4, 0)).toPoint())
    cursor = (sheet._screen_point(0, (.5, -.1)) + QPointF(3, -2)).toPoint()
    QTest.mouseMove(sheet, cursor)
    app.processEvents()
    assert tool.snap is None
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=cursor)
    assert view["weld_marks"][0]["point"] == pytest.approx(sheet._projected_point_at(0, cursor))
    view["hidden_owners"] = ["bar:B"]
    sheet.invalidate_view_geometry(0)
    paint()
    cursor = (sheet._screen_point(0, (1., .1)) + QPointF(-2, 2)).toPoint()
    QTest.mouseMove(sheet, cursor)
    assert tool.snap is None and not tool.snap_indicator.isVisible()


def test_snap_hover_does_not_repaint_model_context_and_clears_on_leave(scene, monkeypatch):
    app, window, sheet, tool, view, paint = scene
    tool.start()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.4, 0)).toPoint())
    app.processEvents()
    renders = []
    original = sheet._draw_sheet_views
    def draw(*args):
        renders.append(True)
        return original(*args)
    monkeypatch.setattr(sheet, "_draw_sheet_views", draw)
    for point in ((.5, -.1), (1, .1), (.5, .1)):
        QTest.mouseMove(sheet, (sheet._screen_point(0, point) + QPointF(2, -2)).toPoint())
        app.processEvents()
        assert tool.snap_indicator.isVisible()
    assert not renders
    QApplication.sendEvent(sheet, QEvent(QEvent.Type.Leave))
    app.processEvents()
    assert tool.snap is None and not tool.snap_indicator.isVisible()


def test_weld_snap_is_restricted_to_selected_view(scene):
    import copy
    app, window, sheet, tool, view, paint = scene
    other = copy.deepcopy(view)
    view["position"], other["position"] = (.2, .5), (.8, .5)
    view["scale_denominator"] = other["scale_denominator"] = 10.
    other.pop("component_detail_group")
    sheet.set_sheet_views([view, other])
    paint()
    tool.start()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.4, 0)).toPoint())
    assert tool.view_index == 0
    target = sheet._screen_point(1, (.5, -.1))
    QTest.mouseMove(sheet, target.toPoint())
    app.processEvents()
    assert tool.snap is None and not tool.snap_indicator.isVisible()
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=target.toPoint())
    assert not view.get("weld_marks") and not other.get("weld_marks")


def test_detail_group_frame_keeps_paper_bounds_during_zoom_pan_and_resize(scene):
    app, window, sheet, tool, view, paint = scene
    from PySide6.QtCore import QRectF
    def paper_frame():
        bounds = sheet._component_group_hit_rects['detail-A']
        area, scale = sheet._drawing_area, sheet._sheet_pixels_per_mm
        return ((bounds.x()-area.x())/scale, (bounds.y()-area.y())/scale,
                bounds.width()/scale, bounds.height()/scale)
    expected = paper_frame()
    for zoom in (1.75, .65, 2.1, 1.):
        sheet._zoom_factor = zoom
        sheet._pan_offset = QPointF(23 * zoom, -11 * zoom)
        sheet._navigating = True
        paint()
        assert paper_frame() == pytest.approx(expected)
        sheet._finish_navigation()
        paint()
        assert paper_frame() == pytest.approx(expected)
    sheet.resize(1030, 740)
    paint()
    assert paper_frame() == pytest.approx(expected)
    before = QRectF(sheet._component_group_hit_rects['detail-A'])
    view['component_detail_group']['label_position'] = (.5, .28)
    paint()
    assert sheet._component_group_hit_rects['detail-A'] != before
    assert sheet._component_group_hit_rects['detail-A'].contains(sheet._component_group_title_hit_rects['detail-A'])


def test_weld_project_colors_and_text_height_are_independent(scene):
    app, window, sheet, tool, view, paint = scene
    settings = dict(weld_line_color='#ff0000', weld_symbol_color='#00ff00',
                    weld_text_color='#0000ff', weld_text_height_mm=5.)
    class Spy:
        def __init__(self, painter):
            self.painter, self.colors, self.fonts = painter, [], []
        def __getattr__(self, key):
            return getattr(self.painter, key)
        def setPen(self, pen):
            self.colors.append(pen.color().name())
            self.painter.setPen(pen)
        def setFont(self, font):
            self.fonts.append(font.pixelSize())
            self.painter.setFont(font)
    image = QImage(500, 300, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    spy = Spy(painter)
    draw_weld(spy, QPointF(20, 200), dict(DEFAULTS, tail='E7018'), 3, settings=settings)
    painter.end()
    assert spy.colors == ['#ff0000', '#00ff00', '#0000ff']
    assert set(spy.fonts) == {15}
    sheet._project_settings.update(settings)
    view['weld_marks'] = [dict(DEFAULTS, point=(.5, 0), offset_mm=(18, -16))]
    paint()
    assert tool.panel.project_settings()['weld_text_height_mm'] == 5
    # Defaults also apply to old marks, which contain no style properties.
    from osa.ui.project_sheet import default_project_settings
    defaults = default_project_settings()
    assert (defaults['weld_line_color'], defaults['weld_symbol_color'], defaults['weld_text_color']) == ('#ff0000', '#000000', '#000000')
    assert defaults['weld_text_height_mm'] == 3.


def test_weld_settings_section_saves_and_restores_project_preferences(scene):
    from PySide6.QtWidgets import QListWidget
    from osa.ui.dialogs import ProjectSheetSettingsDialog
    from osa.ui.project_sheet import default_project_settings, default_project_sheet_settings
    app, window, sheet, tool, view, paint = scene
    dialog = ProjectSheetSettingsDialog('Sheet', default_project_sheet_settings('Sheet'), default_project_settings(), 1)
    navigation = dialog.findChild(QListWidget)
    assert navigation.findItems('Solda', Qt.MatchFlag.MatchExactly)
    assert dialog._weld_color_values == dict(weld_symbol_color='#000000', weld_line_color='#ff0000', weld_text_color='#000000')
    dialog._weld_color_values.update(weld_line_color='#880000', weld_text_color='#123456', weld_symbol_color='#654321')
    dialog.weld_text_height_spin.setValue(4.5)
    dialog._save()
    restored = ProjectSheetSettingsDialog('Sheet', dialog.result_settings, dialog.result_project_settings, 1)
    assert restored.weld_text_height_spin.value() == 4.5
    assert restored._weld_color_values == dialog._weld_color_values
    restored.reject()


@pytest.mark.parametrize('select_first', [False, True])
def test_pan_during_weld_launch_keeps_flow_and_snaps(scene, select_first):
    app, window, sheet, tool, view, paint = scene
    tool.start()
    if select_first:
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.4, 0)).toPoint())
    old_pan = QPointF(sheet._pan_offset)
    start = QPoint(420, 300)
    QTest.mousePress(sheet, Qt.MouseButton.MiddleButton, pos=start)
    QTest.mouseMove(sheet, start + QPoint(55, 32))
    app.processEvents()
    assert sheet._pan_offset == old_pan + QPointF(55, 32)
    QTest.mouseRelease(sheet, Qt.MouseButton.MiddleButton, pos=start + QPoint(55, 32))
    app.processEvents()
    assert sheet._pan_anchor is None and tool.active
    assert not view.get('weld_marks')
    if not select_first:
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._screen_point(0, (.4, 0)).toPoint())
    target = sheet._screen_point(0, (.5, -.1))
    # Force a real hover after synthetic button-held movement in the offscreen backend.
    QTest.mouseMove(sheet, QPoint(40, 40))
    tool._hover_snap(target + QPointF(2, -2))
    app.processEvents()
    assert tool.snap is not None and tool.snap[4] == 'center'
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=(target + QPointF(2, -2)).toPoint())
    assert view['weld_marks'][0]['point'] == pytest.approx((.5, -.1))
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert not tool.active


def test_reference_line_is_compact_adaptive_and_stable_across_zoom():
    from PySide6.QtGui import QFont
    app = QApplication.instance() or QApplication([])
    simple = weld_layout(DEFAULTS, QFont())
    assert simple['length_mm'] == 18
    labeled = weld_layout(dict(DEFAULTS, length=1500, pitch=2500), QFont())
    assert labeled['length_mm'] > simple['length_mm']
    # Windows font metrics are a little wider than the Linux CI font; the
    # notation must still fit in a compact reference line.
    assert labeled['length_mm'] < 45
    assert labeled['length'] == '1500-2500'
    assert weld_layout(dict(DEFAULTS, size=6.35), QFont())['size'] == '6,35'
    # Layout uses fixed paper metrics, not the current zoom's screen font size.
    for size in (5, 11, 35):
        font = QFont(); font.setPixelSize(size)
        assert weld_layout(DEFAULTS, font) == simple


@pytest.mark.parametrize('kind', ['fillet', 'v'])
@pytest.mark.parametrize('contour', ['flat', 'convex', 'concave'])
@pytest.mark.parametrize('side', ['arrow', 'other'])
def test_contours_follow_weld_face_and_correct_convexity(kind, contour, side):
    from PySide6.QtGui import QPainterPath
    app = QApplication.instance() or QApplication([])
    class Spy:
        def __init__(self, painter): self.painter, self.paths = painter, []
        def __getattr__(self, name): return getattr(self.painter, name)
        def drawPath(self, path): self.paths.append(QPainterPath(path)); self.painter.drawPath(path)
    image = QImage(500, 300, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    spy = Spy(painter)
    draw_weld(spy, QPointF(100, 200), dict(DEFAULTS, kind=kind, contour=contour, side=side), 2)
    painter.end()
    path = spy.paths[1]
    offset = 4  # Four move/line elements form each basic weld symbol.
    first = QPointF(path.elementAt(offset).x, path.elementAt(offset).y)
    last_index = offset + (1 if contour == 'flat' else 3)
    last = QPointF(path.elementAt(last_index).x, path.elementAt(last_index).y)
    sign = 1 if side == 'arrow' else -1
    assert last.x() > first.x()
    if kind == 'fillet':
        assert last.y() - first.y() == pytest.approx(-sign * (last.x() - first.x()))
    else:
        assert last.y() == pytest.approx(first.y())
    if contour != 'flat':
        # Cubic Bezier midpoint relative to the straight chord has the requested sign.
        p1 = QPointF(path.elementAt(offset+1).x, path.elementAt(offset+1).y)
        p2 = QPointF(path.elementAt(offset+2).x, path.elementAt(offset+2).y)
        midpoint = (first + p1*3 + p2*3 + last) / 8
        outward = QPointF(1, sign) if kind == 'fillet' else QPointF(0, sign)
        displacement = midpoint - (first + last)/2
        projection = displacement.x()*outward.x() + displacement.y()*outward.y()
        assert projection * (1 if contour == 'convex' else -1) > 0


def test_drag_arrow_tip_snaps_and_keeps_reference_line_fixed_and_escape_restores(scene):
    app, window, sheet, tool, view, paint = scene
    mark = dict(DEFAULTS, point=(.8, 0), offset_mm=(18, -16))
    view['weld_marks'] = [mark]
    paint()
    original = tuple(mark['point'])
    anchor = sheet._screen_point(0, original)
    elbow = anchor + QPointF(*mark['offset_mm']) * sheet._sheet_pixels_per_mm
    target = sheet._screen_point(0, (1., .1))
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=anchor.toPoint())
    assert tool.drag[3] and tool._drag_background is not None
    QTest.mouseMove(sheet, (target+QPointF(1, 1)).toPoint())
    assert mark['point'] == pytest.approx((1., .1))
    actual_elbow = sheet._screen_point(0, mark['point']) + QPointF(*mark['offset_mm']) * sheet._sheet_pixels_per_mm
    assert actual_elbow.x() == pytest.approx(elbow.x())
    assert actual_elbow.y() == pytest.approx(elbow.y())
    assert tool._drag_background is not None
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert mark['point'] == original and mark['offset_mm'] == (18, -16)
    paint()
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=anchor.toPoint())
    QTest.mouseMove(sheet, target.toPoint())
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=target.toPoint())
    assert mark['point'] == pytest.approx((1., .1))
    assert tool.drag is None and tool._drag_background is None
