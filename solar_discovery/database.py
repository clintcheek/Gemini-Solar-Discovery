from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .classifier import qualify_record
from .models import DocumentRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    borrower TEXT NOT NULL DEFAULT '',
    property_address TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    lender TEXT NOT NULL DEFAULT '',
    loan_date TEXT NOT NULL DEFAULT '',
    loan_amount NUMERIC,
    county TEXT NOT NULL DEFAULT '',
    document_number TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Active',
    grantor TEXT NOT NULL DEFAULT '',
    grantee TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    town TEXT NOT NULL DEFAULT '',
    legal_description TEXT NOT NULL DEFAULT '',
    book_volume_page TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    search_term TEXT NOT NULL DEFAULT '',
    solar_score INTEGER NOT NULL DEFAULT 0,
    solar_classification TEXT NOT NULL DEFAULT 'Unqualified',
    matched_keywords TEXT NOT NULL DEFAULT '[]',
    qualification_source TEXT NOT NULL DEFAULT 'recorder_metadata',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(county, document_number, grantor, grantee)
);

CREATE INDEX IF NOT EXISTS idx_filings_lender ON filings(lender);
CREATE INDEX IF NOT EXISTS idx_filings_date ON filings(loan_date);
CREATE INDEX IF NOT EXISTS idx_filings_county ON filings(county);
CREATE INDEX IF NOT EXISTS idx_filings_document ON filings(document_number);
CREATE INDEX IF NOT EXISTS idx_filings_solar_score ON filings(solar_score);

CREATE TABLE IF NOT EXISTS checkpoints(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

UPSERT = """
INSERT INTO filings(
    borrower, property_address, phone, email, lender, loan_date, loan_amount,
    county, document_number, status, grantor, grantee, document_type, town,
    legal_description, book_volume_page, source_url, search_term
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(county, document_number, grantor, grantee) DO UPDATE SET
    borrower=excluded.borrower,
    property_address=CASE WHEN excluded.property_address <> '' THEN excluded.property_address ELSE filings.property_address END,
    phone=CASE WHEN excluded.phone <> '' THEN excluded.phone ELSE filings.phone END,
    email=CASE WHEN excluded.email <> '' THEN excluded.email ELSE filings.email END,
    lender=excluded.lender,
    loan_date=excluded.loan_date,
    loan_amount=COALESCE(excluded.loan_amount, filings.loan_amount),
    status=excluded.status,
    document_type=excluded.document_type,
    town=excluded.town,
    legal_description=excluded.legal_description,
    book_volume_page=excluded.book_volume_page,
    source_url=CASE WHEN excluded.source_url <> '' THEN excluded.source_url ELSE filings.source_url END,
    search_term=excluded.search_term,
    updated_at=CURRENT_TIMESTAMP
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate_legacy_records()
        self.conn.executescript(SCHEMA)
        self._add_missing_columns()
        self.conn.commit()

    def _add_missing_columns(self) -> None:
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(filings)")}
        additions = {
            "solar_score": "INTEGER NOT NULL DEFAULT 0",
            "solar_classification": "TEXT NOT NULL DEFAULT 'Unqualified'",
            "matched_keywords": "TEXT NOT NULL DEFAULT '[]'",
            "qualification_source": "TEXT NOT NULL DEFAULT 'recorder_metadata'",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE filings ADD COLUMN {name} {definition}")

    def _migrate_legacy_records(self) -> None:
        existing = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='records'"
        ).fetchone()
        if not existing:
            return
        self.conn.executescript(SCHEMA)
        self.conn.execute("""
            INSERT OR IGNORE INTO filings(
                borrower, property_address, phone, email, lender, loan_date,
                loan_amount, county, document_number, status, source_url, search_term
            )
            SELECT name, property_address, phone, email, lender, loan_date,
                   loan_amount, 'Dallas', instrument_id, 'Active', source_url, search_term
            FROM records
        """)
        self.conn.execute("ALTER TABLE records RENAME TO records_v01_archive")
        self.conn.commit()

    def save(self, record: DocumentRecord) -> None:
        record.normalize()
        self.conn.execute(UPSERT, record.database_values())
        self.conn.commit()

    def save_many(self, records: Iterable[DocumentRecord]) -> int:
        normalized = [record.normalize().database_values() for record in records]
        if not normalized:
            return 0
        self.conn.executemany(UPSERT, normalized)
        self.conn.commit()
        return len(normalized)

    def qualify_all(self) -> int:
        records = self.rows()
        updates = []
        for record in records:
            result = qualify_record(record)
            updates.append((
                result.score,
                result.classification,
                result.keywords_json(),
                "recorder_metadata",
                record.county,
                record.document_number,
                record.grantor,
                record.grantee,
            ))
        self.conn.executemany("""
            UPDATE filings
            SET solar_score=?, solar_classification=?, matched_keywords=?,
                qualification_source=?, updated_at=CURRENT_TIMESTAMP
            WHERE county=? AND document_number=? AND grantor=? AND grantee=?
        """, updates)
        self.conn.commit()
        return len(updates)

    def checkpoint(self, key: str, value: object | None = None) -> str:
        if value is None:
            row = self.conn.execute("SELECT value FROM checkpoints WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else "0"
        self.conn.execute("""
            INSERT INTO checkpoints(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, str(value)))
        self.conn.commit()
        return str(value)

    def rows(self) -> list[DocumentRecord]:
        rows = self.conn.execute("""
            SELECT borrower, property_address, phone, email, lender, loan_date,
                   loan_amount, county, document_number, status, grantor, grantee,
                   document_type, town, legal_description, book_volume_page,
                   source_url, search_term, solar_score, solar_classification,
                   matched_keywords, qualification_source
            FROM filings
            ORDER BY solar_score DESC, loan_date DESC, borrower, document_number
        """).fetchall()
        return [DocumentRecord.from_mapping(dict(row)) for row in rows]

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0])

    def qualified_count(self, minimum_score: int = 20) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM filings WHERE solar_score >= ?", (minimum_score,)
        ).fetchone()[0])

    def close(self) -> None:
        self.conn.close()
