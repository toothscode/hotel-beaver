#!/usr/bin/env python3
"""
Turn a raw Hotel Beaver output CSV into a human-friendly one for Excel / Sheets.

What it does:
  * writes UTF-8 *with BOM* so Excel shows ’ à ₹ correctly
  * reorders columns: who/when/what first, prices next, long text + codes last
  * adds Nights and Per-Night (incl. tax) columns
  * rounds money to whole rupees
  * flattens multi-line descriptions into one line ("A • B • C")
  * keeps only the first image URL + an image count
  * sorts by Hotel → Check-in → Total price

Usage:
    python tools/make_viewable_csv.py                      # latest file in output/
    python tools/make_viewable_csv.py "output/output - 2026-11-17_16-01-18.csv"

Writes "<original name> - viewable.csv" next to the input.
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def money(v: str) -> int | str:
    try:
        return round(float(v))
    except (TypeError, ValueError):
        return ""


def one_line(text: str) -> str:
    """Collapse bullet/newline-separated text into a single readable line."""
    parts = [re.sub(r"^[-•*<\s]+", "", p).strip() for p in re.split(r"\n+", text or "")]
    parts = [re.sub(r"\s{2,}", " ", p).rstrip(".") for p in parts if p]
    return " • ".join(parts)


def nights(check_in: str, check_out: str) -> int | str:
    try:
        return (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    except ValueError:
        return ""


def transform(row: dict) -> dict:
    n = nights(row["Check In Date"], row["Check Out Date"])
    total = money(row["Total With Tax"])
    images = [u.strip() for u in (row["Images url"] or "").split(";") if u.strip()]
    return {
        "Hotel": row["Hotel Name"],
        "Check In": row["Check In Date"],
        "Check Out": row["Check Out Date"],
        "Nights": n,
        "Occupancy": row["Occupancy"],
        "Room": row["Room Name"],
        "Rate Plan": row["rate type"],
        "Meal Plan": row.get("Meal Plan", ""),
        "BAR": row.get("Is BAR", ""),
        "Free Cancellation": row.get("Free Cancellation", ""),
        "Free Cancel Until": row.get("Free Cancellation Until", ""),
        "Free Cancel (days before)": row.get("Free Cancel Days Before Check-in", ""),
        "Currency": row["Currency"],
        "Room Rate": money(row["Rate"]),
        "Tax": money(row["Tax Amount"]),
        "Total (incl. Tax)": total,
        "Per Night (incl. Tax)": round(total / n) if isinstance(total, int) and n else "",
        "Rooms Left": row["Available Inventory"],
        "Inclusions": one_line(row["Rate description in popup modal"]),
        "Cancellation Policy": one_line(row["Cancellation policy in popup modal"]),
        "Room Code": row["Room Code"],
        "Rate Code": row["Rate Code"],
        "Image": images[0] if images else "",
        "# Images": len(images),
        "Scraped On": row["Scrapped On"],
    }


def sort_key(r: dict):
    total = r["Total (incl. Tax)"]
    return (r["Hotel"], r["Check In"], total if isinstance(total, int) else float("inf"))


def main() -> None:
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
    else:
        raw = [p for p in OUTPUT_DIR.glob("output - *.csv") if not p.stem.endswith("viewable")]
        if not raw:
            sys.exit(f"No output CSVs found in {OUTPUT_DIR}")
        src = max(raw, key=lambda p: p.stat().st_mtime)

    with open(src, encoding="utf-8-sig", newline="") as f:
        rows = sorted((transform(r) for r in csv.DictReader(f)), key=sort_key)

    dst = src.with_name(f"{src.stem} - viewable.csv")
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} rows → {dst}")


if __name__ == "__main__":
    main()
