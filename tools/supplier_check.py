#!/usr/bin/env python3
"""
Supplier vs Volt sheet -- minimal. One sheet per hotel, one row per room per check-in date.

Per room the website shows at most 3 breakfast prices (scraped exactly, nothing calculated):
    STANDARD RATE  (Breakfast Inclusive / Best Available Rate)
    MEMBER RATE    (member price of that same plan)
    MEMBER OFFER   (member-only offer: The City Special, Taj Club, ... -- lowest if several)

Supplier net (formulas on the sheet, % cells editable):
    Standard 20,000: less 10% = 18,000 -> + 18% GST on 18,000 = 21,240 -> - 10% of 18,000 = 19,440
    Member   16,000: + 18% GST = 18,880 -> - 10% of 16,000 = 17,280          (same for Member Offer)
    GST 5% instead of 18% when the scraped rate is <= 7,500/night.
Lowest of the 3 supplier nets is compared with Volt's rate (Volt is incl. taxes).

    python tools/supplier_check.py <run-folder> [<run-folder> ...]     -> one Excel for all hotels
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402
from openpyxl.comments import Comment  # noqa: E402
from openpyxl.formatting.rule import CellIsRule, FormulaRule  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402

from core.excel import (BAD_FILL, BORDER, DATE_FMT, GOOD_FILL, HEADER_FILL, HEADER_FONT,  # noqa: E402
                        INPUT_FILL, INR, PCT)
from core.pricing import MEMBER_BAR, MEMBER_OFFER, STANDARD_BAR  # noqa: E402
from core.registry import load_config  # noqa: E402

BNB = "Breakfast (BnB)"
HEADERS = ["Check-in", "Room",
           "Standard (excl. GST)", "Standard incl. GST", "Supplier Net - Standard",
           "Member (excl. GST)", "Member incl. GST", "Supplier Net - Member",
           "Member Offer (excl. GST)", "Member Offer incl. GST", "Supplier Net - Member Offer",
           "LOWEST Supplier Net", "VOLT RATE (incl. taxes) - type here", "Volt - Supplier", "Result"]
WIDTHS = [17, 34, 13, 13, 14, 13, 13, 14, 13, 13, 14, 14, 16, 13, 16]
GROUPS = [("C", "E", "STANDARD", "DCE6F1"), ("F", "H", "MEMBER", "E2EFDA"),
          ("I", "K", "MEMBER OFFER", "FCE4D6"), ("L", "O", "COMPARE WITH VOLT", "FFF2CC")]
HEAD, FIRST = 6, 7          # header row, first data row
# settings cells (row 2)
DISC, COMM, GST_HI, THRESH, GST_LO = "$B$2", "$D$2", "$F$2", "$H$2", "$J$2"


def gst(cell: str) -> str:
    return f"IF({cell}<={THRESH},{GST_LO},{GST_HI})"


def net_standard(c: str) -> str:
    """20,000 -> 18,000 -> +GST on 18,000 -> -10% of 18,000 = 19,440"""
    d = f"{c}*(1-{DISC})"
    return f'=IF({c}="","",{d}+{d}*{gst(c)}-{d}*{COMM})'


def net_member(c: str) -> str:
    """16,000 -> +GST on 16,000 -> -10% of 16,000 = 17,280"""
    return f'=IF({c}="","",{c}+{c}*{gst(c)}-{c}*{COMM})'


# --------------------------------------------------------------------------- #
def load(run_dirs):
    records, dates, order = [], set(), []
    for d in map(Path, run_dirs):
        records += list(csv.DictReader(open(d / "raw_rates.csv", encoding="utf-8")))
        p = json.loads((d / "params.json").read_text(encoding="utf-8"))
        d0 = date.fromisoformat(p["date_from"])
        dates |= {(d0 + timedelta(days=i)).isoformat() for i in range(p["n_dates"])}
        st = json.loads((d / "status.json").read_text(encoding="utf-8"))
        order += [h["name"] for h in st.get("hotels", []) if h["name"] not in order]
    return records, sorted(dates), order


def three_rates(rs):
    """(standard, member, offer) records for one room on one date -- exactly what the website shows."""
    def low(xs):
        return min(xs, key=lambda r: float(r["Rate"])) if xs else None
    member_codes = {r["Rate Code"] for r in rs if r["Rate Category"] == MEMBER_BAR}
    std = (low([r for r in rs if r["Rate Category"] == STANDARD_BAR and r["Rate Code"] in member_codes])
           or low([r for r in rs if r["Rate Category"] == STANDARD_BAR]))
    member = low([r for r in rs if r["Rate Category"] == MEMBER_BAR
                  and (std is None or r["Rate Code"] == std["Rate Code"])])
    offer = low([r for r in rs if r["Rate Category"] == MEMBER_OFFER])
    return std, member, offer


def room_rows(records, hotel, dates):
    """Yields (date, room, std, member, offer); a date with no breakfast rate -> one 'Sold out' row."""
    by = {}
    for r in records:
        if r["Hotel Name"] == hotel and r["Meal Plan"] == BNB and r.get("Rate") not in (None, ""):
            by.setdefault(r["Check In Date"], {}).setdefault(r["Room Name"], []).append(r)
    for d in dates:
        rooms = by.get(d)
        if not rooms:
            yield d, None, None, None, None
            continue
        rows = [(room, *three_rates(rs)) for room, rs in rooms.items()]
        rows.sort(key=lambda x: min(float(r["Rate"]) for r in x[1:] if r))   # cheapest room first
        for room, std, member, offer in rows:
            yield d, room, std, member, offer


# --------------------------------------------------------------------------- #
def build(records, dates, hotels, path: Path):
    wb = Workbook()
    wb.remove(wb.active)
    s = load_config().get("pricing", {})
    used = set()
    for hotel in hotels:
        title = hotel.split(",")[0].replace("'", "").replace("’", "")[:31]
        while title in used:
            title = title[:29] + "_2"
        used.add(title)
        _sheet(wb.create_sheet(title), hotel, records, dates, s)
    wb.save(path)
    return path


def _sheet(ws, hotel, records, dates, s):
    ws["A1"] = hotel
    ws["A1"].font = Font(bold=True, size=14, color="1F3A5F")
    ws["E1"] = ("1 night, 2 adults, 1 room, breakfast. Rates exactly as tajhotels.com shows them. "
                "Volt rate = incl. taxes.")
    ws["E1"].font = Font(italic=True, color="595959")

    settings = [("A2", "Discount (standard)", "B2", s.get("discount_pct", 10) / 100, PCT),
                ("C2", "Commission", "D2", s.get("commission_pct", 10) / 100, PCT),
                ("E2", "GST", "F2", s.get("gst_high_pct", 18) / 100, PCT),
                ("G2", "GST if rate <=", "H2", s.get("gst_threshold_per_night", 7500), INR),
                ("I2", "-> GST", "J2", s.get("gst_low_pct", 5) / 100, PCT)]
    for lab, text, cell, v, fmt in settings:
        ws[lab] = text
        ws[lab].font = Font(bold=True)
        ws[lab].alignment = Alignment(horizontal="right")
        ws[cell], ws[cell].number_format, ws[cell].fill = v, fmt, INPUT_FILL
    # supplier's own examples, through the SAME formulas as the rows below
    ws["A3"], ws["C3"], ws["F3"] = "Check (supplier's examples)", 20000, 16000
    ws["E3"], ws["H3"] = net_standard("C3"), net_member("F3")
    ws["I3"] = "<- must be 19,440 and 17,280"
    for c in ("C3", "E3", "F3", "H3"):
        ws[c].number_format = INR
    for c in ("E3", "H3"):
        ws[c].font = Font(bold=True)
    for c in ("A3", "I3"):
        ws[c].font = Font(italic=True, color="595959")

    for a, b, text, color in GROUPS:          # group band above the headers
        ws.merge_cells(f"{a}{HEAD - 1}:{b}{HEAD - 1}")
        c = ws[f"{a}{HEAD - 1}"]
        c.value, c.font = text, Font(bold=True)
        c.fill, c.alignment = PatternFill("solid", fgColor=color), Alignment(horizontal="center")
    for i, (h, w) in enumerate(zip(HEADERS, WIDTHS), 1):
        c = ws.cell(row=HEAD, column=i, value=h)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[c.column_letter].width = w
    ws.row_dimensions[HEAD].height = 45

    num = lambda r, k: round(float(r[k]), 2) if r and r.get(k) not in (None, "") else None  # noqa: E731
    n = FIRST
    for d, room, std, member, offer in room_rows(records, hotel, dates):
        ws.cell(row=n, column=1, value=date.fromisoformat(d)).number_format = DATE_FMT
        if room is None:
            ws.cell(row=n, column=2, value="Sold out - no breakfast rate").font = Font(italic=True, color="9C0006")
        else:
            vals = {2: room, 3: num(std, "Rate"), 4: num(std, "Total With Tax"), 5: net_standard(f"C{n}"),
                    6: num(member, "Rate"), 7: num(member, "Total With Tax"), 8: net_member(f"F{n}"),
                    9: num(offer, "Rate"), 10: num(offer, "Total With Tax"), 11: net_member(f"I{n}"),
                    12: f'=IF(COUNT(E{n},H{n},K{n})=0,"",MIN(E{n},H{n},K{n}))',
                    14: f'=IF(OR(M{n}="",L{n}=""),"",M{n}-L{n})',
                    15: f'=IF(N{n}="","",IF(N{n}>0,"Supplier cheaper",IF(N{n}<0,"Volt cheaper","Same")))'}
            for col, v in vals.items():
                ws.cell(row=n, column=col, value=v)
            for col in range(3, 15):
                ws.cell(row=n, column=col).number_format = INR
            for col in (5, 8, 11, 12):
                ws.cell(row=n, column=col).font = Font(bold=True)
            ws.cell(row=n, column=13).fill = INPUT_FILL
            if offer:   # which offer it is, on hover
                ws.cell(row=n, column=9).comment = Comment(offer["rate type"], "scraper")
        for c in ws[n][:15]:
            c.border = BORDER
        n += 1
    last = max(n - 1, FIRST)
    # green = the lowest of the 3 supplier nets on that row
    for col in ("E", "H", "K"):
        ws.conditional_formatting.add(f"{col}{FIRST}:{col}{last}", FormulaRule(
            formula=[f'AND(ISNUMBER({col}{FIRST}),{col}{FIRST}=$L{FIRST})'], fill=GOOD_FILL))
    ws.conditional_formatting.add(f"O{FIRST}:O{last}", CellIsRule(operator="equal", formula=['"Supplier cheaper"'], fill=GOOD_FILL))
    ws.conditional_formatting.add(f"O{FIRST}:O{last}", CellIsRule(operator="equal", formula=['"Volt cheaper"'], fill=BAD_FILL))
    ws.freeze_panes = f"C{FIRST}"
    ws.auto_filter.ref = f"A{HEAD}:O{last}"


if __name__ == "__main__":
    runs = sys.argv[1:]
    recs, dts, hotels = load(runs)
    out = Path(runs[0]) / f"Supplier vs Volt {dts[0]} to {dts[-1]} - {len(hotels)} hotels - {datetime.now():%d%b %H%M}.xlsx"
    print(build(recs, dts, hotels, out))
