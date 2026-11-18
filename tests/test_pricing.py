"""
Price + GST columns and Excel export tests (no TAC -- the team applies it).
GST rule (pending team confirmation): per night per room on price excl. GST,
< 7,500 -> 5%, otherwise 18%. Run:  python -m pytest tests -q
"""
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.excel import best_deals, write_excel  # noqa: E402
from core.pricing import MEMBER_BAR, OTHER, STANDARD_BAR, price_columns  # noqa: E402


def rec(rate, tax=None, ci="2027-01-10", co="2027-01-11", nightly=None, rooms=1, **kw):
    r = {"Rate": rate, "Tax Amount": tax, "Check In Date": ci, "Check Out Date": co, "Rooms": rooms}
    if nightly:
        r["Nightly Rates (excl. tax)"] = "; ".join(str(x) for x in nightly)
    r.update(kw)
    return r


def test_below_threshold_5pct_matches_hotel():
    # Real: Boulevard9 NPGBB 2N x 6,600 -> hotel tax 660 (5%)
    p = price_columns(rec(13200, 660, co="2027-01-12", nightly=[6600, 6600]))
    assert (p["GST %"], p["GST Amount"], p["Price incl. GST"], p["GST Check"]) == ("5%", 660, 13860, "OK")
    assert (p["Per Night excl. GST"], p["Per Night incl. GST"]) == (6600, 6930)


def test_above_threshold_18pct_matches_hotel():
    # Real: Taj Tirupati T05 2N 12,590 + 12,390 -> hotel tax 4,496.40 (18%)
    p = price_columns(rec(24980, 4496.4, co="2027-01-12", nightly=[12590, 12390]))
    assert (p["GST %"], p["GST Amount"], p["GST Check"]) == ("18%", 4496.4, "OK")


def test_slab_decided_on_price_before_gst_not_after():
    # 7,000 excl. GST is below 7,500 -> 5%, even though 7,000 + 18% would be above
    p = price_columns(rec(7000, 350))
    assert p["GST %"] == "5%" and p["GST Check"] == "OK"


def test_exactly_7500_is_5pct_by_default_and_configurable():
    assert price_columns(rec(7500, 375))["GST %"] == "5%"
    strict = price_columns(rec(7500, 1350), {"gst_threshold_inclusive": False})
    assert strict["GST %"] == "18%" and strict["GST Check"] == "OK"


def test_mixed_slabs_per_night():
    # weekday 7,000 (5% = 350) + weekend 8,200 (18% = 1,476) = 1,826
    p = price_columns(rec(15200, 1826, co="2027-01-12", nightly=[7000, 8200]))
    assert p["GST %"] == "Mixed 5%/18%" and p["GST Check"] == "OK"


def test_threshold_is_per_room():
    # 2 rooms, 14,000/night total -> 7,000 per room -> 5%
    assert price_columns(rec(14000, 700, rooms=2))["GST %"] == "5%"


def test_hotel_gst_that_differs_is_flagged_not_hidden():
    p = price_columns(rec(10000, 500))           # rule says 18% = 1,800
    assert p["GST Amount"] == 500                # hotel's figure is what we report
    assert p["GST Check"].startswith("Differs")


def test_missing_hotel_tax_falls_back_to_rule():
    p = price_columns(rec(10000, None))
    assert p["GST Amount"] == 1800 and p["GST Check"] == "No hotel tax -- rule used"


def test_no_tac_columns_anywhere():
    p = price_columns(rec(10000, 1800, **{"Rate Category": STANDARD_BAR}))
    assert not any("TAC" in k or "Net" in k for k in p)


# ---- Excel ------------------------------------------------------------------ #
def full(rate, tax, cat, plan, code, meal="Breakfast (BnB)", free="Yes"):
    r = rec(rate, tax, co="2027-01-14", **{
        "Hotel Name": "Taj Palace, New Delhi", "Room Name": "Deluxe", "rate type": plan,
        "Rate Code": code, "Meal Plan": meal, "Free Cancellation": free, "Rate Category": cat,
        "Free Cancellation Until": "2027-01-08 14:00" if free == "Yes" else "",
        "Free Cancel Days Before Check-in": 2 if free == "Yes" else "", "Adults": 2,
        "Cancellation policy in popup modal": "x", "Rate description in popup modal": "y"})
    r.update(price_columns(r))
    return r


def test_best_deal_never_picks_pricier_lookalike():
    # Real 10-14 Jan Taj Palace TKX prices: T05 268,300 | T15 254,885 | NPGBB 214,640 | T15N 242,141
    rows = [full(268300, 268300 * .18, STANDARD_BAR, "Breakfast Inclusive Rate", "T05"),
            full(254885, 254885 * .18, STANDARD_BAR, "Stay A Bit Longer", "T15"),
            full(214640, 214640 * .18, MEMBER_BAR, "Member Rate Gold - Breakfast Inclusive", "NPGBB"),
            full(242141, 242141 * .18, MEMBER_BAR, "Stay A Bit Longer Member Rate", "T15N")]
    deals = best_deals(rows)
    assert len(deals) == 1 and deals[0]["best"]["Rate Code"] == "NPGBB"


def test_best_deal_shows_refundable_alternative():
    rows = [full(9000, 1620, OTHER, "Advance Purchase", "T09N", free="No (Non-refundable)"),
            full(12000, 2160, STANDARD_BAR, "BAR", "T05")]
    d = best_deals(rows)[0]
    assert d["best"]["Rate Code"] == "T09N" and d["refundable"]["Rate Code"] == "T05"


def test_excel_file_structure(tmp_path):
    rows = [full(268300, 268300 * .18, STANDARD_BAR, "Breakfast Inclusive Rate", "T05"),
            full(9000, 1620, OTHER, "Advance Purchase", "T09N", free="No (Non-refundable)")]
    out = write_excel(rows, tmp_path / "x.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames == ["Best Deals", "All Rates", "Policies", "Search Info"]
    ws = wb["All Rates"]
    headers = [c.value for c in ws[1]]
    for h in ["Price excl. GST", "GST %", "GST", "Price incl. GST", "Per Night excl. GST",
              "Per Night incl. GST", "Rate Type", "Meal Plan", "Cancellation", "GST Check"]:
        assert h in headers
    assert not any("TAC" in h or "Net" in h for h in headers)
    assert ws.max_row == 3 and ws.freeze_panes == "C2" and ws.auto_filter.ref
    cxl = [ws.cell(row=i, column=headers.index("Cancellation") + 1).value for i in (2, 3)]
    assert "Non-refundable" in cxl and any(c.startswith("Free until") for c in cxl)
    info = {r[0]: r[1] for r in wb["Search Info"].iter_rows(values_only=True) if r[0]}
    assert "PENDING TEAM CONFIRMATION" in info["GST %"]
