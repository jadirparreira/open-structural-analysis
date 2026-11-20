"""NBR 14762:2010, 9.6.2: independent direct values in kN and cm²."""

import pytest

from osa.verification.cold_formed import tension_resistance


@pytest.mark.parametrize(("outside", "connection", "ct", "expected", "governing"), [
    (10.0, 10.0, 1.0, 250 / 1.1, "escoamento da seção bruta"),
    (5.0, 10.0, 1.0, 200 / 1.35, "ruptura fora da ligação"),
    (10.0, 7.0, 0.8, 224 / 1.65, "ruptura na ligação"),
])
def test_each_tension_limit_can_govern(outside, connection, ct, expected, governing):
    result = tension_resistance(gross_area_cm2=10, net_outside_cm2=outside,
                                net_connection_cm2=connection, fy_kn_cm2=25, fu_kn_cm2=40, ct=ct)
    assert result.resistance_kn == pytest.approx(expected)
    assert result.governing == governing


@pytest.mark.parametrize(("field", "value"), [
    ("gross_area_cm2", 0), ("net_outside_cm2", float("nan")),
    ("net_connection_cm2", float("inf")), ("ct", 1.1),
    ("net_connection_cm2", 10.1),
])
def test_tension_rejects_missing_or_inconsistent_connection_data(field, value):
    inputs = {"gross_area_cm2": 10., "net_outside_cm2": 8., "net_connection_cm2": 7.,
              "fy_kn_cm2": 25., "fu_kn_cm2": 40., "ct": .8}
    inputs[field] = value
    with pytest.raises(ValueError):
        tension_resistance(**inputs)
