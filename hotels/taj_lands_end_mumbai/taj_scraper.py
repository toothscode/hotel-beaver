#!/usr/bin/env python3
"""
Taj Lands End, Mumbai — hotel scraper.

Self-contained for this hotel: the low-level Taj API/CMS client (`TajClient`)
and the `BaseHotelScraper` implementation (`TajScraper`) live here together.
Shared pieces (the scraper interface, AI extractor, rate limiter, CSV model)
come from the root `core` package; secrets/settings come from the root `.env`.
"""
import argparse
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests
from dotenv import load_dotenv

# Ensure package directory is on sys.path for direct execution
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Project root (two levels up) holds the shared `core` package and the .env.
project_root = current_dir.parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from core import (  # noqa: E402
    BaseHotelScraper,
    RoomOccupancy,
    SearchRequest,
    build_ai_extractor,
    load_search_request,
)

OUTPUT_DIR = project_root / "output"

# ---- Hotel-specific config & constants --------------------------------- #
_env_path = project_root / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

try:
    from hotels.taj_lands_end_mumbai.constants import (
        DEFAULT_CURRENCY,
        DEFAULT_HOTEL_ID,
        DEFAULT_HOTEL_URL,
        DEFAULT_TENANT,
        DEFAULT_USER_AGENT,
        HOTEL_LABEL,
        HOTEL_NAME,
        HUDINI_BASE_URL,
        ORIGIN,
        REFERER,
        SANITY_API_VERSION,
        SANITY_DATASET,
        SANITY_PROJECT_ID,
    )
except ImportError:
    from constants import (
        DEFAULT_CURRENCY,
        DEFAULT_HOTEL_ID,
        DEFAULT_HOTEL_URL,
        DEFAULT_TENANT,
        DEFAULT_USER_AGENT,
        HOTEL_LABEL,
        HOTEL_NAME,
        HUDINI_BASE_URL,
        ORIGIN,
        REFERER,
        SANITY_API_VERSION,
        SANITY_DATASET,
        SANITY_PROJECT_ID,
    )


# ========================================================================= #
# Low-level API / CMS client
# ========================================================================= #
class TajClient:
    """
    Client for interacting with Taj Hotels APIs and Sanity CMS.
    Bypasses Akamai Bot Manager via Chrome TLS impersonation (curl_cffi).
    """

    SANITY_PROJECT_ID = SANITY_PROJECT_ID
    SANITY_DATASET = SANITY_DATASET
    SANITY_API_VERSION = SANITY_API_VERSION

    HUDINI_BASE_URL = HUDINI_BASE_URL

    def __init__(self, hotel_id: str = DEFAULT_HOTEL_ID):
        self.hotel_id = hotel_id
        self.session = requests.Session(impersonate="chrome124")
        self.headers = {
            "tenant": DEFAULT_TENANT,
            "Content-Type": "application/json",
            "Origin": ORIGIN,
            "Referer": REFERER,
            "User-Agent": DEFAULT_USER_AGENT,
        }
        self._catalog_cache: Optional[Dict[str, Any]] = None

    def _sanity_ref_to_url(self, ref: str) -> Optional[str]:
        """Convert Sanity image ref (image-<hash>-<dim>-<ext>) to HTTPS CDN URL."""
        if not ref or not ref.startswith("image-"):
            return None
        stripped = ref[len("image-"):]
        if "-" in stripped:
            base, ext = stripped.rsplit("-", 1)
            return f"https://cdn.sanity.io/images/{self.SANITY_PROJECT_ID}/{self.SANITY_DATASET}/{base}.{ext}"
        return None

    def get_hotel_catalog(self) -> Dict[str, Any]:
        """Fetch hotel details, room categories, names, and images from Sanity CMS."""
        if self._catalog_cache:
            return self._catalog_cache

        groq_query = f"""*[_type == "hotel" && hotelId == "{self.hotel_id}"][0]{{
          hotelName,
          hotelId,
          identifier,
          "rooms": hotelRooms->roomsList[]{{
            roomCode,
            "roomName": basicInfo.title,
            "images": basicInfo.media[].imageAsset.image[].asset._ref,
            "largeImages": basicInfo.media[].imageAsset.largeImage[].asset._ref,
            "description": basicInfo.description
          }}
        }}"""

        encoded_query = urllib.parse.quote(groq_query)
        url = (
            f"https://{self.SANITY_PROJECT_ID}.api.sanity.io/{self.SANITY_API_VERSION}/data/query/"
            f"{self.SANITY_DATASET}?query={encoded_query}"
        )

        resp = self.session.get(url)
        if resp.status_code != 200:
            print(f"[Warning] Failed to fetch Sanity catalog (HTTP {resp.status_code})")
            return {"hotelName": "Taj Lands End, Mumbai", "rooms": {}}

        data = resp.json().get("result", {})
        rooms_dict = {}
        for r in data.get("rooms", []):
            code = r.get("roomCode")
            if not code:
                continue

            # Convert images to CDN URLs
            raw_refs = (r.get("images") or []) + (r.get("largeImages") or [])
            urls = []
            seen = set()
            for ref in raw_refs:
                cdn_url = self._sanity_ref_to_url(ref)
                if cdn_url and cdn_url not in seen:
                    seen.add(cdn_url)
                    urls.append(cdn_url)

            rooms_dict[code] = {
                "roomCode": code,
                "roomName": r.get("roomName") or code,
                "description": r.get("description"),
                "imageUrls": urls,
            }

        self._catalog_cache = {
            "hotelName": data.get("hotelName", "Taj Lands End, Mumbai"),
            "identifier": data.get("identifier", "taj-lands-end-mumbai"),
            "rooms": rooms_dict,
        }
        return self._catalog_cache

    def get_calendar_lead(self, start_date: str, end_date: str, length_of_stay: int = 1) -> List[Dict[str, Any]]:
        """Fetch calendar lead availability across a date range."""
        url = f"{self.HUDINI_BASE_URL}/calendar-view"
        payload = {
            "hotelId": self.hotel_id,
            "startDate": start_date,
            "endDate": end_date,
            "lengthOfStay": length_of_stay,
            "rateFilter": "RRG,PKG,MD",
        }
        resp = self.session.post(url, headers=self.headers, json=payload)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("getHotelLeadAvailability", {}).get("leadAvailability", [])
        return []

    def get_room_availability(
        self,
        start_date: str,
        end_date: str,
        adults: int = 2,
        children: int = 0,
        rooms: int = 1,
    ) -> Dict[str, Any]:
        """Fetch live room availability, pricing, cancellation policies, and packages."""
        url = f"{self.HUDINI_BASE_URL}/hotel-availability"
        payload = {
            "hotelId": self.hotel_id,
            "startDate": start_date,
            "endDate": end_date,
            "numRooms": rooms,
            "adults": adults,
            "children": children,
            "rateFilter": "RRG,PKG,MD",
            "memberTier": "copper",
            "package": "PKG",
            "isOfferLandingPage": False,
            "rateCode": None,
            "promoCode": None,
            "promoType": None,
            "couponCode": None,
            "agentId": None,
            "agentType": None,
            "isMyAccount": False,
            "isCorporate": False,
            "isLogin": False,
            "isMemberOffer1": False,
            "isMemberOffer2": False,
            "forSomeoneElse": False,
        }

        resp = self.session.post(url, headers=self.headers, json=payload)
        if resp.status_code != 200:
            print(f"[Error] Availability request failed: HTTP {resp.status_code}")
            return {}

        return resp.json()

    def extract_structured_rooms(
        self,
        avail_data: Dict[str, Any],
        check_in: str,
        check_out: str,
        adults: int = 2,
        children: int = 0,
        rooms: int = 1,
    ) -> List[Dict[str, Any]]:
        """Parse the raw availability JSON into flat records (CSV-keyed dicts)."""
        catalog = self.get_hotel_catalog()
        rooms_catalog = catalog.get("rooms", {})

        room_availability = avail_data.get("roomAvailability", {})
        room_rates = room_availability.get("roomRates", [])
        package_rates = room_availability.get("packagesRates", [])
        member_rates = room_availability.get("memberExclusiveRates", [])
        promotion_rates = room_availability.get("promotionRates", [])

        all_groups = room_rates + package_rates + member_rates + promotion_rates
        records = []

        occupancy_desc = f"{adults} Adult{'s' if adults != 1 else ''}"
        if children > 0:
            occupancy_desc += f", {children} Child{'ren' if children != 1 else ''}"
        occupancy_desc += f", {rooms} Room{'s' if rooms != 1 else ''}"

        for group in all_groups:
            room_code = group.get("roomCode")
            room_info = rooms_catalog.get(room_code, {})

            room_name = (
                room_info.get("roomName")
                or group.get("roomCategory")
                or f"Room ({room_code})"
            )

            image_urls = room_info.get("imageUrls", [])
            images_str = "; ".join(image_urls) if image_urls else ""

            for r in group.get("rooms", []):
                rate_content = r.get("rateContent", {})
                rate_name = rate_content.get("name") or r.get("rateCode")
                currency = rate_content.get("currencyCode") or "INR"

                details = rate_content.get("details", {})
                rate_desc = (
                    details.get("detailedDescription")
                    or details.get("description")
                    or ""
                ).strip()

                cancellation_policy = (
                    r.get("cancellationPolicy", {}).get("description")
                    or ""
                ).strip()

                # Pricing
                std_rate = r.get("standardRate") or {}
                mem_rate = r.get("memberRate") or {}
                chosen_rate = std_rate if std_rate.get("total") else mem_rate

                total_obj = chosen_rate.get("total", {})
                price = total_obj.get("amount")
                total_with_taxes = total_obj.get("amountWithTaxesFees")
                tax_amount = chosen_rate.get("tax", {}).get("amount")
                inventory = chosen_rate.get("availableInventory")

                records.append({
                    "Room Name": room_name,
                    "Check In Date": check_in,
                    "Check Out Date": check_out,
                    "Occupancy": occupancy_desc,
                    "Adults": adults,
                    "Children": children,
                    "Rooms": rooms,
                    "Rate": price,
                    "Currency": currency,
                    "Cancellation policy in popup modal": cancellation_policy,
                    "Rate description in popup modal": rate_desc,
                    "Images url": images_str,
                    "rate type": rate_name,
                    "Rate Code": r.get("rateCode"),
                    "Room Code": room_code,
                    "Tax Amount": tax_amount,
                    "Total With Tax": total_with_taxes,
                    "Available Inventory": inventory,
                })

        return records


def extract_hotel_id(url_or_id: str) -> str:
    """Extract GUID hotelId from a full URL or return the ID directly."""
    if not url_or_id:
        return DEFAULT_HOTEL_ID
    match = re.search(r"hotelId=([a-f0-9\-]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()


# ========================================================================= #
# Scraper (implements the shared interface)
# ========================================================================= #
class TajScraper(BaseHotelScraper):
    """Scraper for the Taj Hotels booking platform."""

    name = HOTEL_NAME
    label = HOTEL_LABEL

    def __init__(self, hotel_id: str = DEFAULT_HOTEL_ID, use_claude: bool = False):
        self.hotel_id = hotel_id
        self.use_claude = use_claude
        self.client = TajClient(hotel_id=hotel_id)

    def scrape(self, request: SearchRequest) -> List[Dict[str, Any]]:
        occ = request.aggregate_occupancy()  # Taj API accepts flat totals only
        windows = request.windows()

        print("==================================================")
        print(f"Taj Hotels Room Scraper — {self.name} (ID: {self.hotel_id})")
        print(
            f"{len(windows)} window(s) from {request.start_date}, "
            f"{request.night_duration} night(s) each | occupancy -> "
            f"{occ['adults']} adult(s), {occ['children']} child(ren), "
            f"{occ['rooms']} room(s)"
        )
        print("==================================================")

        all_records: List[Dict[str, Any]] = []
        for c_in, c_out in windows:
            print(f"\n[Scraping] {c_in} to {c_out} ...")
            avail_data = self.client.get_room_availability(
                start_date=c_in,
                end_date=c_out,
                adults=occ["adults"],
                children=occ["children"],
                rooms=occ["rooms"],
            )
            extracted = self.client.extract_structured_rooms(
                avail_data=avail_data,
                check_in=c_in,
                check_out=c_out,
                adults=occ["adults"],
                children=occ["children"],
                rooms=occ["rooms"],
            )
            print(f"  -> {len(extracted)} room/rate option(s)")
            all_records.extend(extracted)

        if not all_records:
            print("\n[Notice] No room rates for the selected dates.")
            next_in, next_out = self._find_earliest_available_date()
            print(f"Nearest suggested availability: {next_in} to {next_out}")

        return all_records

    def postprocess(
        self, records: List[Dict[str, Any]], request: SearchRequest
    ) -> List[Dict[str, Any]]:
        """Optional AI enrichment pass (enabled via --use-claude).

        The provider (Claude or OpenAI) is chosen by AI_PROVIDER in the root
        .env; this hotel just asks `core` for the configured extractor.
        """
        if not self.use_claude:
            return records
        extractor = build_ai_extractor()
        if extractor.is_available():
            print(f"\n[AI] Enhancing {len(records)} records with "
                  f"{type(extractor).__name__}...")
            return extractor.enhance_records(records)
        print("\n[AI] No AI provider configured. Using parsed records.")
        return records

    def _find_earliest_available_date(self) -> Tuple[str, str]:
        """First available 1-night date from the calendar view."""
        today = datetime.now()
        start_str = today.strftime("%Y-%m-%d")
        end_str = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        for item in self.client.get_calendar_lead(start_str, end_str, length_of_stay=1):
            if item.get("available") is True:
                return item.get("arrivalDate"), item.get("departureDate")
        arr = (today + timedelta(days=4)).strftime("%Y-%m-%d")
        dep = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        return arr, dep


def _request_from_cli(args, scraper: TajScraper) -> SearchRequest:
    """
    Build a SearchRequest from the legacy manual-date flags, so manual mode
    flows through the same `scrape()` path as the shared config.
    """
    rooms = [RoomOccupancy(adults=args.adults, children=[0] * args.children, infants=0)]

    if not args.check_in:
        print("[Info] No check-in date. Querying calendar for earliest availability...")
        c_in, c_out = scraper._find_earliest_available_date()
        print(f"[Info] Selected: {c_in} -> {c_out}")
    else:
        c_in = args.check_in
        c_out = args.check_out or (
            datetime.strptime(c_in, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")

    if args.date_range_end:
        # Consecutive 1-night stays from check-in up to date_range_end.
        span = (
            datetime.strptime(args.date_range_end, "%Y-%m-%d")
            - datetime.strptime(c_in, "%Y-%m-%d")
        ).days
        return SearchRequest(
            start_date=c_in, scrape_for_n_days=max(span, 1), night_duration=1, rooms=rooms
        )

    nights = (
        datetime.strptime(c_out, "%Y-%m-%d") - datetime.strptime(c_in, "%Y-%m-%d")
    ).days
    return SearchRequest(
        start_date=c_in, scrape_for_n_days=1, night_duration=max(nights, 1), rooms=rooms
    )


def main():
    parser = argparse.ArgumentParser(
        description="Taj Lands End Mumbai Hotel Room & Rate Scraper"
    )
    parser.add_argument("--url", default=DEFAULT_HOTEL_URL, help="Landing page URL or hotelId")
    parser.add_argument("--hotel-id", default=DEFAULT_HOTEL_ID, help="Taj Hotel ID")
    parser.add_argument("--check-in", default=None, help="Check-in date (YYYY-MM-DD)")
    parser.add_argument("--check-out", default=None, help="Check-out date (YYYY-MM-DD)")
    parser.add_argument("--date-range-end", default=None,
                        help="Scrape consecutive check-in dates up to this date")
    parser.add_argument("--adults", type=int, default=2, help="Number of adults")
    parser.add_argument("--children", type=int, default=0, help="Number of children")
    parser.add_argument("--rooms", type=int, default=1, help="Number of rooms")
    parser.add_argument("--use-claude", action="store_true", help="Enable AI enrichment pass")
    parser.add_argument("--output", default=None, help="Custom output CSV path")
    parser.add_argument("--search-request", default=None,
                        help="Path to search_request.json (sliding-window + occupancy). "
                             "Overrides the manual --check-in/--adults/... flags.")
    args = parser.parse_args()

    hotel_id = extract_hotel_id(args.url or args.hotel_id)
    scraper = TajScraper(hotel_id=hotel_id, use_claude=args.use_claude)

    if args.search_request:
        request = load_search_request(args.search_request)
    else:
        request = _request_from_cli(args, scraper)

    scraper.run(request, output_dir=OUTPUT_DIR, output_file=args.output)


if __name__ == "__main__":
    main()
