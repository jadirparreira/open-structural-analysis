"""Contrato da importação: geometria, persistência e falhas transacionais."""

import base64
import copy
import hashlib
import json
import os
import struct
import zipfile
import zlib
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
from osa.transcriptions.prj import PrjImporter
from osa.transcriptions.prj_reader import Reader, extract, load_stream
from osa.transcriptions.prj_reader.decode import Decoder
from osa.transcriptions.plates import pending_plate_count


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


@pytest.fixture
def variant_prj(tmp_path):
    """Variantes sintéticas do binário real: alteram apenas tags de serialização.

    Não representam arquivos reais de outras versões do formato PRJ.
    """
    if not os.environ.get("OSA_TEST_PRJ"):
        pytest.skip("Defina OSA_TEST_PRJ para a regressão binária.")
    raw, source = load_stream(os.environ["OSA_TEST_PRJ"])
    reader = Reader(raw, source)

    def create(code, *, tags="all", broken=False):
        data = bytearray(raw)
        if tags == "root":
            struct.pack_into("<I", data, reader.classes["Projeto"][0].data_offset, code)
        else:
            for header in reader.headers:
                p = header.data_offset
                while p + 4 <= header.next_header_offset and reader.u32(p) == 3419:
                    struct.pack_into("<I", data, p, code)
                    p += 4
                if header.class_name == "QiUUID":
                    struct.pack_into("<I", data, header.data_offset, 106)
                elif header.class_name == "TSecaoMista":
                    struct.pack_into("<2I", data, header.data_offset, 106, 107)
        if broken:
            decoder = Decoder(reader)
            beam = decoder.beam(reader.classes["ElementoViga"][0])
            line = decoder.line(reader.by_id[beam["line_id"]])
            data[line["end"] - 1] = ord("!")
        target = tmp_path / f"variant_{code}_{tags}.prj"
        if tags == "root":
            target.write_bytes(data)
        else:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("__DADOS__", data)
        return target

    return create


@pytest.mark.parametrize(
    "code,tags", [(2281, "root"), (2281, "all"), (3028, "all"), (9999, "all")]
)
def test_binary_variants_use_record_layout_instead_of_version_gate(
    variant_prj, code, tags, tmp_path
):
    source = variant_prj(code, tags=tags)
    original = source.read_bytes()
    model = StructuralModel()
    report = ProjectService(model).load(source)
    assert (len(model.nodes), len(model.bars), len(model.rigid_bars)) == (28, 16, 16)
    assert report["internal_version_code"] == code
    assert report["compatibility"]["mode"] == "structural_probe"
    assert not report["decode_warnings"]
    target = tmp_path / "converted_variant.osa"
    ProjectService(model).save(target)
    restored = StructuralModel()
    ProjectService(restored).load(target)
    assert restored.as_dict() == model.as_dict()
    assert source.read_bytes() == original


@pytest.mark.parametrize("code", [2281, 3419])
def test_incompatible_binary_layout_keeps_current_model(variant_prj, code):
    source = variant_prj(code, broken=True)
    original = source.read_bytes()
    model = StructuralModel()
    model.add_node("Keep", 1, 2, 3)
    snapshot = model.as_dict()
    with pytest.raises(ProjectImportError) as error:
        ProjectService(model).load(source)
    assert f"código interno {code}" in str(error.value)
    assert "ElementoViga" in str(error.value)
    assert "0x" in str(error.value)
    assert model.as_dict() == snapshot
    assert source.read_bytes() == original


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


@pytest.mark.skipif(
    not os.environ.get("OSA_WANDER_PRJ"),
    reason="Defina OSA_WANDER_PRJ para conferir o PRJ 3075 real.",
)
def test_wander_real_bar_import_materials_and_round_trip(tmp_path):
    result = PrjImporter().read(os.environ["OSA_WANDER_PRJ"], ImportOptions())
    counts = result.report["counts"]
    assert (counts["beam_groups"], counts["beams"], counts["columns"]) == (105, 318, 109)
    assert (counts["foundation_columns"], counts["isolated_foundation_columns"]) == (24, 4)
    assert (counts["excluded_lower_column_segments"], counts["excluded_column_segments"]) == (8, 8)
    assert counts["excluded_elements"]["lajes"] == 158
    sections = result.report["geometry_mapping"]["section_review"]
    assert {item["beam_name"] for item in sections} == {"V6_T1", "V6_T2"}
    assert len(result.report["geometry_mapping"]["omitted_columns"]) == 16
    beams = result.report["source_evidence"]["beams"]
    first = next(item for item in beams if item["name"] == "V6_T1")
    assert first["end_offsets_xy_raw"] == pytest.approx([19, 30, -20, 0])
    assert first["offsets_geometry_check"] and first["wall_ids"]

    axes = {
        (item["name"], item["floor_id"]): item["axis_xy_raw"]
        for item in result.report["geometry_mapping"]["column_axes"]
    }
    assert axes["P1", 1] == pytest.approx([170.21, 2054.7])
    assert axes["P2", 2] == pytest.approx([660.21, 2054.7])
    assert axes["P10", 1] == pytest.approx([170.21, 1187.7])
    assert axes["P10", 5] == pytest.approx([170.21, 1182.7])
    assert axes["P29", 1] == pytest.approx([205.21, 2054.7])

    model = StructuralModel()
    model.load_dict(result.project_data)
    source_map = result.report["member_sources"]
    pillar = next(
        name for name, source in source_map.items()
        if source["kind"] == "column" and source["original_name"] == "P10"
        and source["floor_id"] == 5
    )
    pillar_top = model.nodes[model.bars[pillar].end_node]
    assert (pillar_top.x, pillar_top.y) == pytest.approx((1.7021, 11.827))
    beam_name = next(
        name for name, source in source_map.items()
        if source["kind"] == "beam" and source["original_name"] == "V2_T1"
        and source["floor_id"] == 1
    )
    beam_start = model.nodes[model.bars[beam_name].start_node]
    assert (beam_start.x, beam_start.y) == pytest.approx((1.7971, 20.547))
    wood_names = [
        name for name, source in result.report["member_sources"].items()
        if source.get("material_override")
    ]
    assert {result.report["member_sources"][name]["original_name"] for name in wood_names} == {"G1", "G2", "G3"}
    assert all(model.material_types[model.bars[name].material] == "Madeira" for name in wood_names)
    path = tmp_path / "wander.osa"
    ProjectRepository().save(model, path)
    restored = StructuralModel()
    ProjectRepository().load(restored, path)
    assert len(restored.bars) == 427
    assert restored.import_metadata["geometry_mapping"]["section_review"] == sections
    assert all(restored.material_types[restored.bars[name].material] == "Madeira" for name in wood_names)


@pytest.mark.skipif(
    not os.environ.get("OSA_BRUNO_PRJ"),
    reason="Defina OSA_BRUNO_PRJ para conferir o perfil de bloco real.",
)
def test_bruno_foundation_bar_heights_and_mismatched_evidence():
    raw, source = load_stream(os.environ["OSA_BRUNO_PRJ"])
    reader = Reader(raw, source)
    decoder = Decoder(reader)
    pillars = [decoder.column(header) for header in reader.classes["ElPilarFundacao"]]
    assert len(pillars) == 26
    assert all(p["foundation_raw"]["bar_height_raw"] == 52 for p in pillars)
    assert sum(p["foundation_raw"]["height_corroboration"] == "column_gravity" for p in pillars) == 22

    first = reader.classes["ElPilarFundacao"][0]
    height_field = next(
        field for field in reader.fields
        if field["object_id"] == first.serial_id and field["field"] == "foundation_bar_height"
    )
    modified = bytearray(raw)
    struct.pack_into("<d", modified, height_field["offset"], 53)
    changed = Reader(bytes(modified), source)
    pillar = Decoder(changed).column(changed.classes["ElPilarFundacao"][0])
    assert pillar["foundation_raw"]["kind"] == "unmapped_foundation_geometry"


@pytest.mark.skipif(
    not os.environ.get("OSA_TEST_PRJ"),
    reason="Defina OSA_TEST_PRJ para alterar somente os códigos brutos de apoio.",
)
def test_reader_preserves_unmapped_support_codes_without_assigning_restraints():
    raw, source = load_stream(os.environ["OSA_TEST_PRJ"])
    reader = Reader(raw, source)
    h = reader.classes["ElPilarFundacao"][0]
    Decoder(reader).column(h)
    offsets = {
        field["field"]: field["offset"]
        for field in reader.fields
        if field["object_id"] == h.serial_id
    }
    data = bytearray(raw)
    flags = [0, 2, 5, 1, 0, 7]
    struct.pack_into("<I", data, offsets["foundation_switch_raw"], 7)
    struct.pack_into("<6I", data, offsets["foundation_six_flags_raw"], *flags)
    changed = Reader(bytes(data))
    footing = Decoder(changed).column(changed.classes["ElPilarFundacao"][0])[
        "foundation_raw"
    ]
    assert footing["six_flags_raw"] == flags
    assert footing["switch_raw"] == 7
    assert footing["settlement_depth_raw"] == 150
    assert footing["support_mapping"] == "pending"


@pytest.mark.skipif(
    not os.environ.get("OSA_FOUNDATIONS_PRJ"),
    reason="Defina OSA_FOUNDATIONS_PRJ para o PRJ real 2281.",
)
def test_real_2281_foundation_records_and_optional_footing_data():
    source = Path(os.environ["OSA_FOUNDATIONS_PRJ"])
    original = source.read_bytes()
    reader = Reader(*load_stream(source))
    decoder = Decoder(reader)
    columns = [decoder.column(h) for h in reader.classes["ElPilarFundacao"]]
    assert len(columns) == 22
    assert {column["name"] for column in columns} == {f"P{i}" for i in range(1, 23)}
    for column in columns:
        foundation = column["foundation_raw"]
        assert foundation["settlement_depth_raw"] == 150
        assert foundation["kind"] == "pad_footing"
        assert foundation["layout_prefix_size"] == 25
        assert (
            reader.by_id[foundation["gravity_object_id"]].class_name
            == "TDadosGravSapata"
        )
        assert reader.bytes(column["end"] - 1, 1) == b"]"
    # Confere a alternativa de sapata quando o código passa pelo ramo 3075;
    # os bytes deste cenário sintético continuam sendo da amostra 2281.
    fallback_reader = Reader(*load_stream(source))
    fallback_reader.version = 3075
    fallback = Decoder(fallback_reader).column(fallback_reader.classes["ElPilarFundacao"][0])
    assert fallback["foundation_raw"]["kind"] == "pad_footing"
    assert fallback["foundation_raw"]["settlement_depth_raw"] == 150
    assert source.read_bytes() == original


@pytest.fixture(scope="module")
def arara_source():
    if not os.environ.get("OSA_FOUNDATIONS_PRJ"):
        pytest.skip("Defina OSA_FOUNDATIONS_PRJ para o PRJ real Arara Azul.")
    source = Path(os.environ["OSA_FOUNDATIONS_PRJ"])
    assert (
        hashlib.sha256(source.read_bytes()).hexdigest()
        == "b609beeeb2515c67f7c260d92a2fd01be2c4db98c571457cf296c866dfd5a993"
    )
    return source


@pytest.fixture(scope="module")
def arara_launch(arara_source):
    return extract(Reader(*load_stream(arara_source)))


def test_real_arara_geometry_all_spans_and_native_round_trip(arara_source, tmp_path):
    model = StructuralModel()
    report = ProjectService(model).load(arara_source)
    assert (len(model.nodes), len(model.bars), len(model.rigid_bars)) == (225, 145, 133)
    expected_counts = {
        "nodes": 225,
        "members": 145,
        "beams": 101,
        "beam_groups": 30,
        "beam_segments": 101,
        "intermediate_points": 26,
        "columns": 44,
        "rigid_links": 133,
        "applied_loads": 0,
        "support_candidates": 22,
        "pending_plates": 0,
        "preserved_wall_records": 54,
    }
    assert {key: report["counts"][key] for key in expected_counts} == expected_counts
    assert not report["decode_warnings"]
    assert not model.actions
    assert all(not any(node.supports) for node in model.nodes.values())
    assert all(not any(bar.releases) for bar in model.bars.values())
    assert {node.z for node in model.nodes.values()} == {-1.5, 0, 5}
    assert all(
        model.nodes[item["node_name"]].z == -1.5
        and item["mapping_status"] == "pending_support_calibration"
        for item in report["support_candidates"]
    )
    evidence = report["source_evidence"]
    groups = {group["object_id"]: group for group in evidence["beam_groups"]}
    assert len(groups) == 30
    assert sum(group["segment_count"] for group in groups.values()) == 101
    assert any(group["segment_count"] > 1 for group in groups.values())
    assert all(group["object_end_known"] is False for group in groups.values())
    assert len(evidence["walls"]) == 54
    assert any(wall["load_data_raw"] for wall in evidence["walls"])
    assert len(evidence["points"]) == 26
    assert any(point["action_records_raw"] for point in evidence["points"])
    segments = {beam["segment_id"]: beam for beam in evidence["beams"]}
    imported_ids = set()
    for name, origin in report["member_sources"].items():
        if origin["kind"] != "beam":
            continue
        segment = segments[origin["segment_id"]]
        imported_ids.add(origin["segment_id"])
        group = groups[origin["beam_object_id"]]
        assert segment["segment_id"] in group["segment_ids"]
        assert segment["offsets_geometry_check"]
        bar = model.bars[name]
        for node_name, coords in (
            (bar.start_node, segment["xy_i_raw"]),
            (bar.end_node, segment["xy_j_raw"]),
        ):
            node = model.nodes[node_name]
            assert (node.x, node.y) == pytest.approx([v * 0.01 for v in coords])
    assert imported_ids == set(segments)
    used_nodes = {
        name
        for bar in (*model.bars.values(), *model.rigid_bars.values())
        for name in (bar.start_node, bar.end_node)
    }
    assert used_nodes == set(model.nodes)
    target = tmp_path / "arara.osa"
    ProjectService(model).save(target)
    restored = StructuralModel()
    ProjectService(restored).load(target)
    assert restored.as_dict() == model.as_dict()
    assert (
        hashlib.sha256(arara_source.read_bytes()).hexdigest()
        == report["source"]["container_sha256"]
    )


@pytest.mark.parametrize("change", ["missing_span", "repeated_span", "unknown_point"])
def test_arara_rejects_omissions_and_unresolved_span_references(arara_launch, change):
    assert arara_launch["decode_errors"] == []
    data = copy.deepcopy(arara_launch)
    if change == "missing_span":
        data["beams"].pop()
    elif change == "repeated_span":
        data["beams"][-1]["segment_id"] = data["beams"][0]["segment_id"]
    else:
        point_ids = {point["object_id"] for point in data["points"]}
        beam = next(beam for beam in data["beams"] if beam["support_j_id"] in point_ids)
        beam["support_j_id"] = -1
    with pytest.raises(ProjectImportError):
        PrjImporter().convert(data, ImportOptions())


@pytest.mark.parametrize("record", ["wall", "later_span"])
def test_arara_corrupt_wall_or_later_span_keeps_current_model(
    arara_source, record, tmp_path
):
    reader = Reader(*load_stream(arara_source))
    decoder = Decoder(reader)
    if record == "wall":
        value = decoder.wall(reader.classes["Parede"][0])
    else:
        groups = [decoder.beam(h) for h in reader.classes["ElementoViga"]]
        group = next(group for group in reversed(groups) if group["segment_count"] > 1)
        value = group["segments"][-1]
    data = bytearray(reader.data)
    data[value["end"] - 1] = ord("!")
    source = tmp_path / "corrupt.prj"
    source.write_bytes(data)
    model = StructuralModel()
    model.add_node("Keep", 1, 2, 3)
    snapshot = model.as_dict()
    with pytest.raises(ProjectImportError) as error:
        ProjectService(model).load(source)
    # A parede desta amostra está embutida em uma viga; a falha é reportada
    # pelo registro de lançamento que tentou decodificá-la.
    assert "ElementoViga" in str(error.value)
    assert "código interno 2281" in str(error.value)
    assert model.as_dict() == snapshot
    assert source.read_bytes() == data


def test_supported_extensions_case_insensitive():
    assert is_import_path("test.PRJ")
    assert is_import_path("test.PRJ.ZIP")
    assert not is_import_path("project.osa")
    assert not is_import_path("arbitrary.zip")


@pytest.mark.skipif(
    not os.environ.get("OSA_TEST_PRJ"),
    reason="Defina OSA_TEST_PRJ para o teste com PRJ real.",
)
def test_real_prj_open_save_reopen(tmp_path):
    source = Path(os.environ["OSA_TEST_PRJ"])
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    model = StructuralModel()
    report = ProjectService(model).load(source)
    assert (len(model.nodes), len(model.bars), len(model.rigid_bars)) == (28, 16, 16)
    assert len(model.actions) == 0
    base_node = report["support_candidates"][0]["node_name"]
    assert model.nodes[base_node].z == pytest.approx(-1.5)
    assert pending_plate_count(report) == 2
    assert [
        (plate["name"], plate["floor_id"])
        for plate in report["plate_transfer"]["records"]
    ] == [("L1", 1), ("L1", 2)]
    assert all(
        member["member_name"]
        for plate in report["plate_transfer"]["records"]
        for member in plate["boundary_members"]
    )
    raw, _ = load_stream(source)
    for slab in report["source_evidence"]["slabs"]:
        region = slab["source_region"]
        assert (
            zlib.decompress(base64.b64decode(region["data"]))
            == raw[region["offset"] : region["end_offset"]]
        )
        assert region["object_end_known"] is False
    with pytest.raises(ValueError, match="placas"):
        ProjectService(model).confirm_import_review()
    with pytest.raises(ValueError, match="placas"):
        require_import_review(model)
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
