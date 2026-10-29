import ezdxf

from osa.domain.model import StructuralModel
from osa.exporters.model_dxf import export_model_to_dxf


def test_export_model_to_dxf_writes_analytical_bar_axes_in_meters(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 1.25, -2.5, 0.0)
    model.add_node("N2", 4.0, -2.5, 3.75)
    model.add_bar("B1", "N1", "N2")

    target = tmp_path / "modelo.dxf"
    line_count = export_model_to_dxf(target, model)

    document = ezdxf.readfile(target)
    lines = list(document.modelspace().query("LINE"))
    assert line_count == 1
    assert document.units == ezdxf.units.M
    assert len(lines) == 1
    assert lines[0].dxf.layer == "BARRAS"
    assert tuple(lines[0].dxf.start) == (1.25, -2.5, 0.0)
    assert tuple(lines[0].dxf.end) == (4.0, -2.5, 3.75)


def test_export_model_to_dxf_does_not_depend_on_solid_offsets(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 0.0, 0.0, 2.0)
    model.add_bar("B1", "N1", "N2")
    model.update_member_solid_face_offsets("B1", (0.5, 0.75))

    target = tmp_path / "modelo.dxf"
    export_model_to_dxf(target, model)

    lines = ezdxf.readfile(target).modelspace().query("LINE")
    assert len(lines) == 1
    line = lines[0]
    assert tuple(line.dxf.start) == (0.0, 0.0, 0.0)
    assert tuple(line.dxf.end) == (0.0, 0.0, 2.0)
