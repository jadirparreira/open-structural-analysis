"""Background worker for reading and validating project files."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter, sleep

from PySide6.QtCore import QObject, Signal, Slot

from osa.model import StructuralModel
from osa.persistence import ProjectRepository
from osa.rendering.batched_renderer import PreparedSceneGeometry, prepare_scene_geometry
from osa.services.model_service import ModelService
from osa.transcriptions import ImportOptions


class ProjectLoadWorker(QObject):
    """Load a project into a private model without touching the GUI model."""

    loaded = Signal(object, object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        path: str | Path,
        *,
        normalize_member_directions: bool = True,
        solid_members_visible: bool = False,
        solid_positioning_enabled: bool = False,
        reference_plane: str = "XY",
        preferred_plane_level: float = 0.0,
        import_options: ImportOptions | None = None,
    ) -> None:
        super().__init__()
        self.path = Path(path)
        self.normalize_member_directions = normalize_member_directions
        self.solid_members_visible = solid_members_visible
        self.solid_positioning_enabled = solid_positioning_enabled
        self.reference_plane = reference_plane
        self.preferred_plane_level = preferred_plane_level
        self.import_options = import_options
        self.report: dict | None = None

    @Slot()
    def run(self) -> None:
        try:
            model = StructuralModel()
            # Native JSON/VTK calls can repeatedly reacquire the GIL before Qt
            # gets a turn. Yield at bounded record/buffer boundaries as well.
            last_yield = perf_counter()

            def yield_control() -> None:
                nonlocal last_yield
                if perf_counter() - last_yield >= 0.004:
                    sleep(0.001)
                    last_yield = perf_counter()
            self.report = ProjectRepository().load(
                model, self.path, import_options=self.import_options,
                progress=self.progress.emit, yield_control=yield_control,
            )
            if self.normalize_member_directions:
                ModelService(model).normalize_member_directions()
            geometry: PreparedSceneGeometry = prepare_scene_geometry(
                model,
                solid_members_visible=self.solid_members_visible,
                position_indicators_with_section=self.solid_members_visible,
                solid_positioning_enabled=self.solid_positioning_enabled,
                reference_plane=self.reference_plane,
                preferred_plane_level=self.preferred_plane_level,
                progress=self.progress.emit,
                yield_control=yield_control,
            )
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
            return
        self.loaded.emit(model, geometry)
