"""Graphical commands consume the same selection as Ctrl-click and rectangles."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog

from osa.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def application_window(qt_app):
    window = MainWindow()
    yield window
    window.scene.plotter.close()
    window.hide()
    window.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def window(application_window):
    window = application_window
    window._reset_model_state()
    for index in range(1, 5):
        window.model.add_node(f"N{index}", index - 1, 0, 0)
    for index in range(1, 4):
        window.model.add_bar(f"B{index}", f"N{index}", f"N{index + 1}")
    window.selected_action_name = "Caso"
    window.set_member_direction_normalization_enabled(False)
    window.scene.render_model(window.model)
    return window


def select(window, *targets):
    window.scene.set_selection_highlight(targets)
    window.scene.selection_changed.emit(tuple(targets))


def ctrl_click(window, monkeypatch, target):
    scene = window.scene
    monkeypatch.setattr(scene._orientation_widget, "is_pointer_over", lambda *_: False)
    monkeypatch.setattr(scene, "_pick", lambda: target)
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        event = QMouseEvent(
            kind, QPointF(100, 100), QPointF(100, 100), QPointF(100, 100),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
        )
        assert scene.eventFilter(scene.plotter, event)


def enter(window):
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    assert window.scene.eventFilter(window.scene.plotter, event)


def click(window, target):
    window.scene.set_selection_highlight((target,))
    window.scene.element_clicked.emit(*target, window.scene.element_center(*target))


def test_copy_keeps_preselection_and_ctrl_toggles_then_copies_twice(window, monkeypatch):
    select(window, ("node", "N4"), ("bar", "B1"), ("bar", "B2"))
    window.start_copy_elements()
    assert window._copy_elements_selection == [("node", "N4"), ("bar", "B1"), ("bar", "B2")]
    ctrl_click(window, monkeypatch, ("bar", "B2"))
    assert window.selected_elements == [("node", "N4"), ("bar", "B1")]
    ctrl_click(window, monkeypatch, ("bar", "B2"))
    enter(window)
    assert window._command_mode == "copy_elements_reference_placement"
    window._handle_copy_placement_point((0, 0, 0))
    window._handle_copy_placement_point((0, 5, 0))
    assert len(window.model.bars) == 5
    assert len(window.model.nodes) == 8
    window._handle_copy_placement_point((0, 5, 0))
    assert len(window.model.bars) == 5
    window._handle_copy_placement_point((0, 10, 0))
    assert len(window.model.bars) == 7
    assert window._copy_elements_selection == [("node", "N4"), ("bar", "B1"), ("bar", "B2")]
    window.cancel_member_placement()
    assert window._command_mode is None
    assert not window.scene._placement_active()


def test_copy_normal_click_replaces_selection_and_empty_click_clears(window):
    window.start_copy_elements()
    click(window, ("bar", "B1"))
    click(window, ("bar", "B2"))
    assert window._copy_elements_selection == [("bar", "B2")]
    window.scene.empty_clicked.emit()
    enter(window)
    assert window._copy_elements_selection == []
    assert window.scene._selected_elements == ()
    assert window._command_mode == "copy_elements_selection"


def test_copy_accepts_ctrl_rectangle(window, monkeypatch):
    window.start_copy_elements()
    scene = window.scene
    monkeypatch.setattr(scene._orientation_widget, "is_pointer_over", lambda *_: False)
    targets = (("bar", "B1"), ("bar", "B2"), ("node", "N4"))
    monkeypatch.setattr(scene, "_elements_in_rectangle", lambda *_: targets)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10), QPointF(10, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(100, 100), QPointF(100, 100), QPointF(100, 100),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
    )
    assert scene.eventFilter(scene.plotter, press)
    assert scene.eventFilter(scene.plotter, release)
    assert window.selected_elements == list(targets)
    enter(window)
    assert window._command_mode == "copy_elements_reference_placement"


@pytest.mark.parametrize("preselected", [False, True])
def test_reverse_applies_to_every_selected_member(window, monkeypatch, preselected):
    if preselected:
        select(window, ("bar", "B1"), ("bar", "B2"))
    window.start_reverse_member()
    if not preselected:
        ctrl_click(window, monkeypatch, ("bar", "B1"))
        ctrl_click(window, monkeypatch, ("bar", "B2"))
        assert window.model.bars["B1"].start_node == "N1"
        enter(window)
    assert window.model.bars["B1"].start_node == "N2"
    assert window.model.bars["B2"].start_node == "N3"
    assert window.model.bars["B3"].start_node == "N3"


@pytest.mark.parametrize("preselected", [False, True])
def test_join_accepts_two_selected_members(window, monkeypatch, preselected):
    if preselected:
        select(window, ("bar", "B1"), ("bar", "B2"))
    window.start_join_members()
    if not preselected:
        ctrl_click(window, monkeypatch, ("bar", "B1"))
        ctrl_click(window, monkeypatch, ("bar", "B2"))
        enter(window)
    assert tuple(window.model.bars) == ("B1", "B3")
    assert (window.model.bars["B1"].start_node, window.model.bars["B1"].end_node) == ("N1", "N3")


@pytest.mark.parametrize("preselected", [False, True])
def test_join_accepts_multiple_members_in_any_selection_order(window, monkeypatch, preselected):
    targets = (("bar", "B2"), ("bar", "B3"), ("bar", "B1"))
    if preselected:
        select(window, *targets)
    window.start_join_members()
    if not preselected:
        for target in targets:
            ctrl_click(window, monkeypatch, target)
        enter(window)
    assert tuple(window.model.bars) == ("B2",)
    assert tuple(window.model.nodes) == ("N1", "N4")
    assert (window.model.bars["B2"].start_node, window.model.bars["B2"].end_node) == ("N1", "N4")


def test_join_rejects_noncollinear_group_without_partial_changes(window, monkeypatch):
    window.model.update_node("N4", 3, 1, 0)
    window.scene.render_model(window.model)
    before = dict(window.model.bars), dict(window.model.nodes), window.model.revision
    window.start_join_members()
    for name in ("B1", "B2", "B3"):
        ctrl_click(window, monkeypatch, ("bar", name))
    enter(window)
    assert (window.model.bars, window.model.nodes, window.model.revision) == before
    assert len(window.model.bars) == 3


@pytest.mark.parametrize("preselected", [False, True])
def test_split_requires_exactly_one_selected_member(window, monkeypatch, preselected):
    opened = []

    def open_member(name):
        opened.append(name)
        monkeypatch.setattr(window.split_member_dialog, "split_configuration", lambda: (name, (0.5, 0.5)))
        window.apply_split_member()

    monkeypatch.setattr(window.split_member_dialog, "open_for_member", open_member)
    if preselected:
        select(window, ("bar", "B1"), ("bar", "B2"))
    window.start_split_member()
    if not preselected:
        ctrl_click(window, monkeypatch, ("bar", "B1"))
        ctrl_click(window, monkeypatch, ("bar", "B2"))
    enter(window)
    assert not opened
    assert len(window.model.bars) == 3
    ctrl_click(window, monkeypatch, ("bar", "B2"))
    enter(window)
    assert opened == ["B1"]
    assert len(window.model.bars) == 4


@pytest.mark.parametrize("preselected", [False, True])
def test_copy_properties_has_one_reference_and_multiple_destinations(window, monkeypatch, preselected):
    window.model.update_member_color("B1", "#0969da")
    monkeypatch.setattr(window.member_property_copy_panel, "selected_properties", lambda: frozenset({"color"}))
    if preselected:
        select(window, ("bar", "B1"), ("bar", "B2"), ("bar", "B3"))
    window.start_copy_member_properties()
    if not preselected:
        click(window, ("bar", "B1"))
        ctrl_click(window, monkeypatch, ("bar", "B2"))
        ctrl_click(window, monkeypatch, ("bar", "B3"))
    enter(window)
    assert {member.color for member in window.model.bars.values()} == {"#0969da"}
    assert window._copy_properties_reference == "B1"
    assert window.selected_elements == []


@pytest.mark.parametrize("target_kind", ["node", "bar"])
@pytest.mark.parametrize("preselected", [False, True])
def test_action_applies_once_to_all_matching_targets(window, monkeypatch, target_kind, preselected):
    names = ("N1", "N2") if target_kind == "node" else ("B1", "B2")
    launch = (target_kind, "global", {"FZ": (-5.0,)})
    dialog = SimpleNamespace(
        exec=lambda: QDialog.DialogCode.Accepted,
        launch_data=lambda: launch,
        rect=lambda: QRect(0, 0, 100, 100), move=lambda *_: None,
    )
    monkeypatch.setattr("osa.ui.main_window.ActionDialog", lambda *_: dialog)
    if preselected:
        select(window, *((target_kind, name) for name in names))
    window.start_load_command()
    if not preselected:
        for name in names:
            ctrl_click(window, monkeypatch, (target_kind, name))
        enter(window)
    actions = tuple(window.model.actions.values())
    assert len(actions) == 2
    assert {action.target for action in actions} == set(names)
    enter(window)
    assert len(window.model.actions) == 2


def test_delete_removes_the_full_selection_members_before_nodes(window):
    select(window, ("node", "N1"), ("bar", "B1"), ("bar", "B2"), ("node", "N2"))
    window.scene.plotter.setFocus()
    window.delete_selected()
    assert tuple(window.model.bars) == ("B3",)
    assert tuple(window.model.nodes) == ("N3", "N4")


def test_scene_hide_and_reveal_accept_ctrl_selection(window, monkeypatch):
    window.model.add_scene_view("Vista")
    window.scene.render_model(window.model)
    window.start_scene_hide_selection()
    ctrl_click(window, monkeypatch, ("bar", "B1"))
    ctrl_click(window, monkeypatch, ("bar", "B2"))
    enter(window)
    assert window.model.scene_views["Vista"] == {"B1", "B2"}
    window.start_scene_reveal_selection()
    ctrl_click(window, monkeypatch, ("bar", "B1"))
    ctrl_click(window, monkeypatch, ("bar", "B2"))
    ctrl_click(window, monkeypatch, ("bar", "B2"))
    enter(window)
    assert window.model.scene_views["Vista"] == {"B2"}
    window.show_all_scene_members()
    assert window.model.scene_views["Vista"] == set()


def test_escape_cancels_pending_multi_selection_without_model_changes(window, monkeypatch):
    revision = window.model.revision
    for start in (
        window.start_copy_elements, window.start_reverse_member,
        window.start_join_members, window.start_split_member,
        window.start_copy_member_properties,
    ):
        window.clear_selection()
        start()
        ctrl_click(window, monkeypatch, ("bar", "B1"))
        ctrl_click(window, monkeypatch, ("bar", "B2"))
        window.cancel_member_placement()
        assert window._command_mode is None
        assert window.model.revision == revision
        assert len(window.model.bars) == 3
