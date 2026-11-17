#!/usr/bin/env python3
"""
Shared configuration, loaded once from the root `.env`.

Holds the cross-hotel AI + rate-limit settings. Hotel-specific values (e.g. a
hotel id) stay in that hotel's own config, but they read the same root `.env`.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Load the single root .env (fallback to default search if absent).
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

# Which AI provider the extractor factory builds: "claude" | "openai".
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").strip().lower()

# Claude / Anthropic
CLAUDE_AI_API_KEY = os.getenv("CLAUDE_AI_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5").strip()

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Shared AI rate limit (sliding window)
AI_RATE_LIMIT_WINDOW_MS = int(os.getenv("AI_RATE_LIMIT_WINDOW_MS", "60000"))
AI_RATE_LIMIT_MAX = int(os.getenv("AI_RATE_LIMIT_MAX", "1"))
