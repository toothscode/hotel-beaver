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
```

All results are automatically saved into a single timestamped CSV inside `output/` (e.g. `output/output - 2026-11-17_14-03-47.csv`).

---

## 🏨 Supported Hotels

| Hotel | Directory | Booking Engine | Anti-Bot Technology |
|---|---|---|---|
| **Taj Lands End, Mumbai** | `hotels/taj_lands_end_mumbai/` | Taj / Hudini API | Chrome TLS impersonation (`curl_cffi`) |
| **The Leela Ambience, Delhi** | `hotels/leela_ambience_delhi/` | SynXis (Sabre) | Headless browser challenge clearance (`Playwright`) |

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
│   └── leela_ambience_delhi/
│       ├── constants.py         # Chain ID, Hotel ID, SynXis endpoints
│       └── leela_scraper.py     # Scraper implementation (BaseHotelScraper)
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

1. Create a folder under `hotels/` (e.g. `hotels/my_hotel/`).
2. Add a `constants.py` for its hotel ID and URLs.
3. Add a `my_hotel_scraper.py` subclassing `BaseHotelScraper` from `core`.
4. Run `python3 main.py` — it will automatically discover and run your new scraper!
