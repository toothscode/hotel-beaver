#!/usr/bin/env python3
"""
AI extraction interface + providers, shared across hotels.

`AIExtractor` is the interface. It owns the provider-agnostic work — batching,
the extraction prompt, rate limiting, JSON parsing, and graceful fallback to the
raw records on any error. A concrete provider only implements:

    is_available() -> bool
    _complete(prompt) -> str     # one text completion call

So Claude and OpenAI (or any future provider) differ by a few lines. Pick one
with `build_ai_extractor()`, driven by `AI_PROVIDER` in the root .env.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from . import config
from .rate_limiter import RateLimiter, SlidingWindowRateLimiter

_PROMPT_HEADER = (
    "You are a specialized hotel data extraction agent. "
    "Analyze the following hotel room availability and pricing items.\n"
    "Ensure these fields are accurately extracted and formatted for each item:\n"
    "- Room Name\n- Check In Date\n- Check Out Date\n"
    "- Occupancy related fields (Occupancy description, Adults, Children, Rooms)\n"
    "- Rate (numeric price amount)\n- Currency (e.g. INR)\n"
    "- Cancellation policy in popup modal (full plain text terms)\n"
    "- Rate description in popup modal (full description including inclusions/rules)\n"
    "- Images url (semicolon-separated URLs)\n"
    "- rate type (rate plan name)\n\n"
)


class AIExtractor(ABC):
    """Interface for an AI enrichment pass over scraped records."""

    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter(
            window_ms=config.AI_RATE_LIMIT_WINDOW_MS,
            max_requests=config.AI_RATE_LIMIT_MAX,
        )

    # ---- provider-specific (subclasses implement these two) ------------ #
    @abstractmethod
    def is_available(self) -> bool:
        """True if the provider is configured and ready (API key, client)."""
        raise NotImplementedError

    @abstractmethod
    def _complete(self, prompt: str) -> str:
        """Send one prompt to the provider and return the text response."""
        raise NotImplementedError

    # ---- shared (provider-agnostic) ------------------------------------ #
    def enhance_records(
        self, raw_records: List[Dict[str, Any]], batch_size: int = 25
    ) -> List[Dict[str, Any]]:
        """Verify/clean/enrich records in batches; fall back to raw on error."""
        if not self.is_available():
            print(f"[{type(self).__name__}] Not available; using raw records.")
            return raw_records
        if not raw_records:
            return []

        enhanced: List[Dict[str, Any]] = []
        for i in range(0, len(raw_records), batch_size):
            batch = raw_records[i : i + batch_size]
            print(f"[{type(self).__name__}] Processing batch {i // batch_size + 1} "
                  f"({len(batch)} records)...")
            self.rate_limiter.acquire()
            try:
                prompt = (
                    _PROMPT_HEADER
                    + f"INPUT DATA:\n{json.dumps(batch, indent=2)}\n\n"
                    + "Return ONLY a valid JSON list of objects with these exact "
                      "keys, with no extra commentary."
                )
                text = self._complete(prompt).strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    text = "\n".join(
                        lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
                    )
                parsed = json.loads(text)
                enhanced.extend(parsed if isinstance(parsed, list) else batch)
            except Exception as e:  # noqa: BLE001 - provider-agnostic fallback
                print(f"[{type(self).__name__}] Warning: call failed ({e}). "
                      f"Falling back to raw records.")
                enhanced.extend(batch)
        return enhanced


class ClaudeExtractor(AIExtractor):
    """Anthropic Claude provider."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 rate_limiter: Optional[RateLimiter] = None):
        super().__init__(rate_limiter)
        self.api_key = (api_key or config.CLAUDE_AI_API_KEY or "").strip()
        self.model = model or config.CLAUDE_MODEL or "claude-sonnet-4-5"
        self._client = None
        if self.api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except Exception as e:  # noqa: BLE001
                print(f"[ClaudeExtractor] Failed to init client: {e}")

    def is_available(self) -> bool:
        return bool(self._client and self.api_key)

    def _complete(self, prompt: str) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))


class OpenAIExtractor(AIExtractor):
    """OpenAI provider (requires the `openai` package)."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 rate_limiter: Optional[RateLimiter] = None):
        super().__init__(rate_limiter)
        self.api_key = (api_key or config.OPENAI_API_KEY or "").strip()
        self.model = model or config.OPENAI_MODEL or "gpt-4o-mini"
        self._client = None
        if self.api_key:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            except Exception as e:  # noqa: BLE001
                print(f"[OpenAIExtractor] Failed to init client: {e}")

    def is_available(self) -> bool:
        return bool(self._client and self.api_key)

    def _complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


def build_ai_extractor(provider: Optional[str] = None) -> AIExtractor:
    """Build the configured AI extractor (default: AI_PROVIDER from .env)."""
    name = (provider or config.AI_PROVIDER or "claude").strip().lower()
    if name == "openai":
        return OpenAIExtractor()
    if name == "claude":
        return ClaudeExtractor()
    raise ValueError(f"Unknown AI_PROVIDER '{name}'. Use 'claude' or 'openai'.")
