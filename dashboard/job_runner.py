"""
Background worker for one dashboard run:  python dashboard/job_runner.py <run_dir>

Runs the selected hotels with the same safety rules as main.py (core/runner),
writes status.json after every check-in date (also the heartbeat), honours
cancel.flag, and saves the Excel + raw CSV into the run folder.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

from core import RoomOccupancy, SearchRequest, write_csv  # noqa: E402
from core.excel import write_excel  # noqa: E402
from core.registry import available_hotels  # noqa: E402
from core.runner import RunCancelled, run_hotels  # noqa: E402
from jobs import write_json_atomic  # noqa: E402


def main(run_dir: Path) -> int:
    params = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
    status_path, cancel_flag = run_dir / "status.json", run_dir / "cancel.flag"
    started = time.time()
    status = {"state": "running", "created": started, "heartbeat": started,
              "done": 0, "total": params["n_searches"], "note": "starting...", "hotels": []}
    write_json_atomic(status_path, status)

    try:
        by_key = {e.key: e for e in available_hotels()}
        entries = [by_key[k] for k in params["hotels"]]
        request = SearchRequest(
            start_date=params["date_from"], scrape_for_n_days=params["n_dates"],
            night_duration=params["nights"],
            rooms=[RoomOccupancy(adults=params["adults"])] * params.get("rooms", 1),
        )

        def on_progress(statuses, done, total, note):
            status.update(heartbeat=time.time(), done=done, total=total, note=note,
                          hotels=[vars(s) for s in statuses])
            write_json_atomic(status_path, status)
            if cancel_flag.exists():
                raise RunCancelled()

        result = run_hotels(entries, request, on_progress)
        cancelled = any(s.state == "cancelled" for s in result.statuses)

        files = {}
        if result.records:
            title = (f"Hotel Rates {params['date_from']} to {params['date_to']} - "
                     f"{params['nights']}N {params['adults']}A")
            files["excel"] = str(write_excel(result.records, run_dir / f"{title}.xlsx",
                                             request, result.statuses))
            files["csv"] = str(write_csv(result.records, run_dir / "raw_rates.csv"))
        status.update(
            state="cancelled" if cancelled else "done",
            heartbeat=time.time(), finished=time.time(), rows=len(result.records),
            hotels=[vars(s) for s in result.statuses], **files,
            note=("Cancelled -- partial results saved" if cancelled else
                  "Finished" if result.ok else "Finished with problems -- see hotel status"),
        )
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        status.update(state="failed", heartbeat=time.time(), finished=time.time(),
                      note=f"{type(e).__name__}: {e}")
    write_json_atomic(status_path, status)
    return 0 if status["state"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
