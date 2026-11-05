"""Contrato da importação: geometria, persistência e falhas transacionais."""

import copy

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
from osa.transcriptions.prj import PrjImporter


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
                    "foundation_raw": {
                        "kind": "pad_footing",
                        "settlement_depth_raw": 150,
                        "depth_reference": "baldrame_top_to_footing_bottom",
                        "six_flags_raw": [1] * 6,
                        "six_values_raw": [0.0] * 6,
                    }
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
        "inventory": [
            {"class_name": "ElementoViga", "count": 2},
            {"class_name": "Pavimento", "count": 2},
            {"class_name": "CroquiPavimento", "count": 2},
            {"class_name": "ElementoPilar", "count": 4},
        ],
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
    result = PrjImporter().convert(launch, ImportOptions())
    model = StructuralModel()
    model.load_dict(result.project_data)
    assert (len(model.nodes), len(model.bars), len(model.rigid_bars)) == (10, 6, 4)
    assert list(model.nodes) == [f"N{index}" for index in range(1, 11)]
    assert list(model.bars) == [f"B{index}" for index in range(1, 7)]
    assert sorted({node.z for node in model.nodes.values()}) == [-1.5, 0, 3]
    beam_name = next(
        name
        for name, source in result.report["member_sources"].items()
        if source["kind"] == "beam" and source["original_name"] == "V1"
    )
    beam = model.bars[beam_name]
    a, b = (model.nodes[name] for name in (beam.start_node, beam.end_node))
    assert b.x - a.x == pytest.approx(4.7)
    assert beam.geometry_dict() == {"b": 200, "h": 500}
    assert model.materials["Concreto C-25"][:4] == pytest.approx(
        (24150000.0, 10062500.0, 0.2, 25.0)
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
    result = PrjImporter().convert(launch, ImportOptions())
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
    model.load_dict(PrjImporter().convert(launch, ImportOptions()).project_data)
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
    path.write_bytes(b"not a recognized PRJ file")
    model = StructuralModel()
    model.add_node("Keep", 1, 2, 3)
    snapshot = model.as_dict()
    with pytest.raises(ProjectImportError):
        ProjectService(model).load(path)
    assert model.as_dict() == snapshot


@pytest.mark.parametrize(
    "change",
    [
        "decode_error",
        "beam_count",
        "missing_floor",
        "missing_croqui",
        "missing_column",
        "unknown_reference",
        "slab",
        "unknown_column",
        "non_rectangular",
    ],
)
def test_unsupported_content_is_refused(launch, change):
    if change == "decode_error":
        launch["decode_errors"] = [{"class_name": "Viga", "offset_hex": "0x10"}]
    elif change == "beam_count":
        launch["croquis"][0]["beam_count"] = 2
    elif change == "missing_floor":
        launch["floors"].pop()
    elif change == "missing_croqui":
        launch["croquis"].pop()
    elif change == "missing_column":
        launch["columns"].pop()
    elif change == "unknown_reference":
        launch["beams"][0]["support_j_id"] = 999
    elif change == "slab":
        launch["inventory"].append({"class_name": "Laje", "count": 1})
    elif change == "unknown_column":
        extra = copy.deepcopy(launch["columns"][0])
        extra.update(object_id=999, name="P99", referenced_by_beam=False)
        launch["columns"].append(extra)
    elif change == "non_rectangular":
        launch["sections"][0]["geometric_values_raw"][0] = 10
    with pytest.raises(ProjectImportError):
        PrjImporter().convert(launch, ImportOptions())


@pytest.mark.parametrize("code", [2281, 3028, 9999])
def test_same_launch_layout_accepts_other_codes_and_preserves_provenance(
    launch, code, tmp_path
):
    reference = PrjImporter().convert(launch, ImportOptions())
    launch["internal_version_code"] = code
    result = PrjImporter().convert(launch, ImportOptions())
    for key in ("nodes", "members", "rigid_bars", "materials"):
        assert result.project_data[key] == reference.project_data[key]
    assert result.report["internal_version_code"] == code
    assert result.report["compatibility"]["mode"] == "structural_probe"
    assert result.report["requires_review"] is True
    assert any(
        str(code) in warning and "amostra real" in warning
        for warning in result.report["warnings"]
    )
    model = StructuralModel()
    model.load_dict(result.project_data)
    target = tmp_path / "other_version.osa"
    ProjectService(model).save(target)
    restored = StructuralModel()
    ProjectService(restored).load(target)
    assert restored.import_metadata == result.report


def test_auxiliary_decode_failure_is_reported_without_blocking_geometry(launch):
    launch["decode_errors"] = [
        {
            "class_name": "Combinacao",
            "offset_hex": "0x123",
            "error": "Layout auxiliar diferente",
        }
    ]
    result = PrjImporter().convert(launch, ImportOptions())
    assert len(result.project_data["members"]) == 6
    assert result.report["decode_warnings"] == launch["decode_errors"]
    assert any(
        "registros auxiliares" in warning for warning in result.report["warnings"]
    )
    assert result.project_data["load_combinations"] == []


def test_options_change_geometry_and_keep_assumptions_explicit(launch):
    options = ImportOptions(
        first_floor_elevation_m=10,
        include_lower_columns=False,
        preserve_end_offsets=False,
        import_material_properties=False,
    )
    result = PrjImporter().convert(launch, options)
    assert result.project_data["rigid_bars"] == []
    assert len(result.project_data["members"]) == 4
    assert sorted({node["z"] for node in result.project_data["nodes"]}) == [10, 13]
    assert result.report["options"]["preserve_end_offsets"] is False
    assert "Concreto para revisão" in result.project_data["materials"]


def test_footing_nodes_use_each_settlement_depth_and_preserve_pending_supports(launch):
    launch["floors"][0]["height_raw"] = 999
    launch["columns"][1]["foundation_raw"]["settlement_depth_raw"] = 225
    result = PrjImporter().convert(
        launch, ImportOptions(first_floor_elevation_m=10)
    )
    nodes = {node["name"]: node for node in result.project_data["nodes"]}
    original_node_names = {
        original: name
        for name, source in result.report["node_sources"].items()
        for original in source["original_names"]
    }
    assert nodes[original_node_names["Base_P1"]]["z"] == pytest.approx(8.5)
    assert nodes[original_node_names["Base_P2"]]["z"] == pytest.approx(7.75)
    assert nodes[original_node_names["Superior_P1"]]["z"] == pytest.approx(13)
    assert all(not any(node["supports"]) for node in nodes.values())
    assert [p["settlement_depth_m"] for p in result.report["support_candidates"]] == [
        1.5,
        2.25,
    ]
    assert all(
        p["mapping_status"] == "pending_support_calibration"
        for p in result.report["support_candidates"]
    )
    assert all(
        p["source_flags_raw"] == [1] * 6 for p in result.report["support_candidates"]
    )
    assert result.project_data["actions"] == []


def test_zero_first_floor_height_does_not_replace_footing_depth(launch):
    launch["floors"][0]["height_raw"] = 0
    result = PrjImporter().convert(launch, ImportOptions())
    assert {node["z"] for node in result.project_data["nodes"]} == {-1.5, 0, 3}


@pytest.mark.parametrize("depth", [0, -150, float("nan"), None])
def test_invalid_footing_depth_is_refused(launch, depth):
    launch["columns"][0]["foundation_raw"]["settlement_depth_raw"] = depth
    with pytest.raises(ProjectImportError, match="[Aa]ltura"):
        PrjImporter().convert(launch, ImportOptions())


def test_pile_cap_reference_is_not_interpreted_as_footing_settlement(launch):
    launch["columns"][0]["foundation_raw"]["kind"] = "pile_cap"
    result = PrjImporter().convert(launch, ImportOptions())
    assert result.report["counts"]["excluded_lower_column_segments"] == 1
    assert [item["column_name"] for item in result.report["support_candidates"]] == ["P2"]
    result = PrjImporter().convert(
        launch, ImportOptions(include_lower_columns=False)
    )
    assert result.report["support_candidates"] == []


def test_foundation_column_uses_own_floor_and_bar_height(launch):
    column = launch["columns"][2]
    column["class_name"] = "ElPilarFundacao"
    column["foundation_raw"] = {
        "kind": "pile_cap", "bar_height_raw": 52,
        "height_reference": "floor_to_foundation_bar_bottom",
    }
    launch["inventory"][-1]["count"] = 3
    launch["inventory"].append({"class_name": "ElPilarFundacao", "count": 1})
    result = PrjImporter().convert(launch, ImportOptions())
    nodes = {node["name"]: node for node in result.project_data["nodes"]}
    name = next(
        name for name, source in result.report["member_sources"].items()
        if source["object_id"] == column["object_id"] and source["foundation_bar"]
    )
    member = next(member for member in result.project_data["members"] if member["name"] == name)
    assert nodes[member["start_node"]]["z"] == pytest.approx(2.48)
    assert nodes[member["end_node"]]["z"] == pytest.approx(3.0)
    support = next(s for s in result.report["support_candidates"] if s["source_object_id"] == column["object_id"])
    assert support["bar_height_m"] == pytest.approx(0.52)
    assert "settlement_depth_m" not in support


def test_unreferenced_native_foundation_column_is_preserved(launch):
    launch["columns"].append({
        "object_id": 5, "class_name": "ElPilarFundacao", "name": "P3",
        "floor_id": 1, "xy_raw": [1000, 0], "section_id": 102,
        "rectangular_dimensions_candidate_raw": [20, 30], "referenced_by_beam": False,
        "region_role": "base_cad",
        "foundation_raw": {"kind": "pile_cap", "bar_height_raw": 52,
                           "height_reference": "floor_to_foundation_bar_bottom"},
    })
    launch["inventory"].append({"class_name": "ElPilarFundacao", "count": 1})
    result = PrjImporter().convert(launch, ImportOptions())
    assert result.report["counts"]["foundation_columns_without_beams"] == 1
    assert result.report["counts"]["isolated_foundation_columns"] == 1
    assert result.report["isolated_foundation_columns"][0]["column_name"] == "P3"
    assert any(s["column_name"] == "P3" and s["elevation_m"] == pytest.approx(-0.52)
               for s in result.report["support_candidates"])
    assert all(not any(node["supports"]) for node in result.project_data["nodes"])


def test_foundation_summary_does_not_count_footing_configuration_as_footings(launch):
    launch["inventory"].extend([
        {"class_name": "CfgPavSapata", "count": 6},
        {"class_name": "CfgObraSapata", "count": 1},
        {"class_name": "TDadosSapataSemPilar", "count": 1},
        {"class_name": "Sapata", "count": 2},
    ])
    result = PrjImporter().convert(launch, ImportOptions())
    assert result.report["counts"]["excluded_elements"]["sapatas"] == 2


def test_new_foundation_column_keeps_existing_bar_names_in_3219(launch):
    launch["internal_version_code"] = 3219
    before = PrjImporter().convert(launch, ImportOptions()).report["member_sources"]
    launch["columns"].append({
        "object_id": 5, "class_name": "ElPilarFundacao", "name": "P3",
        "floor_id": 1, "xy_raw": [1000, 0], "section_id": 102,
        "rectangular_dimensions_candidate_raw": [20, 30], "referenced_by_beam": False,
        "region_role": "base_cad",
        "foundation_raw": {"kind": "pile_cap", "bar_height_raw": 52,
                           "height_reference": "floor_to_foundation_bar_bottom"},
    })
    launch["inventory"].append({"class_name": "ElPilarFundacao", "count": 1})
    after = PrjImporter().convert(launch, ImportOptions()).report["member_sources"]
    assert all(after[name]["object_id"] == source["object_id"] for name, source in before.items())


def test_3075_additional_section_fields_are_reported(launch):
    launch["internal_version_code"] = 3075
    launch["sections"][0]["geometric_values_raw"] = [45, 10, 0, 0, 20, 50, 0]
    result = PrjImporter().convert(launch, ImportOptions())
    sections = result.report["geometry_mapping"]["section_review"]
    assert len(sections) == 2
    assert all(item["rectangular_candidate_mm"] == [200, 500] for item in sections)
    assert all(item["section_values_raw"] == [45, 10, 0, 0, 20, 50, 0] for item in sections)
    assert all(result.report["member_sources"][item["member_name"]]["section_requires_review"] for item in sections)


def test_individual_wood_material_uses_review_reference(launch):
    launch["beams"][0]["material_override"] = {
        "type": "Madeira", "class_name": "Dicotiledônea-C40",
        "class_values_raw": [0.00095, 74880.0, 3744.0, 4.5e-6],
    }
    result = PrjImporter().convert(launch, ImportOptions())
    model = StructuralModel()
    model.load_dict(result.project_data)
    beam_name = next(
        name for name, source in result.report["member_sources"].items()
        if source.get("material_override")
    )
    material = model.bars[beam_name].material
    assert model.material_types[material] == "Madeira"
    assert "revisão" in material
    assert result.report["member_sources"][beam_name]["material_override"]["class_values_raw"][1] == 74880
    assert any("madeira" in warning.lower() for warning in result.report["warnings"])




















def test_supported_extensions_case_insensitive():
    assert is_import_path("test.PRJ")
    assert is_import_path("test.PRJ.ZIP")
    assert not is_import_path("project.osa")
    assert not is_import_path("arbitrary.zip")
