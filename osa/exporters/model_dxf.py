"""Export the analytical bar centrelines of a structural model to DXF."""

from __future__ import annotations

from pathlib import Path


def export_model_to_dxf(filename: str | Path, model) -> int:
    """Write one metric 3D DXF line for each bar and return the line count.

    The exported geometry comes from the analytical member end nodes. Solid
    section dimensions and visual placement offsets are intentionally ignored.
    """
    import ezdxf

    document = ezdxf.new("R2010")
    document.units = ezdxf.units.M
    document.header["$MEASUREMENT"] = 1
    document.layers.new("BARRAS", dxfattribs={"color": 7, "lineweight": 13})
    modelspace = document.modelspace()
    line_count = 0
    for member in model.bars.values():
        try:
            start = model.nodes[member.start_node]
            end = model.nodes[member.end_node]
        except KeyError as error:
            raise ValueError(
                f"A barra {member.name} referencia um nó que não existe."
            ) from error
        modelspace.add_line(
            (float(start.x), float(start.y), float(start.z)),
            (float(end.x), float(end.y), float(end.z)),
            dxfattribs={"layer": "BARRAS"},
        )
        line_count += 1
    document.saveas(Path(filename))
    return line_count
