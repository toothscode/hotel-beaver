---
name: supplier-vs-volt
description: Scrape IHCL (Taj, Vivanta, SeleQtions, Gateway) breakfast rates exactly as tajhotels.com shows them and build the "Supplier vs Volt" Excel (standard, member, member offer -> supplier net -> compare with Volt). Use when asked to scrape IHCL / Taj rates, run the supplier check, compare the supplier with Volt, add a hotel to the list, or "do the same for the next 30 days".
---

# Supplier vs Volt (IHCL hotels)

Our supplier sells IHCL hotels to us at a discount on **breakfast** rates. This skill scrapes the
rates the website shows, applies the supplier's formula, and builds one Excel where the team types
Volt's rate and sees who is cheaper.

## Run it (one command)

```
python tools/supplier_vs_volt.py                      # all hotels in config, today + 30 check-in dates
python tools/supplier_vs_volt.py --from 2026-12-01 --days 35
python tools/supplier_vs_volt.py --hotels taj_mahal_new_delhi,savoy_ooty
```

- Always **1 night, 2 adults, 1 room**, one row per room per check-in date.
- 16 hotels x 30 dates = 480 searches, about **40 minutes**. Run it in the background and wait;
  never start a second scrape at the same time.
- The Excel is written to `output/runs/<date_time>/Supplier vs Volt <from> to <to> - <n> hotels.xlsx`
  and also appears on the dashboard (`start_dashboard.bat`) with a download button.
- First time on a new PC: run `setup_windows.bat` (see SETUP_NEW_PC.md).

## The rules (the user was explicit -- do not deviate)

1. **Never calculate, estimate or assume a rate.** Every price in the sheet is what the hotel's
   booking system returned, with and without tax. If the website shows something that is not in the
   data, say so; do not fill it in.
2. **Breakfast plans only.** No room only, no half board, no packages.
3. Per room, the website has **at most 3 breakfast prices**:
   | Column | What it is |
   |---|---|
   | **Standard** | STANDARD RATE of "Breakfast Inclusive Rate" / "Best Available Rate : Breakfast Inclusive" |
   | **Member** | MEMBER RATE of that same plan (usually 10% or 15% lower -- varies by hotel and date, never assume) |
   | **Member Offer** | member-only offer (The City Special, Taj Club, Suite Surprises Member...), lowest if several; hover the cell to see its name |
4. The request in `core/ihcl.py` is **exactly the website's own request** (`rateFilter "RRM"`,
   `memberTier "member"`). Do not change it -- the old `"RRG,PKG,MD"` / `"copper"` request returned
   wrong member prices.

## Supplier formula (on the sheet as live formulas; the yellow % cells are editable)

| | Example | Formula |
|---|---|---|
| **Supplier Net - Standard** | 20,000 -> less 10% = 18,000 -> + 18% GST on 18,000 = 21,240 -> - 10% of 18,000 = **19,440** | `S x 0.9 + GST on (S x 0.9) - 10% of (S x 0.9)` |
| **Supplier Net - Member** | 16,000 -> + 18% GST = 18,880 -> - 10% of 16,000 = **17,280** | `M + GST on M - 10% of M` (no discount) |
| **Supplier Net - Member Offer** | same as Member | `O + GST on O - 10% of O` |

- GST is 18%, or **5% when the scraped rate is <= 7,500/night** (matches what the hotel charges).
- **LOWEST Supplier Net** = lowest of the 3 (highlighted green), compared with **Volt's rate, which
  includes taxes**. Result: "Supplier cheaper" (green) / "Volt cheaper" (red).
- Row 3 of every sheet runs the supplier's own examples through the same formulas: it must show
  **19,440** and **17,280**.

## Excel layout (keep it minimal -- the user does not want extra sheets or columns)

One sheet per hotel. Columns: Check-in | Room | Standard, Standard incl. GST, Supplier Net - Standard |
Member, Member incl. GST, Supplier Net - Member | Member Offer, Member Offer incl. GST, Supplier Net -
Member Offer | LOWEST Supplier Net | VOLT RATE (yellow, typed by the team) | Volt - Supplier | Result.
"incl. GST" columns are the hotel's own tax-inclusive price (scraped), not calculated.
A date with no breakfast rate shows one row "Sold out - no breakfast rate".

## Accuracy -- what the tool checks, and what you must report

The command prints an AUDIT. Before sharing the Excel, confirm and tell the user:
- every hotel `OK` (a `!!` line means that hotel's data is missing or incomplete);
- `GST differs from hotel's own tax: 0` and `member above standard: 0`;
- re-fetch lines: random hotel/dates fetched again after the scrape. "identical" = proof the sheet
  holds what the website returns. A few "changed" = the hotel repriced or sold a room since the
  scrape (normal for live prices); many = investigate before sharing;
- `Excel check ... errors=0 checks=19440/17280`.
To verify one price by hand: open the hotel on tajhotels.com with the same date, 1 night, 2 adults,
and compare STANDARD RATE / MEMBER RATE for that room with the sheet.

## Blocking and failures

- Requests are paced (one at a time). If IHCL **blocks** the run, it stops all IHCL hotels and does
  **not** retry -- wait a few hours. Never loop retries against a block.
- A hotel that **failed on a network timeout** is retried once automatically at the end.
- "Sold out" dates are real (the hotel has no breakfast rate that night), not errors.

## Add a hotel

1. Add an entry to `hotels` in `config/hotels.json` (same shape as the others: key, name, brand,
   `engine: "ihcl"`, `hotel_id` from the IHCL Sanity catalog, `tenant: "taj"`, site). Match the
   hotel name exactly -- similar names exist (Taj Mahal vs Taj Palace, Taj Bangalore vs Taj MG Road).
2. Add its key to `supplier_hotels` in the same file.
3. Test it alone first: `python tools/supplier_vs_volt.py --hotels <key> --days 3`.

## Rebuild without scraping

`python tools/supplier_vs_volt.py --merge <run folder> [<run folder> ...]` merges finished runs (per
hotel, the last run where it finished OK) and builds a fresh Excel. Partial runs live in
`output/runs/_parts/`.
