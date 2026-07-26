from __future__ import annotations

import csv
from pathlib import Path

from .parser import parse_results

PORTAL = "https://dallas.tx.publicsearch.us/"


def test_saved_pages(root: Path) -> Path:
    debug = root / "data" / "debug"
    output = root / "output"
    output.mkdir(parents=True, exist_ok=True)
    report = output / "Dallas_Parser_Test.csv"

    rows: list[list[object]] = []
    for path in sorted(debug.glob("result_*.html")):
        term = path.stem.split("_", 2)[-1].replace("_", " ")
        records = parse_results(path.read_text(encoding="utf-8", errors="ignore"), term, PORTAL)
        rows.append([path.name, term, len(records), " | ".join(r.document_number for r in records[:10])])

    with report.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Saved HTML", "Search Term", "Parsed Rows", "First Document Numbers"])
        writer.writerows(rows)
    return report
