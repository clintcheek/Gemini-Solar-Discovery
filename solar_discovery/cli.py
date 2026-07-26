from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .dallas import ACQUISITION_TERMS, AcquisitionStats, DallasConnector
from .database import Database
from .exporter import export_excel

ROOT = Path(__file__).resolve().parent.parent


def setup_log() -> Path:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    return path


def print_acquisition_summary(stats: AcquisitionStats, connector: DallasConnector) -> None:
    print("\nACQUISITION SUMMARY")
    print("-------------------")
    print(f"Pages captured: {stats.pages_captured:,}")
    print(f"Rows reviewed: {stats.rows_seen:,}")
    print(f"Rows within date window: {stats.rows_in_range:,}")
    print(f"Unique recent filings: {stats.unique_in_range:,}")
    print(f"Rows older than cutoff: {stats.rows_older_than_cutoff:,}")
    print(f"Rows with unreadable dates: {stats.rows_with_unreadable_dates:,}")
    print(f"Newest date seen: {stats.newest_date_seen or 'N/A'}")
    print(f"Oldest date seen: {stats.oldest_date_seen or 'N/A'}")
    print(f"Stop reason: {stats.stop_reason}")
    print(f"Required date window: {connector.date_window.start} through {connector.date_window.end}")


def main() -> None:
    log_path = setup_log()
    # Build 0005 uses a separate database so Build 0003 historical records cannot leak into exports.
    db = Database(ROOT / "data" / "solar_discovery_v5.db")
    connector = DallasConnector(db, ROOT)
    try:
        print("\nSOLAR DISCOVERY v0.5 - DALLAS RECENT UCC/PACE QUALIFICATION TEST")
        print(f"Date window: {connector.date_window.start} through {connector.date_window.end}")
        print(f"Development cap: {connector.max_records:,} unique filings")
        print("1. Acquire recent UCC/PACE pages")
        print("2. Parse acquired pages into the Build 0005 database")
        print("3. Qualify parsed filings with solar-equipment keywords")
        print("4. Export qualified filings to Excel")
        print("5. Reset acquisition checkpoint")
        print("6. Run acquire + parse + qualify + export")
        print("7. Exit")
        choice = input("\nChoose 1-7: ").strip()

        if choice == "1":
            print("Document-type searches:", ", ".join(ACQUISITION_TERMS))
            print("Raw pages are saved before parsing. Press Ctrl+C to stop safely.")
            stats = connector.acquire()
            print_acquisition_summary(stats, connector)
            print(f"Raw page folder: {connector.raw_root}")
        elif choice == "2":
            pages, rows_seen, rows_saved = connector.parse_acquired()
            print(f"Raw pages parsed: {pages:,}")
            print(f"Rows reviewed: {rows_seen:,}")
            print(f"Recent rows saved: {rows_saved:,}")
            print(f"Unique recent filings in database: {db.count():,}")
        elif choice == "3":
            processed = db.qualify_all()
            print(f"Filings qualified: {processed:,}")
            print(f"Possible-or-better solar filings: {db.qualified_count(20):,}")
        elif choice == "4":
            path = export_excel(db.rows(), ROOT / "output")
            print(f"Workbook created: {path}")
            print(f"Unique recent filings exported: {db.count():,}")
        elif choice == "5":
            connector.reset_acquisition()
            print("Build 0005 acquisition checkpoint reset. Existing Build 0005 raw pages are preserved.")
        elif choice == "6":
            stats = connector.acquire()
            print_acquisition_summary(stats, connector)
            pages, rows_seen, rows_saved = connector.parse_acquired()
            processed = db.qualify_all()
            path = export_excel(db.rows(), ROOT / "output")
            print(f"Raw pages parsed: {pages:,}")
            print(f"Rows reviewed: {rows_seen:,}")
            print(f"Recent rows saved: {rows_saved:,}")
            print(f"Filings qualified: {processed:,}")
            print(f"Possible-or-better solar filings: {db.qualified_count(20):,}")
            print(f"Unique recent filings in database: {db.count():,}")
            print(f"Workbook created: {path}")
        else:
            print("Exiting.")
    except KeyboardInterrupt:
        print("\nStopped safely. Run again to resume from the saved Build 0005 checkpoint.")
    finally:
        db.close()
        print(f"Log file: {log_path}")


if __name__ == "__main__":
    main()
