"""
Constants for Taj Palace, New Delhi.

Same IHCL Hudini booking backend + Sanity CMS as Taj Lands End (tenant "taj");
only the hotel id differs. Hotel id verified against Sanity
(identifier "taj-palace-new-delhi").
"""
import os

# Hotel identification
HOTEL_NAME = "Taj Palace, New Delhi"
HOTEL_LABEL = "Taj Palace Delhi"
HOTEL_ID = "288269fe-6d2d-4a25-be73-780418822a53"
# Prefixed env vars so this never picks up Taj Lands End's generic HOTEL_ID.
DEFAULT_HOTEL_ID = os.getenv("TAJ_PALACE_DELHI_HOTEL_ID", HOTEL_ID).strip()

HOTEL_URL = (
    "https://www.tajhotels.com/en-in/bookings/landing-page"
    f"?hotelId={DEFAULT_HOTEL_ID}"
)
DEFAULT_HOTEL_URL = os.getenv("TAJ_PALACE_DELHI_HOTEL_URL", HOTEL_URL).strip()

# Sanity CMS configuration (shared IHCL dataset)
SANITY_PROJECT_ID = "ocl5w36p"
SANITY_DATASET = "ihcl_prod"
SANITY_API_VERSION = "v2022-10-01"

# Hudini booking service (shared IHCL backend)
HUDINI_BASE_URL = "https://api-cug1-825v2.tajhotels.com/hudiniService/v1"

# Client defaults
DEFAULT_TENANT = "taj"
DEFAULT_CURRENCY = "INR"
BASE_URL = "https://www.tajhotels.com"
ORIGIN = "https://www.tajhotels.com"
REFERER = "https://www.tajhotels.com/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
