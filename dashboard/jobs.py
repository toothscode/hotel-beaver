"""
Run storage for the dashboard. Each run lives in output/runs/<run-id>/:

    params.json   what was asked (hotels, dates, nights, adults)
    status.json   live progress, written by job_runner.py (heartbeat)
    cancel.flag   created by the dashboard's Cancel button
    log.txt       full scraper log
    *.xlsx/*.csv  results

Only ONE run may be active at a time: all IHCL hotels share one Akamai front,
so two parallel runs would double the request rate and risk a block.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "output" / "runs"
STALE_AFTER_S = 180          # no heartbeat for 3 min -> runner died
SECONDS_PER_SEARCH = 5.2     # measured: 3-6 s pacing, capped at 12/min


def estimate_minutes(n_searches: int) -> float:
    return n_searches * SECONDS_PER_SEARCH / 60


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def list_runs(limit: int = 15) -> List[Dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    runs = []
    dirs = [d for d in RUNS_DIR.iterdir() if (d / "params.json").exists()]
    # newest first by when the run was set up (folder names are not always timestamps)
    for d in sorted(dirs, key=lambda d: (d / "params.json").stat().st_mtime, reverse=True)[:limit]:
        params, status = _read(d / "params.json"), _read(d / "status.json")
        if params:
            runs.append({"dir": d, "params": params, "status": status or {"state": "queued"}})
    return runs


def is_alive(status: Dict[str, Any]) -> bool:
    if status.get("state") not in ("queued", "running"):
        return False
    beat = status.get("heartbeat") or status.get("created") or 0
    return time.time() - float(beat) < STALE_AFTER_S


def active_run() -> Optional[Dict[str, Any]]:
    for run in list_runs(limit=5):
        if is_alive(run["status"]):
            return run
    return None


def start_run(params: Dict[str, Any]) -> Path:
    if active_run():
        raise RuntimeError("A scrape is already running -- wait for it or cancel it.")
    run_dir = RUNS_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json_atomic(run_dir / "params.json", params)
    write_json_atomic(run_dir / "status.json", {"state": "queued", "created": time.time(),
                                                "heartbeat": time.time(), "done": 0,
                                                "total": params["n_searches"], "note": "starting..."})
    flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with open(run_dir / "log.txt", "w", encoding="utf-8") as log:
        subprocess.Popen([sys.executable, str(ROOT / "dashboard" / "job_runner.py"), str(run_dir)],
                         cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                         creationflags=flags, env=env)
    return run_dir


def cancel_run(run_dir: Path) -> None:
    (Path(run_dir) / "cancel.flag").write_text("cancel", encoding="utf-8")
