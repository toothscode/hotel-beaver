#!/usr/bin/env python3
"""
ONE command: scrape IHCL breakfast rates -> accuracy audit -> "Supplier vs Volt" Excel.

    python tools/supplier_vs_volt.py                         # all hotels in config "supplier_hotels", today + 30 dates
    python tools/supplier_vs_volt.py --from 2026-12-01 --days 35
    python tools/supplier_vs_volt.py --hotels taj_mahal_new_delhi,savoy_ooty
    python tools/supplier_vs_volt.py --merge <run> <run> ... # no scraping: merge finished runs, build Excel

Always 1 night, 2 adults, 1 room. Rates are exactly what tajhotels.com shows (same request as the website).
Safety: one request at a time with pacing; a BLOCKED hotel stops IHCL for the run and is never retried.
A hotel that FAILED on a network timeout is retried once, on its own, at the end.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.registry import available_hotels, load_config  # noqa: E402
from tools.supplier_check import build, load  # noqa: E402

RUNS = ROOT / "output" / "runs"
PARTS = RUNS / "_parts"
BNB = "Breakfast (BnB)"


def say(msg=""):
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
def scrape(keys, date_from: date, days: int, run_dir: Path) -> dict:
    names = {e.key: e.name for e in available_hotels()}
    run_dir.mkdir(parents=True, exist_ok=True)
    params = {"hotels": keys, "hotel_names": [names[k] for k in keys],
              "date_from": date_from.isoformat(), "date_to": (date_from + timedelta(days=days - 1)).isoformat(),
              "n_dates": days, "nights": 1, "adults": 2, "rooms": 1, "n_searches": len(keys) * days}
    (run_dir / "params.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    say(f"Scraping {len(keys)} hotel(s) x {days} dates = {params['n_searches']} searches "
        f"(~{params['n_searches'] * 5 // 60 + 1} min) -> {run_dir}")
    with open(run_dir / "log.txt", "w", encoding="utf-8") as log:
        subprocess.run([sys.executable, str(ROOT / "dashboard" / "job_runner.py"), str(run_dir)],
                       stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    return json.loads((run_dir / "status.json").read_text(encoding="utf-8"))


def merge(run_dirs, out_dir: Path) -> Path:
    """Per hotel keep the rows of the LAST run where that hotel finished 'ok'."""
    out_dir.mkdir(parents=True, exist_ok=True)
    best, order, header, params = {}, [], None, None
    for d in map(Path, run_dirs):
        st = json.loads((d / "status.json").read_text(encoding="utf-8"))
        params = params or json.loads((d / "params.json").read_text(encoding="utf-8"))
        rows = list(csv.DictReader(open(d / "raw_rates.csv", encoding="utf-8"))) if (d / "raw_rates.csv").exists() else []
        header = header or (list(rows[0].keys()) if rows else None)
        for h in st.get("hotels", []):
            if h["key"] not in order:
                order.append(h["key"])
            if h["state"] == "ok" or h["key"] not in best:
                best[h["key"]] = (h, [r for r in rows if r["Hotel Name"] == h["name"]])
    hotels = [best[k][0] for k in order]
    with open(out_dir / "raw_rates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, header)
        w.writeheader()
        for k in order:
            w.writerows(best[k][1])
    params.update(hotels=order, hotel_names=[h["name"] for h in hotels], n_searches=len(order) * params["n_dates"])
    bad = [h for h in hotels if h["state"] != "ok"]
    status = {"state": "done", "done": params["n_searches"], "total": params["n_searches"],
              "rows": sum(len(best[k][1]) for k in order), "hotels": hotels,
              "note": "Finished" if not bad else f"Finished -- NOT ok: {', '.join(h['name'] for h in bad)}"}
    (out_dir / "params.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    (out_dir / "status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
    return out_dir


# --------------------------------------------------------------------------- #
def audit(run_dir: Path, n_recheck: int = 4) -> bool:
    """Internal checks + fresh re-fetch of random hotel/dates. True = everything consistent."""
    rows = list(csv.DictReader(open(run_dir / "raw_rates.csv", encoding="utf-8")))
    st = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    params = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
    ok = True
    say("\nAUDIT")
    for h in st["hotels"]:
        flag = "OK " if h["state"] == "ok" else "!! "
        ok &= h["state"] == "ok"
        say(f"  {flag}{h['name'][:45]:45} {h['detail'][:40]:40} sold out: {len(h.get('sold_out_dates') or [])} date(s)")
    gst_bad = [r for r in rows if r["GST Check"] != "OK"]
    pairs = {}
    for r in rows:
        if r["Meal Plan"] == BNB:
            pairs.setdefault((r["Hotel Name"], r["Check In Date"], r["Room Code"], r["Rate Code"]), {})[r["Price Type"]] = float(r["Rate"])
    above = [k for k, v in pairs.items() if "Member" in v and "Standard" in v and v["Member"] > v["Standard"]]
    say(f"  GST differs from hotel's own tax: {len(gst_bad)}   member above standard: {len(above)}")
    ok &= not gst_bad and not above

    entries = {e.key: e for e in available_hotels()}
    good = [h for h in st["hotels"] if h["state"] == "ok"]
    d0 = date.fromisoformat(params["date_from"])
    same = diff = 0
    for _ in range(min(n_recheck, len(good))):
        h = random.choice(good)
        d = (d0 + timedelta(days=random.randrange(params["n_dates"]))).isoformat()
        co = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        c = entries[h["key"]].build().client
        fresh = {(r["Room Code"], r["Rate Code"], r["Price Type"]): float(r["Rate"])
                 for r in c.extract_structured_rooms(c.get_room_availability(d, co, 2, 0, 1), d, co, 2, 0, 1)
                 if r["Meal Plan"] == BNB}
        old = {(r["Room Code"], r["Rate Code"], r["Price Type"]): float(r["Rate"]) for r in rows
               if r["Hotel Name"] == h["name"] and r["Check In Date"] == d and r["Meal Plan"] == BNB}
        s = sum(old.get(k) == v for k, v in fresh.items())
        dif = len(set(fresh) | set(old)) - s
        same, diff = same + s, diff + dif
        say(f"  re-fetch {h['name'][:35]:35} {d}: {s}/{len(fresh)} identical" + (f", {dif} changed" if dif else ""))
    say(f"  re-fetch total: {same} identical, {diff} changed"
        + ("  (a change = the hotel repriced since the scrape)" if diff else ""))
    return ok


def excel_recalc_and_check(path: Path) -> str:
    """Windows + Excel only: calculate, save values (so previews show numbers), read the check cells."""
    ps = f"""$xl = New-Object -ComObject Excel.Application; $xl.Visible=$false; $xl.DisplayAlerts=$false
try {{ $wb=$xl.Workbooks.Open('{path}'); $xl.CalculateFull(); $err=0; $chk=@()
  foreach ($ws in $wb.Worksheets) {{ foreach ($c in $ws.UsedRange.Cells) {{ if ($c.Text -like '#*') {{ $err++ }} }}
    $chk += ($ws.Range('E3').Value2.ToString() + '/' + $ws.Range('H3').Value2.ToString()) }}
  $wb.Save(); $wb.Close($false); 'errors=' + $err + ' checks=' + (($chk | Sort-Object -Unique) -join ',') }}
finally {{ $xl.Quit() }}"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=600)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # no Excel / not Windows -- the formulas still calculate when the file is opened
        return f"skipped ({e.__class__.__name__})"


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="date_from", default=date.today().isoformat())
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--hotels", default="all", help="comma-separated keys, or 'all' (config supplier_hotels)")
    ap.add_argument("--merge", nargs="+", help="build from finished run folders instead of scraping")
    ap.add_argument("--recheck", type=int, default=4, help="random hotel/dates re-fetched to prove accuracy")
    a = ap.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if a.merge:
        final = merge(a.merge, RUNS / stamp)
    else:
        keys = load_config()["supplier_hotels"] if a.hotels == "all" else a.hotels.split(",")
        known = {e.key for e in available_hotels()}
        if unknown := [k for k in keys if k not in known]:
            sys.exit(f"Unknown hotel key(s): {unknown}. See config/hotels.json")
        main_dir = PARTS / f"{stamp}_main"
        st = scrape(keys, date.fromisoformat(a.date_from), a.days, main_dir)
        runs = [main_dir]
        failed = [h["key"] for h in st["hotels"] if h["state"] == "failed"]
        if any(h["state"] in ("blocked", "skipped") for h in st["hotels"]):
            say("!! IHCL BLOCKED this run -- not retrying anything. Wait a few hours before the next run.")
        elif failed:
            say(f"Retrying once (network timeout): {failed}")
            runs.append(PARTS / f"{stamp}_retry")
            scrape(failed, date.fromisoformat(a.date_from), a.days, runs[-1])
        final = merge(runs, RUNS / stamp)

    accurate = audit(final, a.recheck)
    recs, dts, hotels = load([final])
    out = build(recs, dts, hotels, final / f"Supplier vs Volt {dts[0]} to {dts[-1]} - {len(hotels)} hotels.xlsx")
    say(f"\nExcel check (must be errors=0 checks=19440/17280): {excel_recalc_and_check(out.resolve())}")
    say(f"\nDONE{'' if accurate else ' -- WITH PROBLEMS, read the AUDIT above'}: {out.resolve()}")


if __name__ == "__main__":
    main()
