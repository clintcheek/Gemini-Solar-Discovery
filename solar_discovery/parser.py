from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import DocumentRecord

SPACE = re.compile(r"\s+")
MONEY = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{2})?)")
ADDRESS = re.compile(
    r"\b\d{1,7}\s+[A-Za-z0-9.'#\- ]{2,70}\s+"
    r"(?:ST|STREET|AVE|AVENUE|RD|ROAD|DR|DRIVE|LN|LANE|CT|COURT|"
    r"BLVD|BOULEVARD|WAY|PKWY|PARKWAY|PL|PLACE|TRL|TRAIL|CIR|CIRCLE|"
    r"HWY|HIGHWAY|TER|TERRACE)\b(?:[^\n|]{0,60})?",
    re.IGNORECASE,
)

HEADER_ALIASES = {
    "grantor": {"grantor", "seller", "debtor", "borrower"},
    "grantee": {"grantee", "buyer", "secured party", "lender"},
    "document_type": {"doc type", "document type", "instrument type", "type"},
    "loan_date": {"recorded date", "recording date", "filed date", "date"},
    "document_number": {"doc number", "document number", "instrument number", "doc #", "document #"},
    "book_volume_page": {"book/volume/page", "book volume page", "book/page", "volume/page"},
    "town": {"town", "city"},
    "legal_description": {"legal description", "legal", "property description"},
}

LABEL_PATTERN = re.compile(
    r"(?P<label>Grantor|Seller|Debtor|Borrower|Grantee|Buyer|Secured Party|Lender|"
    r"Doc(?:ument)?\s*(?:Number|#)|Instrument\s*Number|Doc(?:ument)?\s*Type|Instrument\s*Type|"
    r"Recorded\s*Date|Recording\s*Date|Filed\s*Date|Book/Volume/Page|Book/Page|Town|City|"
    r"Legal\s*Description|Property\s*Description)\s*[:\-]?\s*",
    re.IGNORECASE,
)


def clean(value: object) -> str:
    return SPACE.sub(" ", str(value or "")).strip()


def canonical_header(value: str) -> str:
    candidate = clean(value).lower().replace("\u00a0", " ")
    candidate = re.sub(r"[.:]+$", "", candidate)
    for canonical, aliases in HEADER_ALIASES.items():
        if candidate in aliases:
            return canonical
    return candidate


def _row_cells(row: Tag) -> list[Tag]:
    cells = row.find_all(["th", "td"], recursive=False)
    if cells:
        return cells
    return row.select(":scope > [role='cell'], :scope > [role='columnheader'], :scope > [role='gridcell']") or row.select(
        "[role='cell'],[role='columnheader'],[role='gridcell']"
    )


def _extract_link(cell: Tag | None, base_url: str) -> str:
    if cell is None:
        return ""
    link = cell.select_one("a[href]")
    return urljoin(base_url, link.get("href", "")) if link else ""


def _header_map(table: Tag) -> dict[int, str]:
    rows = table.select("tr,[role='row']")
    for row in rows[:10]:
        cells = _row_cells(row)
        labels = [canonical_header(c.get_text(" ", strip=True)) for c in cells]
        recognized = sum(label in HEADER_ALIASES for label in labels)
        if recognized >= 2:
            return {index: label for index, label in enumerate(labels)}
    return {}


def _candidate_tables(soup: BeautifulSoup) -> list[Tag]:
    candidates = list(soup.select("table,[role='table'],[role='grid']"))
    seen: set[int] = set()
    output: list[Tag] = []
    for candidate in candidates:
        identity = id(candidate)
        if identity not in seen:
            seen.add(identity)
            output.append(candidate)
    return output


def _status_for(document_type: str) -> str:
    value = document_type.lower()
    if any(word in value for word in ("release", "termination", "satisfaction", "discharge")):
        return "Released"
    if any(word in value for word in ("assignment", "amendment", "continuation", "change")):
        return "Changed"
    return "Active"


def _property_address(text: str) -> str:
    match = ADDRESS.search(text)
    return clean(match.group(0)) if match else ""


def _loan_amount(text: str) -> str | None:
    values: list[float] = []
    for match in MONEY.finditer(text):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return str(max(values)) if values else None


def _record(values: dict[str, str], row_text: str, term: str, base_url: str, county: str, source_url: str = "") -> DocumentRecord:
    document_type = values.get("document_type", "")
    grantor = values.get("grantor", "")
    grantee = values.get("grantee", "")
    return DocumentRecord.from_mapping({
        "borrower": grantor,
        "property_address": _property_address(" ".join((values.get("legal_description", ""), values.get("town", ""), row_text))),
        "lender": grantee or term,
        "loan_date": values.get("loan_date", ""),
        "loan_amount": _loan_amount(row_text),
        "county": county,
        "document_number": values.get("document_number", ""),
        "status": _status_for(document_type),
        "grantor": grantor,
        "grantee": grantee,
        "document_type": document_type,
        "town": values.get("town", ""),
        "legal_description": values.get("legal_description", ""),
        "book_volume_page": values.get("book_volume_page", ""),
        "source_url": source_url,
        "search_term": term,
    })


def _parse_structured(soup: BeautifulSoup, term: str, base_url: str, county: str) -> list[DocumentRecord]:
    output: list[DocumentRecord] = []
    for table in _candidate_tables(soup):
        headers = _header_map(table)
        if not headers:
            continue
        for row in table.select("tr,[role='row']"):
            cells = _row_cells(row)
            if not cells or any(cell.name == "th" for cell in cells):
                continue
            values: dict[str, str] = {}
            for index, cell in enumerate(cells):
                header = headers.get(index)
                if header in HEADER_ALIASES:
                    values[header] = clean(cell.get_text(" ", strip=True))
            if not any(values.get(key) for key in ("document_number", "grantor", "grantee")):
                continue
            document_cell = next((cells[i] for i, header in headers.items() if header == "document_number" and i < len(cells)), None)
            output.append(_record(values, clean(row.get_text(" ", strip=True)), term, base_url, county,
                                  _extract_link(document_cell, base_url) or _extract_link(row, base_url)))
    return output


def _label_values(text: str) -> dict[str, str]:
    matches = list(LABEL_PATTERN.finditer(text))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = canonical_header(match.group("label"))
        if key in HEADER_ALIASES:
            values[key] = clean(text[start:end].strip(" :-|"))
    return values


def _parse_cards(soup: BeautifulSoup, term: str, base_url: str, county: str) -> list[DocumentRecord]:
    output: list[DocumentRecord] = []
    selectors = "article,.search-result,.searchResult,.result-card,.resultCard,[data-testid*='result'],[class*='result-item'],[class*='resultItem']"
    candidates = list(soup.select(selectors))
    if not candidates:
        candidates = [node for node in soup.find_all(["div", "li"]) if len(LABEL_PATTERN.findall(clean(node.get_text(" ", strip=True)))) >= 3]
    for node in candidates:
        text = clean(node.get_text(" ", strip=True))
        values = _label_values(text)
        if not any(values.get(key) for key in ("document_number", "grantor", "grantee")):
            continue
        output.append(_record(values, text, term, base_url, county, _extract_link(node, base_url)))
    return output


def parse_results(html: str, term: str, base_url: str, county: str = "Dallas") -> list[DocumentRecord]:
    """Parse Dallas result tables, ARIA grids, or labeled result cards."""
    soup = BeautifulSoup(html, "lxml")
    records = _parse_structured(soup, term, base_url, county)
    records.extend(_parse_cards(soup, term, base_url, county))

    output: list[DocumentRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        key = (record.county.casefold(), record.document_number.casefold(), record.grantor.casefold(), record.grantee.casefold())
        if key not in seen:
            seen.add(key)
            output.append(record)
    return output
