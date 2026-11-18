#!/usr/bin/env python3
"""
Access safety shared by every hotel: polite pacing + block detection.

Rules every hotel scraper follows:
  1. Call `pacer.wait()` before EVERY request to the hotel's site/API.
  2. Run every response through `detect_block()`. If it returns a reason,
     raise `HotelBlockedError` -- never turn a block into "0 rows".
  3. Never retry a blocked request in a loop. (A cookie/session-based hotel may
     rebuild its session ONCE, then must give up.)

`HotelBlockedError.block_group` lets hotels that sit behind the same bot
protection (e.g. every IHCL property shares one Akamai) be skipped together
once one of them is blocked.
"""
from __future__ import annotations

import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from . import config as _config  # noqa: F401  (loads the root .env first)
from .rate_limiter import SlidingWindowRateLimiter

# ---- Settings (root .env) ------------------------------------------------ #
DELAY_MIN_S = float(os.getenv("SCRAPE_DELAY_MIN_S", "3"))
DELAY_MAX_S = float(os.getenv("SCRAPE_DELAY_MAX_S", "6"))
# Hard ceiling on top of the random delay: at most N requests per minute.
MAX_REQ_PER_MIN = int(os.getenv("SCRAPE_MAX_REQ_PER_MIN", "12"))
REQUEST_TIMEOUT_S = int(os.getenv("SCRAPE_REQUEST_TIMEOUT_S", "30"))

# HTTP statuses that mean "you are not welcome", not "bad input".
BLOCK_STATUSES = {401: "unauthorised (session/cookie rejected)",
                  403: "forbidden (bot protection)",
                  429: "rate limited",
                  503: "service unavailable / challenge"}

# Body fingerprints of known bot-protection pages.
_CHALLENGE_PATTERNS = [
    (r"access denied.*you don't have permission", "Akamai 'Access Denied' page"),
    (r"pardon our interruption", "Imperva challenge page"),
    (r"incapsula|_incap_", "Imperva/Incapsula challenge page"),
    (r"principal not found", "SynXis session/cookie rejected"),
    (r"captcha", "captcha page"),
]


class ScrapeInterrupted(Exception):
    """A scrape stopped part-way. Scrapers attach the rows collected so far to
    `.records` before re-raising, so partial results are never lost."""

    def __init__(self, *args):
        super().__init__(*args)
        self.records: List[Dict[str, Any]] = []


class RunCancelled(ScrapeInterrupted):
    """The user pressed Cancel (raised from the progress callback)."""


class HotelBlockedError(ScrapeInterrupted, RuntimeError):
    """A hotel's site refused us. Stop sending requests to it this run."""

    def __init__(self, hotel: str, reason: str, block_group: Optional[str] = None):
        super().__init__(f"{hotel}: {reason}")
        self.hotel = hotel
        self.reason = reason
        self.block_group = block_group
        # Rows scraped before the block; filled in by the scraper / base class.
        self.records: List[Dict[str, Any]] = []


def detect_block(status: int, content_type: str, body: str,
                 expect_json: bool = True) -> Optional[str]:
    """
    Classify a response. Returns a human-readable block reason, or None if the
    response looks like a genuine API answer (including a genuine "sold out").
    """
    snippet = (body or "")[:2000].lower()
    for pattern, label in _CHALLENGE_PATTERNS:
        if re.search(pattern, snippet, flags=re.DOTALL):
            return f"HTTP {status}: {label}"
    if status in BLOCK_STATUSES:
        return f"HTTP {status}: {BLOCK_STATUSES[status]}"
    if expect_json and status == 200 and "json" not in (content_type or "").lower():
        if snippet.lstrip().startswith(("<!doctype", "<html")):
            return "HTTP 200 but HTML instead of JSON (likely a challenge page)"
    return None


class Pacer:
    """Random human-ish delay before each request + a per-minute ceiling.

    Use `Pacer.for_group(name)` so hotels behind the same bot protection share
    one clock (back-to-back hotels must not burst the same Akamai/Imperva).
    """

    _registry: Dict[str, "Pacer"] = {}

    @classmethod
    def for_group(cls, group: str) -> "Pacer":
        if group not in cls._registry:
            cls._registry[group] = cls()
        return cls._registry[group]

    def __init__(self, min_s: float = DELAY_MIN_S, max_s: float = DELAY_MAX_S,
                 max_per_min: int = MAX_REQ_PER_MIN):
        self.min_s, self.max_s = min_s, max(max_s, min_s)
        self._limiter = SlidingWindowRateLimiter(window_ms=60000, max_requests=max_per_min)
        self._last: Optional[float] = None

    def wait(self) -> None:
        if self._last is not None:
            gap = random.uniform(self.min_s, self.max_s)
            remaining = gap - (time.time() - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._limiter.acquire()
        self._last = time.time()
