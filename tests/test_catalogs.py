from osa.data import CatalogLoader


def test_gerdau_w_catalog_has_all_migrated_profiles_and_named_units():
    profiles = CatalogLoader().w_profiles()
    assert len(profiles) == 100
    required = {"name", "mass_kg_m", "d_mm", "bf_mm", "tw_mm", "tf_mm", "area_cm2"}
    assert all(required <= profile.keys() for profile in profiles)


def test_material_catalog_contains_the_three_defaults():
    names = {item["name"] for item in CatalogLoader().materials()}
    assert names == {"Aço Estrutural", "Concreto Estrutural", "Madeira Estrutural"}
