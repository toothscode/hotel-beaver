"""
Offline tests for block detection, pacing and block handling (no network).

Response bodies below are the REAL ones captured on 2026-11-18:
  - Akamai 403 from Hudini when called without a Chrome TLS fingerprint
  - SynXis 401 from Leela when called without the reese84/sbeSessionID cookies

Run:  python -m pytest tests -q
"""
import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import HotelBlockedError, Pacer, SearchRequest, RoomOccupancy, detect_block  # noqa: E402

AKAMAI_403 = ('<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n<H1>Access Denied</H1>\n \n'
              'You don\'t have permission to access "http&#58;&#47;&#47;api-cug1-825v2.tajhotels.com/" on this server.')
LEELA_401 = ('{"Message":"Principal not found","ServiceName":"ProductManagerService",'
             '"OperationName":"GetProductAvailability","FaultType":"Unknown"}')
IMPERVA_PAGE = "<!DOCTYPE html><html><head><title>Pardon Our Interruption</title>"
SOLD_OUT_JSON = '{"roomAvailability":{"roomRates":[],"packagesRates":[]}}'


# --------------------------------------------------------------------------- #
# detect_block: every known block signal is caught; real answers are not
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status,ctype,body,expect_blocked", [
    (403, "text/html", AKAMAI_403, True),                 # IHCL / Akamai
    (401, "application/json", LEELA_401, True),           # Leela cookie/session failure
    (200, "text/html", IMPERVA_PAGE, True),               # challenge page served as 200
    (429, "application/json", "{}", True),                # rate limited
    (503, "text/html", "<html>busy</html>", True),
    (200, "application/json", SOLD_OUT_JSON, False),      # sold out is NOT a block
    (200, "application/json;charset=utf-8", '{"a":1}', False),
    (500, "application/json", '{"error":"bad payload"}', False),  # bug, not block
])
def test_detect_block(status, ctype, body, expect_blocked):
    assert (detect_block(status, ctype, body) is not None) == expect_blocked


# --------------------------------------------------------------------------- #
# Pacer: enforces the minimum gap; groups share one clock
# --------------------------------------------------------------------------- #
def test_pacer_enforces_min_gap():
    p = Pacer(min_s=0.3, max_s=0.4, max_per_min=100)
    p.wait()
    t0 = time.time()
    p.wait()
    assert time.time() - t0 >= 0.29


def test_pacer_group_is_shared():
    assert Pacer.for_group("ihcl-akamai") is Pacer.for_group("ihcl-akamai")
    assert Pacer.for_group("ihcl-akamai") is not Pacer.for_group("other")


# --------------------------------------------------------------------------- #
# IHCL scrapers: 403 mid-run -> HotelBlockedError carrying earlier rows
# --------------------------------------------------------------------------- #
from core.registry import available_hotels  # noqa: E402
from core.runner import run_hotels  # noqa: E402

# Three representative config hotels (Taj, Vivanta tenant, SeleQtions).
IHCL_KEYS = ["taj_palace_new_delhi", "vivanta_ekta_nagar", "savoy_ooty"]


def _build(key):
    return next(e for e in available_hotels() if e.key == key).build()


def _resp(status, ctype, body, json_obj=None):
    return SimpleNamespace(status_code=status, headers={"content-type": ctype}, text=body,
                           json=lambda: json_obj)


ONE_RATE = {"roomAvailability": {"roomRates": [{"roomCode": "X1", "rooms": [{
    "rateCode": "R1", "rateContent": {"name": "BAR", "categoryCode": "BAR"},
    "standardRate": {"total": {"amount": 100, "amountWithTaxesFees": 118},
                     "tax": {"amount": 18}, "availableInventory": 2}}]}]}}


@pytest.mark.parametrize("key", IHCL_KEYS)
def test_ihcl_block_mid_run_keeps_rows(key, monkeypatch):
    s = _build(key)
    assert s.block_group == "ihcl-akamai" and s.auth_cookies == ()
    s.client.pacer = Pacer(min_s=0, max_s=0, max_per_min=1000)
    s.client._catalog_cache = {"rooms": {}}
    calls = iter([_resp(200, "application/json", "{}", ONE_RATE),
                  _resp(403, "text/html", AKAMAI_403)])
    monkeypatch.setattr(s.client.session, "post", lambda *a, **k: next(calls))
    req = SearchRequest("2030-01-01", 3, 1, [RoomOccupancy(adults=2)])

    with pytest.raises(HotelBlockedError) as exc:
        s.collect(req)
    e = exc.value
    assert "Akamai" in e.reason and e.block_group == "ihcl-akamai"
    assert len(e.records) == 1 and e.records[0]["Hotel Name"] == s.name   # stamped
    assert e.records[0]["Price incl. GST"] == 118                           # priced: hotel tax 18


@pytest.mark.parametrize("key", IHCL_KEYS)
def test_ihcl_null_fields_do_not_crash(key):
    s = _build(key)
    s.client._catalog_cache = {"rooms": {}}
    data = {"roomAvailability": {"roomRates": [None, {"roomCode": "X", "rooms": [{
        "rateCode": "R", "rateContent": None, "cancellationPolicy": None,
        "standardRate": None, "memberRate": {"total": None, "tax": None}}]}],
        "packagesRates": None}}
    rows = s.client.extract_structured_rooms(data, "2030-01-01", "2030-01-02")
    assert len(rows) == 1 and rows[0]["Rate"] is None


def test_registry_has_all_16_team_hotels_unique():
    keys = {e.key for e in available_hotels()}
    team = {"taj_tirupati", "taj_palace_new_delhi", "taj_surajkund", "taj_damdama_lake",
            "taj_gandhinagar", "boulevard9_nadiad", "vivanta_ekta_nagar", "gateway_diu",
            "fort_house_diu", "vivanta_katra", "taj_bangalore", "taj_falaknuma_palace",
            "taj_exotica_andamans", "taj_fishermans_cove", "savoy_ooty", "taj_mahal_new_delhi"}
    assert team <= keys
    ids = [e.build().hotel_id for e in available_hotels() if e.source == "config"]
    assert len(ids) == len(set(ids))                                  # no duplicate hotel ids


# --------------------------------------------------------------------------- #
# Runner: blocked group is skipped, rows kept, other groups continue
# --------------------------------------------------------------------------- #
def test_runner_skips_blocked_group():
    from core import BaseHotelScraper
    from core.registry import HotelEntry

    sent = []

    class A(BaseHotelScraper):
        name, block_group = "Hotel A", "front-1"
        def scrape(self, request):
            sent.append(self.name)
            e = HotelBlockedError(self.name, "HTTP 403: test")
            e.records = [{"Room Name": "r", "Rate": 100, "Check In Date": "2030-01-01",
                          "Check Out Date": "2030-01-02"}]
            raise e

    class B(BaseHotelScraper):
        name, block_group = "Hotel B", "front-1"   # same front as A
        def scrape(self, request):
            sent.append(self.name); return []

    class C(BaseHotelScraper):
        name = "Hotel C"                            # independent
        def scrape(self, request):
            sent.append(self.name); return [{"Room Name": "c"}]

    entries = [HotelEntry(k, c.name, "", "test", c) for k, c in (("a", A), ("b", B), ("c", C))]
    req = SearchRequest("2030-01-01", 1, 1, [RoomOccupancy(adults=2)])
    res = run_hotels(entries, req)
    assert sent == ["Hotel A", "Hotel C"]                        # B never contacted
    assert [s.state for s in res.statuses] == ["blocked", "skipped", "ok"]
    assert {r.get("Hotel Name") for r in res.records} == {"Hotel A", "Hotel C"}
    assert not res.ok


def test_runner_cancel_keeps_partial_rows():
    """Cancel mid-hotel must keep the dates already scraped (bug found 2026-11-18)."""
    from core import BaseHotelScraper, RunCancelled
    from core.registry import HotelEntry

    class Slow(BaseHotelScraper):
        name = "Hotel S"
        def scrape(self, request):
            rows = []
            try:
                for i, (ci, co) in enumerate(request.windows(), 1):
                    rows.append({"Room Name": "r", "Rate": 100, "Check In Date": ci, "Check Out Date": co})
                    self.report_progress(i, 5, f"{ci}: 1 rates")
            except RunCancelled as e:
                e.records = rows
                raise
            return rows

    def on_progress(statuses, done, total, note):
        if done >= 2:
            raise RunCancelled()

    req = SearchRequest("2030-01-01", 5, 1, [RoomOccupancy(adults=2)])
    res = run_hotels([HotelEntry("s", "Hotel S", "", "test", Slow)], req, on_progress)
    assert res.statuses[0].state == "cancelled"
    assert len(res.records) == 2 and res.records[0]["Hotel Name"] == "Hotel S"
    assert "Price incl. GST" in res.records[0]                 # priced like normal rows
