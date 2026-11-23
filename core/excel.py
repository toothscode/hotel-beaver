#!/usr/bin/env python3
"""
Clean Excel export for the contracting team -- breakfast (BnB) rates only by
default (config/hotels.json -> pricing.excel_meal_plans).

Sheets
  1. Compare      one row per Hotel x Check-in x Room, PER NIGHT, excl. GST:
                  STANDARD RATE | MEMBER RATE (as tajhotels.com shows) | member-only offer
                  -> OUR RATE = the lowest of all breakfast rates (member first on a tie)
                  -> - discount % -> - commission % -> GST -> net rate
                  -> Volt rate (typed in) -> difference.  All maths are live Excel
                  formulas driven by the yellow settings cells at the top.
  2. All Rates    every breakfast price shown on the website (standard + member).
  3. Policies     full inclusions + cancellation text, one row per plan.
  4. Search Info  what was searched, per-hotel status, rules used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .pricing import DEFAULT_SETTINGS, MEMBER_BAR, MEMBER_OFFER, OTHER, STANDARD_BAR

MEAL_ORDER = {"Room Only": 0, "Breakfast (BnB)": 1, "Half Board": 2, "Full Board": 3, "Unknown": 4}
PRICE_KEY = "Price incl. GST"

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
NONREF_FILL = PatternFill("solid", fgColor="FDE2E1")
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
KEY_FILL = PatternFill("solid", fgColor="E8F3EC")
GOOD_FILL = PatternFill("solid", fgColor="C6EFCE")
BAD_FILL = PatternFill("solid", fgColor="FFC7CE")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(bottom=THIN)
INR = '"₹"#,##0'
PCT = "0%"
DATE_FMT = "ddd, dd-mmm-yyyy"

VOLT_GST_OPTIONS = ("No", "Yes")
COMPARE_OPTIONS = ("Net Rate (excl. GST)", "After Discount (excl. GST)", "Our Rate (no discount)")


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


def rate_kind(r: Dict[str, Any]) -> str:
    """Rate Type for any hotel. IHCL sets Rate Category; others (Leela) fall back to the name."""
    cat = r.get("Rate Category")
    if cat:
        return cat
    if "member" in str(r.get("rate type", "")).lower():
        return MEMBER_OFFER
    return STANDARD_BAR if r.get("Is BAR") == "Yes" else OTHER


def _nights(r: Dict[str, Any]) -> int:
    try:
        return max(int(r.get("Nights") or 1), 1)
    except (TypeError, ValueError):
        return 1


@dataclass
class Candidate:
    """One bookable (or website-shown) price for a room, per night excl. GST."""
    per_night: float
    kind: str           # STANDARD_BAR / MEMBER_BAR / MEMBER_OFFER / OTHER
    plan: str
    record: Dict[str, Any]


# Tie-break when two plans cost the same: member offer (City Special) first.
KIND_PRIORITY = {MEMBER_OFFER: 0, MEMBER_BAR: 1, STANDARD_BAR: 2, OTHER: 3}


def pick_our_rate(cands: List[Candidate]) -> Candidate:
    """The rate we quote: the lowest of all breakfast rates for this room and night."""
    # TODO(human): decide if a non-refundable rate (e.g. "Advance Purchase") may be
    # "our rate". Today: plain lowest price, member plan first on a tie.
    return min(cands, key=lambda c: (round(c.per_night, 2), KIND_PRIORITY.get(c.kind, 9)))


def candidates_for(rows: List[Dict[str, Any]]) -> List[Candidate]:
    out: List[Candidate] = []
    for r in rows:
        rate, n = _num(r.get("Rate")), _nights(r)
        if rate is None:
            continue
        out.append(Candidate(rate / n, rate_kind(r), str(r.get("rate type", "")), r))
    return out


def standard_of(cands: List[Candidate]) -> Optional[Candidate]:
    """Website STANDARD RATE: the BAR plan that also shows a MEMBER RATE (e.g. Breakfast
    Inclusive Rate), else the cheapest standard BAR plan."""
    member_codes = {c.record.get("Rate Code") for c in cands if c.kind == MEMBER_BAR}
    base = [c for c in cands if c.kind == STANDARD_BAR and c.record.get("Rate Code") in member_codes]
    base = base or [c for c in cands if c.kind == STANDARD_BAR]
    return min(base, key=lambda c: c.per_night) if base else None


def compare_rows(records: Iterable[Dict[str, Any]], meal_plans: Sequence[str]) -> List[Dict[str, Any]]:
    """One row per (hotel, check-in, nights, room) with the candidates summarised."""
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in records:
        if r.get("Meal Plan") in meal_plans and _num(r.get("Rate")) is not None:
            k = (r.get("Hotel Name", ""), str(r.get("Check In Date", "")), _nights(r), r.get("Room Name", ""))
            groups.setdefault(k, []).append(r)
    out = []
    for (hotel, ci, nights, room), rows in sorted(groups.items()):
        cands = candidates_for(rows)
        if not cands:
            continue

        def cheapest(kinds):
            m = [c for c in cands if c.kind in kinds]
            return min(m, key=lambda c: (round(c.per_night, 2), KIND_PRIORITY.get(c.kind, 9))) if m else None

        out.append({"hotel": hotel, "check_in": ci, "nights": nights, "room": room,
                    "standard": standard_of(cands), "member_rate": cheapest({MEMBER_BAR}),
                    "offer": cheapest({MEMBER_OFFER}), "ours": pick_our_rate(cands)})
    return out


# --------------------------------------------------------------------------- #
def _style_header(ws, row: int, widths: Sequence[int]):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(row=row, column=i)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 45


def _sheet(wb: Workbook, title: str, headers: Sequence[str], widths: Sequence[int]):
    ws = wb.create_sheet(title)
    ws.append(list(headers))
    _style_header(ws, 1, widths)
    ws.freeze_panes = "C2"
    return ws


def _finish(ws, money_cols: Iterable[int], date_cols: Iterable[int], key_cols: Iterable[int] = (),
            first_row: int = 2):
    for row in ws.iter_rows(min_row=first_row):
        for c in row:
            c.border = BORDER
        for i in money_cols:
            row[i - 1].number_format = INR
        for i in date_cols:
            row[i - 1].number_format = DATE_FMT
        for i in key_cols:
            row[i - 1].fill = KEY_FILL
            row[i - 1].font = Font(bold=True)
    ws.auto_filter.ref = f"A{first_row - 1}:{get_column_letter(ws.max_column)}{ws.max_row}"


# --------------------------------------------------------------------------- #
COMPARE_HEADERS = [
    "Hotel", "Check-in", "Nights", "Room",                                       # A-D
    "STANDARD RATE /night", "MEMBER RATE /night",                                 # E-F
    "Member-only Offer", "Member-only Offer /night",                              # G-H
    "OUR RATE /night (lowest)", "Our Rate Plan", "Rate Type", "Cancellation",     # I-L
    "Discount", "After Discount", "Commission", "Net Rate excl. GST",             # M-P
    "GST %", "GST", "Net Rate incl. GST",                                         # Q-S
    "VOLT RATE /night (type here)", "Our Value Compared", "Difference (Volt - Ours)",  # T-V
    "Difference %", "Result",                                                     # W-X
]
COMPARE_WIDTHS = [30, 16, 7, 30, 13, 15, 32, 13, 14, 34, 16, 34,
                  11, 12, 11, 13, 7, 11, 13, 15, 13, 14, 10, 13]
HEADER_ROW = 9


def _write_compare(wb: Workbook, records: List[Dict[str, Any]], s: Dict[str, Any]) -> int:
    ws = wb.active
    ws.title = "Compare"
    ws["A1"] = "Compare with Volt -- per night, per room, excl. GST unless stated. Yellow cells are editable."
    ws["A1"].font = Font(bold=True, size=12, color="1F3A5F")
    settings = [  # (label cell, label, value cell, value, format)
        ("A2", "Discount %", "B2", float(s["discount_pct"]) / 100, PCT),
        ("A3", "Commission %", "B3", float(s["commission_pct"]) / 100, PCT),
        ("A4", "GST % (Our Rate <= threshold)", "B4", float(s["gst_low_pct"]) / 100, PCT),
        ("A5", "GST % (above threshold)", "B5", float(s["gst_high_pct"]) / 100, PCT),
        ("A6", "GST threshold /night", "B6", float(s["gst_threshold_per_night"]), INR),
        ("D2", "Volt rates include GST?", "E2", "No", None),
        ("D3", "Compare Volt with", "E3", COMPARE_OPTIONS[0], None),
    ]
    for lc, label, vc, value, fmt in settings:
        ws[lc], ws[vc] = label, value
        ws[lc].font = Font(bold=True)
        ws[vc].fill = INPUT_FILL
        if fmt:
            ws[vc].number_format = fmt
    ws["D4"] = ("Our Rate = lowest breakfast rate for the room (member plans first on a tie). "
                "Then - Discount - Commission. GST slab decided on Our Rate BEFORE discount, "
                "charged on the discounted price. PENDING TEAM CONFIRMATION.")
    ws["D4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("D4:L7")
    for cell, opts in (("E2", VOLT_GST_OPTIONS), ("E3", COMPARE_OPTIONS)):
        dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(cell)

    for i, h in enumerate(COMPARE_HEADERS, 1):
        ws.cell(row=HEADER_ROW, column=i, value=h)
    _style_header(ws, HEADER_ROW, COMPARE_WIDTHS)
    ws.freeze_panes = f"E{HEADER_ROW + 1}"

    low = "<=" if s.get("gst_threshold_inclusive", True) else "<"
    rows = compare_rows(records, s["excel_meal_plans"])
    for n, c in enumerate(rows, HEADER_ROW + 1):
        o, std, web, mem = c["ours"], c["standard"], c["member_rate"], c["offer"]
        ws.append([
            c["hotel"], _d(c["check_in"]), c["nights"], c["room"],
            round(std.per_night, 2) if std else None,
            round(web.per_night, 2) if web else None,
            mem.plan if mem else None, round(mem.per_night, 2) if mem else None,
            round(o.per_night, 2), o.plan, o.kind, cancellation_text(o.record),
            f"=I{n}*$B$2", f"=I{n}-M{n}", f"=N{n}*$B$3", f"=N{n}-O{n}",
            f"=IF(I{n}{low}$B$6,$B$4,$B$5)", f"=N{n}*Q{n}", f"=P{n}+R{n}",
            None,
            (f'=IF($E$3="{COMPARE_OPTIONS[2]}",I{n}*IF($E$2="Yes",1+Q{n},1),'
             f'IF($E$3="{COMPARE_OPTIONS[1]}",N{n}*IF($E$2="Yes",1+Q{n},1),'
             f'P{n}+IF($E$2="Yes",R{n},0)))'),
            f'=IF(T{n}="","",T{n}-U{n})', f'=IF(T{n}="","",V{n}/U{n})',
            f'=IF(T{n}="","",IF(ABS(V{n})<1,"Same",IF(V{n}>0,"Volt higher","Volt lower")))',
        ])
        ws.cell(row=n, column=20).fill = INPUT_FILL
        ws.cell(row=n, column=17).number_format = PCT
        ws.cell(row=n, column=23).number_format = "0.0%"
        if str(o.record.get("Free Cancellation", "")).startswith("No"):
            ws.cell(row=n, column=12).fill = NONREF_FILL
    _finish(ws, money_cols=[5, 6, 8, 9, 13, 14, 15, 16, 18, 19, 20, 21, 22], date_cols=[2],
            key_cols=[9], first_row=HEADER_ROW + 1)
    for col in (16, 19):  # net rates in bold
        for row in ws.iter_rows(min_row=HEADER_ROW + 1, min_col=col, max_col=col):
            row[0].font = Font(bold=True)
    last = max(ws.max_row, HEADER_ROW + 1)
    ws.conditional_formatting.add(f"X{HEADER_ROW + 1}:X{last}",
                                  CellIsRule(operator="equal", formula=['"Volt higher"'], fill=GOOD_FILL))
    ws.conditional_formatting.add(f"X{HEADER_ROW + 1}:X{last}",
                                  CellIsRule(operator="equal", formula=['"Volt lower"'], fill=BAD_FILL))
    return len(rows)


def write_excel(records: List[Dict[str, Any]], path: str | Path, request=None,
                statuses: Optional[List[Any]] = None, settings: Optional[Dict[str, Any]] = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if settings is None:
        try:
            from .registry import load_config
            settings = load_config().get("pricing", {})
        except Exception:
            settings = {}
    s = {**DEFAULT_SETTINGS, **{k: v for k, v in settings.items() if not k.startswith("_")}}
    meals = list(s["excel_meal_plans"])
    shown = [r for r in records if r.get("Meal Plan") in meals]
    wb = Workbook()

    # ---- 1. Compare --------------------------------------------------- #
    n_compare = _write_compare(wb, records, s)

    # ---- 2. All Rates ------------------------------------------------- #
    ws = _sheet(wb, "All Rates", [
        "Hotel", "Check-in", "Check-out", "Nights", "Adults", "Room", "Rate Plan", "Rate Type",
        "Price Type", "Meal Plan", "Price excl. GST", "Member Only", "GST %", "GST",
        "Price incl. GST", "Per Night excl. GST", "Per Night incl. GST", "Cancellation",
        "Free Cancel Until", "Rooms Left", "Rate Code", "Room Code", "GST Check",
    ], [30, 16, 16, 7, 7, 30, 34, 16, 8, 15, 13, 14, 8, 11, 13, 13, 13, 40, 17, 8, 9, 9, 14])
    gst_ok = gst_bad = 0
    sort_key = lambda r: (r.get("Hotel Name", ""), str(r.get("Check In Date", "")),  # noqa: E731
                          r.get("Room Name", ""), _num(r.get("Rate")) or 9e15)
    for r in sorted(shown, key=sort_key):
        check = r.get("GST Check", "")
        gst_ok += check == "OK"
        gst_bad += bool(check) and check != "OK"
        kind = rate_kind(r)
        ws.append([
            r.get("Hotel Name"), _d(r.get("Check In Date")), _d(r.get("Check Out Date")),
            r.get("Nights"), r.get("Adults"), r.get("Room Name"), r.get("rate type"), kind,
            r.get("Price Type") or ("Member" if kind in (MEMBER_BAR, MEMBER_OFFER) else "Standard"),
            r.get("Meal Plan"), _num(r.get("Rate")), "Yes" if kind == MEMBER_OFFER else "No", r.get("GST %"),
            _num(r.get("GST Amount")), _num(r.get(PRICE_KEY)), _num(r.get("Per Night excl. GST")),
            _num(r.get("Per Night incl. GST")), cancellation_text(r),
            r.get("Free Cancellation Until") or "", r.get("Available Inventory"),
            r.get("Rate Code"), r.get("Room Code"), check,
        ])
        if str(r.get("Free Cancellation", "")).startswith("No"):
            ws.cell(row=ws.max_row, column=18).fill = NONREF_FILL
        if check and check != "OK":
            ws.cell(row=ws.max_row, column=23).fill = WARN_FILL
    _finish(ws, money_cols=[11, 14, 15, 16, 17], date_cols=[2, 3], key_cols=[11])

    # ---- 3. Policies -------------------------------------------------- #
    ws = _sheet(wb, "Policies", ["Hotel", "Rate Code", "Rate Plan", "Rate Type", "Meal Plan",
                                 "Inclusions", "Cancellation Policy (hotel text)"],
                [30, 10, 34, 16, 15, 70, 70])
    seen = set()
    for r in sorted(shown, key=lambda r: (r.get("Hotel Name", ""), str(r.get("Rate Code")))):
        k = (r.get("Hotel Name"), r.get("Rate Code"), r.get("Cancellation policy in popup modal"))
        if k in seen:
            continue
        seen.add(k)
        ws.append([r.get("Hotel Name"), r.get("Rate Code"), r.get("rate type"), rate_kind(r),
                   r.get("Meal Plan"), r.get("Rate description in popup modal"),
                   r.get("Cancellation policy in popup modal")])
        for c in ws[ws.max_row][5:7]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    _finish(ws, money_cols=[], date_cols=[])

    # ---- 4. Search Info ----------------------------------------------- #
    ws = wb.create_sheet("Search Info")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 100
    info = [("Generated", datetime.now().strftime("%d %b %Y, %I:%M %p"))]
    if request is not None:
        wins = request.windows()
        occ = request.aggregate_occupancy()
        info += [("Check-in dates", f"{wins[0][0]} to {wins[-1][0]} ({len(wins)} dates)"),
                 ("Nights per stay", request.night_duration),
                 ("Occupancy", f"{occ['adults']} adult(s), {occ['rooms']} room(s)")]
    info += [("Rates scraped", f"{len(records)} in total; {len(shown)} are {', '.join(meals)} "
                               f"(shown in this file -- other meal plans are in the raw CSV)"),
             ("Compare rows", f"{n_compare} hotel x date x room combinations"), ("", ""),
             ("RULES", ""),
             ("Source", "Exactly the prices tajhotels.com shows on its Room Rates tab (same request "
                        "as the website): STANDARD RATE and MEMBER RATE per plan, plus member-only "
                        "offers. Nothing is calculated."),
             ("Our Rate", "Lowest breakfast rate for the room and night (member first on a tie)."),
             ("Rate Type", "Standard BAR (website STANDARD RATE) | Member BAR (website MEMBER RATE of "
                           "the same plan) | Member Offer (member-only plan, e.g. The City Special) | Other"),
             ("Discount / Commission", f"Compare sheet: Our Rate - {s['discount_pct']:g}% discount, "
                                       f"then - {s['commission_pct']:g}% commission on the discounted "
                                       f"price. Change the yellow cells to recalculate."),
             ("GST %", "Rule: price excl. GST per night per room below Rs 7,500 -> 5%, otherwise 18%; "
                       "decided before discount. PENDING TEAM CONFIRMATION."),
             ("GST Check", f"Hotel GST vs the rule: {gst_ok} rows OK, {gst_bad} rows differ "
                           f"(highlighted yellow in All Rates)."),
             ("", ""), ("HOTEL STATUS", "")]
    for row in info:
        ws.append(list(row))
    for st in statuses or []:
        extra = f" | sold out: {', '.join(st.sold_out_dates)}" if st.sold_out_dates else ""
        ws.append([st.name, f"{st.state.upper()} -- {st.detail}{extra}"])
    for row in ws.iter_rows():
        if row[0].value in ("RULES", "HOTEL STATUS"):
            row[0].font = Font(bold=True, color="1F3A5F")
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(path)
    return path
