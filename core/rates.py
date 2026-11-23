#!/usr/bin/env python3
"""
Shared rate classification: meal plan + free-cancellation window.

Every hotel maps its own API fields onto these helpers so the CSV columns
"Meal Plan", "Free Cancellation", "Free Cancellation Until" and
"Free Cancel Days Before Check-in" mean the same thing for every hotel.

Indian hotel meal-plan conventions (used in rate codes, e.g. Leela "STMAP"):
    EP  = European Plan       -> Room Only
    CP  = Continental Plan    -> Breakfast (BnB)
    MAP = Modified American   -> Half Board (breakfast + 1 meal)
    AP  = American Plan       -> Full Board (all meals)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, Optional

ROOM_ONLY = "Room Only"
BREAKFAST = "Breakfast (BnB)"
HALF_BOARD = "Half Board"
FULL_BOARD = "Full Board"
UNKNOWN = "Unknown"

# Lines that only advertise a discount, never an inclusion.
_MARKETING = re.compile(r"\b(savings?|discount|\d+\s*%\s*off)\b", re.I)
_FULL_BOARD = re.compile(
    r"breakfast,?\s+lunch,?\s+(and|&)\s+dinner"
    r"|\ball\s+meals\b|\bfull[\s-]board\b|\ball[\s-]inclusive\b"
    r"|(?<!modified )\bamerican plan\b"
)
_HALF_BOARD = re.compile(
    r"\b(one|1)\s+(major\s+|set\s+)?meal\b"
    r"|\blunch\s+or\s+dinner\b"
    r"|\bbreakfast\s+(and|&)\s+(lunch|dinner)\b"
    r"|\bhalf[\s-]board\b|\bmodified american plan\b"
)
_ROOM_ONLY = re.compile(r"\broom[\s-]only\b|\bwithout\s+breakfast\b|\beuropean plan\b")
_BREAKFAST = re.compile(r"\bbreakfast\b")


def classify_meal_plan(
    rate_code: str,
    name: str,
    description: str,
    breakfast_flag: Optional[bool] = None,
) -> str:
    """
    Return one of ROOM_ONLY / BREAKFAST / HALF_BOARD / FULL_BOARD / UNKNOWN.

    Inputs:
      rate_code      e.g. "R04", "NPGRO", "BB0T3", "STMAP"
      name           rate plan name, e.g. "Best Available Rate - Room Only"
      description    full inclusions text (may mention "one major meal")
      breakfast_flag structured API flag when the hotel has one (IHCL
                     `indicators.breakfastIncluded`), else None (Leela)
    """
    code = (rate_code or "").upper().strip()
    # Drop marketing lines ("20% Savings on ... Meal-inclusive Stays",
    # "15% savings on the dining experience"): they mention meals without
    # including them. The rate name is always kept.
    lines = [ln for ln in re.split(r"[\n.;|]+", description or "")
             if ln.strip() and not _MARKETING.search(ln)]
    text = " ".join([name or ""] + lines).lower()

    # 1. More food wins: an "extra meal" rate is also breakfast_flag=True.
    if _FULL_BOARD.search(text):
        return FULL_BOARD
    if _HALF_BOARD.search(text) or code.endswith("MAP"):
        return HALF_BOARD
    # 2. Explicit room only (text, or EP plan code). A bare "AP" is never
    #    matched: "Advance Purchase" (T09N) is not American Plan. Plan codes
    #    only as a PREFIX: "PKGREP" ends in EP but is a breakfast package.
    if _ROOM_ONLY.search(text) or code.startswith("EP"):
        return ROOM_ONLY
    # 3. Breakfast: structured flag first (IHCL), then text.
    if breakfast_flag is True or _BREAKFAST.search(text) or code.startswith("CP"):
        return BREAKFAST
    # 4. API says explicitly "no breakfast" and nothing else was found.
    if breakfast_flag is False:
        return ROOM_ONLY
    return UNKNOWN


def free_cancellation(
    check_in: str,
    refundable: Optional[bool],
    days_before: Optional[int],
    time_hhmm: Optional[str] = None,
    default_time: str = "1400",
) -> Dict[str, str]:
    """
    Build the three free-cancellation columns from structured policy fields.

    refundable   True  -> free cancellation until a deadline
                 False -> non-refundable (penalty from booking)
                 None  -> unknown (policy missing)
    days_before  days before check-in the free window closes (IHCL
                 `cancelTimeIn`, SynXis `CancelTimeIn`)
    time_hhmm    deadline time on that day ("1400"); "0"/"" -> default_time
                 (hotel check-in time, as SynXis policies are worded
                 relative to the 14:00 check-in)
    """
    if refundable is None:
        return {"Free Cancellation": "Unknown", "Free Cancellation Until": "",
                "Free Cancel Days Before Check-in": ""}
    if not refundable:
        return {"Free Cancellation": "No (Non-refundable)", "Free Cancellation Until": "",
                "Free Cancel Days Before Check-in": ""}

    days = int(days_before or 0)
    hhmm = str(time_hhmm or "").strip()
    if not hhmm or hhmm == "0":
        hhmm = default_time
    hhmm = hhmm.zfill(4)
    deadline = datetime.strptime(check_in, "%Y-%m-%d") - timedelta(days=days)
    deadline = deadline.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]))
    return {
        "Free Cancellation": "Yes",
        "Free Cancellation Until": deadline.strftime("%Y-%m-%d %H:%M"),
        "Free Cancel Days Before Check-in": days,
    }
