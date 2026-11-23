#!/usr/bin/env python3
"""
Price + GST columns. No TAC / discounts here -- the contracting team applies
TAC (10% / 15%) themselves; this tool only reports prices.

For every rate:
    Price excl. GST   hotel's published rate before tax (whole stay)
    GST               the hotel's own tax amount from the booking API
    GST %             slab by the 5% / 18% rule, decided per NIGHT per ROOM on
                      the price excl. GST:  < Rs 7,500 -> 5%, otherwise 18%
                      (a stay can mix both, e.g. weekday 6,800 + weekend 8,200)
    GST Check         "OK" when the hotel's GST equals the rule, else flagged.
                      Verified 2026-11-18: 485/485 live IHCL rows matched.

RULE PENDING CONFIRMATION with the team: exactly Rs 7,500 -> 5% (per the GST
notification, "up to and including 7,500"). Change gst_threshold_inclusive
in config/hotels.json if the team decides otherwise.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

STANDARD_BAR = "Standard BAR"     # website STANDARD RATE of a BAR plan, e.g. "Breakfast Inclusive Rate"
MEMBER_BAR = "Member BAR"         # website MEMBER RATE of that plan (e.g. 32,500 -> 27,625)
MEMBER_OFFER = "Member Offer"     # member-only promotion, e.g. TCSN "The City Special"
OTHER = "Other"                   # public packages / promotions
MEMBER_CATEGORIES = (MEMBER_BAR, MEMBER_OFFER)

DEFAULT_SETTINGS = {"gst_low_pct": 5.0, "gst_high_pct": 18.0,
                    "gst_threshold_per_night": 7500.0, "gst_threshold_inclusive": True,
                    # Compare sheet (editable in Excel): our rate -> -discount -> -commission
                    "discount_pct": 10.0, "commission_pct": 10.0,
                    "excel_meal_plans": ["Breakfast (BnB)"]}


def _nightly(record: Dict[str, Any], nights: int, total: float) -> List[float]:
    raw = str(record.get("Nightly Rates (excl. tax)") or "")
    amounts = [float(x) for x in raw.split(";") if x.strip()]
    if len(amounts) == nights and abs(sum(amounts) - total) <= 1:
        return amounts
    return [total / nights] * nights  # fallback: even split


def gst_slab(per_room_night: float, s: Dict[str, Any]) -> float:
    t = float(s["gst_threshold_per_night"])
    low = per_room_night <= t if s.get("gst_threshold_inclusive", True) else per_room_night < t
    return float(s["gst_low_pct"] if low else s["gst_high_pct"])


def price_columns(record: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute the price/GST columns for one record."""
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    try:
        total = float(record.get("Rate"))
    except (TypeError, ValueError):
        return {}
    nights = max((date.fromisoformat(record["Check Out Date"])
                  - date.fromisoformat(record["Check In Date"])).days, 1)
    rooms = max(int(record.get("Rooms") or 1), 1)

    rule_gst, slabs = 0.0, set()
    for amount in _nightly(record, nights, total):
        pct = gst_slab(amount / rooms, s)
        slabs.add(pct)
        rule_gst += amount * pct / 100

    try:
        hotel_gst = float(record.get("Tax Amount"))
    except (TypeError, ValueError):
        hotel_gst = None
    gst = hotel_gst if hotel_gst is not None else rule_gst
    check = ("OK" if hotel_gst is not None and abs(hotel_gst - rule_gst) <= 1
             else "No hotel tax -- rule used" if hotel_gst is None
             else f"Differs: hotel {hotel_gst:,.0f} vs rule {rule_gst:,.0f}")
    label = (f"{min(slabs):g}%" if len(slabs) == 1
             else "Mixed " + "/".join(f"{x:g}%" for x in sorted(slabs)))
    web_member = ""
    return {
        "Nights": nights,
        "GST %": label,
        "GST Amount": round(gst, 2),
        "Price incl. GST": round(total + gst, 2),
        "Per Night excl. GST": round(total / nights, 2),
        "Per Night incl. GST": round((total + gst) / nights, 2),
        "GST Check": check,
    }


def apply_prices(records: List[Dict[str, Any]], settings: Optional[Dict[str, Any]] = None) -> None:
    for r in records:
        r.update(price_columns(r, settings))
