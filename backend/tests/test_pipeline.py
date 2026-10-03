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
from app.pipeline.engine_adapter import (FALLBACK_MANIFEST, EngineAdapter, default_preset, normalize_manifest,
                                         preset_grid)
from app.pipeline.explain import explain, facts
from app.pipeline.llm import GeminiProvider, LLMError, RulesProvider, parse_json_text, rules_classify
from app.pipeline.shortlist import shortlist
from app.pipeline.ticks import TickSet, assemble, build_ticks, replay_points
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

    def catalog():
        if catalog_raises:
            raise RuntimeError("broken build")
        return raw

    def replay_grid(family, position, ticks):
        mod.calls.append((family, dict(position), {k: len(v) for k, v in ticks.items()}))
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

    def __init__(self, gemini=None, prices=None, gamma=None):
        self.requests: list[httpx.Request] = []
        self.gemini, self.prices, self.gamma = gemini, prices, gamma

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
        return httpx.Response(404)


def mock_http(router: Router) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(router))


class FakeMassive:
    def __init__(self, fail: bool = False):
        self.fail, self.paths = fail, []

    def get_all(self, path, params=None, max_pages=500):
        self.paths.append(path)
        if self.fail:
            raise RuntimeError("massive down")
        return [{"t": (T0 - 1800 + 3600 * i) * 1000, "c": 500.0 - i} for i in range(N_POINTS)]


def make_client(*, module=None, router: Router | None = None, massive=None, offline=False, provider=None):
    app = create_app()
    app.state.pipeline_adapter = EngineAdapter(module=module)
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

def test_assemble_never_invents_depth_and_joins_without_lookahead():
    pts = [(100, 0.3), (200, 0.4), (300, 0.5)]
    bars = [(150, 10.0), (250, 11.0)]
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


def test_replay_points_from_index():
    pts, name = replay_points("polymarket", FED_ID)
    assert name == "fed-hike-25bps-oct-2026-history.jsonl" and len(pts) > 700
    assert replay_points("polymarket", "../../etc/passwd") == ([], None)


def test_build_ticks_live_history_resolves_token_and_aligns_bars():
    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES", "tokNO"]', "question": "q"})
    fm = FakeMassive()
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(r), massive=lambda: fm))
    assert ts.source == "live_history" and ts.n == N_POINTS and ts.has_underlying and ts.token_id == "tokYES"
    hist_req = next(q for q in r.requests if q.url.path == "/prices-history")
    assert hist_req.url.params["market"] == "tokYES"
    assert fm.paths and fm.paths[0].startswith("/v2/aggs/ticker/SPY/range/1/hour/")


def test_build_ticks_falls_back_to_replay_then_none():
    r = Router(prices=None, gamma=None)  # every network call fails
    ts = run(build_ticks({"source": "polymarket", "id": FED_ID}, "SPY", http=mock_http(r), massive=lambda: None))
    assert ts.source == "replay" and ts.n > 700 and not ts.has_underlying
    ts = run(build_ticks({"source": "polymarket", "id": "nope"}, "SPY", http=mock_http(r), massive=lambda: None))
    assert ts.source == "none" and ts.ticks is None
    ts = run(build_ticks({"source": "kalshi", "id": "KXFED"}, "SPY", http=None))
    assert ts.source == "none" and any("Kalshi" in n for n in ts.notes)


def test_build_ticks_survives_massive_failure():
    r = Router(prices=history(), gamma={"clobTokenIds": '["tokYES"]'})
    ts = run(build_ticks({"source": "polymarket", "id": "777"}, "SPY", http=mock_http(r),
                         massive=lambda: FakeMassive(fail=True)))
    assert ts.source == "live_history" and not ts.has_underlying
    assert any("Massive" in n for n in ts.notes)


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
    assert score_row({"pnl": 110.0, "fees": 10.0, "max_dd": 50.0}, "opportunity") == pytest.approx(2.0)
    assert score_row({"pnl_net": 30.0, "pnl": 999.0, "max_dd": 0.0}, "opportunity") == pytest.approx(30.0)
    assert score_row({"pnl": float("nan")}, "opportunity") is None
    assert score_row({"hedge_var_reduction": 0.4}, "hedge") == 0.4


# ---------------------------------------------------------------- POST /pipeline/fit

RESPONSE_KEYS = {"event_class", "division", "family", "preset_index", "params", "score", "alternatives", "rationale",
                 "llm", "ticks_source", "n_ticks", "scored"}


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
    assert (j["family"], j["preset_index"], j["scored"]) == ("macro_fed_hedge", 7, True)
    assert j["score"] == pytest.approx(0.9)
    assert j["ticks_source"] == "live_history" and j["n_ticks"] == N_POINTS
    assert len(j["alternatives"]) == 3 and "SPY" in j["rationale"]
    fam, position, lens = eng.calls[0]
    assert position["shares_held"] == 1200.0 and position["direction"] == "up_on_yes"
    assert lens["bid_px_0"] == N_POINTS and lens["under_px"] == N_POINTS


def test_fit_scored_false_without_engine_offline():
    c = make_client(module=None, offline=True)
    j = c.post("/pipeline/fit", json={"market": {"source": "polymarket", "id": FED_ID}, "ticker": "TLT",
                                      "shares_held": 500}).json()
    assert j["scored"] is False and j["score"] is None
    assert j["family"] == "macro_fed_hedge" and j["ticks_source"] == "replay" and j["n_ticks"] > 700
    assert "without a replay score" in j["rationale"]


def test_fit_unsupported_class():
    c = make_client(module=fake_hedgecore(), offline=True)
    resp = c.post("/pipeline/fit", json={"question": "Who will win the Super Bowl?", "ticker": "NKE"})
    assert resp.status_code == 200
    j = resp.json()
    assert j["event_class"] == "unsupported" and j["family"] is None and j["division"] is None
    assert j["alternatives"] == [] and j["params"] == {} and j["ticks_source"] == "none"


def test_fit_without_shares_uses_opportunity_division():
    c = make_client(module=None, offline=True)
    j = c.post("/pipeline/fit", json={"question": "Will Bitcoin hit $150k in 2026?", "ticker": "COIN"}).json()
    assert j["division"] == "opportunity" and j["family"] == "no_bid_seller" and j["scored"] is False


def test_fit_uses_gemini_when_provider_works():
    def handler(request):
        body = json.loads(request.content)
        if "event_class" in json.dumps(body["generationConfig"]["responseSchema"]):
            return httpx.Response(200, json=gemini_payload({"event_class": "housing"}))
        return httpx.Response(200, json=gemini_payload({"rationale": "Picked by rules. No replay score."}))

    r = Router(gemini=handler)
    p = GeminiProvider("k", http=mock_http(r))
    c = make_client(module=None, offline=True, provider=p)
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
    assert j["llm"] == "rules" and j["scored"] is False and j["ticks_source"] == "none"


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

    c = make_client(module=None, offline=True)
    j = c.get("/pipeline/fits").json()
    assert "fits" in j
