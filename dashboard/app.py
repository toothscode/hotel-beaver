"""
Hotel Rate Finder -- browser dashboard for the contracting team.

Start:  double-click start_dashboard.bat   (or: streamlit run dashboard/app.py)
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

from core.registry import available_hotels  # noqa: E402
import jobs  # noqa: E402

MAX_SEARCHES = 1000          # hard cap per run (~90 min)
STATE_ICON = {"ok": "✅", "running": "⏳", "pending": "•", "blocked": "⛔",
              "skipped": "⏭️", "failed": "❌", "cancelled": "✖️"}

st.set_page_config(page_title="Hotel Rate Finder", page_icon="🏨", layout="centered")


@st.cache_data(ttl=300)
def hotel_options():
    return [(e.key, e.name, e.brand) for e in available_hotels()]


def fmt_minutes(m: float) -> str:
    return f"about {m:.0f} min" if m >= 1.5 else "under 2 min"


# --------------------------------------------------------------------------- #
# Live progress of the active run (refreshes itself every 2 s)
# --------------------------------------------------------------------------- #
@st.fragment(run_every=2)
def progress_panel(run_dir: Path):
    status = jobs._read(run_dir / "status.json") or {}
    if not jobs.is_alive(status):
        st.rerun()  # finished -> redraw the whole page (form + results)
    done, total = status.get("done", 0), max(status.get("total", 1), 1)
    st.progress(done / total, text=f"{done} of {total} searches  ·  {status.get('note', '')}")
    left = jobs.estimate_minutes(total - done)
    st.caption(f"Time left: {fmt_minutes(left)}. You can close this tab -- the scrape keeps running.")
    for h in status.get("hotels", []):
        st.write(f"{STATE_ICON.get(h['state'], '•')} **{h['name']}** — {h.get('detail') or h['state']}")


# --------------------------------------------------------------------------- #
st.title("🏨 Hotel Rate Finder")
st.caption("Live breakfast rates (standard + member) from hotel websites → Excel with our lowest rate, "
           "discount, commission, GST and a Volt comparison column.")

active = jobs.active_run()
if active:
    p = active["params"]
    st.subheader("Scrape in progress")
    st.write(f"{len(p['hotels'])} hotel(s) · check-in {p['date_from']} → {p['date_to']} · "
             f"{p['nights']} night(s) · {p['adults']} adult(s)")
    progress_panel(active["dir"])
    if st.button("Cancel scrape", type="secondary"):
        jobs.cancel_run(active["dir"])
        st.toast("Cancelling after the current search… partial results will be saved.")
else:
    options = hotel_options()
    names = {k: n for k, n, _ in options}
    with st.container(border=True):
        hotels = st.multiselect("Hotels", options=[k for k, _, _ in options],
                                format_func=lambda k: names[k], placeholder="Choose one or more hotels")
        today = date.today()
        picked = st.date_input("Check-in dates (from → to)", value=(today + timedelta(days=7),
                               today + timedelta(days=13)), min_value=today,
                               max_value=today + timedelta(days=500), format="DD/MM/YYYY")
        c1, c2 = st.columns(2)
        nights = c1.number_input("Nights per stay", min_value=1, max_value=30, value=1, step=1)
        adults = c2.number_input("Adults per room", min_value=1, max_value=4, value=2, step=1)

        date_from, date_to = (picked if isinstance(picked, tuple) and len(picked) == 2
                              else (None, None))
        if date_from and date_to:
            n_dates = (date_to - date_from).days + 1
            n_searches = n_dates * len(hotels)
            st.info(f"**{len(hotels)} hotel(s) × {n_dates} check-in date(s) = {n_searches} searches** "
                    f"· {fmt_minutes(jobs.estimate_minutes(n_searches))}\n\n"
                    f"Each stay: check-in on each date, {nights} night(s), {adults} adult(s), 1 room.")
        else:
            n_dates = n_searches = 0
            st.warning("Pick both a **from** and a **to** date in the calendar.")

        too_big = n_searches > MAX_SEARCHES
        if too_big:
            st.error(f"That is {n_searches} searches -- the limit per run is {MAX_SEARCHES} "
                     f"(to stay safe from blocking). Choose fewer hotels or dates.")
        if st.button("Get rates", type="primary", use_container_width=True,
                     disabled=not hotels or not n_dates or too_big):
            jobs.start_run({
                "hotels": hotels, "hotel_names": [names[k] for k in hotels],
                "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                "n_dates": n_dates, "nights": int(nights), "adults": int(adults), "rooms": 1,
                "n_searches": n_searches,
            })
            st.rerun()

# --------------------------------------------------------------------------- #
# Past runs
# --------------------------------------------------------------------------- #
st.subheader("Results")
runs = [r for r in jobs.list_runs() if not jobs.is_alive(r["status"])]
if not runs:
    st.caption("No results yet.")
for run in runs:
    p, s = run["params"], run["status"]
    try:   # dashboard runs are named by start time; tool/manual runs may have any name
        started = datetime.strptime(run["dir"].name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        started = datetime.fromtimestamp(run["dir"].stat().st_mtime)
    when = started.strftime("%d %b, %I:%M %p")
    state = s.get("state", "?")
    icon = {"done": "✅", "cancelled": "✖️", "failed": "❌"}.get(state, "⚠️")
    problems = [h for h in s.get("hotels", []) if h["state"] not in ("ok",)]
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown(f"{icon} **{when}** · {', '.join(p.get('hotel_names', p['hotels']))}")
        a.caption(f"Check-in {p['date_from']} → {p['date_to']} · {p['nights']}N · {p['adults']} adults"
                  f" · {s.get('rows', 0)} rates · {s.get('note', state)}")
        for h in problems:
            a.caption(f"{STATE_ICON.get(h['state'], '•')} {h['name']}: {h.get('detail') or h['state']}")
        # every Excel in the run folder (dashboard export + Supplier Check / Lowest Member reports)
        for x in sorted(run["dir"].glob("*.xlsx")):
            if x.name.startswith("~$"):     # Excel's lock file while the workbook is open
                continue
            b.download_button(f"⬇ {x.stem[:40]}", data=x.read_bytes(), file_name=x.name,
                              key=f"{run['dir']}|{x.name}", use_container_width=True,
                              mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
