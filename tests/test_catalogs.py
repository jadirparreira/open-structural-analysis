from osa.data import CatalogLoader


def test_gerdau_w_catalog_has_all_migrated_profiles_and_named_units():
    profiles = CatalogLoader().w_profiles()
    assert len(profiles) == 108
    required = {"name", "d_mm", "bf_mm", "tw_mm", "tf_mm"}
    assert all(required <= profile.keys() for profile in profiles)
    assert all("mass_kg_m" not in profile for profile in profiles)


def test_laminated_catalogs_keep_only_profile_geometry():
    catalog_families = CatalogLoader().section_families("Aço")
    assert [item["name"] for item in catalog_families[:5]] == [
        "W Laminado", "I Laminado", "U Laminado", "L Laminado", "T Laminado"
    ]
    families = {item["name"]: item["profiles"] for item in catalog_families}
    assert {"b_mm", "t_mm"} <= families["L Laminado"][0].keys()
    assert {"d_mm", "bf_mm", "tw_mm", "tf_mm"} <= families["T Laminado"][0].keys()
    assert len(families["I Laminado"]) == 8
    assert families["I Laminado"][0] == {
        "name": "I 76 x 8.5",
        "d_mm": 76.2,
        "bf_mm": 59.18,
        "tw_mm": 4.32,
        "tf_mm": 6.6,
    }
    calculated_fields = {"mass_kg_m", "area_cm2", "Ix_cm4", "Iy_cm4", "It_cm4", "Cw_cm6"}
    for family in ("W Laminado", "I Laminado", "U Laminado", "L Laminado", "T Laminado"):
        assert all(not (calculated_fields & profile.keys()) for profile in families[family])


def test_material_catalog_contains_the_three_defaults():
    names = {item["name"] for item in CatalogLoader().materials()}
    assert names == {"Aço Estrutural", "Concreto Estrutural", "Madeira Estrutural"}


def test_wood_catalog_exposes_the_three_parametric_solid_sections():
    names = [item["name"] for item in CatalogLoader().section_families("Madeira")]
    assert names == ["Circular", "Quadrada", "Retangular"]


def test_formed_steel_families_use_the_current_names():
    names = [item["name"] for item in CatalogLoader().section_families("Aço")]
    assert names[5:9] == ["U Formado", "C Formado", "Z Formado", "L Formado"]
    assert "Z Enrijecido Formado" not in names
