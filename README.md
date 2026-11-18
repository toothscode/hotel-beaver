# Hotel Beaver 🏨

**Hotel Beaver** is an automated room and rate scraper for hotel booking engines. Given a search criteria (dates, length of stay, and guest occupancy), it queries hotel booking systems and aggregates room rates, taxes, room descriptions, images, and cancellation policies into a single unified CSV report.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```
*(Playwright is used by Leela to handle Imperva anti-bot protection).*

### 2. Set Your Search Criteria
Edit `config/search_request.json` with your desired dates and occupancy:
```json
{
  "start_date": "today",
  "scrape_for_n_days": 10,
  "night_duration": 2,
  "rooms": [
    { "adults": 2, "children": [], "infants": 0 }
  ]
}
```

### 3. Run the Scraper
```bash
# Scrape all hotels
python3 main.py

# Or scrape a specific hotel
python3 main.py --only leela_ambience_delhi
python3 main.py --only taj_lands_end_mumbai
python3 main.py --only vivanta_ahmedabad_sg_highway
```

All results are automatically saved into a single timestamped CSV inside `output/` (e.g. `output/output - 2026-11-17_14-03-47.csv`).

---

## 🖥️ Dashboard (for the contracting team)

**Double-click `start_dashboard.bat`** — the dashboard opens in your browser (http://localhost:8501).

1. **Hotels** — pick one or more.
2. **Check-in dates (from → to)** — every date in the range is a check-in date.
3. **Nights per stay** and **Adults per room**.
4. The page shows *hotels × dates = searches* and the estimated time (≈ 5 s per search; 400 searches ≈ 35 min) **before** you start. Max 1,000 searches per run.
5. **Get rates** → live progress. You can close the tab; the scrape keeps running. **Cancel** keeps what was already scraped.
6. **Download Excel** from the Results list.

Only one scrape runs at a time (all IHCL hotels share one bot-protection front).

### The Excel file
| Sheet | What it shows |
|---|---|
| **Best Deals** | Cheapest rate (price incl. GST) per hotel × check-in × meal plan, plus the cheapest refundable alternative |
| **All Rates** | Every room × rate plan: price excl. GST, GST %, GST, price incl. GST, per-night prices, Rate Type (Standard BAR / Member BAR / Other), cancellation terms |
| **Policies** | Full inclusions + cancellation text per rate plan |
| **Search Info** | What was searched, per-hotel status (OK / sold out / blocked), GST rule + GST check |

### Prices & GST
* **No TAC / discount is applied** — the team decides 10% / 15% using the *Rate Type* column.
* **GST** is the hotel's own tax. The tool checks it against the rule *price excl. GST per night per room below ₹7,500 → 5%, otherwise 18%* and highlights any row that differs (*GST Check* column). **Rule pending team confirmation** — settings in `config/hotels.json` → `pricing`.

---

## 🏨 Supported Hotels

| Hotels | Defined in | Booking Engine | Anti-Bot |
|---|---|---|---|
| **18 IHCL hotels** (Taj, Vivanta, SeleQtions, Gateway) — the team's 16 + Taj Lands End + Vivanta Ahmedabad | `config/hotels.json` → one shared scraper `core/ihcl.py` | IHCL Hudini API | Chrome TLS impersonation (`curl_cffi`), no cookies |
| **The Leela Ambience, Delhi** | `hotels/leela_ambience_delhi/` | SynXis (Sabre) | Headless browser + Imperva cookies (`Playwright`) |

`python main.py --list` shows every hotel key. Old per-hotel IHCL copies are kept in `archive/` for reference only.

---|---|---|---|
| **Taj Lands End, Mumbai** | `hotels/taj_lands_end_mumbai/` | Taj / Hudini API | Chrome TLS impersonation (`curl_cffi`) |
| **The Leela Ambience, Delhi** | `hotels/leela_ambience_delhi/` | SynXis (Sabre) | Headless browser challenge clearance (`Playwright`) |
| **Vivanta Ahmedabad, SG Highway** | `hotels/vivanta_ahmedabad_sg_highway/` | Taj / Hudini API (`tenant: vivanta`) | Chrome TLS impersonation (`curl_cffi`) |

> Each hotel folder has its own `constants.py` defining its hotel ID, chain ID, URLs, and API endpoints.

---

## ⚙️ How Search Configuration Works (`config/search_request.json`)

* **`start_date`**: The first check-in date (`"today"` or `"YYYY-MM-DD"`).
* **`scrape_for_n_days`**: How many consecutive check-in dates to scrape (sliding window).
* **`night_duration`**: Number of nights per stay.
* **`rooms`**: Array of rooms with `adults`, `children` (list of child ages, e.g. `[5, 8]`), and `infants`.

#### Sliding Window Example:
If `start_date = "2026-11-17"`, `scrape_for_n_days = 3`, and `night_duration = 2`:
* Window 1: `2026-11-17` to `2026-11-19`
* Window 2: `2026-11-18` to `2026-11-20`
* Window 3: `2026-11-19` to `2026-11-21`

---

## 🛡️ Access Safety (avoiding blocks)

**Before a big run or after adding a hotel**, run the pre-flight check:
```bash
python tools/check_access.py        # exit 1 = do NOT start a full run
python -m pytest tests -q           # offline tests for block detection/pacing
```

| Hotel | Cookies required | What gets us in | Block signal |
|---|---|---|---|
| Leela Ambience Delhi | `reese84` (Imperva, ~30d), `sbeSessionID` | Headless browser clears challenge | Challenge page or `401 Principal not found` |
| Taj Lands End / Taj Palace / Vivanta (IHCL) | none (verified) | Chrome TLS fingerprint (`curl_cffi`) | `403 Access Denied` (Akamai) |

Rules every scraper follows (see `core/access.py`):
* **Pacing:** random 3–6 s between requests to the same bot-protection front (IHCL hotels share one clock), max 12/min. Tune via `SCRAPE_*` in `.env`.
* **Stop on first block:** a block raises `HotelBlockedError` → that hotel stops, rows so far are kept, other hotels behind the same front are skipped, run exits `1` and prints `BLOCKED`. A block is never reported as "0 rows".
* **Cookie hotels:** if cookie generation fails or the session is rejected, the session is rebuilt **once**, then the hotel is marked BLOCKED.
* **New hotel with cookies:** declare them in `auth_cookies` and make `tools/check_access.py` pass before scheduling it.

---

## 📂 Project Structure

```text
hotel-beaver/
├── main.py                      # Main entrypoint (runs all or filtered hotels)
├── config/
│   └── search_request.json      # Search settings (dates, duration, occupancy)
├── hotels/                      # Hotel scrapers
│   ├── taj_lands_end_mumbai/
│   │   ├── constants.py         # Hotel ID, URLs, Sanity CMS endpoints
│   │   └── taj_scraper.py       # Scraper implementation (BaseHotelScraper)
│   ├── leela_ambience_delhi/
│   │   ├── constants.py         # Chain ID, Hotel ID, SynXis endpoints
│   │   └── leela_scraper.py     # Scraper implementation (BaseHotelScraper)
│   └── vivanta_ahmedabad_sg_highway/
│       ├── constants.py         # Hotel ID, tenant, Hudini + Sanity endpoints
│       └── vivanta_scraper.py   # Scraper implementation (BaseHotelScraper)
├── core/                        # Shared framework (interfaces, models, CSV writer)
├── output/                      # Generated CSV reports
└── requirements.txt             # Python dependencies
```

---

## 🤖 Optional Configuration (`.env`)

You can create a `.env` file (see `.env.example`) for optional settings:

```env
# Optional: AI Provider for rate extraction (pass --use-claude to enable)
AI_PROVIDER=claude
CLAUDE_AI_API_KEY=your_key_here

# Optional: Run Leela browser in visible mode (0 = visible browser, 1 = headless)
LEELA_HEADLESS=1
```

---

## ➕ Adding a New Hotel

**IHCL hotel (Taj / Vivanta / SeleQtions / Gateway / Ginger):** add one line to `config/hotels.json`
(`key`, `name`, `brand`, `hotel_id` from the IHCL Sanity catalog, `tenant`, `site`).
Then run `python tools/check_access.py` and a 1–3 date test before giving it to the team.

**Other booking engine:** create `hotels/<key>/<key>_scraper.py` subclassing `BaseHotelScraper`
(see `hotels/leela_ambience_delhi/`). Declare `auth_cookies` if the API needs cookies, fill
`Meal Plan`, `Rate Category`, cancellation columns via `core.rates`, and pass `tools/check_access.py`.
