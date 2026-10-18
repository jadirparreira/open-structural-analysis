from dataclasses import replace
from struct import pack

import ezdxf
import numpy as np
import pytest
import pyvista as pv

from osa.domain.drawing_reference import DrawingReference, ReferenceGeometry
from osa.importers.drawing_reference import import_drawing_reference
from osa.model import StructuralModel
from osa.rendering.drawing_reference_renderer import DrawingReferenceRenderer


def _import(document, tmp_path):
    filename = tmp_path / "planta.dxf"
    document.saveas(filename)
    return import_drawing_reference(filename)


def _lines(result):
    return np.frombuffer(result.reference.geometry.lines, dtype="<f8").reshape(-1, 2, 2)


def _document():
    document = ezdxf.new()
    document.units = 6  # metres
    return document


def test_import_preserves_cad_origin_converts_units_and_flattens(tmp_path):
    document = _document()
    document.units = 4  # millimetres
    document.modelspace().add_line((1000, 2000, 3000), (4000, 5000, 6000))
    result = _import(document, tmp_path)
    np.testing.assert_allclose(_lines(result), [[[1, 2], [4, 5]]])
    assert result.reference.origin == (0, 0, 0)
    assert result.reference.plane == "XY"
    assert result.reference.visible
    assert not result.warnings


@pytest.mark.parametrize("pattern", ([1.0, 0.6, -0.4], [1.2, 0.6, -0.2, 0.0, -0.4]))
def test_linetypes_produce_real_gaps_and_dots(tmp_path, pattern):
    document = _document()
    document.linetypes.new("CUSTOM", dxfattribs={"pattern": pattern})
    document.layers.new("DASHES", dxfattribs={"linetype": "CUSTOM"})
    document.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "DASHES"})
    lines = _lines(_import(document, tmp_path))
    lengths = np.linalg.norm(lines[:, 1] - lines[:, 0], axis=1)
    assert len(lines) > 5
    assert lengths.sum() < 9
    assert max(lengths) <= 0.60001
    if 0.0 in pattern:
        assert min(lengths) < 0.001


def test_solid_hatch_holes_remain_empty(tmp_path):
    document = _document()
    hatch = document.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)], is_closed=True, flags=1)
    hatch.paths.add_polyline_path([(1, 1), (3, 1), (3, 3), (1, 3)], is_closed=True, flags=0)
    result = _import(document, tmp_path)
    triangles = np.frombuffer(result.reference.geometry.triangles, dtype="<f8").reshape(-1, 3, 2)
    a = triangles[:, 1] - triangles[:, 0]
    b = triangles[:, 2] - triangles[:, 0]
    areas = abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2
    assert areas.sum() == pytest.approx(12)


def test_pattern_hatches_are_lines_and_respect_holes(tmp_path):
    document = _document()
    hatch = document.modelspace().add_hatch()
    hatch.set_pattern_fill("USER", style=0, definition=[(0, (0, 0), (0, 0.25), [])])
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)], is_closed=True, flags=1)
    hatch.paths.add_polyline_path([(1, 1), (3, 1), (3, 3), (1, 3)], is_closed=True, flags=0)
    result = _import(document, tmp_path)
    lines = _lines(result)
    assert len(lines) > 10
    assert not result.reference.geometry.triangles
    midpoints = lines.mean(axis=1)
    assert not np.any(np.all((midpoints > 1.001) & (midpoints < 2.999), axis=1))


def test_blocks_curves_and_hidden_layers(tmp_path):
    document = _document()
    block = document.blocks.new("ROOM")
    block.add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("ROOM", (4, 3), dxfattribs={"rotation": 90, "xscale": 2})
    document.layers.new("HIDDEN").off()
    document.modelspace().add_line((100, 100), (200, 200), dxfattribs={"layer": "HIDDEN"})
    document.modelspace().add_circle((0, 0), 1)
    result = _import(document, tmp_path)
    lines = _lines(result)
    np.testing.assert_allclose(lines[0], [[4, 3], [4, 5]], atol=1e-10)
    assert len(lines) > 20
    assert np.max(lines) < 6
    assert not result.warnings


def test_unitless_dxf_reports_unit_assumption(tmp_path):
    document = _document()
    document.units = 0
    document.modelspace().add_line((0, 0), (1, 0))
    result = _import(document, tmp_path)
    assert "1 unidade = 1 metro" in result.warnings[0]


def test_rejects_unsupported_and_empty_or_corrupt_dxf(tmp_path):
    with pytest.raises(ValueError, match="DXF ou DWG"):
        import_drawing_reference(tmp_path / "planta.pdf")
    with pytest.raises(ValueError, match="geometria visível"):
        _import(_document(), tmp_path)
    filename = tmp_path / "corrupt.dxf"
    filename.write_text("invalid DXF")
    with pytest.raises(ValueError, match="integridade"):
        import_drawing_reference(filename)


def test_project_embeds_geometry_and_reference_edits_do_not_invalidate_analysis(tmp_path):
    document = _document()
    document.modelspace().add_line((0, 0), (1, 2))
    reference = _import(document, tmp_path).reference
    model = StructuralModel()
    revision = model.revision
    model.add_reference(reference)
    view_revision = model.view_revision
    model.update_reference(reference.id, origin=(1, 2, 3), plane="YZ", visible=False)
    assert model.revision == revision
    assert model.view_revision == view_revision + 1
    assert model.references[reference.id].geometry is reference.geometry
    filename = tmp_path / "reference.osa"
    model.save(filename)
    (tmp_path / "planta.dxf").unlink()
    loaded = StructuralModel()
    loaded.load(filename)
    restored = loaded.references[reference.id]
    assert (restored.name, restored.origin, restored.plane, restored.visible) == ("planta.dxf", (1, 2, 3), "YZ", False)
    assert restored.geometry.lines == reference.geometry.lines
    model.clear()
    assert not model.references


def test_invalid_reference_load_is_atomic():
    model = StructuralModel()
    model.add_node("existing", 0, 0, 0)
    data = model.as_dict()
    data["references"] = [{"geometry": {"encoding": "unknown"}}]
    with pytest.raises(ValueError, match="não reconhecido"):
        model.load_dict(data)
    assert "existing" in model.nodes


@pytest.mark.parametrize("changes", [{"origin": (float("nan"), 0, 0)}, {"plane": "AB"}])
def test_rejects_invalid_placement(changes):
    reference = DrawingReference("id", "name", ReferenceGeometry())
    with pytest.raises(ValueError):
        replace(reference, **changes)


@pytest.mark.parametrize("plane, expected", [("XY", (11, 22, 30)), ("XZ", (11, 20, 32)), ("YZ", (10, 21, 32))])
def test_renderer_placement(plane, expected):
    reference = DrawingReference("id", "name", ReferenceGeometry(), origin=(10, 20, 30), plane=plane)
    result = DrawingReferenceRenderer.matrix(reference).MultiplyPoint((1, 2, 0, 1))
    assert result[:3] == expected


def test_actor_is_not_pickable_and_edits_reuse_mesh_and_actor():
    geometry = ReferenceGeometry(pack("<dddd", 0, 0, 1, 2))
    reference = DrawingReference("id", "name", geometry)
    plotter = pv.Plotter(off_screen=True)
    try:
        renderer = DrawingReferenceRenderer()
        renderer.sync(plotter, {reference.id: reference})
        actor = renderer.actors[reference.id]
        mesh = actor.GetMapper().GetInput()
        assert not actor.GetPickable()
        renderer.sync(plotter, {reference.id: replace(reference, origin=(4, 5, 6), plane="XZ", visible=False)})
        assert renderer.actors[reference.id] is actor
        assert actor.GetMapper().GetInput() is mesh
        assert not actor.GetVisibility()
        assert actor.GetUserMatrix().MultiplyPoint((1, 2, 0, 1))[:3] == (5, 5, 8)
        renderer.sync(plotter, {})
        assert not renderer.actors
        assert not renderer._meshes
    finally:
        plotter.close()
