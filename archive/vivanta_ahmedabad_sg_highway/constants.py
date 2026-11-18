"""
Constants for Vivanta Ahmedabad, SG Highway.

Vivanta (IHCL) runs on the same Hudini booking backend + Sanity CMS as Taj;
the only differences are the hotel id, the `tenant` header and the site URLs.
"""
import os

# Hotel identification
HOTEL_NAME = "Vivanta Ahmedabad, SG Highway"
HOTEL_LABEL = "Vivanta Ahmedabad"
HOTEL_ID = "d361c899-95fe-434a-943e-bca0b3cdb9b2"
DEFAULT_HOTEL_ID = os.getenv("VIVANTA_HOTEL_ID", HOTEL_ID).strip()

HOTEL_URL = (
    "https://www.vivantahotels.com/en-in/bookings/landing-page"
    f"?hotelId={DEFAULT_HOTEL_ID}"
)
DEFAULT_HOTEL_URL = os.getenv("VIVANTA_HOTEL_URL", HOTEL_URL).strip()

# Sanity CMS configuration (shared IHCL dataset)
SANITY_PROJECT_ID = "ocl5w36p"
SANITY_DATASET = "ihcl_prod"
SANITY_API_VERSION = "v2022-10-01"

# Hudini booking service (shared IHCL backend)
HUDINI_BASE_URL = "https://api-cug1-825v2.tajhotels.com/hudiniService/v1"

# Client defaults
DEFAULT_TENANT = "vivanta"
DEFAULT_CURRENCY = "INR"
BASE_URL = "https://www.vivantahotels.com"
ORIGIN = "https://www.vivantahotels.com"
REFERER = "https://www.vivantahotels.com/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
