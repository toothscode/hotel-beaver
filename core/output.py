#!/usr/bin/env python3
from __future__ import annotations

import csv
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class OutputRecord:
    """
    One row of the output CSV.

    Each attribute maps to a CSV column. `metadata["header"]` is the exact
    column title written to the file. Add a line here to add a column; the
    declaration order is the column order.
    """
    hotel_name: str = field(default="", metadata={"header": "Hotel Name"})
    scrapped_on: str = field(default="", metadata={"header": "Scrapped On"})
    room_name: str = field(default="", metadata={"header": "Room Name"})
    check_in_date: str = field(default="", metadata={"header": "Check In Date"})
    check_out_date: str = field(default="", metadata={"header": "Check Out Date"})
    occupancy: str = field(default="", metadata={"header": "Occupancy"})
    adults: Any = field(default="", metadata={"header": "Adults"})
    children: Any = field(default="", metadata={"header": "Children"})
    rooms: Any = field(default="", metadata={"header": "Rooms"})
    rate: Any = field(default="", metadata={"header": "Rate"})
    currency: str = field(default="", metadata={"header": "Currency"})
    cancellation_policy: str = field(
        default="", metadata={"header": "Cancellation policy in popup modal"}
    )
    rate_description: str = field(
        default="", metadata={"header": "Rate description in popup modal"}
    )
    images_url: str = field(default="", metadata={"header": "Images url"})
    rate_type: str = field(default="", metadata={"header": "rate type"})
    rate_code: str = field(default="", metadata={"header": "Rate Code"})
    room_code: str = field(default="", metadata={"header": "Room Code"})
    tax_amount: Any = field(default="", metadata={"header": "Tax Amount"})
    total_with_tax: Any = field(default="", metadata={"header": "Total With Tax"})
    available_inventory: Any = field(
        default="", metadata={"header": "Available Inventory"}
    )


def csv_fields() -> List[str]:
    """Ordered list of CSV column headers, derived from OutputRecord."""
    return [f.metadata["header"] for f in fields(OutputRecord)]


def output_path(label: str, output_dir: str | Path) -> Path:
    """
    Build the timestamped output path:
        `<output_dir>/<label> - <YYYY-MM-DD_HH-MM-SS>.csv`

    The label is generic (e.g. "output") since a run can cover many hotels;
    rows carry a `Hotel Name` column to tell them apart. The directory is
    created on write by `write_csv`.
    """
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return Path(output_dir).resolve() / f"{label} - {stamp}.csv"


def write_csv(
    records: List[Dict[str, Any]],
    path: str | Path,
    fieldnames: Optional[List[str]] = None,
) -> Path:
    """
    Write `records` (dicts keyed by CSV header) to `path`.

    Columns and their order come from `OutputRecord` unless `fieldnames` is
    passed explicitly. Extra keys in a record are ignored; missing columns are
    written blank.
    """
    out_file = Path(path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cols = fieldnames or csv_fields()

    with open(out_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow(row)

    return out_file
