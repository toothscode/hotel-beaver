#!/usr/bin/env python3
"""
Hotel scraper interface.

Every hotel lives in its own folder under `hotels/` and provides a subclass of
`BaseHotelScraper`. The base class defines the *contract* and owns the output
side (writing the CSV, stamping the Hotel Name, naming the file). Each hotel
implements `scrape()` — where it does everything specific to its site: loop the
sliding windows, adapt the occupancy to its own API, fetch and extract rows.

Minimal new hotel:

    from core import BaseHotelScraper, SearchRequest

    class AcmeScraper(BaseHotelScraper):
        name = "Acme Grand, Goa"
        label = "Acme Grand"

        def scrape(self, request: SearchRequest):
            rows = []
            for check_in, check_out in request.windows():
                ...  # call your site, build dict rows keyed by core.output headers
            return rows
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .access import HotelBlockedError, ScrapeInterrupted
from .pricing import apply_prices
from .search_request import SearchRequest
from .output import output_path as build_output_path, write_csv


class BaseHotelScraper(ABC):
    """Base class every hotel scraper extends."""

    #: Customer-facing hotel name — written into the CSV "Hotel Name" column.
    name: str = ""
    #: Short label used in the output filename: "<label> - <run date>.csv".
    label: str = ""
    #: Hotels sharing one bot-protection front (e.g. all IHCL hotels share one
    #: Akamai). Once one is blocked, the orchestrator skips the rest of the
    #: group this run. Default: the hotel is its own group.
    block_group: str = ""
    #: Cookies the site's API REQUIRES (e.g. Imperva "reese84"). Empty tuple =
    #: verified cookie-free. Reported by tools/check_access.py -- any new hotel
    #: that needs cookies must declare them here and pass that check first.
    auth_cookies: tuple = ()
    #: GST slab settings for the price columns (see core/pricing.py).
    pricing_settings: Optional[Dict[str, float]] = None
    #: Optional callback(done, total, note) set by the dashboard job runner.
    progress_cb: Optional[Callable[[int, int, str], None]] = None

    def report_progress(self, done: int, total: int, note: str = "") -> None:
        """Scrapers call this after each check-in date (no-op without a callback)."""
        if self.progress_cb:
            self.progress_cb(done, total, note)

    # ------------------------------------------------------------------ #
    # Hotel-specific: implemented by each subclass
    # ------------------------------------------------------------------ #
    @abstractmethod
    def scrape(self, request: SearchRequest) -> List[Dict[str, Any]]:
        """
        Fetch and extract ALL rows for the whole request.

        The hotel owns the loop: iterate `request.windows()`, adapt the
        occupancy (`request.aggregate_occupancy()` or `request.rooms`) to its
        own site, and return a flat list of record dicts keyed by the CSV
        header names defined in `core.output.OutputRecord`.
        """
        raise NotImplementedError

    def postprocess(
        self, records: List[Dict[str, Any]], request: SearchRequest
    ) -> List[Dict[str, Any]]:
        """
        Optional hook applied to all records after `scrape()` and before
        writing (e.g. an AI enrichment pass). Default: no-op.
        """
        return records

    # ------------------------------------------------------------------ #
    # Shared: owned by the base class
    # ------------------------------------------------------------------ #
    def collect(self, request: SearchRequest) -> List[Dict[str, Any]]:
        """
        Produce this hotel's rows for `request`, fully stamped and ready to
        write — but WITHOUT writing a file. The orchestrator (main.py) calls
        this for every hotel and writes one combined CSV; `run()` uses it for a
        standalone single-hotel file.
        """
        if not self.name:
            raise ValueError(f"{type(self).__name__} must set class attribute `name`")

        try:
            records = self.scrape(request)
        except ScrapeInterrupted as e:
            # Blocked or cancelled: keep (and stamp + price) the rows scraped
            # so far, then re-raise so the orchestrator reports it.
            if isinstance(e, HotelBlockedError):
                e.block_group = e.block_group or self.group
            self._stamp(e.records)
            apply_prices(e.records, self.pricing_settings)
            raise
        records = self.postprocess(records, request)
        self._stamp(records)
        apply_prices(records, self.pricing_settings)
        return records

    @property
    def group(self) -> str:
        return self.block_group or self.name

    def _stamp(self, records: List[Dict[str, Any]]) -> None:
        scrapped_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in records:
            row.setdefault("Hotel Name", self.name)
            row.setdefault("Scrapped On", scrapped_on)

    def run(
        self,
        request: SearchRequest,
        output_dir: str | Path,
        output_file: Optional[str | Path] = None,
    ) -> Path:
        """Run a single hotel standalone and write its CSV. Returns the path."""
        records = self.collect(request)

        out_file = Path(output_file).resolve() if output_file \
            else build_output_path("output", output_dir)

        print(f"\n==================================================")
        print(f"{self.name} — scraping complete")
        print(f"Total rows: {len(records)}")
        out_file = write_csv(records, out_file)
        print(f"Saved: {out_file}")
        print(f"==================================================")
        return out_file
