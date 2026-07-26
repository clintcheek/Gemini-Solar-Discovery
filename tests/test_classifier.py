from solar_discovery.classifier import qualify_text


def test_explicit_solar_is_confirmed():
    result = qualify_text("All solar photovoltaic panels, inverters, and racking.")
    assert result.classification == "Confirmed Solar"
    assert result.score == 100
    assert "solar" in result.matched_keywords


def test_pv_system_is_confirmed_or_likely():
    result = qualify_text("Collateral includes a PV system and microinverters.")
    assert result.score >= 80
    assert result.classification == "Confirmed Solar"


def test_generic_hvac_is_not_confirmed_solar():
    result = qualify_text("PACE assessment for HVAC and roofing improvements.")
    assert result.classification == "Unqualified"
