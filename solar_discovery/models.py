from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


@dataclass(slots=True)
class DocumentRecord:
    borrower: str = ""
    property_address: str = ""
    phone: str = ""
    email: str = ""
    lender: str = ""
    loan_date: str = ""
    loan_amount: Decimal | None = None
    county: str = "Dallas"
    document_number: str = ""
    status: str = "Active"

    grantor: str = ""
    grantee: str = ""
    document_type: str = ""
    town: str = ""
    legal_description: str = ""
    book_volume_page: str = ""
    source_url: str = ""
    search_term: str = ""
    solar_score: int = 0
    solar_classification: str = "Unqualified"
    matched_keywords: str = "[]"
    qualification_source: str = "recorder_metadata"

    def normalize(self) -> "DocumentRecord":
        for field_name in (
            "borrower", "property_address", "phone", "email", "lender",
            "loan_date", "county", "document_number", "status", "grantor",
            "grantee", "document_type", "town", "legal_description",
            "book_volume_page", "source_url", "search_term", "solar_classification",
            "matched_keywords", "qualification_source",
        ):
            setattr(self, field_name, _text(getattr(self, field_name)))

        if not self.borrower:
            self.borrower = self.grantor
        if not self.lender:
            self.lender = self.grantee or self.search_term
        if not self.status:
            self.status = "Active"
        return self

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "DocumentRecord":
        amount = values.get("loan_amount")
        parsed_amount: Decimal | None = None
        if amount not in (None, ""):
            try:
                parsed_amount = Decimal(str(amount).replace("$", "").replace(",", ""))
            except InvalidOperation:
                parsed_amount = None

        return cls(
            borrower=_text(values.get("borrower")),
            property_address=_text(values.get("property_address")),
            phone=_text(values.get("phone")),
            email=_text(values.get("email")),
            lender=_text(values.get("lender")),
            loan_date=_text(values.get("loan_date")),
            loan_amount=parsed_amount,
            county=_text(values.get("county")) or "Dallas",
            document_number=_text(values.get("document_number")),
            status=_text(values.get("status")) or "Active",
            grantor=_text(values.get("grantor")),
            grantee=_text(values.get("grantee")),
            document_type=_text(values.get("document_type")),
            town=_text(values.get("town")),
            legal_description=_text(values.get("legal_description")),
            book_volume_page=_text(values.get("book_volume_page")),
            source_url=_text(values.get("source_url")),
            search_term=_text(values.get("search_term")),
            solar_score=int(values.get("solar_score") or 0),
            solar_classification=_text(values.get("solar_classification")) or "Unqualified",
            matched_keywords=_text(values.get("matched_keywords")) or "[]",
            qualification_source=_text(values.get("qualification_source")) or "recorder_metadata",
        ).normalize()

    def database_values(self) -> tuple[Any, ...]:
        return (
            self.borrower,
            self.property_address,
            self.phone,
            self.email,
            self.lender,
            self.loan_date,
            str(self.loan_amount) if self.loan_amount is not None else None,
            self.county,
            self.document_number,
            self.status,
            self.grantor,
            self.grantee,
            self.document_type,
            self.town,
            self.legal_description,
            self.book_volume_page,
            self.source_url,
            self.search_term,
        )

    def excel_values(self) -> list[Any]:
        return [
            self.borrower,
            self.property_address,
            self.phone,
            self.email,
            self.lender,
            self.loan_date,
            float(self.loan_amount) if self.loan_amount is not None else None,
            self.county,
            self.document_number,
            self.status,
        ]
