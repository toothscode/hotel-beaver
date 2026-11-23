"""
IHCL scraper (offline). Shapes copied from the live response to the SAME request
tajhotels.com sends (captured in Chrome 2026-11-19): rateFilter "RRM", memberTier "member".
Taj Mahal Delhi, 6-7 Dec 2026, room ATX (Luxury Room City View Twin Bed): the website
shows STANDARD RATE 32,500 / MEMBER RATE 27,625.   Run:  python -m pytest tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ihcl import IHCLClient  # noqa: E402
from core.pricing import MEMBER_BAR, MEMBER_OFFER, OTHER, STANDARD_BAR  # noqa: E402


def money(a):
    return {"total": {"amount": a, "amountWithTaxesFees": a * 1.18}, "tax": {"amount": a * .18}, "daily": []} if a else {}


def rate(code, name, cat, std=None, member=None, breakfast=True):
    return {"rateCode": code,
            "rateContent": {"name": name, "categoryCode": cat,
                            "details": {"rateClass": "Promotional", "description": name,
                                        "indicators": {"breakfastIncluded": breakfast}}},
            "cancellationPolicy": {"isFreeCancellation": True, "cancelTimeIn": 2, "cancelTime": "1400"},
            "standardRate": money(std), "memberRate": money(member)}


AVAIL = {"roomAvailability": {"roomRates": [{"roomCode": "ATX", "rooms": [
    rate("NPMBB", "Breakfast Inclusive Rate", "BAR", std=32500, member=27625),
    rate("TCSN", "The City Special", "PRO", member=26000),
    rate("NPMRO", "Best Available Rate- Room Only", "RAC", std=30000, member=25500, breakfast=False),
    rate("TVVL", "Vivanta Vibes: Bed Breakfast & More", "PRO", std=36000),
]}]}}


def extract():
    c = IHCLClient.__new__(IHCLClient)
    c.get_hotel_catalog = lambda: {"rooms": {"ATX": {"roomName": "LUXURY ROOM CITY VIEW TWIN BED", "imageUrls": []}}}
    return c.extract_structured_rooms(AVAIL, "2026-12-06", "2026-12-07")


def test_request_is_exactly_what_the_website_sends():
    c = IHCLClient("hid", "Taj Mahal, New Delhi")
    sent = {}
    c._post = lambda url, payload: sent.update(payload) or {}
    c.get_room_availability("2026-12-06", "2026-12-07", 2, 0, 1)
    assert (sent["rateFilter"], sent["memberTier"], sent["isLogin"], sent["isEmployeeOffer"]) == ("RRM", "member", False, False)


def test_standard_and_member_rate_both_scraped_exactly_as_website_shows():
    rows = {(r["Rate Code"], r["Price Type"]): r for r in extract()}
    std, mem = rows[("NPMBB", "Standard")], rows[("NPMBB", "Member")]
    assert (std["Rate"], std["Rate Category"], std["rate type"]) == (32500, STANDARD_BAR, "Breakfast Inclusive Rate")
    assert (mem["Rate"], mem["Rate Category"]) == (27625, MEMBER_BAR)        # screenshot: MEMBER RATE 27,625
    assert mem["rate type"] == "Breakfast Inclusive Rate - Member Rate"
    assert mem["Tax Amount"] == 27625 * .18 and mem["Meal Plan"] == "Breakfast (BnB)"


def test_member_only_offer_and_other_plans():
    rows = {(r["Rate Code"], r["Price Type"]): r for r in extract()}
    assert rows[("TCSN", "Member")]["Rate Category"] == MEMBER_OFFER and ("TCSN", "Standard") not in rows
    assert rows[("TCSN", "Member")]["Member Only"] == "Yes"
    assert rows[("NPMRO", "Member")]["Meal Plan"] == "Room Only"
    assert rows[("TVVL", "Standard")]["Rate Category"] == OTHER
    assert len(rows) == 6        # 2 + 1 + 2 + 1 prices, nothing invented
