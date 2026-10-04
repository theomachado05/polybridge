import json
from datetime import date, datetime, timezone

import pytest

from arbscan import datasrc as ds
from arbscan.costs import PolyFee
from arbscan.implied import Quote
from arbscan.parse import kalshi_is_close, parse_pm_question
from arbscan.score import score_row
from synth import make_chain, true_prob


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.headers = payload, status, {}

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, **kw):
        self.calls.append(url)
        return self.responses.pop(0)


def test_parse_in_scope_and_out_of_scope():
    th, why = parse_pm_question("Will NVIDIA (NVDA) close above $1,230.50 on October 5?")
    assert th and (th.ticker, th.strike, th.kind) == ("NVDA", 1230.5, "daily")
    th, _ = parse_pm_question("Will NVIDIA (NVDA) finish week of October 5 above $230?")
    assert th.kind == "weekly"
    th, _ = parse_pm_question("Will NVIDIA (NVDA) close above $230 end of February?")
    assert th.kind == "monthly"
    th, _ = parse_pm_question("Will the market say yes?", "S&P 500 (SPY) closes above ___ on Aug 17?")
    assert th is None
    for q in ("Will Tesla (TSLA) hit $400 this week?", "Will NVIDIA (NVDA) close between $220 and $230?",
              "Will Apple (AAPL) be up or down on October 5?", "Will Bitcoin close above $100,000?",
              "Will Tesla (TSLA) close below $300 on Oct 5?"):
        assert parse_pm_question(q)[0] is None, q
    assert parse_pm_question("Will NVIDIA close above $230 on Oct 5?") == (None, "no_ticker")


def test_kalshi_close_filter():
    assert kalshi_is_close("KXINXU-26OCT02H1600") and not kalshi_is_close("KXINXU-26OCT05H1000")
    assert kalshi_is_close("INXU-26OCT02")


def test_http_caches_counts_and_degrades(tmp_path):
    sess = FakeSession([FakeResp({"a": 1}), FakeResp({}, 429), FakeResp({}, 500), FakeResp({}, 503), FakeResp({}, 500), FakeResp({}, 500), FakeResp({}, 500)])
    http = ds.Http(tmp_path, session=sess, sleep=lambda s: None, max_attempts=2)
    assert http.get_json("http://x/y", {"q": 1}) == {"a": 1}
    assert http.get_json("http://x/y", {"q": 1}) == {"a": 1}
    assert len(sess.calls) == 1
    assert http.get_json("http://x/z") is None
    assert http.failures
    sess2 = FakeSession([FakeResp({"n": 1}), FakeResp({"n": 2})])
    h2 = ds.Http(tmp_path / "b", session=sess2, sleep=lambda s: None)
    assert h2.get_json("http://x/live", cache=False) == {"n": 1} and h2.get_json("http://x/live", cache=False) == {"n": 2}


def test_clob_history_book_and_touch(tmp_path):
    sess = FakeSession([FakeResp({"history": [{"t": 10, "p": 0.4}, {"t": 70, "p": 0.45}]}),
                        FakeResp({"bids": [{"price": "0.40", "size": "10"}, {"price": "0.43", "size": "7"}],
                                  "asks": [{"price": "0.50", "size": "3"}, {"price": "0.46", "size": "9"}], "timestamp": "1000"}),
                        FakeResp({"error": "no data"}, 400)])
    http = ds.Http(tmp_path, session=sess, sleep=lambda s: None)
    assert ds.clob_history(http, "tok", 0, 100) == [(10, 0.4), (70, 0.45)]
    b = ds.clob_book(http, "tok")
    t = ds.book_touch(b)
    assert (t["bid"], t["bid_size"], t["ask"], t["ask_size"]) == (0.43, 7.0, 0.46, 9.0)
    assert ds.clob_history(http, "tok2", 0, 100) == []


def test_kalshi_bid_ask_at_picks_last_two_sided_candle_and_respects_age():
    c = [{"end_period_ts": 100, "yes_bid": {"close_dollars": "0.40"}, "yes_ask": {"close_dollars": "0.46"}},
         {"end_period_ts": 160, "yes_bid": {"close_dollars": "0.41"}, "yes_ask": {"close_dollars": None}},
         {"end_period_ts": 220, "yes_bid": {"close_dollars": "0.99"}, "yes_ask": {"close_dollars": "1.00"}}]
    r = ds.kalshi_bid_ask_at(c, 200)
    assert r == {"t": 100.0, "bid": 0.40, "ask": 0.46}
    assert ds.kalshi_bid_ask_at(c[:1], 100 + 901) is None


class FakeMassive:
    def __init__(self, contracts, quotes):
        self.contracts, self.quotes, self.calls = contracts, quotes, []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.startswith("/v3/reference/options/contracts"):
            return {"results": self.contracts.get(params["expiration_date"], [])}
        if path.startswith("/v3/quotes/"):
            q = self.quotes.get(path.rsplit("/", 1)[1])
            return {"results": [q] if q else []}
        raise RuntimeError("boom")


def test_option_source_nearest_expiry_and_quote_parsing():
    cs = {"2026-10-06": [{"strike_price": 100, "ticker": "O:X100", "shares_per_contract": 100},
                         {"strike_price": 105, "ticker": "O:X105", "shares_per_contract": 10}]}
    qs = {"O:X100": {"bid_price": 1.0, "ask_price": 1.2, "bid_size": 3, "ask_size": 4, "sip_timestamp": 5_000_000_000}}
    src = ds.OptionSource(FakeMassive(cs, qs), today=date(2026, 10, 3))
    exp, chain = src.nearest_expiry("X", date(2026, 10, 5))
    assert exp == "2026-10-06" and chain == {100.0: "O:X100"}
    q = src.quote("O:X100", datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert (q.bid, q.ask, q.bid_size, q.ts) == (1.0, 1.2, 3.0, 5.0)
    assert src.quote("O:NOPE", datetime(2026, 10, 3, tzinfo=timezone.utc)) is None
    assert ds.OptionSource(FakeMassive({}, {}), date(2026, 10, 3)).nearest_expiry("X", date(2026, 10, 5)) is None


def test_option_source_failure_is_recorded_not_raised():
    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("down")
    src = ds.OptionSource(Boom(), date(2026, 10, 3))
    assert src.contracts("X", "2026-10-05") == {} and src.failures


def _pm(mid, h=0.02, age=60.0, assumed=True, size=None):
    return dict(mid=mid, bid=mid - h, ask=mid + h, bid_size=size, ask_size=size, age_s=age, spread_assumed=assumed)


def _score(pm, k=100.0, half=0.01, live=False, clean=True, snap=1000.0, qts=1000.0, **kw):
    chain, quotes = make_chain(100.0, 0.30, 1 / 252, half=half, ts=qts)
    return score_row(pm=pm, strike=k, chain=chain, get_quote=lambda tk: quotes[tk], snap_ts=snap,
                     expiry_close_ts=snap + 86400, clean=clean, live=live, fee=PolyFee(), meta={"event": "e"}, **kw)


def test_score_row_fair_pm_has_no_gap_and_rich_pm_is_robust():
    p = true_prob(100.0, 100.0, 0.30, 1 / 252, 0.04)
    r = _score(_pm(p))
    assert r["status"] == "scored" and r["label"] in ("none", "gap_mid") and r["edge"] < 0
    r = _score(_pm(p + 0.25, h=0.01))
    assert r["label"] == "gap_robust" and r["trade"].startswith("A") and r["edge"] > 0.1
    assert r["edge_1tick"] is not None and r["strip_loss"] == pytest.approx(0.5)
    r = _score(_pm(p - 0.25, h=0.01))
    assert r["label"] == "gap_robust" and r["trade"].startswith("B")


def test_score_row_gates_and_never_executable_when_spread_assumed_or_options_closed():
    p = true_prob(100.0, 100.0, 0.30, 1 / 252, 0.04)
    assert _score(_pm(0.99))["status"] == "pm_extreme"
    assert _score(_pm(p, age=2000))["status"] == "pm_stale"
    assert _score(dict(mid=None, bid=None, ask=None, age_s=None))["status"] == "no_pm_price"
    stale = _score(_pm(p + 0.25, h=0.01), snap=1000.0 + 5000, qts=1000.0)
    assert stale["status"] == "no_chain"
    assert _score(_pm(p + 0.25), clean=False)["label"] == "not_scored"
    live_pm = _pm(p + 0.25, h=0.01, age=None, assumed=False, size=1000)
    closed = _score(live_pm, live=True, snap=1000.0 + 5000, qts=1000.0)
    assert closed["label"] == "gap_robust" and closed["options_open"] is False
    opened = _score(live_pm, live=True)
    assert opened["label"] == "gap_executable"
    small = _score(_pm(p + 0.25, h=0.01, age=None, assumed=False, size=100), live=True)
    assert small["label"] == "gap_robust"
    assert _score(_pm(p + 0.25, h=0.01, size=1000), live=True)["label"] != "gap_executable"
