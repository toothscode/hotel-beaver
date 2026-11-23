#!/usr/bin/env python3
"""
Pre-flight access check -- run BEFORE adding a new hotel and before big runs.

For every hotel under hotels/ it reports:
  * which cookies the API declares as REQUIRED (`auth_cookies`)
  * for cookie-based hotels: whether cookie generation succeeds and how long
    the cookies stay valid
  * for cookie-free hotels: confirms the session really holds no cookies
  * one paced probe request (check-in in 5 days, 1 night) -> OK / BLOCKED

Exit code 1 if any hotel is BLOCKED or FAILED -> do not start a full run.

Usage:
    python tools/check_access.py
    python tools/check_access.py --only leela_ambience_delhi
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.registry import available_hotels  # noqa: E402
from core import HotelBlockedError, RoomOccupancy, SearchRequest  # noqa: E402


def cookie_report(scraper) -> str:
    """Inspect the live session the probe just used (before it is closed)."""
    client = getattr(scraper, "client", None)
    ctx = getattr(client, "_ctx", None)
    if ctx is not None:  # Playwright browser session (e.g. Leela)
        jar = {c["name"]: c for c in ctx.cookies()}
        parts = []
        for name in scraper.auth_cookies:
            c = jar.get(name)
            if not c:
                parts.append(f"{name}=MISSING")
                continue
            exp = c.get("expires", -1)
            ttl = f"{(exp - time.time()) / 86400:.0f}d" if exp and exp > 0 else "session"
            parts.append(f"{name}=ok({ttl})")
        return ", ".join(parts)
    session = getattr(client, "session", None)
    if session is not None:  # curl_cffi session (IHCL)
        held = sorted(dict(session.cookies))
        return f"holds cookies: {held}" if held else "none held (cookie-free)"
    return "n/a"


def probe(entry) -> tuple[str, str, str, str]:
    scraper = entry.build()
    declared = ", ".join(scraper.auth_cookies) or "none"
    d = date.today() + timedelta(days=5)
    req = SearchRequest(d.isoformat(), 1, 1, [RoomOccupancy(adults=2)])

    # Keep the browser open long enough to read its cookies.
    client = getattr(scraper, "client", None)
    real_close = getattr(client, "close", None)
    if real_close:
        client.close = lambda: None
    t0 = time.time()
    try:
        rows = scraper.scrape(req)
        status = f"OK   {len(rows)} rows in {time.time() - t0:.0f}s"
        cookies = cookie_report(scraper)
    except HotelBlockedError as e:
        status, cookies = f"BLOCKED  {e.reason}", cookie_report(scraper)
    except Exception as e:  # noqa: BLE001
        status, cookies = f"FAILED   {e}", "-"
    finally:
        if real_close:
            client.close = real_close
            real_close()
    return scraper.name, declared, status, cookies


def main_cli() -> int:
    ap = argparse.ArgumentParser(description="Pre-flight access check for all hotels")
    ap.add_argument("--only", default=None, help="hotel key(s), comma-separated")
    args = ap.parse_args()

    wanted = set(args.only.split(",")) if args.only else None
    results = [probe(e) for e in available_hotels() if not wanted or e.key in wanted]
    print("\n" + "=" * 100)
    print(f"{'Hotel':42} {'Required cookies':24} Result / cookie state")
    print("-" * 100)
    bad = 0
    for name, declared, status, cookies in results:
        bad += status.startswith(("BLOCKED", "FAILED"))
        print(f"{name[:41]:42} {declared:24} {status}")
        print(f"{'':42} {'':24} cookies: {cookies}")
    print("=" * 100)
    print("ALL CLEAR -- safe to run." if not bad else f"{bad} hotel(s) NOT OK -- do not start a full run.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_cli())
