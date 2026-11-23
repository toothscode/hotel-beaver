# Hotel Rate Finder — setup on a new Windows PC

## One-time setup (≈10 minutes)

1. **Install Python 3.12** from https://www.python.org/downloads/
   On the first installer screen tick **"Add python.exe to PATH"**, then *Install Now*.
2. **Unzip** the `hotel-beaver` folder somewhere simple, e.g. `C:\Users\<you>\hotel-beaver`
   (not inside OneDrive / a synced folder).
3. **Double-click `setup_windows.bat`.** It installs everything, runs the tests and checks that
   every hotel website is reachable from your network. Wait for **"Setup complete"**.
   If it shows **[X]** or **[!]**, send a screenshot to Pratyush.

## Every day

* **Double-click `start_dashboard.bat`** → the dashboard opens in your browser.
* Keep the black window open while you use it. Close it when done.
* Excel files are also saved in `output\runs\<date-time>\`.

## The "Supplier vs Volt" Excel (the main job)

Open a terminal in the folder (type `cmd` in the folder's address bar) and run:

    .venv\Scripts\python.exe tools\supplier_vs_volt.py

It scrapes the 16 IHCL hotels for today + 30 dates (about 40 minutes — leave the window open),
checks accuracy, and prints the path of `Supplier vs Volt ... .xlsx`. Type Volt's rate (incl. taxes)
in the yellow column. Options: `--from 2026-12-01 --days 35`, `--hotels taj_mahal_new_delhi,savoy_ooty`.
Full rules (3 rates per room, supplier formula): `.claude\skills\supplier-vs-volt\SKILL.md`
(Claude Code reads it automatically when you ask it to "run the supplier check").

## Rules (so the hotels don't block us)

* Run **one search at a time** (the dashboard enforces this).
* Keep runs to what you need — ~400 searches (4 hotels × 100 dates) is fine.
* If the dashboard says **BLOCKED** for a hotel: stop, wait a few hours, tell Pratyush.
  Don't keep retrying.
* Don't change the pacing settings (`SCRAPE_*`).

## If something breaks and you have Claude Code

Open Claude Code in the `hotel-beaver` folder and paste:

> I'm a non-technical user on Windows. This folder is the "Hotel Rate Finder" (Streamlit dashboard
> in `dashboard/app.py`, started by `start_dashboard.bat`; one-time setup is `setup_windows.bat`,
> which creates `.venv`). Please get it working:
> 1. Check Python 3.12 is installed and on PATH; run `setup_windows.bat` steps one by one using
>    `.venv\Scripts\python.exe` and fix any install error.
> 2. Run `.venv\Scripts\python.exe -m pytest tests -q` — all tests must pass.
> 3. Run `.venv\Scripts\python.exe tools\check_access.py`. If it reports BLOCKED / 403 / Access
>    Denied, **stop and tell me — do not retry in a loop, do not reduce delays, do not bypass bot
>    protection.** Explain in plain words.
> 4. Start the dashboard with `start_dashboard.bat` and confirm http://localhost:8501 opens.
> Do NOT edit scraper code, pacing (`core/access.py`, `SCRAPE_*`) or `config/hotels.json`,
> and do not run large scrapes yourself — a 1-hotel, 1-date test at most.
