#!/usr/bin/env python3
"""
Run a set of hotels against one SearchRequest -- shared by main.py (CLI) and
the dashboard job runner, so both follow the same safety rules:

  * hotels run one after another (never in parallel)
  * a block stops that hotel, keeps its rows, and skips every other hotel
    behind the same bot-protection front (block_group) for this run
  * one hotel failing never stops the others
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .access import HotelBlockedError, RunCancelled  # noqa: F401 (re-exported)
from .registry import HotelEntry
from .search_request import SearchRequest


@dataclass
class HotelStatus:
    key: str
    name: str
    state: str = "pending"          # pending|running|ok|blocked|skipped|failed|cancelled
    rows: int = 0
    detail: str = ""
    sold_out_dates: List[str] = field(default_factory=list)


@dataclass
class RunResult:
    records: List[dict] = field(default_factory=list)
    statuses: List[HotelStatus] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.state == "ok" for s in self.statuses)


ProgressFn = Callable[[List[HotelStatus], int, int, str], None]


def run_hotels(entries: List[HotelEntry], request: SearchRequest,
               on_progress: Optional[ProgressFn] = None) -> RunResult:
    """
    on_progress(statuses, done_requests, total_requests, note) is called after
    every check-in date; it may raise RunCancelled to stop cleanly.
    """
    n_dates = len(request.windows())
    total = n_dates * len(entries)
    result = RunResult(statuses=[HotelStatus(e.key, e.name) for e in entries])
    blocked_groups: set = set()
    done_before = 0

    def emit(note: str, done: int) -> None:
        if on_progress:
            on_progress(result.statuses, done, total, note)

    for entry, status in zip(entries, result.statuses):
        try:
            scraper = entry.build()
            if scraper.group in blocked_groups:
                status.state = "skipped"
                status.detail = f"skipped: '{scraper.group}' blocked earlier in this run"
                done_before += n_dates
                emit(f"{entry.name}: skipped (blocked group)", done_before)
                continue
            status.state = "running"
            base = done_before

            def cb(i: int, n: int, note: str, status=status, base=base) -> None:
                if "sold out" in note:
                    status.sold_out_dates.append(note.split(":")[0])
                emit(f"{status.name}: {note}", base + i)

            scraper.progress_cb = cb
            emit(f"{entry.name}: starting", base)
            rows = scraper.collect(request)
            result.records.extend(rows)
            status.state, status.rows = "ok", len(rows)
            status.detail = f"{len(rows)} rates"
        except RunCancelled as e:
            result.records.extend(e.records)   # keep rows scraped before Cancel
            status.state, status.rows = "cancelled", len(e.records)
            status.detail = f"cancelled (kept {len(e.records)} rates)"
            for s in result.statuses:
                if s.state == "pending":
                    s.state = "cancelled"
            break
        except HotelBlockedError as e:
            result.records.extend(e.records)
            blocked_groups.add(e.block_group)
            status.state, status.rows = "blocked", len(e.records)
            status.detail = f"BLOCKED: {e.reason} (kept {len(e.records)} rates)"
        except Exception as e:  # noqa: BLE001 - one hotel must not kill the run
            status.state, status.detail = "failed", f"{type(e).__name__}: {e}"
        done_before += n_dates
        emit(f"{entry.name}: {status.state}", done_before)
    return result
