"""Vector PDF output using exactly the workspace's sheet drawing routines."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from PySide6.QtCore import QIODevice, QMarginsF, QRectF, QSaveFile, QSizeF
from PySide6.QtGui import QColor, QPainter, QPageLayout, QPageSize, QPdfWriter

from .project_sheet import ProjectSheetWorkspace
from .weld_symbols import draw_weld


class _WeldRenderer:
    """Render saved welds without creating an interactive tool or panel."""

    def __init__(self, workspace):
        self.workspace = workspace

    def draw(self, painter, index):
        workspace = self.workspace
        bounds = QRectF()
        for mark in workspace._sheet_views[index].get("weld_marks", ()):
            anchor = workspace._screen_point(index, mark["point"])
            if anchor is not None:
                path = draw_weld(painter, anchor, mark, workspace._sheet_pixels_per_mm,
                                 settings=workspace._project_settings)
                bounds = bounds.united(path.boundingRect())
        return bounds


def _export_workspace(source):
    # Isolate hit rectangles, selections, previews and navigation caches. Saved
    # geometry is read-only while painting and may be shared without a huge copy.
    workspace = ProjectSheetWorkspace(source.window())
    workspace.setFont(source.font())
    # QPdfWriter uses 96 device units/inch; PDF points use 72 units/inch.
    workspace._pdf_model_line_width = 0.5 * 96.0 / 72.0
    workspace._pdf_annotation_line_width = 0.75 * 96.0 / 72.0
    workspace._settings = copy.deepcopy(source._settings)
    workspace._project_settings = copy.deepcopy(source._project_settings)
    workspace._sheet_name = source._sheet_name
    workspace._sheet_count = source._sheet_count
    workspace._sheet_views = tuple(dict(view) for view in source._sheet_views)
    workspace._sheet_texts = source._sheet_texts
    workspace._sheet_lines = source._sheet_lines
    workspace._sheet_image_cache = dict(source._sheet_image_cache)
    workspace._component_group_paper_frames = dict(source._component_group_paper_frames)
    for name in ("steel_profile_rows_provider", "steel_plate_rows_provider", "accessory_rows_provider"):
        setattr(workspace, name, getattr(source, name))
    workspace.weld_tool = _WeldRenderer(workspace)
    return workspace


def export_sheet_pdf(source: ProjectSheetWorkspace, filename: str | Path) -> None:
    """Export the entire active sheet, unaffected by screen zoom and selection.

    The 96 dpi coordinate system matches Qt's screen/design metrics; it does
    not rasterize the output. Model strokes are 0.5 pt; annotations are 0.75 pt.
    QSaveFile keeps an existing destination intact if generation fails.
    """
    width, height = source.paper_size_mm()
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise ValueError("O tamanho da folha deve ser positivo e finito.")
    output = QSaveFile(str(filename))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    workspace = None
    painter = QPainter()
    try:
        writer = QPdfWriter(output)
        writer.setResolution(96)
        writer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Unit.Millimeter,
                                    source._sheet_name, QPageSize.SizeMatchPolicy.ExactMatch))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        writer.setTitle(source._sheet_name)
        writer.setCreator("Open Structural Analysis")
        if not painter.begin(writer):
            raise OSError("Não foi possível iniciar a gravação do PDF.")
        workspace = _export_workspace(source)
        painter.setFont(source.font())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = writer.resolution() / 25.4
        sheet = QRectF(0, 0, width * scale, height * scale)
        painter.fillRect(sheet, QColor("#ffffff"))
        painter.setClipRect(sheet)
        workspace.paint_sheet(painter, sheet, scale)
        if not painter.end():
            raise OSError("Não foi possível finalizar o PDF.")
        del writer
        if not output.commit():
            raise OSError(output.errorString())
    except Exception:
        if painter.isActive():
            painter.end()
        output.cancelWriting()
        raise
    finally:
        if workspace is not None:
            workspace.deleteLater()
