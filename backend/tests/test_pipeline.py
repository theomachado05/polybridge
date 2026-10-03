"""AI fit pipeline (spec section 4). Offline: HTTP is mocked and hedgecore is a fake module."""
from __future__ import annotations

import asyncio
import json
import math
import sys
import types

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import llm as llm_mod
from app.pipeline import service
from app.pipeline.classify import classify
from app.pipeline.engine_adapter import (ENGINE_MANIFEST, FALLBACK_MANIFEST, EngineAdapter, default_preset,
                                         normalize_manifest, preset_grid)
from app.pipeline.explain import explain, facts
from app.pipeline.llm import GeminiProvider, LLMError, RulesProvider, parse_json_text, rules_classify
from app.pipeline.shortlist import shortlist
from app.pipeline.ticks import (TickSet, assemble, available_requirements, build_ticks, massive_bars,
                                orient_to_adverse, recorded_bars, replay_points)
from app.pipeline.tune import score_row, tune

FED_ID = "2589813"  # in market_universe.json and replay_index.json
T0 = 1_790_000_000
N_POINTS = 48


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_mod, "gemini_key", lambda: None)


# ---------------------------------------------------------------- fakes

def fallback_manifest() -> dict:
    return json.loads(FALLBACK_MANIFEST.read_text())


def fake_hedgecore(best: tuple[str, int] = ("macro_fed_hedge", 5), catalog_raises: bool = False,
                   grid_raises: bool = False, nan_scores: bool = False) -> types.ModuleType:
    mod = types.ModuleType("hedgecore")
    raw = fallback_manifest()
    raw["version"] = "fake-engine"
    fams = {f["id"]: f for f in normalize_manifest(raw)["families"]}
    mod.calls = []
    mod.ticks = []

    def catalog():
        if catalog_raises:
            raise RuntimeError("broken build")
        return raw

    def replay_grid(family, position, ticks):
        mod.calls.append((family, dict(position), {k: len(v) for k, v in ticks.items()}))
        mod.ticks.append({k: np.array(v, copy=True) for k, v in ticks.items()})
        if grid_raises:
            raise RuntimeError("engine crashed")
        rows = []
        for i, params in enumerate(preset_grid(fams[family])):
            vr = 0.10 + 0.001 * i
            if (family, i) == best:
                vr = 0.90
            if family == "stress_lead_hedge" and i == 0:
                vr = 0.80
            rows.append({"preset_index": i, "params": params, "n_ticks": len(ticks["ts_ns"]), "n_orders": 3 + i,
                         "pnl": 100.0 - i, "fees": 2.0, "max_dd": 50.0,
                         "hedge_var_reduction": float("nan") if nan_scores else vr,
                         "turnover": 1000.0, "p50_ns": 120, "p99_ns": 900})
        return rows

    mod.catalog, mod.replay_grid = catalog, replay_grid
    return mod


def gemini_payload(obj) -> dict:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}


def history(n: int = N_POINTS) -> list[dict]:
    return [{"t": T0 + 3600 * i, "p": round(0.2 + 0.4 * (i % 12) / 12, 4)} for i in range(n)]


class Router:
    """httpx.MockTransport handler that records requests; per-host behaviour is configurable."""

    def __init__(self, gemini=None, prices=None, gamma=None, kalshi_market=None, kalshi_event=None, candles=None):
        self.requests: list[httpx.Request] = []
        self.gemini, self.prices, self.gamma = gemini, prices, gamma
        self.kalshi_market, self.kalshi_event, self.candles = kalshi_market, kalshi_event, candles

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "generativelanguage.googleapis.com":
            g = self.gemini
            if g is None:
                return httpx.Response(500)
            if isinstance(g, Exception):
                raise g
            return g(request) if callable(g) else httpx.Response(200, json=g)
        if host == "clob.polymarket.com" and path == "/prices-history":
            if self.prices is None:
                return httpx.Response(503)
            return httpx.Response(200, json={"history": self.prices})
        if host == "gamma-api.polymarket.com" and path.startswith("/markets/"):
            if self.gamma is None:
                return httpx.Response(503)
            return httpx.Response(200, json=self.gamma)
        if host == "api.elections.kalshi.com":
            if path.endswith("/candlesticks"):
                return httpx.Response(503) if self.candles is None else httpx.Response(200, json={"candlesticks": self.candles})
            if path.startswith("/trade-api/v2/markets/"):
                return httpx.Response(503) if self.kalshi_market is None else httpx.Response(200, json={"market": self.kalshi_market})
            if path.startswith("/trade-api/v2/events/"):
                return httpx.Response(503) if self.kalshi_event is None else httpx.Response(200, json={"event": self.kalshi_event})
        return httpx.Response(404)


def candles(n: int = N_POINTS) -> list[dict]:
    out = []
    for i in range(n):
        bid, ask = 0.30 + 0.002 * i, 0.34 + 0.002 * i
        c = {"end_period_ts": T0 + 3600 * i, "yes_bid": {"close_dollars": f"{bid:.4f}"},
             "yes_ask": {"close_dollars": f"{ask:.4f}"}, "price": {"previous_dollars": "0.3000"}}
        if i == 3:
            c["yes_ask"] = {}  # empty ask side
        if i == 4:
            c["yes_bid"], c["yes_ask"] = {"close": 40}, {"close": 35}  # legacy cents, crossed -> both sides untrusted
        out.append(c)
    return out


def mock_http(router: Router) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(router))


class FakeMassive:
    """Massive aggregates with realistic semantics: ``t`` (ms) is the START of the bar window.

    Hourly bar i covers [T0 - 1800 + 3600 i, T0 + 1800 + 3600 i), so tick i (at T0 + 3600 i) sits in the middle of
    bar i's window and may only see bar i-1's close. ``hourly=False`` returns no hourly bars (daily fallback)."""

    def __init__(self, fail: bool = False, hourly: bool = True, daily: list[dict] | None = None):
        self.fail, self.paths, self.hourly, self.daily = fail, [], hourly, daily or []

    def get_all(self, path, params=None, max_pages=500):
        self.paths.append(path)
        if self.fail:
            raise RuntimeError("massive down")
        if "/range/1/hour/" in path:
            return [{"t": (T0 - 1800 + 3600 * i) * 1000, "c": 500.0 - i} for i in range(N_POINTS)] if self.hourly else []
        return self.daily


def pinned_adapter(module=None, library: str = "real") -> EngineAdapter:
    """An adapter whose manifest source is pinned, so a test never depends on which files happen to exist.

    library="real": the committed engine/hedgecore/manifest.json (generated from the compiled catalog; authoritative)
    library="fallback": the hand-written app/data/manifest_fallback.json (as on a checkout without the engine manifest)
    A ``module`` (fake or real hedgecore) still wins over both, as in production."""
    if library == "fallback":
        return EngineAdapter(module=module, engine_manifest=FALLBACK_MANIFEST.parent / "no-such-manifest.json")
    assert ENGINE_MANIFEST.is_file(), "the committed engine manifest is missing"
    return EngineAdapter(module=module, engine_manifest=ENGINE_MANIFEST)


@pytest.fixture(params=["real", "fallback"])
def library(request) -> str:
    """Runs a test once against the real catalog manifest and once against the fallback: behavior must agree."""
    return request.param


def make_client(*, module=None, router: Router | None = None, massive=None, offline=False, provider=None,
                library: str = "real"):
    app = create_app()
    app.state.pipeline_adapter = pinned_adapter(module, library)
    app.state.massive = massive
    app.state.pipeline_offline = offline
    if provider is not None:
        app.state.pipeline_provider = provider
    if router is not None:
        app.state.http = mock_http(router)
    return TestClient(app)


# ---------------------------------------------------------------- classify

def test_rules_classify_examples():
    assert rules_classify("Will the Fed increase interest rates by 25 bps after the October 2026 meeting?") == "macro_fed"
    assert rules_classify("2026 Balance of Power: R Senate, R House") == "elections"
    assert rules_classify("Will Trump raise tariffs on Chinese imports to 60%?") == "tariffs_trade"
    assert rules_classify("Will Israel strike Iran before November?") == "geopolitics_energy"
    assert rules_classify("Will 30-year mortgage rates fall below 6%?") == "housing"
    assert rules_classify("Will another regional bank fail in 2026?") == "fig"
    assert rules_classify("Will Indiana enact a data center moratorium by December 31, 2027?") == "tech_regulation"
    assert rules_classify("Will Bitcoin hit $150k in 2026?") == "crypto"
    assert rules_classify("Will Intel announce layoffs and cut its dividend?") == "corporate_8k"
    assert rules_classify("Will Real Madrid win the Champions League?") == "unsupported"
    assert rules_classify("") == "unsupported"


def test_classify_without_key_uses_rules():
    cls, used = run(classify("Will the Fed cut rates?", RulesProvider()))
    assert (cls, used) == ("macro_fed", "rules")


def test_classify_falls_back_when_gemini_errors():
    r = Router(gemini=None)  # HTTP 500
    p = GeminiProvider("k", http=mock_http(r))
    cls, used = run(classify("Will the Fed cut rates in December?", p))
    assert (cls, used) == ("macro_fed", "rules")
    assert len(r.requests) == 1


def test_classify_falls_back_on_gemini_timeout():
    r = Router(gemini=httpx.ReadTimeout("slow"))
    p = GeminiProvider("k", http=mock_http(r))
    cls, used = run(classify("Will Bitcoin hit $150k?", p))
    assert (cls, used) == ("crypto", "rules")


def test_gemini_timeout_is_8_seconds_and_wall_clock_bounded():
    seen = {}

    def slow(request):
        seen["timeout"] = request.extensions.get("timeout")
        raise httpx.ConnectTimeout("no route")

    p = GeminiProvider("k", http=mock_http(Router(gemini=slow)))
    assert p.timeout_s == 8.0
    with pytest.raises(LLMError):
        run(p.classify("Will the Fed cut?", ["macro_fed", "unsupported"]))
    assert seen["timeout"]["read"] == 8.0


def test_gemini_classify_parses_json_and_sends_json_mode(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    r = Router(gemini=gemini_payload({"event_class": "housing"}))
    p = GeminiProvider("secret-key", http=mock_http(r))
    cls, used = run(classify("Will home prices fall?", p, ["housing", "macro_fed", "unsupported"]))
    assert (cls, used) == ("housing", "gemini")
    req = r.requests[0]
    assert req.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert "secret-key" not in str(req.url)
    assert req.headers["x-goog-api-key"] == "secret-key"
    body = json.loads(req.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["properties"]["event_class"]["enum"] == ["housing", "macro_fed", "unsupported"]


def test_gemini_model_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    r = Router(gemini=gemini_payload({"event_class": "crypto"}))
    run(GeminiProvider("k", http=mock_http(r)).classify("btc?", ["crypto", "unsupported"]))
    assert "gemini-test-model:generateContent" in r.requests[0].url.path


@pytest.mark.parametrize("payload", [
    gemini_payload({"event_class": "sports"}),           # outside the allowed set
    gemini_payload("not json at all"),                   # malformed JSON text
    gemini_payload(["macro_fed"]),                       # JSON but not an object
    {"candidates": []},                                  # no text
    {"error": {"code": 400}},
])
def test_gemini_bad_answers_fall_back_to_rules(payload):
    p = GeminiProvider("k", http=mock_http(Router(gemini=payload)))
    cls, used = run(classify("Will the Fed hike rates?", p))
    assert (cls, used) == ("macro_fed", "rules")


def test_parse_json_text_tolerates_fence():
    assert parse_json_text('```json\n{"event_class": "fig"}\n```') == {"event_class": "fig"}
    with pytest.raises(LLMError):
        parse_json_text("{bad")


def test_gemini_explain_uses_only_structured_facts_and_trims_to_three_sentences():
    r = Router(gemini=gemini_payload({"rationale": "One. Two. Three. Four."}))
    p = GeminiProvider("k", http=mock_http(r))
    result = {"event_class": "macro_fed", "division": "hedge", "family": "macro_fed_hedge", "preset_index": 3,
              "params": {"beta": 1.0}, "score": None, "scored": False, "alternatives": [{"family": "x", "score": None,
              "preset_index": 1, "params": {"a": 1.0}, "stats": {"pnl": 5.0}}], "secret_internal": "do not send"}
    text, by_llm = run(explain(result, p))
    assert (text, by_llm) == ("One. Two. Three.", True)
    sent = json.loads(r.requests[0].content)["contents"][0]["parts"][0]["text"]
    assert "do not send" not in sent and "stats" not in sent
    assert facts(result)["alternatives"] == [{"family": "x", "preset_index": 1, "score": None}]


def test_explain_falls_back_to_template_when_gemini_fails():
    p = GeminiProvider("k", http=mock_http(Router(gemini=None)))
    result = {"event_class": "fig", "division": "hedge", "family": "fig_stress", "preset_index": 2,
              "params": {"convexity": 1.5}, "score": None, "scored": False, "n_shortlisted": 4, "ticker": "KRE",
              "unscored_reason": "the compiled hedgecore engine is not available on this server", "alternatives": []}
    text, by_llm = run(explain(result, p))
    assert not by_llm
    assert "fig_stress" in text and "without a replay score" in text


# ---------------------------------------------------------------- library / adapter

def test_library_fallback_when_no_engine_and_no_manifest(tmp_path):
    a = EngineAdapter(module=None, engine_manifest=tmp_path / "missing.json")
    m, src = a.library()
    assert src == "fallback" and not a.can_score
    ids = {f["id"] for f in m["families"]}
    assert {"equity_delta_bridge", "housing_rates", "eightk_opportunity", "poly_kalshi_spread"} <= ids
    assert len(ids) == 16
    assert m["total_presets"] == sum(f["preset_count"] for f in m["families"])
    assert m["event_classes"][-1] == "unsupported"
    pk = next(f for f in m["families"] if f["id"] == "poly_kalshi_spread")
    assert pk["divisions"] == ["hedge", "opportunity"]


def test_library_prefers_manifest_file_over_fallback(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"families": {"x_algo": {"division": "hedge/opp", "event_classes": ["fig"],
                                                      "params": {"a": [1, 2, 3], "b": {"grid": [0.5, 1]}}}}}))
    m, src = EngineAdapter(module=None, engine_manifest=p).library()
    assert src == "manifest_file"
    f = m["families"][0]
    assert f["id"] == "x_algo" and f["preset_count"] == 6 and f["divisions"] == ["hedge", "opportunity"]
    assert m["total_presets"] == 6


def test_library_from_engine_and_broken_catalog_degrades(tmp_path):
    m, src = EngineAdapter(module=fake_hedgecore()).library()
    assert src == "engine" and m["version"] == "fake-engine"
    a = EngineAdapter(module=fake_hedgecore(catalog_raises=True), engine_manifest=tmp_path / "none.json")
    assert a.library()[1] == "fallback"


def test_adapter_imports_hedgecore_when_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "hedgecore", fake_hedgecore())
    a = EngineAdapter()
    assert a.can_score and a.library()[1] == "engine"


def test_module_without_replay_grid_cannot_score():
    mod = types.ModuleType("hedgecore")
    mod.Engine = object  # today's binding: Engine only
    a = EngineAdapter(module=mod)
    assert not a.can_score and a.replay_grid("equity_delta_bridge", {}, {}) is None


def test_get_library_route():
    c = make_client(module=None)
    j = c.get("/library").json()
    assert j["source"] in ("fallback", "manifest_file") and j["can_score"] is False and j["families"]
    j = make_client(module=fake_hedgecore()).get("/library").json()
    assert j["source"] == "engine" and j["can_score"] is True


def test_default_preset_is_middle_of_grid_row_major():
    fam = {"params": [{"name": "a", "grid": [1, 2, 3]}, {"name": "b", "grid": [10, 20, 30, 40]}]}
    idx, params = default_preset(fam)
    assert params == {"a": 2, "b": 20}
    assert preset_grid(fam)[idx] == params


# ---------------------------------------------------------------- shortlist

def test_shortlist_by_class_puts_specific_families_first():
    m = normalize_manifest(fallback_manifest())
    s = shortlist(m, "housing")
    hedge = [f["id"] for f in s["hedge"]]
    assert hedge[0] == "housing_rates"
    assert "equity_delta_bridge" in hedge and "fig_stress" not in hedge and "macro_fed_hedge" not in hedge
    opp = [f["id"] for f in s["opportunity"]]
    assert "no_bid_seller" in opp and "eightk_opportunity" not in opp
    macro = [f["id"] for f in shortlist(m, "macro_fed")["hedge"]]
    assert macro[:2] == ["macro_fed_hedge", "stress_lead_hedge"]
    assert "eightk_opportunity" in [f["id"] for f in shortlist(m, "corporate_8k")["opportunity"]]


def test_shortlist_unsupported_is_empty_and_requirements_demote():
    m = normalize_manifest(fallback_manifest())
    assert shortlist(m, "unsupported") == {"hedge": [], "opportunity": []}
    opp = [f["id"] for f in shortlist(m, "crypto", available=set())["opportunity"]]
    assert opp[0] == "no_bid_seller"  # options/second-venue families go last when unmet
    assert opp.index("poly_kalshi_spread") > opp.index("no_bid_seller")


# ---------------------------------------------------------------- ticks

def test_assemble_never_invents_depth_and_joins_on_known_time():
    pts = [(100, 0.3), (200, 0.4), (300, 0.5)]
    bars = [(150, 10.0), (250, 11.0)]  # (time the close became known, close)
    t = assemble(pts, bars)
    assert set(len(v) for v in t.values()) == {3}
    for side in ("bid", "ask"):
        for kind in ("px", "qty"):
            for i in range(5):
                assert np.isnan(t[f"{side}_{kind}_{i}"]).all()
    assert np.isnan(t["under_px"][0]) and t["under_px"][1] == 10.0 and t["under_px"][2] == 11.0
    assert np.isnan(t["under_bid"]).all() and np.isnan(t["opt_implied_prob"]).all()
    assert t["ts_ns"][0] == 100 * 10**9 and t["ts_ns"].dtype == np.int64
    assert list(t["yes_bid"]) == [0.3, 0.4, 0.5] and math.isclose(t["no_ask"][0], 0.7)


def test_hourly_bar_close_is_only_seen_after_the_bar_ends():
    fm = FakeMassive()
    bars = massive_bars(fm, "SPY", T0, T0 + 3600 * N_POINTS)
    assert bars[0] == (T0 + 1800, 500.0)  # bar 0 starts at T0 - 1800, its close is known an hour later
    pts = [(T0 + 3600 * i, 0.5) for i in range(N_POINTS)]
    under = assemble(pts, bars)["under_px"]
    assert np.isnan(under[0])  # tick 0 is inside bar 0's window: no finished bar yet
    for i in range(1, N_POINTS):  # tick i is inside bar i's window -> bar i-1's close, never bar i's
        assert under[i] == 500.0 - (i - 1)
    # A tick exactly at a bar's end sees that bar; one second earlier it does not.
    end0 = T0 + 1800
    assert assemble([(end0 - 1, 0.5), (end0, 0.5)], bars)["under_px"][1] == 500.0
    assert np.isnan(assemble([(end0 - 1, 0.5)], bars)["under_px"][0])


def test_daily_bars_never_leak_the_same_session_close():
    # 2026-09-28 and 09-29 sessions; Massive daily t = midnight ET (04:00 UTC in EDT).
    d28, d29 = 1790568000, 1790654400
    fm = FakeMassive(hourly=False, daily=[{"t": d28 * 1000, "c": 100.0}, {"t": d29 * 1000, "c": 105.0}])
    bars = massive_bars(fm, "SPY", d28, d29 + 86400)
    assert any("/range/1/day/" in x for x in fm.paths)
    ten_am_29 = d29 + 10 * 3600  # 10:00 ET on 09-29: day 29's 16:00 close is not known yet
    eight_pm_29 = d29 + 20 * 3600
    next_morning = d29 + 86400 + 10 * 3600
    u = assemble([(ten_am_29, 0.5), (eight_pm_29, 0.5), (next_morning, 0.5)], bars)["under_px"]
    assert list(u) == [100.0, 100.0, 105.0]


def test_recorded_bars_use_bar_end(tmp_path):
    (tmp_path / "equity_bars").mkdir()
    (tmp_path / "equity_bars" / "SPY.json").write_text(json.dumps(
        {"ticker": "SPY", "span_s": 3600, "bars": [{"t": 1000, "c": 1.0}, {"t": 4600, "c": 2.0}]}))
    assert recorded_bars("spy", tmp_path) == [(4600, 1.0), (8200, 2.0)]
    (tmp_path / "equity_bars" / "QQQ.json").write_text(json.dumps([{"t": 0, "c": 3.0}]))
    assert recorded_bars("QQQ", tmp_path) == [(86400, 3.0)]  # no span: conservative one day


def test_orient_to_adverse_swaps_yes_and_no_for_up_on_yes():
    t = assemble([(1, 0.3), (2, 0.4)])
    assert orient_to_adverse(t, "down_on_yes") is t
    o = orient_to_adverse(t, "up_on_yes")
    assert np.allclose(o["yes_bid"], [0.7, 0.6]) and np.allclose(o["no_ask"], [0.3, 0.4])
    assert np.isnan(o["bid_px_0"]).all() and np.isnan(o["ask_qty_4"]).all()  # NaN depth stays NaN
    assert np.allclose(t["yes_bid"], [0.3, 0.4])  # input untouched
    t["ask_px_0"][:] = [0.32, 0.42]
    t["ask_qty_0"][:] = [50, 60]
    t["p_other_venue"][:] = [0.31, 0.41]
    o = orient_to_adverse(t, "up_on_yes")
    assert np.allclose(o["bid_px_0"], [0.68, 0.58]) and list(o["bid_qty_0"]) == [50, 60]
    assert np.allclose(o["p_other_venue"], [0.69, 0.59])


def test_available_requirements_from_ticks():
    t = assemble([(1, 0.3), (2, 0.4)])
    assert available_requirements(TickSet(t, "live_history", 2)) == set()
    t["p_other_venue"][1] = 0.38
    assert available_requirements(TickSet(t, "live_history", 2)) == {"both_venues"}
    assert available_requirements(TickSet(None, "none")) == set()


def test_replay_points_from_index():
    pts, name = replay_points("polymarket", FED_ID)
    assert name == "fed-hike-25bps-oct-2026-history.jsonl" and len(pts) > 700
    assert replay_points("polymarket", "../../etc/passwd") == ([], None)


def test_build_ticks_live_history_resolves_token_and_aligns_bars():
    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES", "tokNO"]', "question": "q"})
    fm = FakeMassive()
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(r), massive=lambda: fm))
    assert ts.source == "live_history" and ts.n == N_POINTS and ts.has_underlying and ts.token_id == "tokYES"
    assert np.isnan(ts.ticks["under_px"][0]) and ts.ticks["under_px"][5] == 500.0 - 4  # previous bar's close
    hist_req = next(q for q in r.requests if q.url.path == "/prices-history")
    assert hist_req.url.params["market"] == "tokYES"
    assert fm.paths and fm.paths[0].startswith("/v2/aggs/ticker/SPY/range/1/hour/")


def test_build_ticks_falls_back_to_replay_then_none():
    r = Router(prices=None, gamma=None)  # every network call fails
    ts = run(build_ticks({"source": "polymarket", "id": FED_ID}, "SPY", http=mock_http(r), massive=lambda: None))
    # the bundled replay plus the bundled recorded SPY bars (app/data/equity_bars/SPY.json)
    assert ts.source == "replay" and ts.n > 700 and ts.has_underlying
    assert any("recorded equity bars for SPY" in n for n in ts.notes)
    ts = run(build_ticks({"source": "polymarket", "id": FED_ID}, "ZZZZ", http=mock_http(r), massive=lambda: None))
    assert ts.source == "replay" and not ts.has_underlying
    ts = run(build_ticks({"source": "polymarket", "id": "nope"}, "SPY", http=mock_http(r), massive=lambda: None))
    assert ts.source == "none" and ts.ticks is None
    ts = run(build_ticks({"source": "kalshi", "id": "KXFED-26OCT-T4.25"}, "SPY", http=mock_http(r)))
    assert ts.source == "none" and any("Kalshi" in n for n in ts.notes)


def test_build_ticks_kalshi_candles_use_real_bid_ask():
    r = Router(kalshi_market={"event_ticker": "KXFED-26OCT", "title": "Fed above 4.25%?"},
               kalshi_event={"series_ticker": "KXFED"}, candles=candles())
    ts = run(build_ticks({"source": "kalshi", "id": "KXFED-26OCT-T4.25"}, "SPY", http=mock_http(r),
                         massive=lambda: FakeMassive()))
    assert ts.source == "live_history" and ts.quote_model == "candle_bid_ask" and ts.n == N_POINTS - 1
    req = next(q for q in r.requests if q.url.path.endswith("/candlesticks"))
    assert req.url.path == "/trade-api/v2/series/KXFED/markets/KXFED-26OCT-T4.25/candlesticks"
    assert req.url.params["period_interval"] == "60"
    t = ts.ticks
    assert (t["venue"] == 1).all() and t["ts_ns"][0] == T0 * 10**9  # stamped at candle END
    assert t["yes_bid"][0] == pytest.approx(0.30) and t["yes_ask"][0] == pytest.approx(0.34)
    assert t["no_bid"][0] == pytest.approx(0.66) and t["no_ask"][0] == pytest.approx(0.70)
    assert t["yes_bid"][3] == pytest.approx(0.306) and np.isnan(t["yes_ask"][3]) and np.isnan(t["no_bid"][3])
    # candle 4 was crossed and had no trade close: dropped entirely, never invented
    assert T0 + 3600 * 4 not in set(t["ts_ns"] // 10**9)
    assert np.isnan(t["bid_px_0"]).all() and ts.has_underlying


def test_kalshi_series_falls_back_to_ticker_prefix():
    r = Router(candles=candles())  # market/event lookups fail
    ts = run(build_ticks({"source": "kalshi", "id": "KXCPI-26SEP-T3.0"}, "SPY", http=mock_http(r)))
    req = next(q for q in r.requests if q.url.path.endswith("/candlesticks"))
    assert "/series/KXCPI/markets/KXCPI-26SEP-T3.0/" in req.url.path and ts.source == "live_history"


def test_fit_resolves_kalshi_question_from_api():
    r = Router(kalshi_market={"event_ticker": "KXFED-26OCT", "title": "Will the Fed cut rates in October?"},
               kalshi_event={"series_ticker": "KXFED"}, candles=candles())
    c = make_client(module=fake_hedgecore(best=("macro_fed_hedge", 3)), router=r, massive=FakeMassive())
    j = c.post("/pipeline/fit", json={"market": {"source": "kalshi", "id": "KXFED-26OCT-T4.25"}, "ticker": "TLT",
                                      "shares_held": 100}).json()
    assert j["event_class"] == "macro_fed" and j["ticks_source"] == "live_history"
    assert (j["family"], j["preset_index"]) == ("macro_fed_hedge", 3)


def test_build_ticks_survives_massive_failure():
    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES"]'})
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "ZZZZ", http=mock_http(r),
                         massive=lambda: FakeMassive(fail=True)))
    assert ts.source == "live_history" and not ts.has_underlying
    assert any("Massive" in n for n in ts.notes)


def test_recorded_bars_cover_the_bundled_fed_replay_without_lookahead():
    pts, _ = replay_points("polymarket", FED_ID)
    bars = recorded_bars("SPY")
    assert bars and bars[0][0] <= pts[0][0]
    under = assemble(pts, bars)["under_px"]
    assert np.isfinite(under).all()
    known = [b[0] for b in bars]
    import bisect
    for (t, _), u in zip(pts, under):  # every tick's price is from a bar that had already ended
        j = bisect.bisect_right(known, t) - 1
        assert known[j] <= t and u == bars[j][1]


def test_record_equity_bars_script(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("record_equity_bars",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "record_equity_bars.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fm = FakeMassive()
    out = tmp_path / "equity_bars"
    assert mod.main(["spy", "--start", str(T0), "--end", str(T0 + 86400), "--out-dir", str(out)], client=fm) == 0
    doc = json.loads((out / "SPY.json").read_text())
    assert doc["span_s"] == 3600 and doc["bars"][0] == {"t": T0 - 1800, "c": 500.0}
    assert recorded_bars("SPY", tmp_path)[0] == (T0 + 1800, 500.0)  # read back joined at bar end
    assert mod.main(["QQQ", "--start", "1", "--end", "2", "--out-dir", str(tmp_path)],
                    client=FakeMassive(hourly=False)) == 1


# ---------------------------------------------------------------- tune

def _ticks(with_under=True) -> TickSet:
    pts = [(T0 + 3600 * i, 0.3 + 0.01 * i) for i in range(N_POINTS)]
    bars = [(T0 - 10 + 3600 * i, 100.0 + i) for i in range(N_POINTS)] if with_under else None
    t = assemble(pts, bars)
    return TickSet(t, "live_history", N_POINTS, has_underlying=with_under)


def test_tune_picks_best_preset_and_top3_alternatives():
    a = EngineAdapter(module=fake_hedgecore(best=("macro_fed_hedge", 5)))
    m, _ = a.library()
    fams = shortlist(m, "macro_fed")["hedge"]
    out = tune(a, fams, "hedge", {"shares_held": 1000.0}, _ticks())
    assert out["scored"] and out["family"] == "macro_fed_hedge" and out["preset_index"] == 5
    assert out["score"] == pytest.approx(0.90)
    assert out["params"] == preset_grid(next(f for f in fams if f["id"] == "macro_fed_hedge"))[5]
    alts = out["alternatives"]
    assert len(alts) == 3 and alts[0]["family"] == "stress_lead_hedge" and alts[0]["score"] == pytest.approx(0.80)
    assert len({x["family"] for x in alts}) == 3 and "macro_fed_hedge" not in {x["family"] for x in alts}
    assert all(x["score"] <= out["score"] for x in alts)


def test_tune_unscored_paths_never_invent_scores():
    fams = shortlist(normalize_manifest(fallback_manifest()), "housing")["hedge"]
    out = tune(EngineAdapter(module=None), fams, "hedge", {"shares_held": 10.0}, _ticks())
    assert not out["scored"] and out["score"] is None and out["family"] == "housing_rates"
    assert all(x["score"] is None for x in out["alternatives"])
    a = EngineAdapter(module=fake_hedgecore(nan_scores=True))
    out = tune(a, fams, "hedge", {"shares_held": 10.0}, _ticks())
    assert not out["scored"] and out["score"] is None and "no defined replay scores" in out["unscored_reason"]
    out = tune(EngineAdapter(module=fake_hedgecore(grid_raises=True)), fams, "hedge", {}, _ticks())
    assert not out["scored"]
    out = tune(EngineAdapter(module=fake_hedgecore()), fams, "hedge", {}, _ticks(with_under=False))
    assert not out["scored"] and "equity prices" in out["unscored_reason"]
    out = tune(EngineAdapter(module=fake_hedgecore()), fams, "hedge", {}, TickSet(None, "none"))
    assert not out["scored"] and "no price history" in out["unscored_reason"]


def test_opportunity_score_is_net_pnl_per_unit_drawdown():
    # replay pnl is already net of fees (engine contract): 100 / 50 = 2.0, fees are not subtracted a second time
    assert score_row({"pnl": 100.0, "fees": 10.0, "max_dd": 50.0}, "opportunity") == pytest.approx(2.0)
    assert score_row({"pnl_net": 30.0, "pnl": 999.0, "max_dd": 0.0}, "opportunity") == pytest.approx(30.0)
    assert score_row({"pnl": float("nan")}, "opportunity") is None
    assert score_row({"hedge_var_reduction": 0.4}, "hedge") == 0.4


def test_opportunity_ranking_does_not_charge_fees_twice():
    """Hand numbers. Engine replay pnl is equity marked at the end with every fee already debited from cash
    (replay.cpp: cash -= side*qty*px*mult + fee; pnl = eq). Family A: pnl 100 net, fees 30, dd 50 -> 100/50 = 2.0.
    Family B: pnl 80 net, fees 0, dd 50 -> 80/50 = 1.6. A wins. Subtracting fees again would score A at
    (100-30)/50 = 1.4 and wrongly pick B."""
    class Hand:
        can_score = True

        def replay_grid(self, family_id, position, ticks):
            pnl, fees = {"fam_a": (100.0, 30.0), "fam_b": (80.0, 0.0)}[family_id]
            return [{"preset_index": 0, "params": {}, "n_orders": 4, "pnl": pnl, "fees": fees, "max_dd": 50.0}]

    out = tune(Hand(), [{"id": "fam_b"}, {"id": "fam_a"}], "opportunity", {"option": 0.0}, _ticks())
    assert out["scored"] and out["family"] == "fam_a" and out["score"] == pytest.approx(2.0)
    assert out["alternatives"][0]["family"] == "fam_b" and out["alternatives"][0]["score"] == pytest.approx(1.6)
    assert out["stats"]["fees"] == 30.0  # still reported for display


# ---------------------------------------------------------------- POST /pipeline/fit

RESPONSE_KEYS = {"event_class", "division", "family", "preset_index", "params", "score", "alternatives", "rationale",
                 "llm", "ticks_source", "n_ticks"}  # exactly spec §4


def test_fit_scored_end_to_end_with_fake_engine_and_mocked_http():
    eng = fake_hedgecore(best=("macro_fed_hedge", 7))
    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES"]'})
    c = make_client(module=eng, router=r, massive=FakeMassive())
    resp = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": FED_ID}, "ticker": "spy",
                                         "shares_held": 1200, "direction": "up_on_yes"})
    assert resp.status_code == 200
    j = resp.json()
    assert set(j) == RESPONSE_KEYS
    assert j["event_class"] == "macro_fed" and j["division"] == "hedge" and j["llm"] == "rules"
    assert (j["family"], j["preset_index"]) == ("macro_fed_hedge", 7)
    assert j["score"] == pytest.approx(0.9)
    assert j["ticks_source"] == "live_history" and j["n_ticks"] == N_POINTS
    assert len(j["alternatives"]) == 3 and "SPY" in j["rationale"]
    fam, position, lens = eng.calls[0]
    assert position["shares_held"] == 1200.0 and "direction" not in position  # §3.3 fields only
    assert set(position) == {"shares_held", "equity", "pred_yes", "pred_no", "option"}
    assert lens["bid_px_0"] == N_POINTS and lens["under_px"] == N_POINTS
    # up_on_yes: the engine sees YES re-oriented to the adverse outcome (1 - p)
    assert np.allclose(eng.ticks[0]["yes_bid"], [1 - h["p"] for h in history()])
    assert not {f for f, _, _ in eng.calls} & {"poly_kalshi_spread"}  # no second venue -> not replayed


def _trend_engine():
    """Fake engine whose best preset depends on the YES series it is given: preset 0 when YES (the adverse
    outcome) is mostly cheap, preset 1 when it is mostly dear. Used to prove the direction changes the fit."""
    mod = fake_hedgecore()
    base = mod.replay_grid

    def replay_grid(family, position, ticks):
        rows = base(family, position, ticks)
        dear = float(np.nanmean(ticks["yes_bid"])) > 0.5
        for r in rows:
            r["hedge_var_reduction"] = 0.01
            if family == "macro_fed_hedge" and r["preset_index"] == (1 if dear else 0):
                r["hedge_var_reduction"] = 0.95
        return rows

    mod.replay_grid = replay_grid
    return mod


def test_direction_changes_the_fit():
    body = {"market": {"source": "polymarket", "id": FED_ID}, "ticker": "SPY", "shares_held": 100}
    picks = {}
    for d in ("down_on_yes", "up_on_yes"):
        r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES"]'})
        c = make_client(module=_trend_engine(), router=r, massive=FakeMassive())
        j = c.post("/pipeline/fit", json={**body, "direction": d}).json()
        picks[d] = (j["family"], j["preset_index"])
    assert picks == {"down_on_yes": ("macro_fed_hedge", 0), "up_on_yes": ("macro_fed_hedge", 1)}


def test_unresolved_market_question_says_so():
    c = make_client(module=None, offline=True)
    j = c.post("/pipeline/fit", json={"market": {"source": "kalshi", "id": "KXUNKNOWN-99"}, "ticker": "SPY",
                                      "shares_held": 10}).json()
    assert j["family"] is None and j["event_class"] == "unsupported"
    assert "could not be resolved" in j["rationale"] and "outside every supported" not in j["rationale"]


def test_unmet_requirement_families_are_left_out(library):
    c = make_client(module=None, offline=True, library=library)
    j = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": FED_ID}, "ticker": "TLT",
                                      "shares_held": 500}).json()
    assert "poly_kalshi_spread" not in {a["family"] for a in j["alternatives"]}
    j = c.post("/pipeline/fit", json={"question": "Will Bitcoin hit $150k in 2026?", "ticker": "COIN"}).json()
    fams = {j["family"]} | {a["family"] for a in j["alternatives"]}
    assert not fams & {"poly_kalshi_spread", "binary_vs_spread_arb", "vol_vs_pm_move"}


def test_fit_cache_is_bounded_and_expires():
    from app.pipeline.router import FitCache
    now = [0.0]
    cache = FitCache(ttl_s=10, max_entries=3, clock=lambda: now[0])
    for i in range(5):
        cache.put(f"k{i}", i)
    assert len(cache) == 3 and cache.get("k0") is None and cache.get("k4") == 4
    cache.get("k2")  # refresh k2, so k3 is the oldest
    cache.put("k5", 5)
    assert cache.get("k3") is None and cache.get("k2") == 2
    now[0] = 11
    assert cache.get("k2") is None and len(cache) == 2


def test_fit_scored_false_without_engine_offline(library):
    c = make_client(module=None, offline=True, library=library)
    j = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": FED_ID}, "ticker": "TLT",
                                      "shares_held": 500}).json()
    assert j["score"] is None
    assert j["family"] == "macro_fed_hedge" and j["ticks_source"] == "replay" and j["n_ticks"] > 700
    assert "without a replay score" in j["rationale"]


def test_fit_unsupported_class():
    c = make_client(module=fake_hedgecore(), offline=True)
    resp = c.post("/pipeline/fit", json={"question": "Who will win the Super Bowl?", "ticker": "NKE"})
    assert resp.status_code == 200
    j = resp.json()
    assert j["event_class"] == "unsupported" and j["family"] is None and j["division"] is None
    assert j["alternatives"] == [] and j["params"] == {} and j["ticks_source"] == "none"


def test_fit_without_shares_uses_opportunity_division(library):
    c = make_client(module=None, offline=True, library=library)
    j = c.post("/pipeline/fit", json={"question": "Will Bitcoin hit $150k in 2026?", "ticker": "COIN"}).json()
    assert j["division"] == "opportunity" and j["family"] == "no_bid_seller" and j["score"] is None


def test_fit_uses_gemini_when_provider_works(library):
    def handler(request):
        body = json.loads(request.content)
        if "event_class" in json.dumps(body["generationConfig"]["responseSchema"]):
            return httpx.Response(200, json=gemini_payload({"event_class": "housing"}))
        return httpx.Response(200, json=gemini_payload({"rationale": "Picked by rules. No replay score."}))

    r = Router(gemini=handler)
    p = GeminiProvider("k", http=mock_http(r))
    c = make_client(module=None, offline=True, provider=p, library=library)
    j = c.post("/pipeline/fit", json={"question": "Will the 30-year mortgage rate fall below 6%?", "ticker": "ITB",
                                      "shares_held": 100}).json()
    assert j["llm"] == "gemini" and j["event_class"] == "housing" and j["family"] == "housing_rates"
    assert j["rationale"] == "Picked by rules. No replay score."


def test_fit_never_500(monkeypatch):
    async def boom(req, deps):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(service, "run_fit", boom)
    c = make_client(module=None, offline=True)
    resp = c.post("/pipeline/fit", json={"question": "Will the Fed cut?", "ticker": "SPY", "shares_held": 1})
    assert resp.status_code == 200
    j = resp.json()
    assert set(j) == RESPONSE_KEYS and j["family"] is None and j["event_class"] == "macro_fed"
    assert "internal error" in j["rationale"]


def test_fit_never_500_with_everything_failing():
    r = Router(gemini=httpx.ReadTimeout("slow"), prices=None, gamma=None)
    c = make_client(module=fake_hedgecore(grid_raises=True), router=r, massive=FakeMassive(fail=True),
                    provider=GeminiProvider("k", http=mock_http(r)))
    resp = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": "999"}, "ticker": "SPY",
                                         "shares_held": 10})
    assert resp.status_code == 200
    j = resp.json()
    assert j["llm"] == "rules" and j["score"] is None and j["ticks_source"] == "none"


@pytest.mark.parametrize("body", [
    {"ticker": "SPY"},                                         # neither market nor question
    {"question": "Fed?", "ticker": ""},
    {"question": "Fed?", "ticker": "SPY", "shares_held": -5},
    {"question": "Fed?", "ticker": "SPY", "direction": "sideways"},
    {"market": {"source": "nyse", "id": "1"}, "ticker": "SPY"},
])
def test_fit_invalid_body_is_422_not_500(body):
    c = make_client(module=None, offline=True)
    assert c.post("/pipeline/fit", json=body).status_code == 422


def test_precomputed_fits_route_and_script(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("precompute_fits",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "precompute_fits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    uni = tmp_path / "u.json"
    uni.write_text(json.dumps({"markets": [
        {"source": "polymarket", "id": FED_ID, "question": "Will the Fed increase interest rates by 25 bps?"},
        {"source": "polymarket", "id": "555", "question": "Will Bitcoin hit $150k?"},
        {"source": "polymarket", "id": "666", "question": "Unmapped market"}]}))
    amap = tmp_path / "m.json"
    amap.write_text(json.dumps({"items": {
        f"polymarket:{FED_ID}": {"mappings": [{"ticker": "TLT", "direction": "down_on_yes"}]},
        "polymarket:555": {"mappings": [{"ticker": "COIN", "direction": "up_on_yes"}]}}}))
    out = tmp_path / "fits.json"
    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES"]'})
    deps = service.Deps(adapter=EngineAdapter(module=fake_hedgecore(best=("crypto_reg_hedge", 2))),
                        provider=RulesProvider(), http=mock_http(r), massive=lambda: FakeMassive())
    res = run(mod.amain(["--out", str(out), "--shares", "100"], deps=deps, universe=uni, ai_map=amap))
    saved = json.loads(out.read_text())
    assert saved["n"] == 2 == res["n"] and saved["library_source"] == "engine" and saved["can_score"] is True
    f = saved["fits"]["polymarket:555"]
    assert (f["family"], f["preset_index"], f["scored"], f["ticker"]) == ("crypto_reg_hedge", 2, True, "COIN")
    assert saved["fits"][f"polymarket:{FED_ID}"]["event_class"] == "macro_fed"
    assert mod.load_jobs(uni, amap, limit=1)[0]["ticker"] == "TLT"
    sm = saved["summary"]
    assert sm["n"] == 2 and sm["scored"] == 2 and sm["ticks_source"] == {"live_history": 2}
    assert sm["fell_back_to_replay"] == [] and sm["no_history"] == [] and sm["timed_out"] == []
    assert saved["provider"] == "rules"

    # offline: the Fed market falls back to its recorded replay, the other has no history; both are listed
    log = tmp_path / "run.log"
    res = run(mod.amain(["--out", str(out), "--offline", "--log", str(log)], universe=uni, ai_map=amap,
                        deps=service.Deps(adapter=EngineAdapter(module=None), offline=True)))
    assert res["summary"]["fell_back_to_replay"] == [f"polymarket:{FED_ID}"]
    assert res["summary"]["no_history"] == ["polymarket:555"] and res["can_score"] is False
    text = log.read_text()
    assert "# summary" in text and f"polymarket:{FED_ID}" in text and "library=" in text

    # a fit that overruns its budget is recorded as unfitted, not retried
    async def slow_fit(req, deps):
        await asyncio.sleep(5)

    mod.fit = slow_fit  # the module was loaded for this test only
    res = run(mod.amain(["--out", str(out), "--offline", "--fit-timeout", "0.05", "--limit", "1"], universe=uni,
                        ai_map=amap, deps=service.Deps(adapter=EngineAdapter(module=None), offline=True)))
    f = res["fits"][f"polymarket:{FED_ID}"]
    assert f["timed_out"] and f["family"] is None and "took over" in f["rationale"]
    assert res["summary"]["timed_out"] == [f"polymarket:{FED_ID}"]

    c = make_client(module=None, offline=True)
    j = c.get("/pipeline/fits").json()
    assert "fits" in j


def test_slow_live_history_falls_back_to_replay_within_budget(monkeypatch, library):
    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"history": history()})

    monkeypatch.setattr(service, "TICKS_BUDGET_S", 0.1)
    c = make_client(module=None, library=library)
    c.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    j = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": FED_ID, "token_id": "tokYES"},
                                      "ticker": "SPY", "shares_held": 5}).json()
    assert j["ticks_source"] == "replay" and j["family"] == "macro_fed_hedge"


# ---------------------------------------------------------------- the real catalog (engine/hedgecore/manifest.json)

def real_manifest() -> dict:
    return normalize_manifest(json.loads(ENGINE_MANIFEST.read_text()))


def test_real_catalog_is_the_library_without_the_module():
    m, src = pinned_adapter(None, "real").library()
    assert src == "manifest_file" and m["total_presets"] == 1278 and len(m["families"]) == 16
    assert sum(f["preset_count"] for f in m["families"]) == 1278
    assert make_client(module=None).get("/library").json()["source"] == "manifest_file"


def test_real_catalog_generic_families_are_not_specific():
    """The compiled catalog spells 'applies to every class' as the full list; those families are generic."""
    fams = {f["id"]: f for f in real_manifest()["families"]}
    generic = {fid for fid, f in fams.items() if f["generic"]}
    assert generic == {"equity_delta_bridge", "book_imbalance_hedge", "poly_kalshi_spread", "no_bid_seller",
                       "binary_vs_spread_arb", "vol_vs_pm_move"}
    sl = shortlist(real_manifest(), "macro_fed")
    # the family built for the class leads; narrower specific families before broader ones, generic ones last
    assert [f["id"] for f in sl["hedge"]][:3] == ["macro_fed_hedge", "fig_stress", "stress_lead_hedge"]
    assert [f["id"] for f in sl["hedge"]][3:5] == ["equity_delta_bridge", "book_imbalance_hedge"]
    assert shortlist(real_manifest(), "housing")["hedge"][0]["id"] == "housing_rates"
    assert shortlist(real_manifest(), "crypto")["hedge"][0]["id"] == "crypto_reg_hedge"


def test_real_catalog_requirements_and_proxies_are_derived():
    fams = {f["id"]: f for f in real_manifest()["families"]}
    assert fams["poly_kalshi_spread"]["requires"] == ["both_venues"]  # CrossVenueGap block
    for fid in ("binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity"):  # option:* instruments
        assert fams[fid]["requires"] == ["listed_options"]
    assert fams["no_bid_seller"]["requires"] == [] and fams["equity_delta_bridge"]["requires"] == []
    assert fams["macro_fed_hedge"]["proxies"] == ["SPY", "IWM", "TLT"]
    assert fams["crypto_reg_hedge"]["proxies"] == ["COIN", "MSTR"]
    assert "proxies" not in fams["election_hedge"]  # 'etf:sector' is a placeholder, not a ticker
    # the fallback manifest declares its own requires; derivation never overrides a declared list
    fb = {f["id"]: f for f in normalize_manifest(fallback_manifest())["families"]}
    assert fb["poly_kalshi_spread"]["requires"] == ["both_venues"]


def test_real_catalog_default_preset_uses_declared_defaults():
    fams = {f["id"]: f for f in real_manifest()["families"]}
    idx, params = default_preset(fams["equity_delta_bridge"])
    assert params == {"coverage": 0.5, "band_shares": 10.0, "sigma_k": 1.0, "fee_ratio": 1.0, "impact": 0.03,
                      "session": 0.0, "wash_guard": 0.0}
    assert preset_grid(fams["equity_delta_bridge"])[idx] == params
    for f in fams.values():  # every family: the index points at its declared defaults
        idx, params = default_preset(f)
        assert preset_grid(f)[idx] == params == {p["name"]: p["default"] for p in f["params"]}


def test_real_catalog_rules_pick_for_each_supported_class():
    """Unscored picks (no engine): every supported class gets its dedicated hedge family when shares are held."""
    want = {"macro_fed": "macro_fed_hedge", "housing": "housing_rates", "fig": "fig_stress",
            "elections": "election_hedge", "tariffs_trade": "tariff_trade_hedge",
            "geopolitics_energy": "energy_geo_hedge", "crypto": "crypto_reg_hedge",
            "tech_regulation": "tech_reg_hedge", "corporate_8k": "equity_delta_bridge",
            "company_specific": "tech_reg_hedge"}
    m = real_manifest()
    for ec, fid in want.items():
        assert shortlist(m, ec)["hedge"][0]["id"] == fid, ec
