#!/usr/bin/env python3
"""
Shared search-request contract for all hotel scrapers.

The root `search_request.json` holds the *rich* occupancy (per-room adults,
child AGES, infants) plus the sliding-window dates. Every hotel scraper parses
it through this module, then adapts the occupancy to whatever its own
website/API accepts (some sites want child ages, some only want totals).

Standard library only — any hotel package can import it regardless of its own
dependencies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple


@dataclass
class RoomOccupancy:
    """Occupancy for a single physical room."""
    adults: int = 1
    children: List[int] = field(default_factory=list)  # list of child AGES
    infants: int = 0

    @property
    def num_children(self) -> int:
        return len(self.children)


@dataclass
class SearchRequest:
    """Parsed + validated representation of search_request.json."""
    start_date: str                 # resolved YYYY-MM-DD (never "today")
    scrape_for_n_days: int          # number of check-in dates (sliding window)
    night_duration: int             # nights per stay
    rooms: List[RoomOccupancy]

    def windows(self) -> List[Tuple[str, str]]:
        """
        Sliding window of stays.

        For i in 0 .. scrape_for_n_days-1:
            check_in  = start_date + i days
            check_out = check_in + night_duration nights

        Produces `scrape_for_n_days` overlapping (check_in, check_out) pairs,
        each stepping forward by one day.
        """
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        out: List[Tuple[str, str]] = []
        for i in range(self.scrape_for_n_days):
            check_in = start + timedelta(days=i)
            check_out = check_in + timedelta(days=self.night_duration)
            out.append(
                (check_in.strftime("%Y-%m-%d"), check_out.strftime("%Y-%m-%d"))
            )
        return out

    def aggregate_occupancy(self) -> Dict[str, int]:
        """
        Flatten the rich per-room occupancy into plain totals.

        For sites/APIs (like Taj) that only accept flat adults / children /
        rooms integers. Child ages and infants are not lost -- they stay
        available via `self.rooms` for sites that need them.
        """
        return {
            "adults": sum(r.adults for r in self.rooms),
            "children": sum(r.num_children for r in self.rooms),
            "infants": sum(r.infants for r in self.rooms),
            "rooms": len(self.rooms),
        }


def _resolve_start_date(value: Any) -> str:
    """Accept 'today' (or empty) -> today's date, else validate YYYY-MM-DD."""
    if value is None or str(value).strip().lower() in ("", "today"):
        return datetime.now().strftime("%Y-%m-%d")
    text = str(value).strip()
    datetime.strptime(text, "%Y-%m-%d")  # raises ValueError on bad input
    return text


def _parse_rooms(raw_rooms: Any) -> List[RoomOccupancy]:
    if not isinstance(raw_rooms, list) or not raw_rooms:
        raise ValueError("search_request: 'rooms' must be a non-empty list")
    rooms: List[RoomOccupancy] = []
    for idx, r in enumerate(raw_rooms):
        if not isinstance(r, dict):
            raise ValueError(f"search_request: rooms[{idx}] must be an object")
        children = r.get("children", [])
        if isinstance(children, int):          # tolerate a bare count
            children = [0] * children
        if not isinstance(children, list):
            raise ValueError(
                f"search_request: rooms[{idx}].children must be a list of ages"
            )
        rooms.append(
            RoomOccupancy(
                adults=int(r.get("adults", 1)),
                children=[int(age) for age in children],
                infants=int(r.get("infants", 0)),
            )
        )
    return rooms


def load_search_request(path: str | Path) -> SearchRequest:
    """Load + validate the root search_request.json."""
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"search_request file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    n_days = int(data.get("scrape_for_n_days", 1))
    if n_days < 1:
        raise ValueError("search_request: 'scrape_for_n_days' must be >= 1")

    nights = int(data.get("night_duration", 1))
    if nights < 1:
        raise ValueError("search_request: 'night_duration' must be >= 1")

    return SearchRequest(
        start_date=_resolve_start_date(data.get("start_date")),
        scrape_for_n_days=n_days,
        night_duration=nights,
        rooms=_parse_rooms(data.get("rooms")),
    )
