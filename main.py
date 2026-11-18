#!/usr/bin/env python3
"""
Hotel Beaver -- command-line entrypoint.

Runs the hotels from config/hotels.json (IHCL) and hotels/<folder>/ (e.g.
Leela) against a search_request.json and writes ONE combined CSV, plus a
formatted Excel file next to it. For the browser dashboard, run
`start_dashboard.bat` (or `streamlit run dashboard/app.py`).

Usage:
    python main.py                               # all hotels, config/search_request.json
    python main.py path/to/search_request.json
    python main.py --only taj_palace_new_delhi   # hotel key (comma-separated for several)
    python main.py --list                        # show hotel keys
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
DEFAULT_SEARCH_REQUEST = ROOT_DIR / "config" / "search_request.json"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from core import load_search_request, output_path, write_csv  # noqa: E402
from core.excel import write_excel  # noqa: E402
from core.registry import available_hotels  # noqa: E402
from core.runner import run_hotels  # noqa: E402


def select_hotels(only: str | None):
    entries = available_hotels()
    if not only:
        return entries
    wanted = [k.strip() for k in only.split(",") if k.strip()]
    by_key = {e.key: e for e in entries}
    missing = [k for k in wanted if k not in by_key]
    if missing:
        raise SystemExit(f"Unknown hotel key(s): {', '.join(missing)}  (see --list)")
    return [by_key[k] for k in wanted]


def run_all(search_request_path: Path, only: str | None = None) -> int:
    if not search_request_path.exists():
        print(f"ERROR: search request not found: {search_request_path}", file=sys.stderr)
        return 1
    request = load_search_request(search_request_path)
    entries = select_hotels(only)

    print("==================================================")
    print(f" Hotel Beaver -- {len(entries)} hotel(s) x {len(request.windows())} check-in date(s)")
    print("==================================================")
    result = run_hotels(entries, request)

    out_file = None
    if result.records:
        out_file = write_csv(result.records, output_path("output", OUTPUT_DIR))
        write_excel(result.records, out_file.with_suffix(".xlsx"), request, result.statuses)

    print("\n==================================================")
    for s in result.statuses:
        print(f"  {s.state.upper():9} {s.name}  {s.detail}")
    print(f" rows={len(result.records)}")
    if out_file:
        print(f" Saved: {out_file}\n        {out_file.with_suffix('.xlsx')}")
    else:
        print(" No rows collected -- no file written.")
    print("==================================================")
    return 0 if result.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotel Beaver -- run hotel scrapers")
    parser.add_argument("search_request", nargs="?", default=str(DEFAULT_SEARCH_REQUEST))
    parser.add_argument("--only", default=None, help="hotel key(s), comma-separated")
    parser.add_argument("--list", action="store_true", help="list hotel keys and exit")
    args = parser.parse_args()
    if args.list:
        for e in available_hotels():
            print(f"{e.key:32} {e.brand:12} {e.name}")
        return
    sys.exit(run_all(Path(args.search_request).resolve(), only=args.only))


if __name__ == "__main__":
    main()
