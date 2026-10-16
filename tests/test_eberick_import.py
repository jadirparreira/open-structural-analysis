"""Contrato da importação: geometria, persistência e falhas transacionais."""

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from osa.model import StructuralModel
from osa.persistence import ProjectRepository
from osa.services.project_service import ProjectService
from osa.transcriptions import (
    ImportOptions,
    ProjectImportError,
    is_import_path,
)
from osa.transcriptions.contracts import require_import_review
from osa.transcriptions.eberick import EberickImporter


@pytest.fixture
def launch():
    """Evidências sintéticas: dois pilares e uma viga em cada pavimento."""
    floors = [
        {
            "object_id": 201,
            "floor_id": 1,
            "name": "Térreo",
            "height_raw": 40,
            "material_defaults": {"CfgPavPilar": "C-25", "CfgPavViga": "C-25"},
        },
        {
            "object_id": 202,
            "floor_id": 2,
            "name": "Superior",
            "height_raw": 300,
            "material_defaults": {"CfgPavPilar": "C-25", "CfgPavViga": "C-25"},
        },
    ]
    columns = []
    beams = []
    for floor_id in (1, 2):
        for number, x in ((1, 0.0), (2, 500.0)):
            columns.append(
                {
                    "object_id": (floor_id - 1) * 2 + number,
                    "name": f"P{number}",
                    "floor_id": floor_id,
                    "xy_raw": [x, 0.0],
                    "section_id": 102,
                    "rectangular_dimensions_candidate_raw": [20, 30],
                    "referenced_by_beam": True,
                    "region_role": "beam_list_and_referenced_elements",
                    "foundation_raw": {"six_flags_raw": [1] * 6}
                    if floor_id == 1
                    else None,
                }
            )
        beams.append(
            {
                "object_id": 10 + floor_id,
                "name": "V1",
                "floor_id": floor_id,
                "support_i_id": (floor_id - 1) * 2 + 1,
                "support_j_id": (floor_id - 1) * 2 + 2,
                "xy_i_raw": [15, 0],
                "xy_j_raw": [485, 0],
                "section_id": 101,
                "rectangular_dimensions_candidate_raw": [20, 50],
            }
        )
    return {
        "source": {"filename": "sintetico.prj", "stream_sha256": "synthetic"},
        "internal_version_code": 3419,
        "decode_errors": [],
        "floors": floors,
        "columns": columns,
        "beams": beams,
        "croquis": [{"floor_id": i, "beam_count": 1} for i in (1, 2)],
        "inventory": [{"class_name": "ElementoViga", "count": 2}],
        "concretes": [
            {
                "name": "C-25",
                "elastic_modulus_raw": 241500,
                "specific_weight_raw": 0.0025,
            }
        ],
        "sections": [
            {
                "object_id": 101,
                "shape_code_raw": 0,
                "geometric_values_raw": [0, 0, 0, 0, 20, 50, 0],
            },
            {
                "object_id": 102,
                "shape_code_raw": 0,
                "geometric_values_raw": [20, 0, 20, 0, 0, 30, 0],
            },
        ],
        "walls": [
            {"object_id": 400, "action_scalars": [{"key": [2, 0], "value_raw": 3}]}
        ],
        "combinations": [],
        "actions": [],
    }


def test_geometry_units_offsets_and_materials(launch):
    result = EberickImporter().convert(launch, ImportOptions())
    model = StructuralModel()
    model.load_dict(result.project_data)
    assert (len(model.nodes), len(model.bars), len(model.rigid_bars)) == (10, 6, 4)
    assert sorted({node.z for node in model.nodes.values()}) == [-0.4, 0, 3]
    beam = model.bars["Superior_V1"]
    a, b = (model.nodes[name] for name in (beam.start_node, beam.end_node))
    assert b.x - a.x == pytest.approx(4.7)
    assert beam.geometry_dict() == {"b": 200, "h": 500}
    assert model.materials["Eberick C-25"] == pytest.approx(
        (23683059.75, 9867941.5625, 0.2, 24.516625)
    )
    assert all(not any(node.supports) for node in model.nodes.values())
    assert not model.actions
    assert model.import_metadata["requires_review"]
    assert (
        model.import_metadata["source_evidence"]["walls"][0]["action_scalars"][0][
            "value_raw"
        ]
        == 3
    )


def test_round_trip_preserves_report_and_review_state(launch, tmp_path):
    result = EberickImporter().convert(launch, ImportOptions())
    model = StructuralModel()
    model.load_dict(result.project_data)
    path = tmp_path / "converted.osa"
    repo = ProjectRepository()
    repo.save(model, path)
    restored = StructuralModel()
    repo.load(restored, path)
    assert restored.as_dict() == model.as_dict()
    with pytest.raises(ValueError, match="experimental"):
        require_import_review(restored)
    service = ProjectService(restored)
    service.confirm_import_review()
    require_import_review(restored)
    repo.save(restored, path)
    other = StructuralModel()
    repo.load(other, path)
    assert other.import_metadata["requires_review"] is False
    assert other.import_metadata["reviewed_at"]
    other.clear()
    assert other.import_metadata == {}


def test_native_load_clears_old_import_metadata(launch, tmp_path):
    model = StructuralModel()
    model.load_dict(EberickImporter().convert(launch, ImportOptions()).project_data)
    native = StructuralModel()
    native.add_node("Original", 0, 0, 0)
    path = tmp_path / "native.osa"
    native.save(path)
    model.load(path)
    assert model.import_metadata == {}
    assert list(model.nodes) == ["Original"]


def test_source_prj_cannot_be_overwritten(tmp_path):
    path = tmp_path / "source.prj"
    path.write_bytes(b"original")
    with pytest.raises(ValueError, match="somente leitura"):
        ProjectRepository().save(StructuralModel(), path)
    assert path.read_bytes() == b"original"
    assert not path.with_suffix(".prj.tmp").exists()


def test_failed_import_does_not_replace_model(tmp_path):
    path = tmp_path / "broken.prj"
    path.write_bytes(b"not an Eberick file")
    model = StructuralModel()
    model.add_node("Keep", 1, 2, 3)
    snapshot = model.as_dict()
    with pytest.raises(ProjectImportError):
        ProjectService(model).load(path)
    assert model.as_dict() == snapshot


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "decode_error",
        "beam_count",
        "slab",
        "unknown_column",
        "non_rectangular",
    ],
)
def test_unsupported_content_is_refused(launch, change):
    if change == "version":
        launch["internal_version_code"] = 3028
    elif change == "decode_error":
        launch["decode_errors"] = [{"class_name": "Viga", "offset_hex": "0x10"}]
    elif change == "beam_count":
        launch["croquis"][0]["beam_count"] = 2
    elif change == "slab":
        launch["inventory"].append({"class_name": "Laje", "count": 1})
    elif change == "unknown_column":
        extra = copy.deepcopy(launch["columns"][0])
        extra.update(object_id=999, name="P99", referenced_by_beam=False)
        launch["columns"].append(extra)
    elif change == "non_rectangular":
        launch["sections"][0]["geometric_values_raw"][0] = 10
    with pytest.raises(ProjectImportError):
        EberickImporter().convert(launch, ImportOptions())


def test_options_change_geometry_and_keep_assumptions_explicit(launch):
    options = ImportOptions(
        first_floor_elevation_m=10,
        include_lower_columns=False,
        preserve_end_offsets=False,
        import_material_properties=False,
    )
    result = EberickImporter().convert(launch, options)
    assert result.project_data["rigid_bars"] == []
    assert len(result.project_data["members"]) == 4
    assert sorted({node["z"] for node in result.project_data["nodes"]}) == [10, 13]
    assert result.report["options"]["preserve_end_offsets"] is False
    assert "Concreto para revisão" in result.project_data["materials"]


def test_supported_extensions_case_insensitive():
    assert is_import_path("test.PRJ")
    assert is_import_path("test.PRJ.ZIP")
    assert not is_import_path("project.osa")
    assert not is_import_path("arbitrary.zip")


@pytest.mark.skipif(
    not os.environ.get("OSA_EBERICK_PRJ"),
    reason="Defina OSA_EBERICK_PRJ para o teste com PRJ real.",
)
def test_real_prj_open_save_reopen(tmp_path):
    source = Path(os.environ["OSA_EBERICK_PRJ"])
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    model = StructuralModel()
    report = ProjectService(model).load(source)
    assert (len(model.nodes), len(model.bars), len(model.rigid_bars)) == (28, 16, 16)
    assert len(model.actions) == 0
    assert (
        report["source"]["stream_sha256"]
        == "ab7a274d6b325867d0512b6db1b8a96a30ba7086cce9e89a0b52f731093e8327"
    )
    target = tmp_path / "teste_conv.osa"
    ProjectService(model).save(target)
    restored = StructuralModel()
    ProjectService(restored).load(target)
    assert restored.as_dict() == model.as_dict()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    assert json.loads(target.read_text())["format"] == "open-structural-analysis/v2"
