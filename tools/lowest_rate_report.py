#!/usr/bin/env python3
"""
Lowest MEMBER breakfast rate per hotel per check-in date -> Excel for a Volt test.

    python tools/lowest_rate_report.py output/runs/<run-folder>

Sheets
  Summary      dates x hotels grid: lowest member rate per night (excl. GST)
  <one/hotel>  per date: lowest member rate + room + plan, standard BAR of that
               room, GST, -discount, -commission, Volt rate (type in) -> difference
  Settings     discount / commission % (yellow, editable -- all sheets recalculate)

"Member rate" = the MEMBER RATE tajhotels.com shows (per plan) or a member-only
offer (e.g. The City Special), breakfast plans only, any room. Nothing calculated.
Tie -> member offer first (same rule as the Compare sheet, core/excel.py).
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402
from openpyxl.formatting.rule import CellIsRule  # noqa: E402
from openpyxl.styles import Alignment, Font  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from core.excel import (BAD_FILL, BORDER, DATE_FMT, GOOD_FILL, HEADER_FILL, HEADER_FONT,  # noqa: E402
                        INPUT_FILL, INR, KEY_FILL, KIND_PRIORITY, NONREF_FILL, PCT, standard_of,
                        Candidate, candidates_for, cancellation_text)
from core.pricing import DEFAULT_SETTINGS, MEMBER_BAR, MEMBER_OFFER, STANDARD_BAR, gst_slab  # noqa: E402
from core.registry import load_config  # noqa: E402

MEMBER_KINDS = {MEMBER_OFFER, MEMBER_BAR}
HEADERS = ["Check-in", "Lowest Member Rate /night (excl. GST)", "Room", "Member Plan", "Rate Type",
           "Cancellation", "Standard BAR same room", "Member saving vs Standard", "GST %", "GST",
           "Member Rate incl. GST", "After Discount", "Net after Commission",
           "VOLT RATE (type here)", "Volt - Member Rate", "Diff %", "Volt - Net", "Result"]
WIDTHS = [17, 16, 34, 36, 18, 36, 14, 11, 7, 10, 14, 12, 14, 14, 13, 8, 12, 13]


def load_records(run_dir: Path):
    return list(csv.DictReader(open(run_dir / "raw_rates.csv", encoding="utf-8")))


def lowest_member(cands: list[Candidate]) -> Candidate | None:
    m = [c for c in cands if c.kind in MEMBER_KINDS]
    return min(m, key=lambda c: (round(c.per_night, 2), KIND_PRIORITY.get(c.kind, 9))) if m else None


def standard_for_room(cands: list[Candidate], room: str) -> float | None:
    c = standard_of([x for x in cands if x.record.get("Room Name") == room])
    return c.per_night if c else None


def header(ws, row, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(row=row, column=i)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 45


def build(run_dir: Path) -> Path:
    params = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    s = {**DEFAULT_SETTINGS, **{k: v for k, v in load_config().get("pricing", {}).items() if not k.startswith("_")}}
    records = [r for r in load_records(run_dir) if r.get("Meal Plan") in s["excel_meal_plans"]]
    d0 = date.fromisoformat(params["date_from"])
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(params["n_dates"])]
    hotels = [h["name"] for h in status.get("hotels", [])] or sorted({r["Hotel Name"] for r in records})
    state = {h["name"]: h for h in status.get("hotels", [])}

    best: dict = {}
    for h in hotels:
        for d in dates:
            cands = candidates_for([r for r in records if r["Hotel Name"] == h and r["Check In Date"] == d])
            low = lowest_member(cands)
            best[(h, d)] = (low, standard_for_room(cands, low.record.get("Room Name")) if low else None)

    wb = Workbook()
    summ = wb.active
    summ.title = "Summary"
    cfg = wb.create_sheet("Settings")
    cfg.column_dimensions["A"].width, cfg.column_dimensions["B"].width = 26, 12
    for i, (label, v) in enumerate([("Discount %", s["discount_pct"] / 100), ("Commission %", s["commission_pct"] / 100),
                                    ("GST % (<= threshold)", s["gst_low_pct"] / 100), ("GST % (above)", s["gst_high_pct"] / 100),
                                    ("GST threshold /night", s["gst_threshold_per_night"])], 1):
        cfg.cell(row=i, column=1, value=label).font = Font(bold=True)
        c = cfg.cell(row=i, column=2, value=v)
        c.fill, c.number_format = INPUT_FILL, (INR if i == 5 else PCT)
    cfg["A7"] = ("Member rate = lowest MEMBER RATE shown on tajhotels.com (or a member-only offer such as "
                 "The City Special). Breakfast plans only, any room, per night, 1 room. GST slab decided on "
                 "the member rate before discount (PENDING CONFIRMATION).")
    cfg["A7"].alignment = Alignment(wrap_text=True, vertical="top")
    cfg.merge_cells("A7:H10")

    # ---- Summary grid ------------------------------------------------- #
    summ["A1"] = (f"Lowest MEMBER breakfast rate per night, excl. GST -- {params['nights']}N, "
                  f"{params['adults']} adults, 1 room. Scraped {status.get('note', '')}.")
    summ["A1"].font = Font(bold=True, size=12, color="1F3A5F")
    summ.append([])
    summ.append(["Check-in"] + hotels)
    header(summ, 3, [17] + [16] * len(hotels))
    for d in dates:
        row = [date.fromisoformat(d)]
        for h in hotels:
            low = best[(h, d)][0]
            row.append(round(low.per_night) if low else ("No rate" if state.get(h, {}).get("state") == "ok" else "not scraped"))
        summ.append(row)
    for row in summ.iter_rows(min_row=4):
        row[0].number_format = DATE_FMT
        for c in row[1:]:
            c.number_format, c.border = INR, BORDER
            if c.value in ("No rate", "not scraped"):
                c.font = Font(italic=True, color="999999")
    summ.freeze_panes = "B4"

    # ---- one sheet per hotel ----------------------------------------- #
    for h in hotels:
        ws = wb.create_sheet(h.split(",")[0].replace("'", "").replace("’", "")[:31])
        ws["A1"] = f"{h} -- lowest member breakfast rate per night (excl. GST unless stated)"
        ws["A1"].font = Font(bold=True, size=12, color="1F3A5F")
        ws.append([])
        ws.append(HEADERS)
        header(ws, 3, WIDTHS)
        for n, d in enumerate(dates, 4):
            low, std = best[(h, d)]
            if not low:
                ws.append([date.fromisoformat(d), "Sold out / no breakfast member rate"])
                ws.cell(row=n, column=2).font = Font(italic=True, color="999999")
                ws.cell(row=n, column=1).number_format = DATE_FMT
                continue
            gst = gst_slab(low.per_night, s) / 100
            ws.append([
                date.fromisoformat(d), round(low.per_night, 2), low.record.get("Room Name"), low.plan, low.kind,
                cancellation_text(low.record), round(std, 2) if std else None,
                f'=IF(G{n}="","",1-B{n}/G{n})',
                f"=IF(B{n}<=Settings!$B$5,Settings!$B$3,Settings!$B$4)" if gst is not None else None,
                f"=B{n}*I{n}", f"=B{n}+J{n}",
                f"=B{n}*(1-Settings!$B$1)", f"=L{n}*(1-Settings!$B$2)",
                None,
                f'=IF(N{n}="","",N{n}-B{n})', f'=IF(N{n}="","",O{n}/B{n})', f'=IF(N{n}="","",N{n}-M{n})',
                f'=IF(N{n}="","",IF(ABS(O{n})<1,"Same",IF(O{n}>0,"Volt higher","Volt lower")))',
            ])
            for col in (2, 7, 10, 11, 12, 13, 14, 15, 17):
                ws.cell(row=n, column=col).number_format = INR
            for col in (8, 9, 16):
                ws.cell(row=n, column=col).number_format = PCT if col != 16 else "0.0%"
            ws.cell(row=n, column=1).number_format = DATE_FMT
            ws.cell(row=n, column=2).fill, ws.cell(row=n, column=2).font = KEY_FILL, Font(bold=True)
            ws.cell(row=n, column=14).fill = INPUT_FILL
            if str(low.record.get("Free Cancellation", "")).startswith("No"):
                ws.cell(row=n, column=6).fill = NONREF_FILL
            for c in ws[n]:
                c.border = BORDER
        last = 3 + len(dates)
        ws.conditional_formatting.add(f"R4:R{last}", CellIsRule(operator="equal", formula=['"Volt higher"'], fill=GOOD_FILL))
        ws.conditional_formatting.add(f"R4:R{last}", CellIsRule(operator="equal", formula=['"Volt lower"'], fill=BAD_FILL))
        ws.freeze_panes = "C4"
        ws.auto_filter.ref = f"A3:R{last}"

    wb.move_sheet("Settings", offset=len(wb.sheetnames))
    out = run_dir / (f"Lowest Member Rates {params['date_from']} to {params['date_to']} - "
                     f"{params['nights']}N {params['adults']}A - {len(hotels)} hotels.xlsx")
    wb.save(out)
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]).resolve()))
