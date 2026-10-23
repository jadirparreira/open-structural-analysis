import os

import numpy as np
import pytest
import pyvista as pv

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.rendering.detailing_2d import (
    projected_visible_intervals,
    visible_segments_from_meshes,
)
from osa.ui.detailing_preview import DetailingViewPreview


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_front_face_splits_occluded_2d_edge():
    triangle_points = np.array(((0.4, -1.0), (0.6, -1.0), (0.5, 1.0)))
    triangles = ((triangle_points, np.array((1.0, 1.0, 1.0))),)

    visible = projected_visible_intervals(
        (0.0, 0.0), (1.0, 0.0), 0.0, 0.0, triangles
    )

    assert np.allclose(visible, ((0.0, 0.45), (0.55, 1.0)))


def test_behind_face_does_not_occlude_edge():
    triangle_points = np.array(((0.4, -1.0), (0.6, -1.0), (0.5, 1.0)))
    triangles = ((triangle_points, np.array((0.0, 0.0, 0.0))),)

    visible = projected_visible_intervals(
        (0.0, 0.0), (1.0, 0.0), 1.0, 1.0, triangles
    )

    assert np.allclose(visible, ((0.0, 1.0),))


def test_cube_preview_produces_planar_vector_segments_only():
    segments = visible_segments_from_meshes(
        (pv.Cube(),), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
    )

    assert len(segments) == 4
    for start, end in segments:
        assert len(start) == len(end) == 2
        assert not np.allclose(start, end)


def test_cylindrical_solid_keeps_view_dependent_silhouette():
    cylinder = pv.Cylinder(
        center=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        radius=1.0,
        height=2.0,
        resolution=64,
    )

    segments = visible_segments_from_meshes(
        (cylinder,), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    )

    vertical_silhouettes = [
        (start, end)
        for start, end in segments
        if abs(start[0] - end[0]) < 1e-6 and abs(start[1] - end[1]) > 1.9
    ]
    assert len(vertical_silhouettes) >= 2


def test_view_direction_changes_which_solid_edges_are_visible():
    rear_large = pv.Cube(center=(0.0, -0.5, 0.0), x_length=2.0, y_length=0.2, z_length=2.0)
    nearer_small = pv.Cube(center=(0.0, 0.5, 0.0), x_length=1.0, y_length=0.2, z_length=1.0)

    from_positive_y = visible_segments_from_meshes(
        (rear_large, nearer_small), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    )
    from_negative_y = visible_segments_from_meshes(
        (rear_large, nearer_small), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)
    )

    assert len(from_positive_y) > len(from_negative_y)


def test_depth_clipped_cube_produces_2d_outline():
    clipped = DetailingViewPreview._clip_to_depth_range(
        pv.Cube(), (0.0, 0.0, 1.0), 2, -0.25, 0.25
    )

    assert clipped is not None
    assert np.allclose(clipped.bounds[4:], (-0.25, 0.25))
    assert len(visible_segments_from_meshes((clipped,), (0, 0, 1), (0, 1, 0))) == 4


def test_rotation_rotates_projected_vector_extent():
    beam = pv.Cube(x_length=2.0, y_length=1.0, z_length=1.0)
    unrotated = visible_segments_from_meshes((beam,), (0, 0, 1), (0, 1, 0), 0)
    rotated = visible_segments_from_meshes((beam,), (0, 0, 1), (0, 1, 0), 90)

    def extents(segments):
        points = np.asarray([point for segment in segments for point in segment])
        return np.ptp(points[:, 0]), np.ptp(points[:, 1])

    assert np.allclose(extents(unrotated), (2.0, 1.0))
    assert np.allclose(extents(rotated), (1.0, 2.0))


def test_preview_uses_2d_painting_and_keeps_pan_zoom(qt_app):
    preview = DetailingViewPreview()
    preview.resize(320, 240)
    preview._segments_2d = (((0.0, 0.0), (1.0, 1.0)),)
    preview._bounds_2d = (0.0, 1.0, 0.0, 1.0)
    preview.show()
    qt_app.processEvents()
    rendered_image = preview.grab().toImage()
    assert min(
        rendered_image.pixelColor(x, y).red()
        for x in range(150, 170)
        for y in range(110, 130)
    ) < 200

    initial_pan = QPointF(preview._pan)
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(preview, QPoint(140, 115))
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(140, 115))
    assert preview._pan == initial_pan + QPointF(40, 15)

    wheel = QWheelEvent(
        QPointF(140, 115),
        QPointF(preview.mapToGlobal(QPoint(140, 115))),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    previous_zoom = preview._zoom
    preview.wheelEvent(wheel)
    assert preview._zoom > previous_zoom
    preview.close()


def test_solid_section_view_builds_exportable_2d_geometry(qt_app):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 4, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.update_bar_section("B1", "Barra Retangular")
    model.update_member_profile("B1", "B1", {"b": 100, "h": 200})
    preview = DetailingViewPreview()

    preview.set_view(
        model,
        "XY",
        0.0,
        upper_offset_cm=50.0,
        lower_offset_cm=50.0,
    )

    segments = preview.segments_2d
    assert len(segments) == 4
    assert all(len(point) == 2 for segment in segments for point in segment)
    points = np.asarray([point for segment in segments for point in segment])
    assert np.allclose((points[:, 0].min(), points[:, 0].max()), (0.0, 4.0))
    assert np.allclose((points[:, 1].min(), points[:, 1].max()), (-0.05, 0.05))
    assert not hasattr(preview, "_plotter")
    preview.close()


def test_custom_plane_uses_same_2d_vector_pipeline(qt_app):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 4, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.update_bar_section("B1", "Barra Retangular")
    model.update_member_profile("B1", "B1", {"b": 100, "h": 200})
    preview = DetailingViewPreview()

    preview.set_view(
        model,
        "custom",
        ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
        upper_offset_cm=50.0,
        lower_offset_cm=50.0,
    )

    assert len(preview.segments_2d) == 4
    preview.close()

