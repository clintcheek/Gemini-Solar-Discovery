from datetime import date

from solar_discovery.dallas import DallasConnector, DateWindow


def test_parse_recording_date_common_formats():
    assert DallasConnector.parse_recording_date("07/25/2026") == date(2026, 7, 25)
    assert DallasConnector.parse_recording_date("2026-07-25") == date(2026, 7, 25)
    assert DallasConnector.parse_recording_date("Jul 25, 2026") == date(2026, 7, 25)
    assert DallasConnector.parse_recording_date("") is None


def test_date_window_contains_boundaries():
    window = DateWindow(date(2016, 7, 25), date(2026, 7, 25))
    assert window.contains(date(2016, 7, 25))
    assert window.contains(date(2026, 7, 25))
    assert not window.contains(date(2016, 7, 24))
