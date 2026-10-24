import ezdxf

from osa.exporters.view_dxf import export_view_to_dxf


def test_export_view_to_dxf_preserves_projected_lines_and_metric_units(tmp_path):
    target = tmp_path / "vista.dxf"
    segments = (
        ((1.25, -2.5), (4.0, -2.5)),
        ((4.0, -2.5), (4.0, 3.75)),
    )

    line_count = export_view_to_dxf(target, segments)

    document = ezdxf.readfile(target)
    lines = list(document.modelspace().query("LINE"))
    assert line_count == 2
    assert document.units == ezdxf.units.M
    assert [line.dxf.layer for line in lines] == ["VISTA", "VISTA"]
    assert [tuple(line.dxf.start) for line in lines] == [
        (1.25, -2.5, 0.0),
        (4.0, -2.5, 0.0),
    ]
    assert [tuple(line.dxf.end) for line in lines] == [
        (4.0, -2.5, 0.0),
        (4.0, 3.75, 0.0),
    ]
