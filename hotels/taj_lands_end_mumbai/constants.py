"""
Constants for Taj Lands End, Mumbai.
"""
import os

# Hotel identification
HOTEL_NAME = "Taj Lands End, Mumbai"
HOTEL_LABEL = "Taj Hotel"
HOTEL_ID = "e1058dfa-fe44-4933-bb1b-85621258d217"
DEFAULT_HOTEL_ID = os.getenv("HOTEL_ID", HOTEL_ID).strip()

HOTEL_URL = f"https://www.tajhotels.com/en-in/bookings/landing-page?hotelId={DEFAULT_HOTEL_ID}"
DEFAULT_HOTEL_URL = os.getenv("HOTEL_URL", HOTEL_URL).strip()

# Sanity CMS configuration
SANITY_PROJECT_ID = "ocl5w36p"
SANITY_DATASET = "ihcl_prod"
SANITY_API_VERSION = "v2022-10-01"

# Hudini booking service
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
