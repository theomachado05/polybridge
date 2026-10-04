// Pins the hedge score labels (headline = what the PM signal adds over a static hedge, raw cut and hedge ratio
// secondary) and the replay sidecar alerts on the Bridge screen.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { FitOut } from "../src/lib/api.ts";
import { NO_SIGNAL_TEXT, VS_STATIC_NOTE, fitScoreView, fitSteps, type PipeContext } from "../src/lib/pipeline.ts";
import { priceSubtitle, replayInfo, replayMismatch, replayNotice } from "../src/lib/realBridge.ts";

const ctx: PipeContext = { question: "Will the Fed hike in October?", venues: ["Polymarket"], yes: 30, vol: "1M", ticker: "JPM", held: 400, move: -1, rev: null, brand: null, why: "" };
const hedge: FitOut = {
  event_class: "macro_fed", division: "hedge", family: "macro_fed_hedge", preset_index: 7, params: { k: 2 }, score: 0.057,
  alternatives: [{ family: "equity_delta_bridge", score: -0.012, stats: { hedge_var_reduction: 0.5, hedge_var_reduction_vs_static: -0.012, avg_hedge_ratio: 0.3 } }],
  rationale: "", llm: "rules", ticks_source: "live_history", n_ticks: 1440,
  score_basis: "hedge_var_reduction_vs_static", score_note: "…", score_raw: 0.339, score_vs_static: 0.057, avg_hedge_ratio: 0.18,
};
const tune = (f: FitOut) => fitSteps(f, ctx).find((s) => s.key === "tune")!.text;

describe("hedge score: signal vs a static hedge", () => {
  it("headlines what the signal adds, with raw variance reduction and hedge ratio secondary", () => {
    const v = fitScoreView(hedge);
    assert.equal(v.headline, "signal adds 5.7% vs a static hedge (in-sample replay, 1,440 ticks)");
    assert.equal(v.secondary, "raw variance reduction 33.9% · average hedge ratio 18.0%");
    assert.equal(v.tone, "positive");
    assert.equal(v.noSignal, false);
    assert.equal(v.short, "signal adds 5.7% vs a static hedge");
    assert.match(v.title, /in-sample/);
    assert.match(v.title, /static hedge of the same average size/);
  });
  it("says plainly, in a neutral tone, when the signal adds nothing (zero or negative)", () => {
    for (const vs of [0, -0.031]) {
      const v = fitScoreView({ ...hedge, score: vs, score_vs_static: vs });
      assert.equal(v.headline, `${NO_SIGNAL_TEXT} (in-sample replay, 1,440 ticks)`);
      assert.equal(v.headline.startsWith("the PM signal adds nothing over a static hedge on this history"), true);
      assert.equal(v.tone, "neutral");
      assert.equal(v.noSignal, true);
      assert.equal(v.short, "PM signal adds nothing over a static hedge");
      assert.doesNotMatch(v.headline, /signal adds \d/);
    }
    assert.match(fitScoreView({ ...hedge, score: -0.031, score_vs_static: -0.031 }).secondary!, /^-3\.1% vs static · raw variance reduction 33\.9%/);
  });
  it("never shows a tiny positive edge as 0.0%, and leaves out ticks when there are none", () => {
    assert.equal(fitScoreView({ ...hedge, score: 0.0003, score_vs_static: 0.0003, n_ticks: 0 }).headline, "signal adds <0.1% vs a static hedge, within noise (in-sample replay)");
  });
  it("reads score as vs-static when score_basis says so, even without score_vs_static", () => {
    const v = fitScoreView({ ...hedge, score_vs_static: null, score_raw: null, avg_hedge_ratio: null });
    assert.match(v.headline, /^signal adds 5\.7% vs a static hedge/);
    assert.equal(v.secondary, null);
  });
  it("an unscored hedge pick is not scored, not 'adds nothing'", () => {
    const v = fitScoreView({ ...hedge, score: null, score_basis: null, score_vs_static: null, score_raw: null, avg_hedge_ratio: null });
    assert.equal(v.scored, false);
    assert.equal(v.headline, "not scored on replay");
    assert.match(tune({ ...hedge, score: null, score_basis: null, score_vs_static: null }), /preset #7 · not scored on replay · k=2\. Runners-up: Equity Delta Bridge\./);
  });
  it("opportunity and legacy (pre score_basis) scores keep their own labels", () => {
    assert.equal(fitScoreView({ ...hedge, division: "opportunity", score_basis: "net_pnl_per_drawdown", score: 0.4123, score_vs_static: null }).headline, "0.412 in-sample");
    const legacy = fitScoreView({ division: "hedge", score: 0.85, n_ticks: 721 });
    assert.equal(legacy.headline, "85.0% var. reduction (in-sample replay)");
    assert.equal(legacy.tone, "neutral");
  });
  it("the tune step leads with the vs-static headline, then the raw cut, hedge ratio and runners-up vs static", () => {
    const t = tune(hedge);
    assert.match(t, /^Macro Fed Hedge preset #7 · signal adds 5\.7% vs a static hedge \(in-sample replay, 1,440 ticks\) · raw variance reduction 33\.9% · average hedge ratio 18\.0% · k=2\./);
    assert.match(t, /Runners-up: Equity Delta Bridge -1\.2% vs static\./);
    assert.equal(t.endsWith(VS_STATIC_NOTE), true);
    assert.match(tune({ ...hedge, score: -0.01, score_vs_static: -0.01 }), /preset #7 · the PM signal adds nothing over a static hedge on this history \(in-sample replay, 1,440 ticks\) · -1\.0% vs static/);
  });
});

describe("replay sidecar alerts", () => {
  const fed = { source: "polymarket", id: "2589813", token_id: "tok-yes" };
  const sum = (m: { source?: string | null; id?: string | null; token_id?: string | null } | null, file = "fed.jsonl") => ({ replay_file: file, replay_market: m });

  it("matches on the same venue and either the market id or the token id, like the backend", () => {
    assert.equal(replayMismatch(replayInfo(sum(fed)), "polymarket", "2589813", null), false);
    assert.equal(replayMismatch(replayInfo(sum({ source: "polymarket", id: null, token_id: "tok-yes" })), "polymarket", "2589813", "tok-yes"), false);
    assert.equal(replayMismatch(replayInfo(sum({ source: "polymarket", id: "999", token_id: null })), "polymarket", "2589813", "tok-yes"), true);
    assert.equal(replayMismatch(replayInfo(sum({ source: "kalshi", id: "2589813", token_id: null })), "polymarket", "2589813", null), true);
    assert.equal(replayMismatch(replayInfo(sum(null)), "polymarket", "2589813", null), false);  // unknown: no claim
  });
  it("reports the market as unknown only when the backend says there is no sidecar", () => {
    assert.equal(replayInfo(sum(null))!.known, false);
    assert.equal(replayInfo(sum(fed))!.known, true);
    assert.equal(replayInfo({ replay_file: "fed.jsonl" })!.known, undefined);  // older backend: not reported
    assert.equal(replayInfo(null), null);
  });
  it("warns on another market's recording and names it", () => {
    const n = replayNotice("replay", "replay", replayInfo(sum({ source: "polymarket", id: "4641065", token_id: null }, "iran.jsonl")), fed)!;
    assert.equal(n.tone, "warn");
    assert.match(n.text, /CAUTION: Do not read this replay \(iran\.jsonl\) as data for this question\. It records a different market \(polymarket:4641065\)/);
    assert.equal(priceSubtitle("replay", "polymarket", replayInfo(sum({ source: "polymarket", id: "4641065" })), "2589813").mismatch, true);
  });
  it("notes a recording with no sidecar, a live-to-replay fallback, and stays quiet otherwise", () => {
    const unknown = replayNotice("replay", "replay", replayInfo(sum(null, "mystery.jsonl")), fed)!;
    assert.equal(unknown.tone, "info");
    assert.match(unknown.text, /mystery\.jsonl has no \.meta\.json sidecar/);
    const fb = replayNotice("replay", "live", replayInfo(sum(fed)), fed)!;
    assert.equal(fb.tone, "info");
    assert.equal(fb.text, "The live feed was not available, so this bridge uses the recording fed.jsonl. It records this market (polymarket:2589813).");
    assert.equal(replayNotice("replay", "live", replayInfo({ replay_file: "fed.jsonl" }), fed)!.text, "The live feed was not available, so this bridge uses the recording fed.jsonl.");
    assert.equal(replayNotice("replay", "replay", replayInfo(sum(fed)), fed), null);
    assert.equal(replayNotice("live", "live", replayInfo(sum({ source: "polymarket", id: "1" })), fed), null);
  });
});

it("vs-static below the noise floor is neutral, at or above it is positive", () => {
  assert.equal(fitScoreView({ ...hedge, score: 0.005, score_vs_static: 0.005 }).tone, "neutral");
  assert.equal(fitScoreView({ ...hedge, score: 0.05, score_vs_static: 0.05 }).tone, "positive");
});
