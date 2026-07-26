import json
import logging
from pathlib import Path
from datetime import datetime
from .database import Database
from .dallas import DallasConnector
from .exporter import export_excel

ROOT = Path(__file__).resolve().parent.parent

def setup_log():
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    path = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    return path

def terms():
    lenders_path = ROOT / "config" / "lenders.json"
    search_terms_path = ROOT / "config" / "search_terms.json"

    lenders = json.loads(lenders_path.read_text(encoding="utf-8"))["lenders"]
    search_terms = json.loads(search_terms_path.read_text(encoding="utf-8"))["solar_terms"]
    return lenders + search_terms

def main():
    # Ensure all working folders exist before opening logs or the database.
    for folder_name in ("logs", "data", "output"):
        (ROOT / folder_name).mkdir(parents=True, exist_ok=True)

    log = setup_log()
    db = Database(ROOT / "data" / "solar_discovery.db")

    try:
        print("\nSOLAR LIEN DISCOVERY v0.1")
        print("1. Start or resume Dallas scan")
        print("2. Export current results to Excel")
        print("3. Reset scan checkpoint")
        print("4. Exit")

        choice = input("\nChoose 1-4: ").strip()

        if choice == "1":
            items = terms()
            start = int(db.checkpoint("dallas_next_term"))
            print(f"{'Resuming' if start else 'Starting'} at search {start + 1} of {len(items)}.")
            print("Chrome will open. Press Ctrl+C here to stop safely.")
            DallasConnector(db, ROOT).scan(items, start)

            path = export_excel(db.rows(), ROOT / "output")
            print(f"\nWorkbook created: {path}")

        elif choice == "2":
            path = export_excel(db.rows(), ROOT / "output")
            print(f"Workbook created: {path}")

        elif choice == "3":
            db.checkpoint("dallas_next_term", 0)
            print("Checkpoint reset.")

        else:
            print("Exiting.")

    finally:
        db.close()
        print(f"Log file: {log}")
