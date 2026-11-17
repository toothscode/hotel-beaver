"""
Constants for The Leela Ambience Convention Hotel, Delhi.
"""
import os

# Hotel identification
HOTEL_NAME = "The Leela Ambience Convention Hotel, Delhi"
HOTEL_LABEL = "Leela Ambience Delhi"
CHAIN_ID = "23514"
HOTEL_ID = "3150"

DEFAULT_CHAIN_ID = os.getenv("LEELA_CHAIN_ID", CHAIN_ID).strip()
DEFAULT_HOTEL_ID = os.getenv("LEELA_HOTEL_ID", HOTEL_ID).strip()
DEFAULT_CURRENCY = os.getenv("LEELA_CURRENCY", "INR").strip()

# Headless browser setting (Imperva clearance)
DEFAULT_HEADLESS = os.getenv("LEELA_HEADLESS", "1").strip().lower() not in ("0", "false", "no")

# Booking engine URLs
BASE_URL = "https://reservations.theleela.com"
AVAIL_URL = f"{BASE_URL}/gw/product/v1/getProductAvailability"
HOTEL_URL = (
    f"{BASE_URL}/?chain={DEFAULT_CHAIN_ID}&hotel={DEFAULT_HOTEL_ID}"
    f"&level=hotel&locale=en-US&currency={DEFAULT_CURRENCY}"
)

# Client / browser defaults
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
