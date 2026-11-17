#!/usr/bin/env python3
"""
Rate limiting interface + default implementation, shared across hotels.

`RateLimiter` is the interface any limiter implements (one `acquire()` that
blocks until a slot is free). `SlidingWindowRateLimiter` is the default:
max_requests per rolling window_ms.
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import List


class RateLimiter(ABC):
    """Interface: block until a request slot is available."""

    @abstractmethod
    def acquire(self) -> None:
        raise NotImplementedError


class SlidingWindowRateLimiter(RateLimiter):
    """Strictly enforces max_requests calls per window_ms milliseconds."""

    def __init__(self, window_ms: int = 60000, max_requests: int = 1):
        self.window_seconds = max(0.1, window_ms / 1000.0)
        self.max_requests = max(1, max_requests)
        self.timestamps: List[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.time()
            # Purge timestamps older than the sliding window
            self.timestamps = [t for t in self.timestamps if now - t < self.window_seconds]

            if len(self.timestamps) >= self.max_requests:
                oldest = self.timestamps[0]
                sleep_needed = self.window_seconds - (now - oldest)
                if sleep_needed > 0:
                    print(
                        f"[RateLimiter] Limit reached "
                        f"({self.max_requests} req / {int(self.window_seconds * 1000)}ms). "
                        f"Waiting {sleep_needed:.2f}s..."
                    )
                    time.sleep(sleep_needed)
                    now = time.time()
                    self.timestamps = [
                        t for t in self.timestamps if now - t < self.window_seconds
                    ]

            self.timestamps.append(time.time())
