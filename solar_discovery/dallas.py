from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeout, sync_playwright

from .database import Database
from .models import DocumentRecord
from .parser import parse_results

PORTAL = "https://dallas.tx.publicsearch.us/"

# Collection is document-type-first. Lender names are intentionally excluded.
ACQUISITION_TERMS = [
    "UCC",
    "UCC FINANCING STATEMENT",
    "FIXTURE FILING",
    "PACE",
    "NOTICE OF ASSESSMENT",
]

_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%Y-%m-%d",
    "%m/%d/%y",
    "%Y%m%d",
    "%b %d, %Y",
    "%B %d, %Y",
)


@dataclass(frozen=True, slots=True)
class DateWindow:
    start: date
    end: date

    @classmethod
    def trailing_years(cls, years: int) -> "DateWindow":
        today = date.today()
        try:
            start = today.replace(year=today.year - years)
        except ValueError:
            # February 29 falls back to February 28 in non-leap cutoff years.
            start = today.replace(year=today.year - years, day=28)
        return cls(start=start, end=today)

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


@dataclass(slots=True)
class RawPage:
    search_term: str
    page_number: int
    html_file: str
    source_url: str
    captured_at_utc: str
    page_hash: str
    in_range_records: int
    oldest_record_date: str
    newest_record_date: str


@dataclass(slots=True)
class AcquisitionStats:
    pages_captured: int = 0
    rows_seen: int = 0
    rows_in_range: int = 0
    unique_in_range: int = 0
    rows_older_than_cutoff: int = 0
    rows_with_unreadable_dates: int = 0
    oldest_date_seen: str = ""
    newest_date_seen: str = ""
    stop_reason: str = "completed"


class DallasConnector:
    """Acquire recent Dallas UCC/PACE result pages, then parse them offline."""

    def __init__(self, db: Database, root: Path):
        self.db = db
        self.root = root
        # A versioned raw-data directory prevents Build 0003 pages from being reparsed.
        self.raw_root = root / "data" / "raw" / "dallas_v5_partitioned"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger("DallasConnector")
        self.max_pages = max(1, int(os.getenv("SOLAR_DISCOVERY_MAX_PAGES", "10000")))
        self.max_records = max(1, int(os.getenv("SOLAR_DISCOVERY_MAX_RECORDS", "5000")))
        self.lookback_years = max(1, int(os.getenv("SOLAR_DISCOVERY_LOOKBACK_YEARS", "10")))
        self.date_window = DateWindow.trailing_years(self.lookback_years)

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()[:80]

    def _term_dir(self, term: str) -> Path:
        path = self.raw_root / self._safe(term)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def parse_recording_date(value: str) -> date | None:
        cleaned = " ".join((value or "").replace("\u00a0", " ").split()).strip(" ,")
        if not cleaned:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        # Accept timestamps whose first ten characters are ISO dates.
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    def select_property(self, page: Page) -> None:
        candidates = [
            lambda: page.get_by_label("Department").select_option(label="Property Records"),
            lambda: page.get_by_text("Property Records", exact=True).click(timeout=4000),
        ]
        for action in candidates:
            try:
                action()
                return
            except Exception:
                continue

    def choose_ocr(self, page: Page) -> None:
        try:
            page.get_by_text("Search Index & Full Text (OCR)", exact=False).click(timeout=4000)
        except Exception:
            self.log.debug("OCR mode already selected or unavailable")

    @staticmethod
    def _fill_first_visible(locators: list[Locator], value: str) -> bool:
        for locator in locators:
            try:
                if locator.count() and locator.first.is_visible():
                    field = locator.first
                    input_type = (field.get_attribute("type") or "").lower()
                    if input_type == "date":
                        parsed = datetime.strptime(value, "%m/%d/%Y").date()
                        field.fill(parsed.isoformat())
                    else:
                        field.fill(value)
                    return True
            except Exception:
                continue
        return False

    def configure_recording_date_window(self, page: Page) -> bool:
        """Apply the 10-year recording-date window before the search is submitted."""
        start_text = self.date_window.start.strftime("%m/%d/%Y")
        end_text = self.date_window.end.strftime("%m/%d/%Y")

        start_locators = [
            page.get_by_label(re.compile(r"record(?:ed|ing)?\s+date\s+(?:from|start|begin)", re.I)),
            page.get_by_label(re.compile(r"(?:from|start|begin)\s+(?:recorded?\s+)?date", re.I)),
            page.get_by_placeholder(re.compile(r"(?:from|start|begin).*date|date.*(?:from|start|begin)", re.I)),
            page.locator("input[name*='record'][name*='from' i], input[id*='record'][id*='from' i]"),
            page.locator("input[name*='startDate' i], input[id*='startDate' i]"),
        ]
        end_locators = [
            page.get_by_label(re.compile(r"record(?:ed|ing)?\s+date\s+(?:to|end|through)", re.I)),
            page.get_by_label(re.compile(r"(?:to|end|through)\s+(?:recorded?\s+)?date", re.I)),
            page.get_by_placeholder(re.compile(r"(?:to|end|through).*date|date.*(?:to|end|through)", re.I)),
            page.locator("input[name*='record'][name*='to' i], input[id*='record'][id*='to' i]"),
            page.locator("input[name*='endDate' i], input[id*='endDate' i]"),
        ]

        start_ok = self._fill_first_visible(start_locators, start_text)
        end_ok = self._fill_first_visible(end_locators, end_text)
        if start_ok and end_ok:
            self.log.info("Applied portal date window: %s through %s", start_text, end_text)
            return True

        self.log.warning(
            "Portal date controls were not detected. The crawler will enforce the cutoff locally and stop on old pages."
        )
        return False

    def configure_newest_first(self, page: Page) -> bool:
        """Prefer descending recording date so the local cutoff can stop pagination safely."""
        select_candidates = [
            page.get_by_label(re.compile(r"sort", re.I)),
            page.locator("select[name*='sort' i], select[id*='sort' i]"),
        ]
        for locator in select_candidates:
            try:
                if not locator.count() or not locator.first.is_visible():
                    continue
                select = locator.first
                for label in (
                    "Recording Date (Newest First)",
                    "Recorded Date (Newest First)",
                    "Recording Date Descending",
                    "Recorded Date Descending",
                    "Newest First",
                ):
                    try:
                        select.select_option(label=label)
                        self.log.info("Applied newest-first sort: %s", label)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def fill(self, page: Page, term: str) -> bool:
        locators = [
            page.get_by_placeholder("Search for grantor/grantee, subdivision, doc type, or doc#"),
            page.get_by_label("Search Term"),
            page.locator("input[type='search']").first,
            page.locator("input[type='text']").first,
        ]
        for locator in locators:
            try:
                if locator.count() and locator.is_visible():
                    locator.fill(term)
                    return True
            except Exception:
                continue
        return False

    def submit(self, page: Page) -> bool:
        actions = [
            lambda: page.get_by_role("button", name="Search", exact=True).click(timeout=5000),
            lambda: page.locator("button[type='submit']").first.click(timeout=5000),
            lambda: page.locator("input[type='submit']").first.click(timeout=5000),
        ]
        for action in actions:
            try:
                action()
                return True
            except Exception:
                continue
        return False

    def wait_for_results(self, page: Page) -> None:
        selectors = [
            "table tbody tr",
            "[role='grid'] [role='row']",
            "text=No results",
            "text=0 results",
        ]
        for selector in selectors:
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=20000)
                return
            except Exception:
                continue
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PlaywrightTimeout:
            page.wait_for_timeout(1000)

    def _save_raw_page(
        self,
        page: Page,
        term: str,
        page_number: int,
        records: list[DocumentRecord],
    ) -> RawPage:
        html = page.content()
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        term_dir = self._term_dir(term)
        html_path = term_dir / f"page_{page_number:06d}.html"
        html_path.write_text(html, encoding="utf-8")

        parsed_dates = [self.parse_recording_date(record.loan_date) for record in records]
        valid_dates = sorted(value for value in parsed_dates if value is not None)
        in_range = sum(1 for value in valid_dates if self.date_window.contains(value))
        record = RawPage(
            search_term=term,
            page_number=page_number,
            html_file=str(html_path.relative_to(self.root)),
            source_url=page.url,
            captured_at_utc=datetime.now(timezone.utc).isoformat(),
            page_hash=digest,
            in_range_records=in_range,
            oldest_record_date=valid_dates[0].isoformat() if valid_dates else "",
            newest_record_date=valid_dates[-1].isoformat() if valid_dates else "",
        )
        with (term_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return record

    @staticmethod
    def _usable_next(locator: Locator) -> bool:
        try:
            if not locator.count() or not locator.is_visible() or not locator.is_enabled():
                return False
            aria_disabled = (locator.get_attribute("aria-disabled") or "").lower()
            disabled = locator.get_attribute("disabled")
            class_name = (locator.get_attribute("class") or "").lower()
            return aria_disabled != "true" and disabled is None and "disabled" not in class_name
        except Exception:
            return False

    def _next_button(self, page: Page) -> Locator | None:
        candidates = [
            page.get_by_role("button", name=re.compile(r"^next$|next page", re.I)).last,
            page.get_by_role("link", name=re.compile(r"^next$|next page", re.I)).last,
            page.locator("button[aria-label*='Next' i],a[aria-label*='Next' i]").last,
            page.locator("button[title*='Next' i],a[title*='Next' i]").last,
            page.locator(".pagination .next:not(.disabled),li.next:not(.disabled) a").last,
        ]
        for locator in candidates:
            if self._usable_next(locator):
                return locator
        return None

    def _advance(self, page: Page, previous_hash: str) -> bool:
        button = self._next_button(page)
        if button is None:
            return False
        try:
            button.scroll_into_view_if_needed(timeout=3000)
            button.click(timeout=8000)
            self.wait_for_results(page)
            for _ in range(20):
                current_hash = hashlib.sha256(page.content().encode("utf-8")).hexdigest()
                if current_hash != previous_hash:
                    return True
                page.wait_for_timeout(250)
        except Exception:
            self.log.debug("Unable to advance result page", exc_info=True)
        return False

    def _classify_page_dates(self, records: list[DocumentRecord], stats: AcquisitionStats) -> tuple[list[DocumentRecord], bool]:
        """Return in-range rows and whether this page proves the remaining pages are too old."""
        in_range: list[DocumentRecord] = []
        readable_dates: list[date] = []

        for record in records:
            stats.rows_seen += 1
            recording_date = self.parse_recording_date(record.loan_date)
            if recording_date is None:
                stats.rows_with_unreadable_dates += 1
                continue
            readable_dates.append(recording_date)
            if self.date_window.contains(recording_date):
                in_range.append(record)
                stats.rows_in_range += 1
            elif recording_date < self.date_window.start:
                stats.rows_older_than_cutoff += 1

        if readable_dates:
            page_oldest = min(readable_dates)
            page_newest = max(readable_dates)
            if not stats.oldest_date_seen or page_oldest.isoformat() < stats.oldest_date_seen:
                stats.oldest_date_seen = page_oldest.isoformat()
            if not stats.newest_date_seen or page_newest.isoformat() > stats.newest_date_seen:
                stats.newest_date_seen = page_newest.isoformat()

        # Stop only when every readable row is older than the cutoff and no row is unreadable.
        # This is safe when the portal is sorted newest-first; otherwise the hard page/record caps remain active.
        all_readable_rows_are_old = bool(readable_dates) and all(value < self.date_window.start for value in readable_dates)
        stop_for_age = all_readable_rows_are_old and len(readable_dates) == len(records)
        return in_range, stop_for_age

    def _date_partitions(self) -> list[DateWindow]:
        """Return newest-first yearly partitions, each safely below the portal's broad 10,000-result window."""
        partitions: list[DateWindow] = []
        cursor_end = self.date_window.end
        while cursor_end >= self.date_window.start:
            cursor_start = max(self.date_window.start, date(cursor_end.year, 1, 1))
            partitions.append(DateWindow(cursor_start, cursor_end))
            cursor_end = cursor_start.replace(day=1) - __import__("datetime").timedelta(days=1)
        return partitions

    @staticmethod
    def _search_url(term: str, window: DateWindow) -> str:
        params = {
            "department": "RP",
            "keywordSearch": "false",
            "recordedDateRange": f"{window.start:%Y%m%d},{window.end:%Y%m%d}",
            "searchOcrText": "false",
            "searchType": "quickSearch",
            "searchValue": term,
        }
        return f"{PORTAL}results?{urlencode(params)}"

    def acquire(self, terms: list[str] | None = None) -> AcquisitionStats:
        """Acquire partitioned Dallas searches without crossing the portal's 10,000-result ceiling."""
        terms = terms or ACQUISITION_TERMS
        stats = AcquisitionStats()
        observed_keys: set[tuple[str, str, str, str]] = set()
        partitions = self._date_partitions()
        start_partition = max(0, int(self.db.checkpoint("dallas_v5_partition")))
        start_term = max(0, int(self.db.checkpoint("dallas_v5_term")))
        start_page = max(1, int(self.db.checkpoint("dallas_v5_page")))

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome", headless=False)
            except Exception:
                browser = playwright.chromium.launch(headless=False)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="en-US")
            try:
                for partition_index in range(start_partition, len(partitions)):
                    window = partitions[partition_index]
                    term_begin = start_term if partition_index == start_partition else 0
                    for term_index in range(term_begin, len(terms)):
                        term = terms[term_index]
                        requested_page = start_page if partition_index == start_partition and term_index == term_begin else 1
                        label = f"{term}__{window.start:%Y%m%d}_{window.end:%Y%m%d}"
                        self.log.info(
                            "Acquiring %s for %s through %s (%d/%d partition)",
                            term, window.start, window.end, partition_index + 1, len(partitions),
                        )
                        page.goto(self._search_url(term, window), wait_until="domcontentloaded", timeout=60000)
                        self.wait_for_results(page)

                        current_page = 1
                        while current_page < requested_page:
                            prior = hashlib.sha256(page.content().encode("utf-8")).hexdigest()
                            if not self._advance(page, prior):
                                break
                            current_page += 1

                        seen_hashes: set[str] = set()
                        while current_page <= min(self.max_pages, 200):
                            html = page.content()
                            records = parse_results(html, term, page.url, county="Dallas")
                            in_range_records, _ = self._classify_page_dates(records, stats)
                            raw = self._save_raw_page(page, label, current_page, records)
                            if raw.page_hash in seen_hashes:
                                self.log.warning("Repeated page detected for %s", label)
                                break
                            seen_hashes.add(raw.page_hash)
                            stats.pages_captured += 1

                            for record in in_range_records:
                                key = (
                                    record.county.strip().casefold(),
                                    record.document_number.strip().casefold(),
                                    record.grantor.strip().casefold(),
                                    record.grantee.strip().casefold(),
                                )
                                if any(key):
                                    observed_keys.add(key)
                            stats.unique_in_range = len(observed_keys)
                            self.db.checkpoint("dallas_v5_partition", partition_index)
                            self.db.checkpoint("dallas_v5_term", term_index)
                            self.db.checkpoint("dallas_v5_page", current_page + 1)
                            self.log.info(
                                "Captured %s page %d; %d unique recent filings",
                                label, current_page, stats.unique_in_range,
                            )
                            if stats.unique_in_range >= self.max_records:
                                stats.stop_reason = f"record cap reached ({self.max_records})"
                                return stats
                            if not self._advance(page, raw.page_hash):
                                break
                            current_page += 1

                        if current_page >= 200 and self._next_button(page) is not None:
                            self.log.warning(
                                "Partition approached portal result ceiling: %s. Build 0005 records this for finer splitting.",
                                label,
                            )
                        self.db.checkpoint("dallas_v5_term", term_index + 1)
                        self.db.checkpoint("dallas_v5_page", 1)
                    self.db.checkpoint("dallas_v5_partition", partition_index + 1)
                    self.db.checkpoint("dallas_v5_term", 0)
                    self.db.checkpoint("dallas_v5_page", 1)
            finally:
                browser.close()
        return stats

    def parse_acquired(self) -> tuple[int, int, int]:
        """Parse saved Build 0004 pages; discard rows outside the configured date window."""
        pages = sorted(self.raw_root.glob("*/page_*.html"))
        parsed_pages = 0
        rows_seen = 0
        saved_rows = 0
        for html_path in pages:
            term = html_path.parent.name.split("__", 1)[0].replace("_", " ")
            html = html_path.read_text(encoding="utf-8", errors="replace")
            records = parse_results(html, term, PORTAL, county="Dallas")
            rows_seen += len(records)
            recent_records = [
                record
                for record in records
                if (recording_date := self.parse_recording_date(record.loan_date)) is not None
                and self.date_window.contains(recording_date)
            ]
            saved_rows += self.db.save_many(recent_records)
            parsed_pages += 1
        self.log.info(
            "Parsed %d raw pages, reviewed %d rows, and saved %d in-range filing rows",
            parsed_pages,
            rows_seen,
            saved_rows,
        )
        return parsed_pages, rows_seen, saved_rows

    def reset_acquisition(self) -> None:
        self.db.checkpoint("dallas_v5_partition", 0)
        self.db.checkpoint("dallas_v5_term", 0)
        self.db.checkpoint("dallas_v5_page", 1)
