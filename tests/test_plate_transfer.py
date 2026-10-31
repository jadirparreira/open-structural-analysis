"""Preservação das lajes e contrato com a futura implementação de placas."""

import copy

import pytest

from osa.model import StructuralModel
from osa.services.project_service import ProjectService
from osa.transcriptions import ProjectImportError
from osa.transcriptions.contracts import require_import_review
from osa.transcriptions.plates import (
    connect_plates,
    pending_plate_count,
    prepare_plate_transfer,
)


@pytest.fixture
def slabs():
    return [
        {
            "object_id": 50,
            "name": "L1",
            "floor_id": 1,
            "floor_name": "Térreo",
            "contour_xy_raw": [[0, 0], [500, 0], [500, 400], [0, 400]],
            "openings_xy_raw": [[[100, 100], [150, 100], [150, 150], [100, 150]]],
            "elevation_offset_raw": -10,
            "thickness_raw": 12,
            "material_name": "C-25",
            "boundary_element_ids": [1, 2, 3, 4],
        }
    ]


class PlateTarget:
    def __init__(self):
        self.calls = []

    def import_plates(self, plates):
        self.calls.append(plates)
        return {plate.source_id: f"Plate:{plate.name}" for plate in plates}


def test_future_plate_target_receives_normalized_geometry_with_opening(slabs):
    transfer = prepare_plate_transfer(slabs, {1: 10}, 0.01)
    snapshot = copy.deepcopy(transfer)
    target = PlateTarget()
    result = connect_plates(transfer, target)
    assert result == {"eberick:50": "Plate:L1"}
    (plate,) = target.calls[0]
    assert plate.thickness_m == pytest.approx(0.12)
    assert plate.contour_m == ((0, 0, 9.9), (5, 0, 9.9), (5, 4, 9.9), (0, 4, 9.9))
    assert plate.openings_m == (
        ((1, 1, 9.9), (1.5, 1, 9.9), (1.5, 1.5, 9.9), (1, 1.5, 9.9)),
    )
    assert plate.material_name == "C-25"
    # A confirmação depende da persistência transacional dos elementos nativos.
    assert transfer == snapshot


def test_partially_mapped_slab_stays_pending_after_save_reopen(tmp_path):
    transfer = prepare_plate_transfer(
        [{"object_id": 99, "name": "L2", "floor_id": 1}], {1: 0}, 0.01
    )
    record = transfer["records"][0]
    assert record["mapping_status"] == "incomplete"
    assert set(record["missing_fields"]) == {
        "contour_m",
        "openings_m",
        "thickness_m",
        "material_name",
    }
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.import_metadata = {"requires_review": False, "plate_transfer": transfer}
    path = tmp_path / "pending.osa"
    ProjectService(model).save(path)
    restored = StructuralModel()
    ProjectService(restored).load(path)
    assert restored.import_metadata == model.import_metadata
    assert pending_plate_count(restored.import_metadata) == 1
    with pytest.raises(ValueError, match="placas"):
        require_import_review(restored)
    target = PlateTarget()
    with pytest.raises(ProjectImportError, match="sem mapeamento"):
        connect_plates(transfer, target)
    assert not target.calls


@pytest.mark.parametrize(
    "change",
    ["thickness", "degenerate", "nan", "unmapped", "missing_floor", "missing_openings"],
)
def test_invalid_second_plate_does_not_create_a_partial_batch(slabs, change):
    second = copy.deepcopy(slabs[0])
    second.update(object_id=51, name="L2")
    if change == "thickness":
        second["thickness_raw"] = -10
    elif change == "degenerate":
        second["contour_xy_raw"] = [[0, 0], [1, 0], [2, 0]]
    elif change == "nan":
        second["contour_xy_raw"][0][0] = float("nan")
    elif change == "unmapped":
        second.pop("contour_xy_raw")
    elif change == "missing_floor":
        second["floor_id"] = 9
    elif change == "missing_openings":
        second.pop("openings_xy_raw")
    target = PlateTarget()
    with pytest.raises(ProjectImportError):
        connect_plates(prepare_plate_transfer([*slabs, second], {1: 0}, 0.01), target)
    assert target.calls == []


def test_import_review_cannot_clear_pending_plates(slabs):
    model = StructuralModel()
    model.import_metadata = {
        "requires_review": True,
        "plate_transfer": prepare_plate_transfer(slabs, {1: 0}, 0.01),
    }
    before = copy.deepcopy(model.import_metadata)
    with pytest.raises(ValueError, match="placas"):
        ProjectService(model).confirm_import_review()
    assert model.import_metadata == before
