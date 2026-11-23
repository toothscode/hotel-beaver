"""Supplier vs Volt sheet: the 3 website prices per room, and the supplier formulas."""
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pricing import MEMBER_BAR, MEMBER_OFFER, OTHER, STANDARD_BAR  # noqa: E402
from tools.supplier_check import build, net_member, net_standard, room_rows, three_rates  # noqa: E402

H = "Taj Mahal, New Delhi"


def r(rate, cat, code, plan, room="LUXURY TWIN", ci="2026-12-06", meal="Breakfast (BnB)", total=None):
    return {"Hotel Name": H, "Check In Date": ci, "Room Name": room, "Meal Plan": meal, "Rate": str(rate),
            "Total With Tax": str(total or rate * 1.18), "Rate Category": cat, "Rate Code": code, "rate type": plan}


# real 6 Dec 2026, Luxury Room City View Twin (website: STANDARD 32,500 / MEMBER 27,625)
ROWS = [r(32500, STANDARD_BAR, "NPMBB", "Breakfast Inclusive Rate", total=38350),
        r(27625, MEMBER_BAR, "NPMBB", "Breakfast Inclusive Rate - Member Rate", total=32597.5),
        r(26000, MEMBER_OFFER, "TCSN", "The City Special"),
        r(27000, MEMBER_OFFER, "TCMBRN", "Taj Club"),
        r(45500, OTHER, "TUGR", "Perfect Staycations", meal="Half Board")]


def test_three_rates_are_exactly_the_website_prices():
    std, mem, offer = three_rates(ROWS)
    assert (std["Rate"], mem["Rate"], offer["Rate"]) == ("32500", "27625", "26000")   # lowest offer
    assert offer["rate type"] == "The City Special"


def test_half_board_ignored_and_sold_out_date_listed():
    out = list(room_rows(ROWS, H, ["2026-12-06", "2026-12-07"]))
    assert len(out) == 2 and out[0][1] == "LUXURY TWIN"
    assert out[1] == ("2026-12-07", None, None, None, None)


def test_formulas_follow_the_supplier_message():
    # standard: discount first, GST and commission on the discounted price
    assert net_standard("C7") == '=IF(C7="","",C7*(1-$B$2)+C7*(1-$B$2)*IF(C7<=$H$2,$J$2,$F$2)-C7*(1-$B$2)*$D$2)'
    # member / member offer: no discount, GST and commission on the member rate itself
    assert net_member("F7") == '=IF(F7="","",F7+F7*IF(F7<=$H$2,$J$2,$F$2)-F7*$D$2)'


def test_sheet_layout(tmp_path):
    out = build(ROWS, ["2026-12-06"], [H], tmp_path / "x.xlsx")
    ws = load_workbook(out)["Taj Mahal"]
    assert [c.value for c in ws[6]][:12] == [
        "Check-in", "Room", "Standard (excl. GST)", "Standard incl. GST", "Supplier Net - Standard",
        "Member (excl. GST)", "Member incl. GST", "Supplier Net - Member",
        "Member Offer (excl. GST)", "Member Offer incl. GST", "Supplier Net - Member Offer", "LOWEST Supplier Net"]
    row = [c.value for c in ws[7]]
    assert row[2:4] == [32500, 38350] and row[5:7] == [27625, 32597.5] and row[8] == 26000
    assert row[4] == net_standard("C7") and row[7] == net_member("F7") and row[10] == net_member("I7")
    assert (ws["C3"].value, ws["F3"].value) == (20000, 16000)        # supplier's examples on the sheet
