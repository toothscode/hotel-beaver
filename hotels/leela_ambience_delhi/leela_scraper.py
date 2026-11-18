#!/usr/bin/env python3
"""
The Leela Ambience Convention Hotel, Delhi — hotel scraper.

Leela runs on the SynXis (Sabre Hospitality) booking engine, so this talks to
a different API than Taj. It posts to SynXis `getProductAvailability` and maps
the normalized response (ContentLists + ProductAvailabilityDetail.Prices) onto
the shared CSV columns. Unlike Taj, Leela's API accepts child AGES, so this
hotel uses the rich occupancy from `search_request.json`.

Shared pieces (interface, AI extractor, CSV model) come from the root `core`
package; settings come from the root `.env`.
"""
import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

project_root = current_dir.parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from core import (  # noqa: E402
    BaseHotelScraper,
    HotelBlockedError,
    ScrapeInterrupted,
    Pacer,
    SearchRequest,
    build_ai_extractor,
    classify_meal_plan,
    detect_block,
    free_cancellation,
    load_search_request,
)

# Cookies the SynXis API requires (Imperva token + SynXis session). Verified
# 2026-11-18: without them the API answers 401 "Principal not found".
REQUIRED_COOKIES = ("reese84", "sbeSessionID")

OUTPUT_DIR = project_root / "output"

# ---- Hotel-specific config & constants --------------------------------- #
_env_path = project_root / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

try:
    from hotels.leela_ambience_delhi.constants import (
        AVAIL_URL,
        BASE_URL,
        DEFAULT_CHAIN_ID,
        DEFAULT_CURRENCY,
        DEFAULT_HEADLESS,
        DEFAULT_HOTEL_ID,
        DEFAULT_USER_AGENT,
        HOTEL_LABEL,
        HOTEL_NAME,
        HOTEL_URL,
    )
except ImportError:
    from constants import (
        AVAIL_URL,
        BASE_URL,
        DEFAULT_CHAIN_ID,
        DEFAULT_CURRENCY,
        DEFAULT_HEADLESS,
        DEFAULT_HOTEL_ID,
        DEFAULT_USER_AGENT,
        HOTEL_LABEL,
        HOTEL_NAME,
        HOTEL_URL,
    )


def _strip_html(text: str) -> str:
    """Turn the SynXis HTML snippets (<li/>, <br/>) into clean plain text."""
    if not text:
        return ""
    text = re.sub(r"<li\s*/?>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text).strip()


# ========================================================================= #
# Low-level SynXis booking-engine client
# ========================================================================= #
class LeelaClient:
    """
    Client for Leela's SynXis booking engine.

    Leela sits behind Imperva bot protection, which only clears a client that
    solves a JavaScript challenge (the `reese84` token) — impossible for a plain
    HTTP client. So we drive a real headless Chromium via Playwright to clear the
    challenge once, then run every availability POST through that browser's own
    request context (so cookies + fingerprint stay consistent). One browser per
    run, reused across all date windows; call close() when done.
    """

    BASE_URL = BASE_URL
    AVAIL_URL = AVAIL_URL
    DEFAULT_USER_AGENT = DEFAULT_USER_AGENT

    def __init__(
        self,
        chain_id: str = DEFAULT_CHAIN_ID,
        hotel_id: str = DEFAULT_HOTEL_ID,
        currency: str = DEFAULT_CURRENCY,
        headless: bool = DEFAULT_HEADLESS,
    ):
        self.chain_id = chain_id
        self.hotel_id = hotel_id
        self.currency = currency
        self.headless = headless
        self._blocked = False  # set once the browser itself is unavailable
        self._session_rebuilt = False  # max ONE cookie/session rebuild per run
        self.pacer = Pacer.for_group(HOTEL_NAME)
        self._activityid = ""
        self._pw = None
        self._browser = None
        self._ctx = None

    @staticmethod
    def _looks_like_challenge(text: str, content_type: str) -> bool:
        """True if the body is an Imperva/Incapsula challenge page, not JSON."""
        if "application/json" in (content_type or "").lower():
            return False
        body = (text[:800] or "").lower()
        return (
            "pardon our interruption" in body
            or "incapsula" in body
            or "_incapsula" in body
            or body.lstrip().startswith("<!doctype")
            or "<html" in body
        )

    def _landing_url(self) -> str:
        return (
            f"{self.BASE_URL}/?chain={self.chain_id}&hotel={self.hotel_id}"
            f"&level=hotel&locale=en-US&currency={self.currency}"
        )

    def _headers(self) -> Dict[str, str]:
        headers = {
            "accept": "*/*",
            "content-type": "application/json; charset=UTF-8",
            "context": "BE",
            "x-business-context": "BE",
            "origin": self.BASE_URL,
            "referer": self._landing_url(),
            "user-agent": self.DEFAULT_USER_AGENT,
        }
        if self._activityid:
            headers["activityid"] = self._activityid
        return headers

    def _ensure_browser(self) -> bool:
        """Launch the browser and clear the Imperva challenge once. Idempotent."""
        if self._ctx is not None:
            return True
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[Leela] Playwright is not installed. Install it with:\n"
                  "  pip install playwright\n  playwright install chromium")
            self._blocked = True
            return False
        try:
            print(f"[Leela] Launching {'headless ' if self.headless else ''}browser "
                  f"to clear the Imperva challenge...")
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._ctx = self._browser.new_context(
                locale="en-US",
                viewport={"width": 1366, "height": 900},
                user_agent=self.DEFAULT_USER_AGENT,
            )
            self._ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = self._ctx.new_page()
            page.goto(self._landing_url(), wait_until="domcontentloaded", timeout=60000)
            # Wait for the challenge to resolve (reese84 cookie appears).
            deadline = time.time() + 25
            cookies: Dict[str, str] = {}
            while time.time() < deadline:
                cookies = {c["name"]: c["value"] for c in self._ctx.cookies()}
                if "reese84" in cookies and cookies.get("sbeSessionID"):
                    break
                page.wait_for_timeout(500)
            self._activityid = cookies.get("sbeSessionID", "")
            page.close()
            missing = [name for name in REQUIRED_COOKIES if not cookies.get(name)]
            if missing:
                # Cookie generation FAILED. Don't fire API calls without a session
                # (that yields 401 "Principal not found" and looks bot-like).
                self.close()
                if not self._session_rebuilt:
                    print(f"[Leela] Cookie generation incomplete (missing {', '.join(missing)}) "
                          f"-- retrying ONCE with a fresh browser...")
                    self._session_rebuilt = True
                    return self._ensure_browser()
                raise HotelBlockedError(
                    HOTEL_NAME,
                    f"cookie generation failed: missing {', '.join(missing)} after 25s "
                    f"(try LEELA_HEADLESS=0 in .env)",
                )
            print(f"[Leela] Session ready (cookies: {', '.join(REQUIRED_COOKIES)}).")
            return True
        except HotelBlockedError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[Leela] Could not start browser session: {e}\n"
                  f"  If the browser binary is missing, run: playwright install chromium")
            self._blocked = True
            self.close()
            return False

    def close(self) -> None:
        """Shut down the browser (call once per run, after all windows)."""
        for closer in (
            lambda: self._ctx and self._ctx.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._browser = self._pw = None

    def get_product_availability(
        self,
        start_date: str,
        end_date: str,
        adults: int,
        child_ages: List[int],
        num_rooms: int,
    ) -> Dict[str, Any]:
        """POST the SynXis availability query (via the browser) and return JSON."""
        if self._blocked:
            raise RuntimeError("Leela browser session unavailable (see error above)")
        if not self._ensure_browser():
            raise RuntimeError("Leela browser could not start (see error above)")
        payload = {
            "Paging": {"Size": 200},
            "ProductAvailabilityQuery": {
                "OnlyCheckRequested": False,
                "AdditionalSortType": "RequestedPrivateThenRequestedPublicThenPublicRates",
                "ReturnFullContentDetails": True,
                "Chain": {"Id": self.chain_id},
                "Hotel": {"Id": self.hotel_id},
                "AccessCode": {},
                "Currency": {"currencyCode": self.currency},
                "ChannelList": {
                    "PrimaryChannel": {"Code": "WEB"},
                    "SecondaryChannel": {"Code": "GC"},
                },
                "LoyaltyList": [
                    {"programID": "GHA", "Level": {"code": lvl}}
                    for lvl in ("GOLD", "RED", "SILVER", "PLATINUM", "TITANIUM")
                ],
                "NumRooms": num_rooms,
                "ProductSortingType": "RoomsThenRates",
                "RoomStay": {
                    "EndDate": end_date,
                    "StartDate": start_date,
                    "GuestCount": [
                        {"AgeQualifyingCode": "Adult", "NumGuests": adults},
                        {
                            "AgeQualifyingCode": "Child",
                            "NumGuests": len(child_ages),
                            "Ages": child_ages,
                        },
                    ],
                    "RateFilterList": [],
                },
                "Template": {"Code": "RoomTri", "Level": "hotel"},
            },
            "UserDetails": {
                "Preferences": {
                    "Language": {"code": "en-US"},
                    "ResponseOptions": "IncludeMealPlan",
                }
            },
            "Version": 1,
        }

        self.pacer.wait()
        try:
            resp = self._ctx.request.post(
                self.AVAIL_URL,
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=40000,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Leela request failed: {e}") from e

        text = resp.text()
        content_type = resp.headers.get("content-type", "")
        reason = detect_block(resp.status, content_type, text)
        if not reason and self._looks_like_challenge(text, content_type):
            reason = f"HTTP {resp.status}: Imperva challenge page"
        if reason:
            if self._session_rebuilt:
                # Already rebuilt the session once this run: stop, don't hammer.
                raise HotelBlockedError(HOTEL_NAME, f"{reason} (after 1 session rebuild)")
            print(f"[Leela] {reason} -- rebuilding the browser session ONCE and retrying...")
            self._session_rebuilt = True
            self.close()
            return self.get_product_availability(start_date, end_date, adults,
                                                 child_ages, num_rooms)
        if resp.status != 200:
            raise RuntimeError(f"Leela availability failed: HTTP {resp.status}")
        try:
            return json.loads(text)
        except ValueError as e:
            raise HotelBlockedError(HOTEL_NAME, f"non-JSON response: {e}") from e

    def extract_structured_rooms(
        self,
        avail_data: Dict[str, Any],
        check_in: str,
        check_out: str,
        adults: int,
        children: int,
        rooms: int,
    ) -> List[Dict[str, Any]]:
        """Map the SynXis response onto the shared CSV record shape."""
        content = avail_data.get("ContentLists", {}) or {}
        detail = avail_data.get("ProductAvailabilityDetail", {}) or {}

        rooms_by_code = {r.get("Code"): r for r in content.get("RoomList", [])}
        cats_by_code = {c.get("CategoryCode"): c for c in content.get("RoomCategoryList", [])}
        rates_by_code = {r.get("Code"): r for r in content.get("RateList", [])}
        policies = content.get("PolicyList", {}) or {}
        cancel_by_code = {c.get("Code"): c for c in policies.get("CancelPolicy", [])}

        occupancy_desc = f"{adults} Adult{'s' if adults != 1 else ''}"
        if children > 0:
            occupancy_desc += f", {children} Child{'ren' if children != 1 else ''}"
        occupancy_desc += f", {rooms} Room{'s' if rooms != 1 else ''}"

        records: List[Dict[str, Any]] = []
        for price in detail.get("Prices", []):
            product = price.get("Product", {}) or {}
            room_code = (product.get("Room") or {}).get("Code")
            rate_code = (product.get("Rate") or {}).get("Code")

            room = rooms_by_code.get(room_code, {})
            room_details = room.get("Details", {}) or {}
            room_name = (
                room.get("Name")
                or cats_by_code.get(room_code, {}).get("Name")
                or f"Room ({room_code})"
            )

            rate = rates_by_code.get(rate_code, {})
            rate_name = rate.get("Name") or rate_code
            rate_details = rate.get("Details", {}) or {}
            rate_desc = _strip_html(rate_details.get("Description", ""))

            cancel_code = (product.get("CancelPolicy") or {}).get("Code")
            cancel_obj = cancel_by_code.get(cancel_code, {}) or {}
            cancel_desc = _strip_html(cancel_obj.get("Description", ""))

            # SynXis: "ChargeWithinDays*" = free until N days before check-in;
            # "AlwaysChargeCancelFee" = non-refundable. Policies are worded
            # relative to the 14:00 check-in, hence default_time.
            charge_type = cancel_obj.get("ChargeType") or ""
            refundable = (
                True if charge_type.startswith("ChargeWithinDays")
                else False if charge_type == "AlwaysChargeCancelFee"
                else None
            )
            cancel_cols = free_cancellation(
                check_in, refundable, cancel_obj.get("CancelTimeIn"),
                cancel_obj.get("CancelTime"), default_time="1400",
            )
            # No structured meal flag in SynXis: classify from code + all text.
            meal_plan = classify_meal_plan(
                rate_code or "",
                rate_name or "",
                rate_desc + "\n" + _strip_html(rate_details.get("DetailedDescription", "")),
                None,
            )
            # SynXis has no BAR category here; "Rack" class is the public rate.
            is_bar = "Yes" if rate_details.get("RateClass") == "Rack" else "No"

            images = [img.get("Path") for img in room_details.get("ImageList", []) if img.get("Path")]
            images_str = "; ".join(images)

            total = ((product.get("Prices", {}) or {}).get("Total", {}) or {}).get("Price", {}) or {}
            total_block = total.get("Total", {}) or {}
            rate_total = total_block.get("Amount")
            total_with_tax = total_block.get("AmountWithTaxesFees")
            tax_amount = (total.get("Tax", {}) or {}).get("Amount")
            currency = total.get("CurrencyCode") or self.currency

            records.append({
                "Room Name": room_name,
                "Check In Date": check_in,
                "Check Out Date": check_out,
                "Occupancy": occupancy_desc,
                "Adults": adults,
                "Children": children,
                "Rooms": rooms,
                "Rate": rate_total,
                "Currency": currency,
                "Cancellation policy in popup modal": cancel_desc,
                "Rate description in popup modal": rate_desc,
                "Images url": images_str,
                "rate type": rate_name,
                "Meal Plan": meal_plan,
                "Is BAR": is_bar,
                **cancel_cols,
                "Rate Code": rate_code,
                "Room Code": room_code,
                "Tax Amount": tax_amount,
                "Total With Tax": total_with_tax,
                "Available Inventory": price.get("AvailableInventory"),
            })

        return records


# ========================================================================= #
# Scraper (implements the shared interface)
# ========================================================================= #
class LeelaScraper(BaseHotelScraper):
    """Scraper for The Leela Ambience Convention Hotel, Delhi (SynXis)."""

    name = HOTEL_NAME
    label = HOTEL_LABEL
    brand = "Leela"
    auth_cookies = REQUIRED_COOKIES

    def __init__(self, use_claude: bool = False):
        self.use_claude = use_claude
        self.client = LeelaClient()

    def health_check(self) -> "tuple[bool, str]":
        """Probe: a single near-date availability call (warms the session)."""
        from datetime import datetime, timedelta
        d1 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        d2 = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        try:
            avail = self.client.get_product_availability(d1, d2, 2, [], 1)
            if not avail:
                return False, "bot-protection / browser unavailable (see Leela notes above)"
            n = len(avail.get("ProductAvailabilityDetail", {}).get("Prices", []))
            return True, f"availability OK ({n} products)"
        except Exception as e:  # noqa: BLE001
            return False, f"error: {e}"
        finally:
            self.client.close()

    def scrape(self, request: SearchRequest) -> List[Dict[str, Any]]:
        occ = request.aggregate_occupancy()
        # Leela accepts child ages — collect them across all rooms.
        child_ages: List[int] = [age for room in request.rooms for age in room.children]
        windows = request.windows()

        print("==================================================")
        print(f"Leela Room Scraper — {self.name}")
        print(
            f"{len(windows)} window(s) from {request.start_date}, "
            f"{request.night_duration} night(s) each | occupancy -> "
            f"{occ['adults']} adult(s), {occ['children']} child(ren) "
            f"(ages {child_ages or '-'}), {occ['rooms']} room(s)"
        )
        print("==================================================")

        all_records: List[Dict[str, Any]] = []
        try:
            for c_in, c_out in windows:
                print(f"\n[Scraping] {c_in} to {c_out} ...")
                avail = self.client.get_product_availability(
                    start_date=c_in,
                    end_date=c_out,
                    adults=occ["adults"],
                    child_ages=child_ages,
                    num_rooms=occ["rooms"],
                )
                extracted = self.client.extract_structured_rooms(
                    avail_data=avail,
                    check_in=c_in,
                    check_out=c_out,
                    adults=occ["adults"],
                    children=occ["children"],
                    rooms=occ["rooms"],
                )
                print(f"  -> {len(extracted)} room/rate option(s)")
                all_records.extend(extracted)
                self.report_progress(windows.index((c_in, c_out)) + 1, len(windows),
                                     f"{c_in}: {len(extracted)} rates")
        except ScrapeInterrupted as e:   # blocked or cancelled
            e.records = all_records      # keep rows scraped so far
            raise
        finally:
            self.client.close()  # always shut the browser down

        return all_records

    def postprocess(
        self, records: List[Dict[str, Any]], request: SearchRequest
    ) -> List[Dict[str, Any]]:
        """Optional AI enrichment pass (enabled via --use-claude)."""
        if not self.use_claude:
            return records
        extractor = build_ai_extractor()
        if extractor.is_available():
            print(f"\n[AI] Enhancing {len(records)} records with "
                  f"{type(extractor).__name__}...")
            return extractor.enhance_records(records)
        print("\n[AI] No AI provider configured. Using parsed records.")
        return records


def main():
    parser = argparse.ArgumentParser(
        description="The Leela Ambience Convention Hotel Delhi — Room & Rate Scraper"
    )
    parser.add_argument("--use-claude", action="store_true", help="Enable AI enrichment pass")
    parser.add_argument("--output", default=None, help="Custom output CSV path")
    parser.add_argument("--search-request", default=None,
                        help="Path to search_request.json (sliding-window + occupancy).")
    args = parser.parse_args()

    scraper = LeelaScraper(use_claude=args.use_claude)
    request = load_search_request(args.search_request or (project_root / "config" / "search_request.json"))
    scraper.run(request, output_dir=OUTPUT_DIR, output_file=args.output)


if __name__ == "__main__":
    main()
