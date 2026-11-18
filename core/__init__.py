"""
core — shared utilities for all hotel scrapers.

Import the pieces you need from here:

    from core import load_search_request          # parse search_request.json
    from core import write_csv, OutputRecord, csv_fields   # CSV output model
"""
from .search_request import (
    RoomOccupancy,
    SearchRequest,
    load_search_request,
)
from .output import (
    OutputRecord,
    csv_fields,
    output_path,
    write_csv,
)
from .base import BaseHotelScraper
from .rate_limiter import RateLimiter, SlidingWindowRateLimiter
from .access import (
    REQUEST_TIMEOUT_S,
    HotelBlockedError,
    Pacer,
    RunCancelled,
    ScrapeInterrupted,
    detect_block,
)
from .rates import classify_meal_plan, free_cancellation
from .ai import (
    AIExtractor,
    ClaudeExtractor,
    OpenAIExtractor,
    build_ai_extractor,
)

__all__ = [
    "RoomOccupancy",
    "SearchRequest",
    "load_search_request",
    "OutputRecord",
    "csv_fields",
    "output_path",
    "write_csv",
    "BaseHotelScraper",
    "RateLimiter",
    "SlidingWindowRateLimiter",
    "REQUEST_TIMEOUT_S",
    "HotelBlockedError",
    "Pacer",
    "RunCancelled",
    "ScrapeInterrupted",
    "detect_block",
    "classify_meal_plan",
    "free_cancellation",
    "AIExtractor",
    "ClaudeExtractor",
    "OpenAIExtractor",
    "build_ai_extractor",
]
