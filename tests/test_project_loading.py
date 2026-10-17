import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.ui import home
from osa.ui.loading_indicator import LoadingIndicator
from osa.ui.main_window import MainWindow


@pytest.fixture
def loading_window(monkeypatch):
    class Store:
        def items(self):
            return []

        def add(self, path):
            pass

    monkeypatch.setattr(home, "RecentProjectStore", Store)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    yield app, window
    window._saved_revision = window.model.revision
    window._saved_view_revision = window.model.view_revision
    window.close()


def _wait_for_loading(app, window):
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if window._project_loading_path is None
                         and window._project_load_thread is None else None)
    poll.start()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert window._project_loading_path is None
    assert window._project_load_thread is None


def test_opening_installs_on_gui_thread_and_animates_between_label_batches(loading_window, monkeypatch, tmp_path):
    app, window = loading_window
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")
    path = tmp_path / "model.osa"
    model.save(path)
    original_steps = window.scene.render_model_steps
    threads = []

    def paced_steps(*args, **kwargs):
        for _ in range(60):
            threads.append(QThread.currentThread())
            yield
        yield from original_steps(*args, **kwargs)

    monkeypatch.setattr(window.scene, "render_model_steps", paced_steps)
    indicator = window.findChild(LoadingIndicator)
    animation_phases = []
    heartbeat = QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: animation_phases.append(indicator.phase))
    heartbeat.start()

    window._open_model_path(path)
    assert window._project_loading_overlay.isVisible()
    assert not window.centralWidget().isEnabled()
    _wait_for_loading(app, window)
    heartbeat.stop()

    assert threads and all(thread == app.thread() for thread in threads)
    assert len(set(animation_phases)) > 1
    assert window.centralWidget().isEnabled()
    assert not window._project_loading_overlay.isVisible()
    assert window.scene._member_batch.names == ("B1",)
    assert window.current_path == path


def test_failed_opening_restores_input_and_preserves_the_current_model(loading_window, monkeypatch, tmp_path):
    app, window = loading_window
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    previous_nodes = dict(window.model.nodes)
    path = tmp_path / "invalid.osa"
    path.write_text('{"format": "invalid"}', encoding="utf-8")

    window._open_model_path(path)
    _wait_for_loading(app, window)

    assert errors
    assert window.model.nodes == previous_nodes
    assert window.centralWidget().isEnabled()
    assert not window._project_loading_overlay.isVisible()


@pytest.mark.parametrize("stage", ["setup", "render"])
def test_scene_failure_releases_loading_overlay_and_shortcuts(loading_window, monkeypatch, tmp_path, stage):
    app, window = loading_window
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    path = tmp_path / "scene.osa"
    StructuralModel().save(path)
    enabled = {action: action.isEnabled() for action in window.actions()}

    def fail_setup():
        raise RuntimeError("Falha ao preparar a janela")

    def fail_render(*args, **kwargs):
        yield
        raise RuntimeError("Falha ao instalar a cena")

    if stage == "setup":
        monkeypatch.setattr(window.top_icon_palette, "reload_scene_views", fail_setup)
    else:
        monkeypatch.setattr(window.scene, "render_model_steps", fail_render)
    window._open_model_path(path)
    _wait_for_loading(app, window)

    assert errors
    assert window.centralWidget().isEnabled()
    assert not window._project_loading_overlay.isVisible()
    assert {action: action.isEnabled() for action in window.actions()} == enabled
