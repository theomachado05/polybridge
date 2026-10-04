import datetime as dt
import json
import math

import pytest

from app.closed import gap as G
from app.closed.session import ET
from app.closed.tracker import ClosureTracker, market_key


def et(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


def _state(move_pp=5.0, at=None):
    tr = ClosureTracker()
    k = market_key("polymarket", "m1")
    tr.observe(k, et(2026, 10, 2, 15, 59), 0.40)
    tr.observe(k, et(2026, 10, 3, 11, 0), 0.40 + move_pp / 100)
    return tr.state(k, at or et(2026, 10, 3, 12, 0))


def test_pooled_default_when_file_absent(tmp_path):
    rates = G.load_rates(tmp_path / "missing.json")
    assert rates.pooled is G.POOLED
    assert abs(G.POOLED.rate_bp_per_pp - 7.52) < 0.01 and abs(G.POOLED.se - 2.92) < 0.01
    e = G.expected_gap_for(_state(5.0), "polymarket", "m1", direction="down_on_yes", rates=rates)
    assert e.label == "pooled" and e.n_closures == 380
    assert e.sign == -1 and abs(e.oriented_move_pp + 5.0) < 1e-9
    assert abs(e.expected_gap_bp - (-5.0 * G.POOLED_RATE)) < 1e-6
    hw = G.Z80 * math.sqrt(25 * G.POOLED.se_eff ** 2 + G.POOLED_RESID_SD ** 2)
    assert e.band_bp[0] == pytest.approx(e.expected_gap_bp - hw) and e.band_bp[1] == pytest.approx(e.expected_gap_bp + hw)
    assert e.reasons == ["GAP_POOLED_RATE"] and e.active and e.band_level == 0.8
    assert G.POOLED.se_eff > G.POOLED.se


def test_orientation_assumed_without_direction():
    e = G.expected_gap_for(_state(2.0), "polymarket", "m1", rates=G.GapRates())
    assert e.sign == 1 and "GAP_ORIENTATION_ASSUMED" in e.reasons


def test_proxy_ticker_flag():
    e = G.expected_gap_for(_state(2.0), "polymarket", "m1", ticker="aapl", direction="up_on_yes", rates=G.GapRates())
    assert e.ticker == "AAPL" and e.basis_ticker == "SPY" and "GAP_PROXY_TICKER" in e.reasons


def test_no_gap_during_regular_hours_or_without_move():
    tr = ClosureTracker()
    k = market_key("polymarket", "m1")
    tr.observe(k, et(2026, 10, 5, 15, 59), 0.3)
    tr.observe(k, et(2026, 10, 6, 10, 0), 0.4)
    e = G.expected_gap_for(tr.state(k, et(2026, 10, 6, 10, 30)), "polymarket", "m1", rates=G.GapRates())
    assert e.expected_gap_bp is None and not e.active and "GAP_NOT_IN_CLOSURE" in e.reasons
    e = G.expected_gap_for(ClosureTracker().state(k, et(2026, 10, 3, 12, 0)), "polymarket", "m1", rates=G.GapRates())
    assert e.expected_gap_bp is None and "GAP_NO_MOVE" in e.reasons and e.n_closures == 380


DOC = {
    "n_min": 20, "z80": 1.2816, "tau_bp_per_pp": 6.0,
    "pooled": {"rate_bp_per_pp": 8.0, "se": 2.0, "resid_sd_bp": 50.0, "n": 600, "n_nonzero": 400, "n_markets": 3},
    "markets": {
        "us-recession-in-2025": {"token_id": "tok-rec", "sign": -1, "etf": "SPY", "rate_bp_per_pp": 10.7,
                                 "rate_raw_bp_per_pp": -10.7, "se": 3.8, "resid_sd_bp": 58.0, "n": 231,
                                 "n_nonzero": 152, "use": "own"},
        "thin-market": {"token_id": "tok-thin", "sign": 1, "etf": "SPY", "rate_bp_per_pp": 40.0, "se": 30.0,
                        "resid_sd_bp": 40.0, "n": 30, "n_nonzero": 8, "use": "pooled"},
    },
}


def test_market_rate_from_file_by_token_id(tmp_path):
    p = tmp_path / "gap_rates.json"
    p.write_text(json.dumps(DOC))
    rates = G.load_rates(p)
    e = G.expected_gap_for(_state(3.0), "polymarket", "gamma-123", token_id="tok-rec", direction="up_on_yes",
                           rates=rates)
    assert e.label == "market" and e.reasons == ["GAP_MARKET_RATE"]
    assert e.sign == -1
    assert e.expected_gap_bp == pytest.approx(10.7 * -3.0)
    assert e.n_closures == 231 and e.n_nonzero == 152 and e.se_eff == 3.8
    hw = 1.2816 * math.sqrt(9 * 3.8 ** 2 + 58.0 ** 2)
    assert e.band_bp[1] - e.band_bp[0] == pytest.approx(2 * hw)
    assert rates.lookup("polymarket", "us-recession-in-2025") is not None


def test_too_few_closures_uses_file_pooled_with_tau(tmp_path):
    rates = G.GapRates.from_doc(DOC)
    e = G.expected_gap_for(_state(2.0), "polymarket", "x", token_id="tok-thin", rates=rates)
    assert e.label == "pooled" and e.reasons == ["GAP_TOO_FEW_CLOSURES"]
    assert e.sign == 1
    assert e.rate_bp_per_pp == 8.0 and e.se_eff == pytest.approx(math.sqrt(4 + 36)) and e.resid_sd_bp == 50.0
    assert e.n_closures == 600


def test_unlisted_market_uses_file_pooled():
    rates = G.GapRates.from_doc(DOC)
    e = G.expected_gap_for(_state(2.0), "kalshi", "KX", direction="down_on_yes", rates=rates)
    assert e.label == "pooled" and e.reasons == ["GAP_POOLED_RATE"] and e.expected_gap_bp == pytest.approx(-16.0)


def test_malformed_file_falls_back(tmp_path):
    p = tmp_path / "gap_rates.json"
    p.write_text("{not json")
    assert G.load_rates(p).pooled is G.POOLED
    assert G.GapRates.from_doc([1, 2]).pooled is G.POOLED
    r = G.GapRates.from_doc({"markets": {"a": {"rate": "x"}, "b": {"rate": 5, "n": 50}}})
    assert "a" not in r.markets
    rate, own, why = G.choose_rate(r, "polymarket", "b")
    assert rate.label == "pooled" and why == ["GAP_TOO_FEW_CLOSURES"]


def test_list_shaped_markets():
    r = G.GapRates.from_doc({"markets": [{"market_source": "polymarket", "market_id": "m9", "rate": 9.0, "se": 2.0,
                                          "n": 40, "n_nonzero": 30}]})
    assert r.lookup("polymarket", "m9").rate_bp_per_pp == 9.0


def test_rate_for_tracker_key(tmp_path, monkeypatch):
    p = tmp_path / "gap_rates.json"
    p.write_text(json.dumps(DOC))
    monkeypatch.setattr(G, "GAP_RATES_PATH", p)
    r = G.rate_for("polymarket:tok-rec")
    assert r is not None and r.rate_bp_per_pp == 10.7 and r.n_closures == 231 and r.se == 3.8
    assert G.rate_for("polymarket:tok-thin") is None and G.rate_for("polymarket:nope") is None
    assert G.rate_for("bad") is None


def test_pooled_rate_policy_is_pinned(monkeypatch):
    doc = {"pooled": {"rate_bp_per_pp": 0.81, "se": 0.55, "resid_sd_bp": 60.8, "n": 1591, "n_nonzero": 1151},
           "tau_bp_per_pp": 4.23, "markets": {}}
    assert G.POOLED_FROM_FILE is True
    r = G.GapRates.from_doc(doc)
    assert r.pooled.rate_bp_per_pp == 0.81 and r.pooled.n_closures == 1591 and r.pooled.label == "pooled"
    assert r.pooled.se_eff == pytest.approx(math.sqrt(0.55 ** 2 + 4.23 ** 2))
    monkeypatch.setattr(G, "POOLED_FROM_FILE", False)
    r = G.GapRates.from_doc(doc)
    assert r.pooled is G.POOLED and r.pooled.n_closures == 380
