#!/usr/bin/env python3
"""
Hotel Beaver — root entrypoint (orchestrator).

Running this file loops every folder under hotels/, collects each hotel's rows
for the shared search_request.json, and writes ONE combined CSV
(output/output - <timestamp>.csv). Rows carry a `Hotel Name` column to tell the
hotels apart.

Shared utilities (the search-request contract, the scraper interface, the CSV
output model) live in the `core/` package.

Usage:
    python3 main.py                         # all hotels, config/search_request.json
    python3 main.py path/to/search_request.json
    python3 main.py --only taj_lands_end_mumbai
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import List, Optional, Type

ROOT_DIR = Path(__file__).resolve().parent
HOTELS_DIR = ROOT_DIR / "hotels"
OUTPUT_DIR = ROOT_DIR / "output"
DEFAULT_SEARCH_REQUEST = ROOT_DIR / "config" / "search_request.json"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from core import (  # noqa: E402
    BaseHotelScraper,
    load_search_request,
    output_path,
    write_csv,
)


# ===================================================================== #
# Orchestrator (runs every hotel against the shared request)
# ===================================================================== #
def discover_hotels(only: str | None = None) -> List[Path]:
    """Hotel folders under hotels/ (optionally filtered to a single one)."""
    hotels: List[Path] = []
    for hotel_dir in sorted(HOTELS_DIR.iterdir()):
        if not hotel_dir.is_dir():
            continue
        if only and hotel_dir.name != only:
            continue
        hotels.append(hotel_dir)
    return hotels


def find_scraper(hotel_dir: Path) -> "Path | None":
    """
    The hotel's scraper entrypoint, by convention: a `*_scraper.py` file
    (e.g. taj_scraper.py), falling back to a plain `scraper.py`. Returns None
    if the folder has neither.
    """
    candidates = sorted(hotel_dir.glob("*_scraper.py"))
    if candidates:
        return candidates[0]
    fallback = hotel_dir / "scraper.py"
    return fallback if fallback.exists() else None


def load_scraper_class(scraper_file: Path) -> Optional[Type[BaseHotelScraper]]:
    """Import a hotel's *_scraper.py and return its BaseHotelScraper subclass."""
    spec = importlib.util.spec_from_file_location(scraper_file.stem, scraper_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, BaseHotelScraper)
            and value is not BaseHotelScraper
        ):
            return value
    return None


def run_all(search_request_path: Path, only: str | None = None) -> int:
    if not search_request_path.exists():
        print(f"ERROR: search request not found: {search_request_path}", file=sys.stderr)
        return 1

    request = load_search_request(search_request_path)

    print("==================================================")
    print(" Hotel Beaver — batch run")
    print(f" Search request: {search_request_path}")
    print("==================================================")

    all_records: List[dict] = []
    ran = skipped = failed = 0
    for hotel_dir in discover_hotels(only):
        scraper_file = find_scraper(hotel_dir)
        if scraper_file is None:
            print(f">> SKIP  {hotel_dir.name} (no *_scraper.py — does not honor contract)")
            skipped += 1
            continue

        print(f"\n>> RUN   {hotel_dir.name}  ({scraper_file.name})")
        try:
            cls = load_scraper_class(scraper_file)
            if cls is None:
                print(f">> SKIP  {hotel_dir.name} (no BaseHotelScraper subclass found)")
                skipped += 1
                continue
            records = cls().collect(request)
            all_records.extend(records)
            print(f"   collected {len(records)} row(s)")
            ran += 1
        except Exception as e:  # noqa: BLE001 - one hotel must not kill the batch
            print(f">> FAIL  {hotel_dir.name} ({e})", file=sys.stderr)
            failed += 1

    # Write ONE combined CSV for the whole run.
    out_file = None
    if all_records:
        out_file = write_csv(all_records, output_path("output", OUTPUT_DIR))

    print("\n==================================================")
    print(f" Done. ran={ran}  skipped={skipped}  failed={failed}  rows={len(all_records)}")
    if out_file:
        print(f" Saved: {out_file}")
    else:
        print(" No rows collected — no file written.")
    print("==================================================")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotel Beaver — run all hotel scrapers")
    parser.add_argument(
        "search_request",
        nargs="?",
        default=str(DEFAULT_SEARCH_REQUEST),
        help="Path to search_request.json (default: ./search_request.json)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Run a single hotel by folder name (e.g. taj_lands_end_mumbai)",
    )
    args = parser.parse_args()
    sys.exit(run_all(Path(args.search_request).resolve(), only=args.only))


if __name__ == "__main__":
    main()
