from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from .models import DocumentRecord

# High-confidence equipment and legal-description terms. Lender names are not required.
SOLAR_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("solar", re.compile(r"\bsolar\b", re.I), 100),
    ("photovoltaic", re.compile(r"\bphotovoltaic(?:s)?\b", re.I), 100),
    ("solar pv", re.compile(r"\bsolar\s+P\.?V\.?\b", re.I), 100),
    ("pv system", re.compile(r"\bP\.?V\.?\s+(?:system|array|panel|module|equipment)\b", re.I), 90),
    ("solar panel", re.compile(r"\bsolar\s+(?:panel|module|array|equipment|system)s?\b", re.I), 100),
    ("inverter", re.compile(r"\b(?:micro)?inverter(?:s)?\b", re.I), 35),
    ("racking", re.compile(r"\bsolar\s+racking\b|\bracking\s+(?:for|of)\s+(?:a\s+)?solar\b", re.I), 80),
    ("net metering", re.compile(r"\bnet[- ]meter(?:ing|ed)?\b", re.I), 45),
    ("distributed generation", re.compile(r"\bdistributed\s+generation\b", re.I), 35),
    ("energy storage", re.compile(r"\benergy\s+storage\s+(?:system|equipment|battery|unit)s?\b", re.I), 25),
    ("clean energy assessment", re.compile(r"\bclean\s+energy\s+assessment\b", re.I), 20),
)

NEGATIVE_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("automotive inverter", re.compile(r"\b(?:vehicle|automobile|truck|marine)\b.{0,80}\binverter\b", re.I | re.S), -40),
    ("hvac only", re.compile(r"\bHVAC\b|\bheating[,]? ventilation[,]? and air conditioning\b", re.I), -10),
    ("roof only", re.compile(r"\broof(?:ing)?\b", re.I), -5),
)


@dataclass(frozen=True, slots=True)
class Qualification:
    score: int
    classification: str
    matched_keywords: tuple[str, ...]

    def keywords_json(self) -> str:
        return json.dumps(self.matched_keywords, ensure_ascii=False)


def record_text(record: DocumentRecord) -> str:
    """Combine all currently available recorder fields into searchable text."""
    return "\n".join(
        value
        for value in (
            record.document_type,
            record.grantor,
            record.grantee,
            record.legal_description,
            record.town,
            record.book_volume_page,
            record.search_term,
        )
        if value
    )


def qualify_text(text: str) -> Qualification:
    normalized = " ".join((text or "").split())
    score = 0
    matches: list[str] = []

    for name, pattern, weight in SOLAR_PATTERNS:
        if pattern.search(normalized):
            score += weight
            matches.append(name)

    for name, pattern, weight in NEGATIVE_PATTERNS:
        if pattern.search(normalized):
            score += weight
            matches.append(name)

    score = max(0, min(score, 100))
    if score >= 80:
        classification = "Confirmed Solar"
    elif score >= 50:
        classification = "Likely Solar"
    elif score >= 20:
        classification = "Possible Solar"
    else:
        classification = "Unqualified"

    return Qualification(score, classification, tuple(dict.fromkeys(matches)))


def qualify_record(record: DocumentRecord) -> Qualification:
    return qualify_text(record_text(record))


def qualify_records(records: Iterable[DocumentRecord]) -> list[tuple[DocumentRecord, Qualification]]:
    return [(record, qualify_record(record)) for record in records]
