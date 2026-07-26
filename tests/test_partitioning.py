from datetime import date
from pathlib import Path

from solar_discovery.dallas import DallasConnector, DateWindow


class DummyDB:
    def checkpoint(self, key, value=None):
        return "0" if value is None else str(value)


def test_search_url_contains_exact_date_partition(tmp_path: Path):
    connector = DallasConnector(DummyDB(), tmp_path)
    url = connector._search_url("UCC", DateWindow(date(2025, 1, 1), date(2025, 12, 31)))
    assert "recordedDateRange=20250101%2C20251231" in url
    assert "searchValue=UCC" in url


def test_partitions_are_newest_first_and_cover_window(tmp_path: Path):
    connector = DallasConnector(DummyDB(), tmp_path)
    parts = connector._date_partitions()
    assert parts[0].end == connector.date_window.end
    assert parts[-1].start == connector.date_window.start
    assert all(parts[i].start > parts[i + 1].start for i in range(len(parts) - 1))
