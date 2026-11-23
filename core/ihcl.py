#!/usr/bin/env python3
"""
One scraper for every IHCL hotel (Taj, Vivanta, SeleQtions, Gateway, ...).

All IHCL brands share one booking backend (Hudini) and one CMS (Sanity), so a
hotel is just a config entry in config/hotels.json:

    {"key": "taj_palace_new_delhi", "name": "Taj Palace, New Delhi",
     "brand": "Taj", "engine": "ihcl", "hotel_id": "<guid>",
     "tenant": "taj", "site": "https://www.tajhotels.com"}

Access safety (verified 2026-11-18, see core/access.py):
  * no cookies needed; Chrome TLS fingerprint via curl_cffi
  * ALL IHCL hotels share one Akamai front -> one shared pacing clock and one
    block group: a block on any IHCL hotel skips the rest for this run.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from curl_cffi import requests

from .access import (REQUEST_TIMEOUT_S, HotelBlockedError, Pacer, ScrapeInterrupted,
                     detect_block)
from .base import BaseHotelScraper
from .pricing import MEMBER_BAR, MEMBER_OFFER, OTHER, STANDARD_BAR
from .rates import classify_meal_plan, free_cancellation
from .search_request import SearchRequest

IHCL_BLOCK_GROUP = "ihcl-akamai"

SANITY_PROJECT_ID = "ocl5w36p"
SANITY_DATASET = "ihcl_prod"
SANITY_API_VERSION = "v2022-10-01"
HUDINI_BASE_URL = "https://api-cug1-825v2.tajhotels.com/hudiniService/v1"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Rate groups read from the availability response. Excluded on purpose:
# dayUsageRates (day-use, not overnight), someoneElseRates (same rates, booked
# for another guest).
RATE_GROUPS = ("roomRates", "packagesRates", "memberExclusiveRates",
               "promotionRates", "offerRates")


class IHCLClient:
    """Low-level client: Hudini availability API + Sanity room catalog."""

    def __init__(self, hotel_id: str, hotel_name: str,
                 tenant: str = "taj", site: str = "https://www.tajhotels.com"):
        self.hotel_id = hotel_id
        self.hotel_name = hotel_name
        self.session = requests.Session(impersonate="chrome124")
        self.headers = {
            "tenant": tenant,
            "Content-Type": "application/json",
            "Origin": site,
            "Referer": site.rstrip("/") + "/",
            "User-Agent": USER_AGENT,
        }
        self._catalog_cache: Optional[Dict[str, Any]] = None
        self.pacer = Pacer.for_group(IHCL_BLOCK_GROUP)

    # ------------------------------------------------------------------ #
    def _post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paced POST to Hudini. Raises HotelBlockedError on any block signal."""
        self.pacer.wait()
        resp = self.session.post(url, headers=self.headers, json=payload,
                                 timeout=REQUEST_TIMEOUT_S)
        reason = detect_block(resp.status_code, resp.headers.get("content-type", ""), resp.text)
        if reason:
            raise HotelBlockedError(self.hotel_name, reason, IHCL_BLOCK_GROUP)
        if resp.status_code != 200:
            raise RuntimeError(f"Hudini {url.rsplit('/', 1)[-1]} failed: HTTP {resp.status_code}")
        try:
            return resp.json() or {}
        except ValueError:
            raise HotelBlockedError(self.hotel_name, "non-JSON response from Hudini", IHCL_BLOCK_GROUP)

    @staticmethod
    def _sanity_ref_to_url(ref: str) -> Optional[str]:
        if not ref or not ref.startswith("image-"):
            return None
        stripped = ref[len("image-"):]
        if "-" not in stripped:
            return None
        base, ext = stripped.rsplit("-", 1)
        return f"https://cdn.sanity.io/images/{SANITY_PROJECT_ID}/{SANITY_DATASET}/{base}.{ext}"

    def get_hotel_catalog(self) -> Dict[str, Any]:
        """Room names + images from Sanity (separate open service, not paced)."""
        if self._catalog_cache is not None:
            return self._catalog_cache
        groq = f"""*[_type == "hotel" && hotelId == "{self.hotel_id}"][0]{{
          hotelName,
          "rooms": hotelRooms->roomsList[]{{
            roomCode,
            "roomName": basicInfo.title,
            "images": basicInfo.media[].imageAsset.image[].asset._ref,
            "largeImages": basicInfo.media[].imageAsset.largeImage[].asset._ref
          }}
        }}"""
        url = (f"https://{SANITY_PROJECT_ID}.api.sanity.io/{SANITY_API_VERSION}/data/query/"
               f"{SANITY_DATASET}?query={urllib.parse.quote(groq)}")
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT_S)
        if resp.status_code != 200:
            print(f"[Warning] Sanity catalog HTTP {resp.status_code} -- no images / CMS room names")
            self._catalog_cache = {"rooms": {}}
            return self._catalog_cache
        data = resp.json().get("result") or {}
        if not data:
            print(f"[Warning] Sanity has no hotel with id {self.hotel_id} -- check hotels.json")
        rooms: Dict[str, Any] = {}
        for r in data.get("rooms") or []:
            code = r.get("roomCode")
            if not code:
                continue
            urls: List[str] = []
            for ref in (r.get("images") or []) + (r.get("largeImages") or []):
                u = self._sanity_ref_to_url(ref)
                if u and u not in urls:
                    urls.append(u)
            rooms[code] = {"roomName": r.get("roomName") or code, "imageUrls": urls}
        self._catalog_cache = {"rooms": rooms}
        return self._catalog_cache

    def get_room_availability(self, start_date: str, end_date: str,
                              adults: int = 2, children: int = 0, rooms: int = 1) -> Dict[str, Any]:
        # EXACTLY the request tajhotels.com sends for its "Room Rates" tab (captured from
        # the live website in Chrome, 2026-11-19). rateFilter "RRM" + memberTier "member"
        # returns each plan with BOTH prices the website shows: STANDARD RATE and MEMBER
        # RATE (e.g. Taj Mahal 6 Dec Luxury Twin: 32,500 / 27,625), plus member-only offers
        # (The City Special). The old "RRG,PKG,MD"/"copper" request did NOT return the
        # website member price -- do not go back to it.
        payload = {
            "hotelId": self.hotel_id, "startDate": start_date, "endDate": end_date,
            "numRooms": rooms, "adults": adults, "children": children,
            "rateFilter": "RRM", "memberTier": "member", "package": "PKG",
            "isOfferLandingPage": False, "rateCode": None, "promoCode": None,
            "promoType": None, "couponCode": None, "agentId": None, "agentType": None,
            "isMyAccount": False, "isCorporate": False, "isLogin": False,
            "isMemberOffer1": False, "isMemberOffer2": False, "forSomeoneElse": False,
            "isEmployeeOffer": False,
        }
        return self._post(f"{HUDINI_BASE_URL}/hotel-availability", payload)

    def get_calendar_lead(self, start_date: str, end_date: str, length_of_stay: int = 1) -> List[Dict[str, Any]]:
        payload = {"hotelId": self.hotel_id, "startDate": start_date, "endDate": end_date,
                   "lengthOfStay": length_of_stay, "rateFilter": "RRG,PKG,MD"}
        data = self._post(f"{HUDINI_BASE_URL}/calendar-view", payload)
        return ((data.get("data") or {}).get("getHotelLeadAvailability") or {}).get("leadAvailability") or []

    # ------------------------------------------------------------------ #
    def extract_structured_rooms(self, avail_data: Dict[str, Any], check_in: str, check_out: str,
                                 adults: int = 2, children: int = 0, rooms: int = 1) -> List[Dict[str, Any]]:
        """Parse the raw availability JSON into flat records (CSV-keyed dicts)."""
        rooms_catalog = self.get_hotel_catalog().get("rooms", {})
        availability = avail_data.get("roomAvailability") or {}
        groups: List[Dict[str, Any]] = []
        for key in RATE_GROUPS:
            groups += availability.get(key) or []

        occupancy = f"{adults} Adult{'s' if adults != 1 else ''}"
        if children > 0:
            occupancy += f", {children} Child{'ren' if children != 1 else ''}"
        occupancy += f", {rooms} Room{'s' if rooms != 1 else ''}"

        records: List[Dict[str, Any]] = []
        for group in groups:
            group = group or {}
            room_code = group.get("roomCode")
            info = rooms_catalog.get(room_code, {})
            room_name = info.get("roomName") or group.get("roomCategory") or f"Room ({room_code})"
            images = "; ".join(info.get("imageUrls", []))

            for r in group.get("rooms") or []:
                content = r.get("rateContent") or {}
                rate_name = content.get("name") or r.get("rateCode") or ""
                details = content.get("details") or {}
                rate_desc = (details.get("detailedDescription") or details.get("description") or "").strip()

                cancel = r.get("cancellationPolicy") or {}
                cancel_cols = free_cancellation(
                    check_in,
                    refundable=cancel.get("isFreeCancellation") if cancel else None,
                    days_before=cancel.get("cancelTimeIn"),
                    time_hhmm=cancel.get("cancelTime"),
                )
                meal_plan = classify_meal_plan(
                    r.get("rateCode") or "", rate_name, rate_desc,
                    (details.get("indicators") or {}).get("breakfastIncluded"),
                )
                # BAR = public best-available rate: category "BAR" or "RAC" (rack),
                # e.g. Vivanta R04 "Best Available Rate - Room Only" is RAC.
                is_bar = (content.get("categoryCode") in ("BAR", "RAC")
                          or "best available rate" in rate_name.lower())
                std = r.get("standardRate") or {}
                mem = r.get("memberRate") or {}
                has_std, has_mem = bool(std.get("total")), bool(mem.get("total"))
                # One row per price the website shows for this plan:
                #   STANDARD RATE -> Standard BAR (BAR/RAC plan) or Other
                #   MEMBER RATE   -> Member BAR (member price of a plan that also has a
                #                    standard price, e.g. NPMBB 32,500 -> 27,625) or
                #                    Member Offer (member-only plan, e.g. TCSN City Special)
                prices = []
                if has_std:
                    prices.append(("Standard", std, STANDARD_BAR if is_bar else OTHER, rate_name))
                if has_mem:
                    prices.append(("Member", mem, MEMBER_BAR if has_std else MEMBER_OFFER,
                                   f"{rate_name} - Member Rate" if has_std else rate_name))
                for price_type, chosen, rate_category, plan_name in prices:
                    total = chosen.get("total") or {}
                    nightly = [((d or {}).get("price") or {}).get("amount")
                               for d in chosen.get("daily") or []]
                    records.append(self._record(
                        room_name, check_in, check_out, occupancy, adults, children, rooms, total,
                        content, cancel, rate_desc, images, plan_name, meal_plan, is_bar,
                        rate_category, price_type, cancel_cols, r, room_code, chosen, nightly))
        return records

    @staticmethod
    def _record(room_name, check_in, check_out, occupancy, adults, children, rooms, total, content,
                cancel, rate_desc, images, plan_name, meal_plan, is_bar, rate_category, price_type,
                cancel_cols, r, room_code, chosen, nightly) -> Dict[str, Any]:
        return {
                    "Room Name": room_name,
                    "Check In Date": check_in,
                    "Check Out Date": check_out,
                    "Occupancy": occupancy,
                    "Adults": adults,
                    "Children": children,
                    "Rooms": rooms,
                    "Rate": total.get("amount"),
                    "Currency": content.get("currencyCode") or "INR",
                    "Cancellation policy in popup modal": (cancel.get("description") or "").strip(),
                    "Rate description in popup modal": rate_desc,
                    "Images url": images,
                    "rate type": plan_name,
                    "Meal Plan": meal_plan,
                    "Is BAR": "Yes" if is_bar else "No",
                    "Rate Category": rate_category,
                    "Price Type": price_type,
                    "Member Only": "Yes" if rate_category == MEMBER_OFFER else "No",
                    **cancel_cols,
                    "Rate Code": r.get("rateCode"),
                    "Room Code": room_code,
                    "Tax Amount": (chosen.get("tax") or {}).get("amount"),
                    "Total With Tax": total.get("amountWithTaxesFees"),
                    "Available Inventory": chosen.get("availableInventory"),
                    "Nightly Rates (excl. tax)": "; ".join(f"{a:.2f}" for a in nightly if a is not None),
        }


class IHCLScraper(BaseHotelScraper):
    """Config-driven scraper for any IHCL hotel (one entry in config/hotels.json)."""

    block_group = IHCL_BLOCK_GROUP
    auth_cookies = ()  # verified 2026-11-18: Hudini sets/needs no cookies

    def __init__(self, entry: Dict[str, Any], use_claude: bool = False):
        self.entry = entry
        self.key = entry["key"]
        self.name = entry["name"]
        self.label = entry.get("label") or entry["name"]
        self.hotel_id = entry["hotel_id"]
        self.use_claude = use_claude
        self.client = IHCLClient(
            hotel_id=self.hotel_id, hotel_name=self.name,
            tenant=entry.get("tenant", "taj"), site=entry.get("site", "https://www.tajhotels.com"),
        )

    def scrape(self, request: SearchRequest) -> List[Dict[str, Any]]:
        occ = request.aggregate_occupancy()  # Hudini accepts flat totals only
        windows = request.windows()
        print(f"\n[IHCL] {self.name}: {len(windows)} check-in date(s), "
              f"{request.night_duration} night(s), {occ['adults']} adult(s), {occ['rooms']} room(s)")
        records: List[Dict[str, Any]] = []
        try:
            for i, (c_in, c_out) in enumerate(windows, 1):
                raw = self.client.get_room_availability(
                    c_in, c_out, occ["adults"], occ["children"], occ["rooms"])
                rows = self.client.extract_structured_rooms(
                    raw, c_in, c_out, occ["adults"], occ["children"], occ["rooms"])
                records.extend(rows)
                print(f"  {c_in} -> {c_out}: {len(rows)} rate option(s)")
                self.report_progress(i, len(windows), f"{c_in}: {len(rows)} rates"
                                     + ("" if rows else " (sold out / no rates)"))
        except ScrapeInterrupted as e:   # blocked or cancelled
            e.records = records          # keep rows scraped so far
            raise
        return records
