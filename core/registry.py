#!/usr/bin/env python3
"""
The single list of hotels the tool can scrape.

Two sources:
  1. config/hotels.json  -- config-driven hotels (every IHCL property)
  2. hotels/<folder>/    -- hand-written scrapers (e.g. Leela / SynXis),
                            discovered by the `*_scraper.py` convention

`available_hotels()` returns HotelEntry objects; `entry.build()` creates a
ready scraper with the GST settings attached.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from .base import BaseHotelScraper

ROOT = Path(__file__).resolve().parents[1]
HOTELS_CONFIG = ROOT / "config" / "hotels.json"
HOTELS_DIR = ROOT / "hotels"


@dataclass
class HotelEntry:
    key: str
    name: str
    brand: str
    source: str                       # "config" | "folder"
    factory: Callable[[], BaseHotelScraper] = field(repr=False)

    def build(self) -> BaseHotelScraper:
        return self.factory()


def load_config(path: Path = HOTELS_CONFIG) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---- folder scrapers (moved here from main.py) ------------------------- #
def find_scraper(hotel_dir: Path) -> Optional[Path]:
    """`*_scraper.py` in the folder, else `scraper.py`, else None."""
    candidates = sorted(hotel_dir.glob("*_scraper.py"))
    if candidates:
        return candidates[0]
    fallback = hotel_dir / "scraper.py"
    return fallback if fallback.exists() else None


def load_scraper_class(scraper_file: Path) -> Optional[Type[BaseHotelScraper]]:
    """Import a hotel's scraper module and return its BaseHotelScraper subclass."""
    spec = importlib.util.spec_from_file_location(scraper_file.stem, scraper_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for value in vars(module).values():
        if (isinstance(value, type) and issubclass(value, BaseHotelScraper)
                and value is not BaseHotelScraper and value.__module__ == module.__name__):
            return value
    return None


def _folder_entries() -> List[HotelEntry]:
    entries: List[HotelEntry] = []
    if not HOTELS_DIR.exists():
        return entries
    for d in sorted(HOTELS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        f = find_scraper(d)
        cls = load_scraper_class(f) if f else None
        if cls is None:
            continue
        entries.append(HotelEntry(key=d.name, name=cls.name or d.name,
                                  brand=getattr(cls, "brand", "") or "Other",
                                  source="folder", factory=cls))
    return entries


def _config_entries(cfg: Dict[str, Any]) -> List[HotelEntry]:
    from .ihcl import IHCLScraper  # local import: curl_cffi only needed if used

    settings = cfg.get("pricing", {})
    entries: List[HotelEntry] = []
    for h in cfg.get("hotels", []):
        if h.get("engine") != "ihcl":
            raise ValueError(f"hotels.json: unknown engine {h.get('engine')!r} for {h.get('key')}")

        def factory(h=h):
            s = IHCLScraper(h)
            s.pricing_settings = settings
            return s

        entries.append(HotelEntry(key=h["key"], name=h["name"], brand=h.get("brand", ""),
                                  source="config", factory=factory))
    return entries


def available_hotels() -> List[HotelEntry]:
    """Config hotels first, then folder hotels. Keys must be unique."""
    cfg = load_config()
    entries = _config_entries(cfg) + _folder_entries()
    seen: Dict[str, str] = {}
    for e in entries:
        if e.key in seen:
            raise ValueError(f"duplicate hotel key {e.key!r} ({seen[e.key]} and {e.source})")
        seen[e.key] = e.source
    for e in entries:
        if e.source == "folder":
            # folder hotels get the shared GST settings too
            orig = e.factory
            e.factory = (lambda orig=orig: _with_settings(orig(), cfg.get("pricing", {})))
    return entries


def _with_settings(scraper: BaseHotelScraper, settings: Dict[str, Any]) -> BaseHotelScraper:
    scraper.pricing_settings = settings
    return scraper
