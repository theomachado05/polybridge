import asyncio
import datetime as dt
import math
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.options import quotes as qt
from app.options import reference as ref
from app.options import router as rt

UTC = dt.timezone.utc
WED = dt.datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
SAT = dt.datetime(2026, 10, 3, 19, 0, tzinfo=UTC)
FRI_CLOSE = dt.datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
E1, E2 = "2026-10-16", "2026-10-23"
WINDOW = dt.date(2026, 10, 16)


def ns(t: dt.datetime) -> int:
    return int(t.timestamp() * 1e9)


FRESH = ns(WED - dt.timedelta(minutes=20))
STALE = ns(WED - dt.timedelta(minutes=60))
FRI_LATE = ns(FRI_CLOSE - dt.timedelta(seconds=2))
FRI_EARLY = ns(FRI_CLOSE - dt.timedelta(minutes=30))


def occ(root, exp, kind, k):
    return f"O:{root}{exp[2:4]}{exp[5:7]}{exp[8:10]}{'C' if kind == 'call' else 'P'}{int(k * 1000):08d}"


def row(kind, k, exp, root="XYZ", spc=100):
    return {"details": {"contract_type": kind, "strike_price": k, "expiration_date": exp,
                        "ticker": occ(root, exp, kind, k), "shares_per_contract": spc},
            "fmv": 1.0, "fmv_last_updated": FRESH, "underlying_asset": {"price": 100.0, "timeframe": "DELAYED"}}


def chain_rows(exps=(E1, E2), strikes=(90, 95, 100, 105, 110, 115), root="XYZ"):
    return [row(kind, k, e, root) for e in exps for k in strikes for kind in ("call", "put")]


def quotes_for(exp, ts=FRESH, root="XYZ"):
    return {occ(root, exp, "call", 100): (5.60, 6.00, ts), occ(root, exp, "call", 105): (2.90, 3.10, ts),
            occ(root, exp, "call", 110): (1.00, 1.20, ts), occ(root, exp, "call", 115): (0.30, 0.40, ts),
            occ(root, exp, "put", 100): (2.40, 2.60, ts), occ(root, exp, "put", 95): (0.90, 1.10, ts),
            occ(root, exp, "put", 90): (0.30, 0.40, ts)}


class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeMassive:

    def __init__(self, rows=None, nbbo=None, fail=False):
        self.rows = chain_rows() if rows is None else rows
        self.nbbo = quotes_for(E1) if nbbo is None else nbbo
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []
        self.session = self

    def get(self, url, params=None, timeout=None):
        path = urlparse(url).path
        p = params or {}
        self.calls.append((path, p))
        if self.fail:
            raise TimeoutError("stalled")
        parts = path.strip("/").split("/")
        if path.startswith("/v3/snapshot/options/") and len(parts) == 4:
            d = lambda r: r["details"]  # noqa: E731
            out = [r for r in self.rows
                   if (p.get("expiration_date.gte") is None or d(r)["expiration_date"] >= p["expiration_date.gte"])
                   and (p.get("expiration_date.lte") is None or d(r)["expiration_date"] <= p["expiration_date.lte"])
                   and (p.get("strike_price.gte") is None or d(r)["strike_price"] >= p["strike_price.gte"])
                   and (p.get("strike_price.lte") is None or d(r)["strike_price"] <= p["strike_price.lte"])
                   and (p.get("contract_type") is None or d(r)["contract_type"] == p["contract_type"])]
            return _Resp({"results": out})
        if path.startswith("/v3/quotes/"):
            q = self.nbbo.get(parts[2])
            res = [{"bid_price": q[0], "ask_price": q[1], "bid_size": 10, "ask_size": 10, "sip_timestamp": q[2]}] if q else []
            return _Resp({"results": res, "status": "DELAYED"})
        return _Resp({}, 404)

    def quote_calls(self):
        return [c[0].split("/")[-1] for c in self.calls if c[0].startswith("/v3/quotes/")]


@pytest.fixture(autouse=True)
def fresh_caches():
    qt.reset_caches()
    ref.reset_caches()
    yield
    qt.reset_caches()
    ref.reset_caches()


def run(coro):
    return asyncio.run(coro)


def G(days):
    return math.exp(0.04 * days / 365.0)


def test_bracket_rule_listed_and_between():
    ks = [90, 95, 100, 105, 110]
    assert ref.bracket_indices(ks, 100) == (1, 3)
    assert ref.bracket_indices(ks, 102.5) == (2, 3)
    assert ref.bracket_indices(ks, 90) is None
    assert ref.bracket_indices(ks, 120) is None


def test_spread_math_call_and_put_by_hand():
    t = 16 / 365
    lg = lambda k, b, a: ref.Leg(f"K{k}", k, b, a, 0.0)  # noqa: E731
    up = ref.SpreadProb(105, 110, lg(105, 2.90, 3.10), lg(110, 1.00, 1.20), t)
    assert up.p_mid == pytest.approx(0.38 * G(16)) and up.p_mid == pytest.approx(0.380667, abs=1e-6)
    assert up.p_lo == pytest.approx(0.34 * G(16)) and up.p_hi == pytest.approx(0.42 * G(16))
    dn = ref.SpreadProb(95, 100, lg(100, 2.40, 2.60), lg(95, 0.90, 1.10), t)
    assert (dn.p_mid, dn.p_lo, dn.p_hi) == pytest.approx((0.30 * G(16), 0.26 * G(16), 0.34 * G(16)))
    wild = ref.SpreadProb(100, 101, lg(100, 3.0, 3.2), lg(101, 0.0, 0.1), t)
    assert wild.p_mid == 1.0 and wild.noarb_violation
    assert ref.touch_from(0.3) == 0.6 and ref.touch_from(0.7) == 1.0


def test_matches_existing_arbscan_spread():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "arb"))
    try:
        from arbscan.implied import Quote, Spread, bracket_indices
    except Exception:  # pragma: no cover - the research tree is not importable here
        pytest.skip("arbscan not importable")
    finally:
        sys.path.pop(0)
    t = 23 / 365
    a = Spread(105, 110, Quote(2.9, 3.1), Quote(1.0, 1.2), t)
    b = ref.SpreadProb(105, 110, ref.Leg("a", 105, 2.9, 3.1, 0), ref.Leg("b", 110, 1.0, 1.2, 0), t)
    assert (a.p_mid, a.p_lo, a.p_hi) == pytest.approx((b.p_mid, b.p_lo, b.p_hi))
    for k in (90, 92.5, 100, 110, 111):
        assert bracket_indices([90, 95, 100, 105, 110], k) == ref.bracket_indices([90, 95, 100, 105, 110], k)


def test_usable_leg_rule_accepts_zero_bid_rejects_stale_and_empty():
    inst = (WED - dt.timedelta(minutes=15)).timestamp()
    now = WED.timestamp()
    assert ref.usable(ref.Leg("x", 1, 0.0, 0.02, FRESH / 1e9), inst, now)
    assert not ref.usable(ref.Leg("x", 1, 0.5, 0.0, FRESH / 1e9), inst, now)
    assert not ref.usable(ref.Leg("x", 1, 0.6, 0.5, FRESH / 1e9), inst, now)
    assert not ref.usable(ref.Leg("x", 1, 0.4, 0.5, STALE / 1e9), inst, now)
    assert not ref.usable(None, inst, now)


def test_end_session_day_and_underlying():
    assert ref.end_session_day(dt.date(2026, 10, 31)) == dt.date(2026, 10, 30)
    assert ref.end_session_day(dt.date(2026, 10, 16)) == dt.date(2026, 10, 16)
    assert ref.underlying_and_root("spx") == ("I:SPX", "SPXW")
    assert ref.underlying_and_root("SPY") == ("SPY", "SPY")


def test_touch_above_during_session_hand_computed():
    fake = FakeMassive()
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=fake, now=WED))
    assert r["available"] is True and r["reason"] is None
    g = G(16)
    assert r["finish_beyond"] == pytest.approx({"mid": 0.38 * g, "lo": 0.34 * g, "hi": 0.42 * g}, abs=1e-6)
    assert r["touch"] == pytest.approx({"mid": 0.76 * g, "lo": 0.68 * g, "hi": 0.84 * g}, abs=1e-6)
    assert r["central"]["kind"] == "touch" and r["central"]["mid"] == r["touch"]["mid"]
    assert r["lower_bound"] == r["finish_beyond"]["mid"]
    assert r["expiry"] == E1 and r["expiry_rank"] == 1 and r["option_type"] == "call"
    assert r["strikes"] == {"lo": 105, "hi": 110, "width": 5, "stepped": 0, "width_pct_of_level": pytest.approx(4.6512, abs=1e-4)}
    assert [l["role"] for l in r["legs"]] == ["long", "short"] and r["legs"][0]["strike"] == 105
    assert r["market_open"] is True and "delayed about 15 minutes" in r["session_label"]
    assert r["as_of"] == "2026-09-30T14:45:00Z"
    assert "reflection" in r["method_note"] and "later than the ticket window" in r["method_note"]
    assert "OPEN LEAD" in r["status"] and "Massive" in r["source"]
    assert "hedge" not in str(r).lower()
    assert sorted(fake.quote_calls()) == sorted([occ("XYZ", E1, "call", 105), occ("XYZ", E1, "call", 110)])


def test_finish_below_put_spread_hand_computed():
    r = run(ref.reference_for("XYZ", 97.5, "below", WINDOW, "finish", client=FakeMassive(), now=WED))
    g = G(16)
    assert r["available"] and r["option_type"] == "put"
    assert r["finish_beyond"] == pytest.approx({"mid": 0.30 * g, "lo": 0.26 * g, "hi": 0.34 * g}, abs=1e-6)
    assert r["central"] == {"kind": "finish", **r["finish_beyond"]}
    assert r["legs"][0]["strike"] == 100 and r["legs"][1]["strike"] == 95
    assert r["lower_bound"] is None


def test_stale_leg_moves_outward_one_strike():
    nb = quotes_for(E1)
    nb[occ("XYZ", E1, "call", 105)] = (2.90, 3.10, STALE)
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(nbbo=nb), now=WED))
    assert r["available"] and r["strikes"]["lo"] == 100 and r["strikes"]["hi"] == 110 and r["strikes"]["stepped"] == 1
    g = G(16)
    assert r["finish_beyond"]["mid"] == pytest.approx((5.80 - 1.10) / 10 * g, abs=1e-6)
    assert any("moved outward" in n for n in r["notes"])


def test_expiry_walk_next_listed_when_first_has_no_quotes():
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(nbbo=quotes_for(E2)), now=WED))
    assert r["available"] and r["expiry"] == E2 and r["expiry_rank"] == 2
    assert r["days_expiry_after_window_end"] == 7
    assert r["finish_beyond"]["mid"] == pytest.approx(0.38 * G(23), abs=1e-6)
    assert any("after the ticket window ends" in n for n in r["notes"])


def test_expiry_walk_stops_after_three_tries():
    exps = ("2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21")
    fake = FakeMassive(rows=chain_rows(exps), nbbo=quotes_for("2026-10-21"))
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=fake, now=WED))
    assert r["available"] is False and r["expiries_tried"] == 3
    assert r["reason"] == "no quote on the bracketing strikes"


def test_no_expiry_within_45_days():
    fake = FakeMassive(rows=chain_rows(("2026-12-18",)), nbbo=quotes_for("2026-12-18"))
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=fake, now=WED))
    assert r["available"] is False and "within 45 days" in r["reason"]


def test_level_outside_listed_strikes():
    r = run(ref.reference_for("XYZ", 114.0, "above", WINDOW, "touch",
                              client=FakeMassive(rows=chain_rows(strikes=(100, 105, 110))), now=WED))
    assert r["available"] is False and r["reason"] == "no listed strikes bracket the level"


def test_weekend_is_fridays_close_and_says_so():
    nb = quotes_for(E1, ts=FRI_LATE)
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(nbbo=nb), now=SAT))
    assert r["available"] is True and r["market_open"] is False and r["market_phase"] == "weekend"
    assert "Friday's close" in r["session_label"] and "weekend" in r["session_label"]
    assert "not tradable now" in r["session_label"] and "2026-10-02 16:00 ET" in r["session_label"]
    assert r["as_of"] == "2026-10-02T20:00:00Z"
    assert r["finish_beyond"]["mid"] == pytest.approx(0.38 * G(14), abs=1e-6)


def test_weekend_rejects_quotes_older_than_ten_minutes_before_the_close():
    nb = quotes_for(E1, ts=FRI_EARLY)
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(nbbo=nb), now=SAT))
    assert r["available"] is False and "Friday's close" in r["session_label"]
    assert r["reason"] == "no usable pair of leg quotes (stale, or no offer)"


def test_zero_bid_leg_flagged_and_touch_capped():
    nb = quotes_for(E1)
    nb[occ("XYZ", E1, "call", 105)] = (4.90, 5.10, FRESH)
    nb[occ("XYZ", E1, "call", 110)] = (0.0, 0.10, FRESH)
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(nbbo=nb), now=WED))
    assert r["available"] and r["zero_bid_leg"] is True
    assert r["finish_beyond"]["mid"] == pytest.approx(0.99 * G(16), abs=1e-6)
    assert r["touch"]["mid"] == 1.0 and r["touch"]["hi"] == 1.0
    assert any("zero bid" in n for n in r["notes"])


def test_spx_uses_index_pm_root_only():
    rows = chain_rows(root="SPXW") + [row("call", k, E1, root="SPX") for k in (95, 100, 105, 110, 115)]
    nb = quotes_for(E1, root="SPXW")
    nb[occ("SPX", E1, "call", 105)] = (9.0, 9.2, FRESH)
    fake = FakeMassive(rows=rows, nbbo=nb)
    r = run(ref.reference_for("SPX", 107.5, "above", WINDOW, "touch", client=fake, now=WED))
    assert r["available"] and r["underlying"] == "I:SPX" and r["option_root"] == "SPXW"
    assert all(l["ticker"].startswith("O:SPXW") for l in r["legs"])
    assert any(c[0] == "/v3/snapshot/options/I:SPX" for c in fake.calls)


def test_non_standard_contracts_ignored():
    rows = [row("call", k, E1, spc=100 if k != 105 else 10) for k in (95, 100, 105, 110, 115)]
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(rows=rows), now=WED))
    assert r["available"] and r["strikes"]["lo"] == 100


def test_window_already_ended():
    r = run(ref.reference_for("XYZ", 107.5, "above", dt.date(2026, 9, 25), "touch", client=FakeMassive(), now=WED))
    assert r["available"] is False and "window ended" in r["reason"]


def test_degrades_never_raises():
    assert run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=None, now=WED))["reason"] == \
        "MASSIVE_API_KEY not set"
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(fail=True), now=WED))
    assert r["available"] is False and r["reason"].startswith("Massive unavailable")
    for bad in (dict(level=-1), dict(direction="up"), dict(kind="both"), dict(window_end="soon"), dict(ticker="nv da")):
        args = {"ticker": "XYZ", "level": 107.5, "direction": "above", "window_end": WINDOW, "kind": "touch", **bad}
        out = run(ref.reference_for(**args, client=FakeMassive(), now=WED))
        assert out["available"] is False and out["reason"]


def test_timeout_is_labelled(monkeypatch):
    async def slow(*a, **k):
        await asyncio.sleep(5)
    monkeypatch.setattr(ref, "_compute", slow)
    monkeypatch.setattr(ref, "TOTAL_TIMEOUT_S", 0.05)
    r = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=FakeMassive(), now=WED))
    assert r["available"] is False and r["reason"].startswith("timed out")


def test_cached_within_the_minute():
    fake = FakeMassive()
    a = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=fake, now=WED))
    n = len(fake.calls)
    b = run(ref.reference_for("XYZ", 107.5, "above", WINDOW, "touch", client=fake, now=WED + dt.timedelta(seconds=5)))
    assert a == b and len(fake.calls) == n


def test_route_validation_and_200(monkeypatch):
    monkeypatch.setattr(ref, "make_client", lambda: None)
    c = TestClient(create_app())
    ok = "/options/reference?ticker=NVDA&level=200&direction=above&window_end=2026-10-30&kind=touch"
    r = c.get(ok)
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["reason"] == "MASSIVE_API_KEY not set"
    for q in ("ticker=NVDA&level=200&direction=up&window_end=2026-10-30",
              "ticker=NVDA&level=-5&direction=above&window_end=2026-10-30",
              "ticker=NVDA&level=200&direction=above&window_end=Oct",
              "ticker=NVDA&level=200&direction=above&window_end=2026-10-30&kind=x",
              "ticker=NV%20DA&level=200&direction=above&window_end=2026-10-30"):
        assert c.get(f"/options/reference?{q}").status_code == 422, q


def test_route_with_mocked_massive(monkeypatch):
    fake = FakeMassive()
    monkeypatch.setattr(ref, "make_client", lambda: fake)
    real = ref.reference_for

    async def pinned(*a, **k):
        return await real(*a, **k, now=WED)
    monkeypatch.setattr(rt.ref, "reference_for", pinned)
    r = TestClient(create_app()).get(
        "/options/reference?ticker=XYZ&level=107.5&direction=above&window_end=2026-10-16&kind=touch")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] and body["touch"]["mid"] == pytest.approx(0.76 * G(16), abs=1e-6)
    assert set(body) >= {"finish_beyond", "touch", "expiry", "strikes", "as_of", "session_label", "method_note", "source"}
