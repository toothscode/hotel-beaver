"""
Tests for core/rates.py, built from REAL rates returned by the APIs on
2026-11-18 (IHCL Hudini + Leela SynXis). Run:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.rates import (  # noqa: E402
    BREAKFAST, FULL_BOARD, HALF_BOARD, ROOM_ONLY, UNKNOWN,
    classify_meal_plan, free_cancellation,
)

# (rate_code, name, description, breakfast_flag) -> expected
MEAL_CASES = [
    # ---- IHCL (structured breakfast flag available) ----
    ("R04", "Best Available Rate - Room Only", "Inclusive of Standard Wi-Fi.", False, ROOM_ONLY),
    ("NPGRO", "Member Rate Gold - Room Only", "7% NeuCoins on eligible spends", False, ROOM_ONLY),
    ("T05", "Breakfast Inclusive Rate", "Rate inclusive of Daily Breakfast. Inclusive of standard Wi-Fi.", True, BREAKFAST),
    ("NPGBB", "Member Rate Gold - Breakfast Inclusive", "Inclusive of buffet breakfast at a designated dining venue.", True, BREAKFAST),
    # trap: "Advance Purchase" -> AP must NOT be read as American Plan (full board)
    ("T09N", "Advance Purchase - Breakfast inclusive", "Inclusive of breakfast.", True, BREAKFAST),
    ("TUGR", "Perfect Staycations: Inclusive of Breakfast and One Set Meal",
     "Inclusive of buffet breakfast and One Major Meal (choice of lunch or dinner) from a set menu at Capital Kitchen.", True, HALF_BOARD),
    # trap: "Savings on ... Meal-inclusive Stays" is marketing; the real inclusion is the 2nd line
    ("TFIN", "Festivals of India",
     "20% Savings on Breakfast & Meal-inclusive Stays.\nInclusive of breakfast and one major meal (choice of buffet lunch or dinner) at a designated dining venue.", True, HALF_BOARD),
    ("TWCI", "City Woyage - Special Offer for Woman Travellers",
     "Includes daily breakfast and one Major Meal (choice of lunch or dinner) from a set menu at Machan.", True, HALF_BOARD),
    # trap: dining *discount* is not a meal
    ("TVVL", "Vivanta Vibes: Bed Breakfast & More",
     "Special rate inclusive of Breakfast.\nHigh Tea with unlimited mocktails.\n15% savings on the dining experience.", True, BREAKFAST),
    # ---- Leela / SynXis (no structured flag -> None) ----
    ("BB0T3", "Bed and Breakfast", "Check-in time is 2:00 pm and Check-out time is 12 noon.", None, BREAKFAST),
    ("GHABB0T3", "Leela DISCOVERY Member Rate", "- Buffet Breakfast\n- 15% savings on Hotel Services except liquor", None, BREAKFAST),
    ("PKGREP", "The Joy of The Season", "- Daily breakfast with nourishing selections by Aujasya\n- Seasonal High Tea", None, BREAKFAST),
    # Indian meal-plan code in the rate code: MAP = half board
    ("STMAP", "TIME Travel with The Leela", "- Turndown Amenity once during the stay\n- Welcome Immunity Drink on Arrival", None, HALF_BOARD),
    # real PKG44 DetailedDescription contains "- Room Only"
    ("PKG44", "Blissful Escapes", "- Room Only\n- Complimentary second drink on select beverages", None, ROOM_ONLY),
    # nothing tells us -> say so, don't guess
    ("PKGX", "Blissful Escapes", "- Outside food Music speakers Hookah etc are not allowed in Hotel Premises.", None, UNKNOWN),
    # ---- generic full board ----
    ("FBX1", "All Meals Package", "Includes breakfast, lunch and dinner daily.", True, FULL_BOARD),
    ("EP01", "Room Only Saver", "Wi-Fi included.", None, ROOM_ONLY),
]


@pytest.mark.parametrize("code,name,desc,flag,expected", MEAL_CASES,
                         ids=[c[0] for c in MEAL_CASES])
def test_classify_meal_plan(code, name, desc, flag, expected):
    assert classify_meal_plan(code, name, desc, flag) == expected


# ---- free cancellation: verified against the API's own description text ----
def test_ihcl_free_until_two_days_before():
    # API text: "Free Cancellation (100% Refund) until 07 Dec 2026 2:00 PM IST" for check-in 09 Dec
    out = free_cancellation("2026-12-09", True, 2, "1400")
    assert out == {"Free Cancellation": "Yes", "Free Cancellation Until": "2026-12-07 14:00",
                   "Free Cancel Days Before Check-in": 2}


def test_synxis_time_zero_uses_checkin_time():
    # Leela "48 Hours Cancellation": CancelTimeIn=2, CancelTime="0", worded vs 1400 check-in
    out = free_cancellation("2026-12-09", True, 2, "0")
    assert out["Free Cancellation Until"] == "2026-12-07 14:00"


def test_non_refundable():
    out = free_cancellation("2027-01-15", False, 0, "0")   # IHCL T09N Advance Purchase
    assert out["Free Cancellation"] == "No (Non-refundable)"
    assert out["Free Cancellation Until"] == ""


def test_unknown_policy():
    assert free_cancellation("2027-01-15", None, None)["Free Cancellation"] == "Unknown"
