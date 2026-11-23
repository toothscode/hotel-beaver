# Playbook: add a new hotel chain scraper

How the IHCL (Taj) scraper was built, as a repeatable process. Read this, then paste the prompt at
the bottom into Claude Code opened in this folder.

## 0. How the existing system fits together (read these files first)

| Layer | File | Job |
|---|---|---|
| Contract | `core/base.py` | `BaseHotelScraper`: every chain subclasses it, returns a list of record dicts |
| Safety | `core/access.py`, `core/rate_limiter.py` | `Pacer` (wait before EVERY request), `detect_block()`, `HotelBlockedError` |
| Chain client | `core/ihcl.py` (copy this as the template) | request builder + `extract_structured_rooms()` -> records |
| Registry | `config/hotels.json` + `core/registry.py` | list of hotels (key, name, hotel_id, engine) |
| Orchestration | `core/runner.py`, `dashboard/job_runner.py` | loops hotels x dates, per-hotel status, stops on block |
| Output | `core/output.py`, `core/pricing.py`, `tools/supplier_check.py` | one standard record schema -> CSV -> Excel |
| Tests | `tests/test_ihcl.py` | offline: a real response saved as a fixture -> expected records |

Because every chain returns the **same record schema** (`core/output.py`), the Excel and dashboard
work for a new chain without changes.

## 1. Find how the website gets its prices (30 min, the step that decides everything)

1. Open the hotel's booking page for a real date in Chrome -> F12 -> **Network** -> filter **Fetch/XHR**.
2. Reload. Look for a JSON response that contains the room prices. Typical names: `availability`,
   `rates`, `search`, `offers`. Right-click it -> **Copy as cURL**.
3. Note: URL, method, **request body**, headers that matter (`tenant`, `Origin`, API key), and
   whether any cookie/token is needed.
4. Three outcomes, in order of preference:
   - **A. Plain JSON API, no cookie** (IHCL): easiest. Use a Python HTTP client.
   - **B. API needs a session cookie/token** the page sets when it loads: fetch it the way a normal
     visitor does (load the page once), reuse it, rebuild it **at most once** if it expires.
   - **C. Prices only exist in the rendered HTML**: use Playwright, slowest and most fragile. Last resort.
5. Save one real response to a file. It becomes your test fixture.

## 2. Copy the website's request EXACTLY

The IHCL member-rate bug came from sending slightly different parameters than the website
(`RRG`/`copper` instead of `RRM`/`member`): standard rates matched, member rates did not.
- Send every parameter the website sends, including loyalty/member flags.
- Compare 3 real prices (screenshot vs scraped) before building anything else.
- Use `curl_cffi` with `impersonate="chrome124"` (as in `core/ihcl.py`): looks like a normal browser.

## 3. Build `core/<chain>.py`

1. Copy `core/ihcl.py`; keep the structure: client class -> `_post()` (calls `pacer.wait()` and
   `detect_block()`) -> `get_room_availability()` -> `extract_structured_rooms()`.
2. Output one record per **price the website shows**: Standard / Member / Member Offer, with
   `Rate`, `Tax Amount`, `Total With Tax`, `Meal Plan`, cancellation, `Rate Category`. Never compute a
   price; if the site doesn't show it, leave it out.
3. Add the chain's hotels to `config/hotels.json` (`engine`, ids). Use exact hotel names; resolve IDs
   from the chain's own catalog and verify with one live request.
4. Register the engine in `core/registry.py`.

## 4. Access safety (non-negotiable; this is how we stay unblocked)

- One request at a time; random delay 3-6 s; max 12 requests/min (`core/access.py`, do not lower).
- Every response through `detect_block()` (403, "Access Denied", captcha, HTML instead of JSON).
  A block raises `HotelBlockedError`: **stop the whole chain for this run and never loop-retry.**
- A network timeout is not a block: retry that hotel once, alone (done in `tools/supplier_vs_volt.py`).
- "Cookie methods": only what a normal visitor does (load the page, keep the session cookie that
  the site itself sets). Do **not** spoof other people's cookies, rotate IPs, or defeat captchas /
  bot protection. If the site blocks, the answer is: wait hours, use the colleague's own connection,
  or ask the chain for API access.
- Test with 1 hotel x 1 date first, then 1 hotel x 3 dates, then the full run.

## 5. Tests (offline, no network, no credits)

Copy `tests/test_ihcl.py`: load the saved real response, assert 3 known prices (Standard, Member,
Offer) equal what the website showed, assert a sold-out date gives 0 rows, assert the request body
equals the website's. Run `python -m pytest tests -q`; everything must pass before a live run.

## 6. Accuracy gate before sharing any Excel

`tools/supplier_vs_volt.py` already does this; reuse it for the new chain:
- every hotel state `ok` (otherwise data is missing),
- tax in each row matches the hotel's own tax figure,
- member price never above standard,
- **re-fetch** random hotel/dates after the scrape and compare price by price,
- Excel recalculated in Excel: 0 errors, check cell shows the supplier's worked example.

## 7. Package

- Add the chain's hotel keys to `supplier_hotels` (or a new list) in `config/hotels.json`.
- Update the skill `.claude/skills/supplier-vs-volt/SKILL.md` (or create `.claude/skills/<chain>/`).
- Re-zip for colleagues (see `SETUP_NEW_PC.md`).

## Keep token/credit use low when doing this with Claude Code

- Do step 1 yourself in Chrome DevTools; paste only the **cURL command and one trimmed response**
  (first 2 rooms) into Claude. That is far cheaper than letting it explore the site.
- Give Claude one task per message, name the files (`core/ihcl.py` as template), and ask it to
  stop after the tests pass. Don't paste whole files or logs; paste the last 20 lines.
- Run long scrapes with the command in step 6 in a plain terminal, not through Claude: they cost nothing.
- Use `/model sonnet` for the build, and `/clear` between chains.

---

## Prompt to paste into Claude Code (open it in the hotel-beaver folder)

```
Add a new hotel chain scraper to this project by following docs/NEW_CHAIN_PLAYBOOK.md exactly.
Use core/ihcl.py as the template and tests/test_ihcl.py for the test style. Be token-efficient:
read only the files you need; no web exploration beyond what I paste.

Chain: <NAME>        Hotels: <exact names>        Booking page: <URL>
I have pasted below (a) the "Copy as cURL" of the request that returns room prices and
(b) one trimmed real response. Screenshot facts to verify against: <hotel, date, room, the
standard / member prices the website shows>.

Rules:
1. Build core/<chain>.py with the same structure (pacer.wait + detect_block on every request,
   extract_structured_rooms returning the standard record schema). Send the website's exact request.
2. Never calculate or assume a price; record only what the response contains.
3. Never loop-retry a block; no IP rotation, no spoofed cookies, no captcha bypass. If blocked,
   stop and tell me.
4. Add the hotels to config/hotels.json and register the engine.
5. Write an offline test from my pasted response; make `python -m pytest tests -q` pass.
6. Live-test 1 hotel x 1 date only, compare to my screenshot, then stop and report. Do not run
   larger scrapes: I will run tools/supplier_vs_volt.py myself.
Stop after step 6 and tell me what to check.
```
