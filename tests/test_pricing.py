"""
Price + GST columns and Excel export tests (no TAC -- the team applies it).
GST rule (pending team confirmation): per night per room on price excl. GST,
< 7,500 -> 5%, otherwise 18%. Run:  python -m pytest tests -q
"""
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.excel import Candidate, compare_rows, pick_our_rate, write_excel  # noqa: E402
from core.pricing import MEMBER_BAR, MEMBER_OFFER, OTHER, STANDARD_BAR, price_columns  # noqa: E402


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


def test_no_calculated_member_price_column():
    assert not any("Website" in k for k in price_columns(rec(67000, 12060)))


# ---- Excel ------------------------------------------------------------------ #
def full(rate, tax, cat, plan, code, meal="Breakfast (BnB)", free="Yes", room="Luxury Room Twin",
         co="2026-12-07", ci="2026-12-06"):
    r = rec(rate, tax, ci=ci, co=co, **{
        "Hotel Name": "Taj Mahal, New Delhi", "Room Name": room, "rate type": plan,
        "Rate Code": code, "Meal Plan": meal, "Free Cancellation": free, "Rate Category": cat,
        "Price Type": "Member" if cat in (MEMBER_BAR, MEMBER_OFFER) else "Standard",
        "Free Cancellation Until": "2026-11-19 14:00" if free == "Yes" else "",
        "Free Cancel Days Before Check-in": 1 if free == "Yes" else "", "Adults": 2,
        "Cancellation policy in popup modal": "x", "Rate description in popup modal": "y"})
    r.update(price_columns(r))
    return r


def screenshot_rows(city_special=True):
    """Real Taj Mahal Delhi, 6 Dec 2026, Luxury Room City View Twin (ATX), as the website shows it."""
    rows = [full(32500, 5850, STANDARD_BAR, "Breakfast Inclusive Rate", "NPMBB"),
            full(27625, 4972.5, MEMBER_BAR, "Breakfast Inclusive Rate - Member Rate", "NPMBB"),
            full(45500, 8190, STANDARD_BAR, "Perfect Staycations", "TUGR", meal="Half Board")]
    if city_special:
        rows.append(full(26000, 4680, MEMBER_OFFER, "The City Special", "TCSN"))
    return rows


def test_our_rate_is_lowest_and_member_offer_wins():
    (row,) = compare_rows(screenshot_rows(), ["Breakfast (BnB)"])
    assert row["standard"].per_night == 32500
    assert row["member_rate"].per_night == 27625
    assert row["offer"].plan == "The City Special" and row["offer"].per_night == 26000
    assert row["ours"].plan == "The City Special" and row["ours"].kind == MEMBER_OFFER


def test_without_member_offer_the_website_member_rate_is_used():
    (row,) = compare_rows(screenshot_rows(city_special=False), ["Breakfast (BnB)"])
    assert row["ours"].per_night == 27625 and row["ours"].kind == MEMBER_BAR


def test_half_board_never_in_compare_and_per_night_for_multi_night():
    hb = [full(30000, 5400, STANDARD_BAR, "Perfect Staycations", "TUGR", meal="Half Board")]
    assert compare_rows(hb, ["Breakfast (BnB)"]) == []
    two = [full(65000, 11700, STANDARD_BAR, "Breakfast Inclusive Rate", "NPMBB", co="2026-12-08")]
    assert compare_rows(two, ["Breakfast (BnB)"])[0]["ours"].per_night == 32500


def test_pick_our_rate_tie_break():
    a = Candidate(100, STANDARD_BAR, "BAR", {})
    b = Candidate(100, MEMBER_OFFER, "City Special", {})
    assert pick_our_rate([a, b]) is b
    assert pick_our_rate([a, Candidate(90, OTHER, "AP", {})]).plan == "AP"


def test_excel_file_structure(tmp_path):
    rows = screenshot_rows() + [full(9000, 1620, OTHER, "Advance Purchase", "T09N",
                                     free="No (Non-refundable)", room="Deluxe")]
    out = write_excel(rows, tmp_path / "x.xlsx", settings={})
    wb = load_workbook(out)
    assert wb.sheetnames == ["Compare", "All Rates", "Policies", "Search Info"]

    cmp_ = wb["Compare"]
    head = [c.value for c in cmp_[9]]
    assert head[8] == "OUR RATE /night (lowest)" and head[19].startswith("VOLT RATE")
    data = {r[3].value: r for r in cmp_.iter_rows(min_row=10)}
    lux = [c.value for c in data["Luxury Room Twin"]]
    n = data["Luxury Room Twin"][0].row
    assert lux[4:6] == [32500, 27625] and lux[8] == 26000 and lux[9] == "The City Special"
    assert lux[12] == f"=I{n}*$B$2" and lux[15] == f"=N{n}-O{n}"     # live formulas, own row
    data = {k: [c.value for c in v] for k, v in data.items()}
    assert (cmp_["B2"].value, cmp_["B3"].value) == (0.10, 0.10)       # 10% discount, 10% commission
    assert data["Deluxe"][11] == "Non-refundable"

    ws = wb["All Rates"]
    headers = [c.value for c in ws[1]]
    for h in ["Price excl. GST", "Price Type", "GST %", "Price incl. GST",
              "Rate Type", "Member Only", "Meal Plan", "Cancellation", "GST Check"]:
        assert h in headers
    assert ws.max_row == 5                                             # Half Board left out
    assert "Half Board" not in [ws.cell(row=i, column=10).value for i in range(2, 6)]
    assert not any("Website" in str(h) or "-15%" in str(h) for h in headers)
    info = {r[0]: r[1] for r in wb["Search Info"].iter_rows(values_only=True) if r[0]}
    assert "PENDING TEAM CONFIRMATION" in info["GST %"]
