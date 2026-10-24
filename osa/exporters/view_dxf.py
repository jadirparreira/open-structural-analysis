"""Write projected detailing-view linework as a metric DXF drawing."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def export_view_to_dxf(
    filename: str | Path,
    segments: Iterable[
        tuple[tuple[float, float], tuple[float, float]]
    ],
) -> int:
    """Export 2D view segments in model units (meters) and return line count."""
    import ezdxf

    document = ezdxf.new("R2010")
    document.units = ezdxf.units.M
    document.header["$MEASUREMENT"] = 1
    document.layers.new(
        "VISTA",
        dxfattribs={"color": 7, "lineweight": 13},
    )
    modelspace = document.modelspace()
    line_count = 0
    for start, end in segments:
        modelspace.add_line(
            (float(start[0]), float(start[1]), 0.0),
            (float(end[0]), float(end[1]), 0.0),
            dxfattribs={"layer": "VISTA"},
        )
        line_count += 1
    document.saveas(Path(filename))
    return line_count
