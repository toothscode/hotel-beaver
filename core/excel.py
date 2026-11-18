#!/usr/bin/env python3
"""
Clean Excel export for the contracting team. Prices only -- no TAC/discounts
(the team applies those). Rate Type (Standard BAR / Member BAR / Other) is
shown so the team can decide which TAC applies.

Sheets
  1. Best Deals   cheapest rate per Hotel x Check-in x Meal Plan (by price incl.
                  GST) + the cheapest refundable alternative. A pricier
                  look-alike plan (e.g. T15N "Stay A Bit Longer Member Rate",
                  +12.8% vs the normal member rate) is never the one shown.
  2. All Rates    every room x rate plan with price excl./incl. GST, per night,
                  cancellation terms.
  3. Policies     full inclusions + cancellation text, one row per plan.
  4. Search Info  what was searched, per-hotel status, GST rule + check.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

MEAL_ORDER = {"Room Only": 0, "Breakfast (BnB)": 1, "Half Board": 2, "Full Board": 3, "Unknown": 4}
PRICE_KEY = "Price incl. GST"

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
NONREF_FILL = PatternFill("solid", fgColor="FDE2E1")
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
KEY_FILL = PatternFill("solid", fgColor="E8F3EC")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(bottom=THIN)
INR = '"₹"#,##0'
DATE_FMT = "ddd, dd-mmm-yyyy"


# --------------------------------------------------------------------------- #
def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _d(v: Any) -> Any:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return v


def cancellation_text(r: Dict[str, Any]) -> str:
    free = r.get("Free Cancellation")
    if free == "Yes":
        try:
            until = datetime.strptime(r["Free Cancellation Until"], "%Y-%m-%d %H:%M")
            when = until.strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ")
        except (KeyError, ValueError):
            when = r.get("Free Cancellation Until", "")
        days = r.get("Free Cancel Days Before Check-in")
        unit = "day" if str(days) == "1" else "days"
        return f"Free until {when} ({days} {unit} before check-in)"
    if free and str(free).startswith("No"):
        return "Non-refundable"
    return "Unknown"


def _sort_key(r: Dict[str, Any]):
    return (r.get("Hotel Name", ""), str(r.get("Check In Date", "")),
            MEAL_ORDER.get(r.get("Meal Plan"), 9), _num(r.get(PRICE_KEY)) or 9e15)


def best_deals(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cheapest rate (incl. GST) per (hotel, check-in, meal plan) + cheapest refundable."""
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in records:
        if _num(r.get(PRICE_KEY)) is None:
            continue
        groups.setdefault((r.get("Hotel Name"), r.get("Check In Date"), r.get("Meal Plan")), []).append(r)
    out = []
    for rows in groups.values():
        rows.sort(key=lambda r: _num(r[PRICE_KEY]))
        best = rows[0]
        refundable = next((r for r in rows if r.get("Free Cancellation") == "Yes"), None)
        out.append({"best": best, "refundable": refundable if refundable is not best else None})
    out.sort(key=lambda x: _sort_key(x["best"]))
    return out


# --------------------------------------------------------------------------- #
def _sheet(wb: Workbook, title: str, headers: Sequence[str], widths: Sequence[int], first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(list(headers))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(row=1, column=i)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "C2"
    return ws


def _finish(ws, money_cols: Iterable[int], date_cols: Iterable[int], key_cols: Iterable[int] = ()):
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.border = BORDER
        for i in money_cols:
            row[i - 1].number_format = INR
        for i in date_cols:
            row[i - 1].number_format = DATE_FMT
        for i in key_cols:
            row[i - 1].fill = KEY_FILL
            row[i - 1].font = Font(bold=True)
    ws.auto_filter.ref = ws.dimensions


def write_excel(records: List[Dict[str, Any]], path: str | Path, request=None,
                statuses: Optional[List[Any]] = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # ---- 1. Best Deals ------------------------------------------------ #
    ws = _sheet(wb, "Best Deals", [
        "Hotel", "Check-in", "Nights", "Meal Plan", "Room", "Rate Plan", "Rate Type",
        "Price excl. GST", "GST %", "GST", "Price incl. GST", "Per Night excl. GST",
        "Per Night incl. GST", "Cancellation", "Cheapest Refundable (incl. GST)", "Refundable Plan",
    ], [34, 17, 7, 15, 30, 34, 13, 14, 8, 11, 14, 13, 13, 42, 16, 34], first=True)
    for d in best_deals(records):
        b, rf = d["best"], d["refundable"]
        ws.append([
            b.get("Hotel Name"), _d(b.get("Check In Date")), b.get("Nights"), b.get("Meal Plan"),
            b.get("Room Name"), b.get("rate type"), b.get("Rate Category"),
            _num(b.get("Rate")), b.get("GST %"), _num(b.get("GST Amount")), _num(b.get(PRICE_KEY)),
            _num(b.get("Per Night excl. GST")), _num(b.get("Per Night incl. GST")),
            cancellation_text(b),
            _num(rf.get(PRICE_KEY)) if rf else None, rf.get("rate type") if rf else None,
        ])
        if str(b.get("Free Cancellation", "")).startswith("No"):
            ws.cell(row=ws.max_row, column=14).fill = NONREF_FILL
    _finish(ws, money_cols=[8, 10, 11, 12, 13, 15], date_cols=[2], key_cols=[11])

    # ---- 2. All Rates ------------------------------------------------- #
    ws = _sheet(wb, "All Rates", [
        "Hotel", "Check-in", "Check-out", "Nights", "Adults", "Room", "Rate Plan", "Rate Type",
        "Meal Plan", "Price excl. GST", "GST %", "GST", "Price incl. GST",
        "Per Night excl. GST", "Per Night incl. GST", "Cancellation", "Free Cancel Until",
        "Rooms Left", "Rate Code", "Room Code", "GST Check",
    ], [34, 17, 17, 7, 7, 30, 34, 13, 15, 14, 8, 11, 14, 13, 13, 42, 17, 8, 9, 9, 14])
    gst_ok = gst_bad = 0
    for r in sorted(records, key=_sort_key):
        check = r.get("GST Check", "")
        gst_ok += check == "OK"
        gst_bad += bool(check) and check != "OK"
        ws.append([
            r.get("Hotel Name"), _d(r.get("Check In Date")), _d(r.get("Check Out Date")),
            r.get("Nights"), r.get("Adults"), r.get("Room Name"), r.get("rate type"),
            r.get("Rate Category"), r.get("Meal Plan"), _num(r.get("Rate")), r.get("GST %"),
            _num(r.get("GST Amount")), _num(r.get(PRICE_KEY)), _num(r.get("Per Night excl. GST")),
            _num(r.get("Per Night incl. GST")), cancellation_text(r),
            r.get("Free Cancellation Until") or "", r.get("Available Inventory"),
            r.get("Rate Code"), r.get("Room Code"), check,
        ])
        if str(r.get("Free Cancellation", "")).startswith("No"):
            ws.cell(row=ws.max_row, column=16).fill = NONREF_FILL
        if check and check != "OK":
            ws.cell(row=ws.max_row, column=21).fill = WARN_FILL
    _finish(ws, money_cols=[10, 12, 13, 14, 15], date_cols=[2, 3], key_cols=[13])

    # ---- 3. Policies -------------------------------------------------- #
    ws = _sheet(wb, "Policies", ["Hotel", "Rate Code", "Rate Plan", "Rate Type", "Meal Plan",
                                 "Inclusions", "Cancellation Policy (hotel text)"],
                [34, 10, 34, 13, 15, 70, 70])
    seen = set()
    for r in sorted(records, key=lambda r: (r.get("Hotel Name", ""), str(r.get("Rate Code")))):
        k = (r.get("Hotel Name"), r.get("Rate Code"), r.get("Cancellation policy in popup modal"))
        if k in seen:
            continue
        seen.add(k)
        ws.append([r.get("Hotel Name"), r.get("Rate Code"), r.get("rate type"), r.get("Rate Category"),
                   r.get("Meal Plan"), r.get("Rate description in popup modal"),
                   r.get("Cancellation policy in popup modal")])
        for c in ws[ws.max_row][5:7]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    _finish(ws, money_cols=[], date_cols=[])

    # ---- 4. Search Info ----------------------------------------------- #
    ws = wb.create_sheet("Search Info")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 95
    info = [("Generated", datetime.now().strftime("%d %b %Y, %I:%M %p"))]
    if request is not None:
        wins = request.windows()
        occ = request.aggregate_occupancy()
        info += [("Check-in dates", f"{wins[0][0]} to {wins[-1][0]} ({len(wins)} dates)"),
                 ("Nights per stay", request.night_duration),
                 ("Occupancy", f"{occ['adults']} adult(s), {occ['rooms']} room(s)")]
    info += [("Rate rows", len(records)), ("", ""),
             ("PRICES", ""),
             ("Price excl. GST", "Hotel's published rate before tax, whole stay. No TAC / discount applied."),
             ("GST", "The hotel's own tax from its booking system."),
             ("GST %", "Rule: price excl. GST per night per room below Rs 7,500 -> 5%, otherwise 18%. "
                       "PENDING TEAM CONFIRMATION (incl. what applies at exactly Rs 7,500)."),
             ("GST Check", f"Hotel GST vs the rule: {gst_ok} rows OK, {gst_bad} rows differ "
                           f"(differences are highlighted yellow in All Rates)."),
             ("Rate Type", "Standard BAR / Member BAR / Other -- for the team's TAC decision."),
             ("Best Deals", "Cheapest price incl. GST per hotel, check-in and meal plan (any room)."),
             ("", ""), ("HOTEL STATUS", "")]
    for row in info:
        ws.append(list(row))
    for s in statuses or []:
        extra = f" | sold out: {', '.join(s.sold_out_dates)}" if s.sold_out_dates else ""
        ws.append([s.name, f"{s.state.upper()} -- {s.detail}{extra}"])
    for row in ws.iter_rows():
        if row[0].value in ("PRICES", "HOTEL STATUS"):
            row[0].font = Font(bold=True, color="1F3A5F")
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(path)
    return path
