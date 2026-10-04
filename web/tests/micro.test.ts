import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  actionPlan, approveEnabled, forwardLine, hasRangeAndSample, latencyLine, latencyView, mechanismById, mechanismFor, numberView, pairGapText,
  mechanismForResult, pairState, recorderLine, rungsInOrder, statusTag, statusTone, ticketActions, ticketGap, ticketReference, ticketStrikes,
  touchProposal, forwardCount, engineLine,
  type EvNumber, type ForwardStatus, type Ladder, type LadderPair, type Mechanism, type Registry, type Ticket, sortTickets,
} from "../src/lib/micro.ts";
import { SCREENS, SCREEN_PATH, FIT_PATH, voiceDrive } from "../src/lib/voiceDrive.ts";
import { evidenceGate, fitAckCopy, fitEvidenceGate } from "../src/lib/risk.ts";

const ROOT = new URL("..", import.meta.url).pathname;
const REPO = join(ROOT, "..");

const num = (o: Partial<EvNumber> = {}): EvNumber => ({
  label: "Fresh ladders, year parsed correctly: net per trade", value: 8.82, unit: "points per contract", ci_low: 6.73, ci_high: 11.13,
  range_kind: "95% interval over dates", sample: { n: 562, units: "trades", also: [{ n: 211, units: "dates" }] },
  result_file: "research/results/ladder_replay/SUMMARY.md", confirmatory: false, result_file_on_disk: true, ...o,
});
const act = (o: Partial<Mechanism["actions_allowed"]>) => ({ mode: "x", trade: false, proposals: false, requires_approval: false, requires_acknowledgement: false, text: "registry text", ...o });
const mech = (id: string, status: string, status_label: string, a: Partial<Mechanism["actions_allowed"]>, numbers: EvNumber[] = []): Mechanism =>
  ({ id, name: `name of ${id}`, status, status_label, claim: `claim of ${id}`, actions_allowed: act(a), numbers, caveats: [], forward_test: null });

const REG: Registry = {
  source_of_truth: "note/NOTE.md", statuses: {}, forward_tests_start: "2026-10-05",
  contract_types: { ladder_rung: "ladders", touch_ticket: "touch", close_above_ticket: "other", btc_15min: "btc_15min", btc_15m_watch: "btc_15min", other: "other" },
  reference_for: { close_above_ticket: "foundation" }, touch_sell_threshold_points: 5,
  mechanisms: [
    mech("foundation", "CONFIRMED_FOUNDATION", "REG-foundation", { mode: "reference_only", text: "Reference only" }),
    mech("ladders", "LEAD", "REG-lead", { trade: true, proposals: true, requires_approval: true }, [num()]),
    mech("touch", "OPEN_LEAD", "REG-open-lead", { trade: true, proposals: true, requires_approval: true, requires_acknowledgement: true, sell_threshold_points: 5 }),
    mech("ticket_option_hedge", "FAILED", "REG-failed", { text: "Never offered" }),
    mech("btc_15min", "WATCH_ONLY", "REG-watch", { mode: "watch_only" }),
    mech("generic_ai_fit", "UNVALIDATED", "REG-unvalidated", { trade: true, proposals: true, requires_approval: true, requires_acknowledgement: true }),
    mech("other", "NO_TESTED_MECHANISM", "REG-none", {}),
  ],
  system: [num({ label: "Receive to decision, live Polymarket feed (median; range to p99)", value: 39, ci_low: 39, ci_high: 3875.9, unit: "microseconds", range_kind: "percentiles", range_desc: "percentiles of the logged decisions: median (p50) and p99, not a confidence interval", sample: { n: 58610, units: "book-update decisions" } })],
};

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(f) ? [p] : [];
  });
}

describe("labels come from the registry", () => {
  it("statusTag shows the registry's status_label verbatim, and nothing without a registry", () => {
    assert.equal(statusTag(mechanismFor(REG, "ladder_rung"))!.text, "REG-lead");
    assert.equal(statusTag(mechanismFor(REG, "touch_ticket"))!.text, "REG-open-lead");
    assert.equal(statusTag(mechanismFor(null, "touch_ticket")), null);
    assert.equal(statusTag(null), null);
  });
  it("mechanismFor follows the registry's contract_types map, unknown types go to other", () => {
    assert.equal(mechanismFor(REG, "close_above_ticket")!.id, "other");
    assert.equal(mechanismFor(REG, "something new")!.id, "other");
    const remapped = { ...REG, contract_types: { ...REG.contract_types, touch_ticket: "other" } };
    assert.equal(mechanismFor(remapped, "touch_ticket")!.id, "other");
  });
  it("no screen hard-codes a registry status label (read from backend/app/closed/evidence.py)", () => {
    const py = readFileSync(join(REPO, "backend/app/closed/evidence.py"), "utf8");
    const block = /STATUS_LABELS = \{([\s\S]*?)\n\}/.exec(py)?.[1] ?? "";
    const labels = [...block.matchAll(/:\s*"([^"]+)"/g)].map((m) => m[1]);
    assert.ok(labels.length >= 6, "STATUS_LABELS parsed");
    const extra = ["OPEN LEAD", "Open lead", "Watch only", "No tested mechanism", "walk-forward failed"];
    for (const f of walk(join(ROOT, "src"))) {
      const src = readFileSync(f, "utf8");
      for (const l of [...labels, ...extra]) assert.ok(!src.includes(l), `${f} hard-codes "${l}"`);
    }
  });
});

describe("no number without its range and sample", () => {
  it("numberView renders value, range and sample together", () => {
    const v = numberView(num())!;
    assert.equal(v.value, "+8.82 points per contract");
    assert.equal(v.range, "[+6.73, +11.13]");
    assert.equal(v.sample, "n = 562 trades · 211 dates");
    assert.equal(v.source, "research/results/ladder_replay/SUMMARY.md");
  });
  it("a number without a range or a sample is never rendered", () => {
    assert.equal(numberView(num({ ci_low: null })), null);
    assert.equal(numberView(num({ ci_high: null })), null);
    assert.equal(numberView(num({ sample: null })), null);
    assert.equal(numberView(num({ sample: { n: 0, units: "trades" } })), null);
    assert.equal(numberView(num({ sample: { n: 5, units: "" } })), null);
    assert.equal(hasRangeAndSample(num()), true);
  });
  it("negative ranges keep their signs; census counts say there is no interval", () => {
    const v = numberView(num({ value: 2.47, ci_low: -1.14, ci_high: 6.26 }))!;
    assert.equal(v.range, "[−1.14, +6.26]");
    const c = numberView(num({ value: 0, ci_low: 0, ci_high: 0, unit: "violations", sample: { n: 34, units: "date ladders" } }))!;
    assert.equal(c.range, "no interval");
    assert.equal(c.sample, "n = 34 date ladders");
  });
  it("an off-main result file names its branch", () => {
    assert.match(numberView(num({ result_file_on_disk: false, source_branch: "r/live-speed", source_commit: "a6ba327" }))!.sourceNote!, /r\/live-speed @ a6ba327/);
  });
  it("the engine strip's latency carries its range and sample", () => {
    const v = latencyView(REG)!;
    assert.equal(v.value, "median 39 µs");
    assert.equal(v.range, "p99 3.9 ms");
    assert.doesNotMatch(v.range, /[\[\]]/);
    assert.equal(v.sample, "n = 58,610 book-update decisions");
    assert.equal(latencyLine(REG), "receive→decision median 39 µs · p99 3.9 ms · n = 58,610 book updates (live feed, network excluded)");
    assert.equal(latencyLine(REG, true), "receive→decision median 39 µs");
    assert.equal(latencyLine({ ...REG, system: [num({ label: "Receive to decision", range_kind: "ci95" })] }), null);
    assert.equal(latencyView(null), null);
  });
  it("percentiles format as median and p99 everywhere, intervals stay bracketed", () => {
    const p = numberView(num({ value: 12, ci_low: 12, ci_high: 2400, unit: "microseconds", range_kind: "percentiles" }))!;
    assert.equal(p.value, "median 12 µs");
    assert.equal(p.range, "p99 2.4 ms");
    assert.equal(numberView(num({ value: 158, ci_low: 158, ci_high: 158, unit: "nanoseconds per call", range_kind: "none" }))!.range, "no interval");
    assert.equal(numberView(num())!.range, "[+6.73, +11.13]");
  });
  it("recorder line: live with age, stopped with the last update time, none without a heartbeat", () => {
    const base = { label: "", ladders: null, touch: null } as unknown as ForwardStatus;
    const hb = { twins: { age_s: 4 } };
    const iso = "2026-10-04T05:36:00Z";
    const live = recorderLine({ ...base, recorder: { dir: "d", heartbeats: hb, state: "live", age_s: 4, last_update_utc: iso } });
    assert.equal(live.text, "recorder: live · last update 4s ago");
    assert.equal(live.ok, true);
    const t = new Date(iso), pad = (x: number) => String(x).padStart(2, "0");
    const stopped = recorderLine({ ...base, recorder: { dir: "d", heartbeats: hb, state: "stopped", age_s: 9000, last_update_utc: iso } });
    assert.equal(stopped.text, `recorder: stopped (last update ${pad(t.getHours())}:${pad(t.getMinutes())})`);
    assert.equal(stopped.ok, false);
    assert.match(recorderLine({ ...base, recorder: null }).text, /no heartbeat/);
  });
  it("forward ladder line carries the denominator and the gap range with n", () => {
    const fw = { label: "", ladders: { label: "", rule: "", state: "ok", snapshots_taken: 1, latest: { snapshot_utc: "t",
      date_ladders: 34, violations_net_of_fees: { count: 0, of_pairs_with_books: 60, nested: 0, locked_usd: 0 },
      gap_points_to_arb: { n_pairs: 60, median: 10.26, p10: 5.07, p90: 30.26, min: 2.65, max: 94.28 } } },
      touch: { label: "", rule: "", state: "no snapshot yet", snapshots_taken: 0, latest: null }, recorder: null } as ForwardStatus;
    const l = forwardLine(fw, "ladders")!;
    assert.match(l, /0 violations after fees of 60 pairs with books/);
    assert.match(l, /median 10\.26 pts \[p10 5\.07, p90 30\.26\], n = 60 pairs/);
    assert.equal(forwardLine(fw, "touch"), "no snapshot yet");
    assert.equal(recorderLine(fw).ok, false);
  });
  it("snapshots before 2026-10-05 are pre-start checks, labelled and never counted as forward-test snapshots", () => {
    const pre = "pre-start check (not part of the forward test)";
    const fw = { label: "", forward_starts: "2026-10-05", pre_start_label: pre,
      ladders: { label: "", rule: "", state: "ok", snapshots_taken: 0, pre_start_checks: 1, forward_starts: "2026-10-05", pre_start_label: pre,
        latest: { snapshot_utc: "t", phase: pre, date_ladders: 34, violations_net_of_fees: { count: 0, of_pairs_with_books: 60, nested: 0, locked_usd: 0 }, gap_points_to_arb: null } },
      touch: { label: "", rule: "", state: "ok", snapshots_taken: 2, pre_start_checks: 3, forward_starts: "2026-10-05",
        latest: { run_utc: "u", phase: "forward test", markets_listed: 4, eligible_first_weekend: 1, eligible_events: 1 } }, recorder: null } as ForwardStatus;
    assert.equal(forwardCount(fw.ladders), "starts 2026-10-05 · 1 pre-start check (not part of the forward test)");
    assert.equal(forwardCount(fw.touch), "2 snapshots · 3 pre-start checks (not part of the forward test)");
    assert.ok(forwardLine(fw, "ladders")!.startsWith(`${pre}: Latest sweep`));
    assert.ok(forwardLine(fw, "touch")!.startsWith("Latest listing"));
    const src = readFileSync(join(ROOT, "src/components/micro/EngineStrip.tsx"), "utf8");
    assert.ok(src.includes("forwardCount(lad)") && !src.includes("lad.snapshots_taken"));
  });
  it("the What-we-tested page renders numbers only through NumberRow / numberView", () => {
    const src = readFileSync(join(ROOT, "src/app/tested/page.tsx"), "utf8");
    assert.ok(!/\.value\b/.test(src), "tested page must not print n.value directly");
    assert.ok(!/ci_low|ci_high/.test(src));
  });
});

describe("actions follow actions_allowed", () => {
  it("touch tickets: proposals behind the acknowledgement gate", () => {
    const p = actionPlan(mechanismFor(REG, "touch_ticket"));
    assert.deepEqual([p.propose, p.approve, p.acknowledge], [true, true, true]);
    assert.equal(approveEnabled(p, false), false);
    assert.equal(approveEnabled(p, true), true);
  });
  it("ladders: proposal and approval, no acknowledgement", () => {
    const p = actionPlan(mechanismFor(REG, "ladder_rung"));
    assert.deepEqual([p.propose, p.approve, p.acknowledge], [true, true, false]);
    assert.equal(approveEnabled(p, false), true);
  });
  it("close-above (no tested mechanism), Bitcoin watch-only, other and the S25 hedge propose nothing", () => {
    for (const t of ["close_above_ticket", "btc_15min", "other"]) assert.equal(actionPlan(mechanismFor(REG, t)).propose, false, t);
    assert.equal(actionPlan(mechanismById(REG, "ticket_option_hedge")).propose, false);
    assert.equal(actionPlan(null).propose, false);
  });
});

describe("no hedge is offered on a ticket", () => {
  const T: Ticket = { id: "1", question: "Will NVDA hit $200 by Oct 30?", type: "touch_ticket", fields: { underlying: "NVDA", level: 200, direction: "up", window_end: "2026-10-30" },
    linkable: true, reasons: [], best_bid: 0.3, best_ask: 0.34,
    contract: { ok: true, expiry: "2026-10-30", option_type: "call", lower_strike: 195, upper_strike: 200 },
    reference: { available: true, finish_beyond: { mid: 0.12, lo: 0.1, hi: 0.14 }, touch: { mid: 0.24, lo: 0.2, hi: 0.28 }, market_open: false, session_label: "market closed (weekend): Friday's close" } };
  it("ticketActions never carries a hedge, whatever the registry says", () => {
    for (const type of ["touch_ticket", "close_above_ticket", "other"]) assert.equal(ticketActions({ ...T, type }, REG).hedge, false);
    assert.equal(ticketActions(T, null).hedge, false);
  });
  it("the ticket board calls no hedge or order endpoint and has no hedge button", () => {
    const src = readFileSync(join(ROOT, "src/components/micro/TicketBoard.tsx"), "utf8");
    for (const bad of ["getHedgeQuote", "getHedges", "createProposal", "startBridge", "openBridge", "approveProposal"]) assert.ok(!src.includes(bad), bad);
    assert.ok(!/>[^<]*\b[Hh]edge\b[^<]*<\/button>/.test(src), "no hedge button");
  });
  it("the touch ticket uses the touch reference, close-above the finish-beyond one; gap in points with a band", () => {
    assert.equal(ticketReference(T)!.mid, 0.24);
    assert.equal(ticketReference({ ...T, type: "close_above_ticket" })!.mid, 0.12);
    const g = ticketGap(T)!;
    assert.equal(g.mid.toFixed(1), "8.0");
    assert.equal(g.lo.toFixed(1), "2.0");
    assert.equal(g.hi.toFixed(1), "14.0");
    assert.equal(ticketGap({ ...T, best_bid: null }), null);
    assert.equal(ticketGap({ ...T, reference: { available: false, reason: "no key" } }), null);
    assert.equal(ticketStrikes(T.contract), "2026-10-30 · 195 / 200 call spread");
    assert.equal(ticketStrikes({ ok: false, reason: "beyond 45 days" }), "not linked: beyond 45 days");
  });
});

describe("ladder board helpers", () => {
  const pair = (o: Partial<LadderPair>): LadderPair => ({ rich: "a", cheap: "b", rich_date: "2026-10-15", cheap_date: "2026-10-31", nested: true, checks: [], reasons: [],
    bid_rich: 0.4, ask_cheap: 0.38, edge_points: 1.2, violation: true, actionable: true, ...o });
  it("only a nested violation on a valid ladder is actionable", () => {
    assert.equal(pairState(pair({}), true), "actionable");
    assert.equal(pairState(pair({}), false), "violation_not_nested");
    assert.equal(pairState(pair({ nested: false, actionable: false }), true), "violation_not_nested");
    assert.equal(pairState(pair({ violation: false, actionable: false, edge_points: -10.5 }), true), "nested");
    assert.equal(pairState(pair({ violation: false, actionable: false, edge_points: null }), true), "no_book");
  });
  it("gap text: edge after fees, or distance from an arbitrage", () => {
    assert.equal(pairGapText(pair({})), "+1.20 pts after fees");
    assert.equal(pairGapText(pair({ edge_points: -10.5 })), "10.50 pts from an arbitrage");
  });
  it("rungs in date order, undated last", () => {
    const l = { rungs: [{ id: "c", date: null }, { id: "b", date: "2026-12-31" }, { id: "a", date: "2026-10-31" }] } as unknown as Ladder;
    assert.deepEqual(rungsInOrder(l).map((r) => r.id), ["a", "b", "c"]);
  });
});

describe("voice navigation stays consistent", () => {
  it("SCREENS match backend/app/agent/tools.py", () => {
    const py = readFileSync(join(REPO, "backend/app/agent/tools.py"), "utf8");
    const list = /^SCREENS = \[([^\]]*)\]/m.exec(py)?.[1] ?? "";
    assert.deepEqual([...list.matchAll(/"([^"]+)"/g)].map((m) => m[1]), [...SCREENS]);
  });
  it("pipeline opens the ladder board; the generic fit moved to /build/fit", () => {
    assert.equal(SCREEN_PATH.pipeline, "/pipeline");
    assert.equal(FIT_PATH, "/build/fit");
    const d = voiceDrive("navigate", { screen: "pipeline" }, { ok: true, tool: "navigate", summary: "", data: { screen: "pipeline" } });
    assert.equal(d.route, "/pipeline");
    assert.match(d.announcement, /ladder board/);
  });
  it("every screen path has a page", () => {
    for (const p of [...Object.values(SCREEN_PATH), FIT_PATH, "/tested"]) {
      const f = join(ROOT, "src/app", p === "/" ? "" : p.split("?")[0], "page.tsx");
      assert.ok(statSync(f).isFile(), f);
    }
  });
});

describe("review fixes: statuses, BTC watch, touch threshold, fit gate", () => {
  it("the generic fit has its own warn-toned UNVALIDATED status; FAILED stays red for S25", () => {
    assert.equal(statusTone("UNVALIDATED"), "warn");
    assert.equal(statusTone("FAILED"), "down");
    assert.equal(statusTag(mechanismById(REG, "generic_ai_fit"))!.text, "REG-unvalidated");
  });
  it("a 15-minute Bitcoin classifier result reaches the watch-only entry", () => {
    assert.equal(mechanismForResult(REG, { type: "other", mechanism: "btc_15m_watch" })!.id, "btc_15min");
    assert.equal(mechanismForResult(REG, { type: "other" })!.id, "other");
    assert.equal(mechanismForResult(REG, { type: "touch_ticket", mechanism: "touch" })!.id, "touch");
  });
  const T: Ticket = { id: "1", question: "Will NVDA hit $200 by Oct 30?", type: "touch_ticket", fields: {}, linkable: true, reasons: [],
    best_bid: 0.3, best_ask: 0.34, reference: { available: true, finish_beyond: { mid: 0.12, lo: 0.1, hi: 0.14 }, touch: { mid: 0.24, lo: 0.2, hi: 0.28 } },
    engine: { family: "touch_ticket_reference", source: "engine", preset: 0, action: "propose", reason: "proposal", latency_ns: 42 } };
  it("the Draft proposal needs the backend's touch_ticket_reference action to be propose", () => {
    assert.ok(touchProposal(T, REG));
    assert.equal(touchProposal({ ...T, engine: { ...T.engine!, action: "hold", reason: "no_signal" } }, REG), null);
    assert.equal(touchProposal({ ...T, engine: undefined }, REG), null);
    assert.equal(engineLine(T.engine, mechanismById(REG, "touch")), `decided by C++ · touch_ticket_reference #0 · proposal · 42 ns · ${mechanismById(REG, "touch")!.status_label}`);
    assert.match(engineLine({ family: "ladder_pair", source: "python_fallback", action: "hold", reason: "python: no violation" }, null)!, /^decided by the Python fallback \(C\+\+ micro families not compiled\) · ladder_pair/);
    assert.equal(engineLine(undefined, null), null);
  });
  it("a touch proposal needs the bid 5+ points above the touch reference, priced at the bid", () => {
    const p = touchProposal(T, REG)!;
    assert.equal(p.price, 0.3);
    assert.equal(p.gapPoints.toFixed(1), "6.0");
    assert.ok(touchProposal({ ...T, best_bid: 0.29, best_ask: 0.40 }, REG));
    assert.equal(touchProposal({ ...T, best_bid: 0.285, best_ask: 0.40 }, REG), null);
    assert.equal(touchProposal({ ...T, type: "close_above_ticket" }, REG), null);
    const noTh = { ...REG, touch_sell_threshold_points: undefined, mechanisms: REG.mechanisms.map((m) => m.id === "touch" ? { ...m, actions_allowed: { ...m.actions_allowed, sell_threshold_points: undefined } } : m) };
    assert.equal(touchProposal(T, noTh), null);
    assert.equal(touchProposal({ ...T, linkable: false }, REG), null);
  });
  it("the threshold comes from the registry touch entry, and the proposal needs the acknowledgement gate", () => {
    const withTh = (th: number | undefined, extra: Partial<Mechanism["actions_allowed"]> = {}) => ({ ...REG, touch_sell_threshold_points: undefined,
      mechanisms: REG.mechanisms.map((m) => m.id === "touch" ? { ...m, actions_allowed: { ...m.actions_allowed, sell_threshold_points: th, ...extra } } : m) });
    assert.equal(touchProposal(T, withTh(7)), null);
    assert.equal(touchProposal(T, withTh(6))!.threshold, 6);
    assert.equal(touchProposal(T, withTh(5, { requires_acknowledgement: false })), null);
    assert.equal(touchProposal(T, withTh(5, { proposals: false })), null);
  });
  it("the ticket board labels the proposal Sell YES and shows it behind the acknowledgement panel", () => {
    const src = readFileSync(join(ROOT, "src/components/micro/TicketBoard.tsx"), "utf8");
    assert.ok(src.includes("Draft proposal (Sell YES)"));
    assert.ok(src.includes("<ProposalPanel plan={plan}"));
    assert.ok(!/5\s*\+?\s*pts|>= ?5\b|threshold\s*=\s*5/.test(src), "no hard-coded threshold in the board");
  });
  it("the ticket board gates proposals on touchProposal and links close-above rows as reference only", () => {
    const src = readFileSync(join(ROOT, "src/components/micro/TicketBoard.tsx"), "utf8");
    assert.ok(src.includes("touchProposal(t, reg)"));
    assert.ok(!/gap\.mid > 0/.test(src));
    assert.ok(src.includes("reference_for?.close_above_ticket"));
  });
  const fit = mechanismById(REG, "generic_ai_fit");
  it("the fit gate always needs the acknowledgement and shows the fit's registry status, even on a validated market", () => {
    const validated = evidenceGate({ validated: true, status: "validated", evidence: "passed R2" } as never);
    assert.equal(validated.needsAck, false);
    const g = fitEvidenceGate(validated, fit);
    assert.equal(g.needsAck, true);
    assert.equal(g.validated, false);
    assert.equal(g.badge.text, "REG-unvalidated");
    assert.notEqual(g.badge.text, "validated");
    assert.equal(fitEvidenceGate(null, null).needsAck, true);
    assert.ok(fitAckCopy("SPY", fit, validated).includes("REG-unvalidated"));
  });
  it("the fit page never auto-opens a bridge", () => {
    const src = readFileSync(join(ROOT, "src/app/build/fit/page.tsx"), "utf8");
    assert.ok(src.includes("fitEvidenceGate("));
    assert.ok(!src.includes("autoOpen"));
  });
  it("the landing page reads statuses from the registry and makes no out-of-sample claim for the replay", () => {
    const src = readFileSync(join(ROOT, "src/app/page.tsx"), "utf8");
    assert.ok(src.includes("useRegistry()") && src.includes("StatusTag"));
    assert.ok(!/passed the out-of-sample test/.test(src));
    assert.ok(!/best in-sample result/.test(src));
  });
});

describe("micro families: catalog, library and engine strip", () => {
  it("parseLibrary carries the catalog's micro families with their status words", async () => {
    const { parseLibrary } = await import("../src/lib/library.ts");
    const lib = parseLibrary({ families: [{ id: "x", preset_count: 3 }], total_presets: 3, micro_total: 19,
      micro_families: [{ id: "ladder_pair", status: "lead", preset_count: 18, division: "micro/ladder", params: [{ name: "min_edge", grid: [1, 2, 3] }] },
                       { id: "touch_ticket_reference", status: "unvalidated", preset_count: 1 }] } as never)!;
    assert.equal(lib.microTotal, 19);
    assert.deepEqual(lib.micro.map((m) => [m.id, m.status, m.presets]), [["ladder_pair", "lead", 18], ["touch_ticket_reference", "unvalidated", 1]]);
    assert.equal(parseLibrary({ families: [{ id: "x" }] } as never)!.micro.length, 0);
  });
  it("boards and strip show the C++ decision from the API, not local math", () => {
    const strip = readFileSync(join(ROOT, "src/components/micro/EngineStrip.tsx"), "utf8");
    assert.ok(strip.includes("micro_bench") && strip.includes("synthetic tape") && strip.includes("b.sample"));
    assert.ok(readFileSync(join(ROOT, "src/app/pipeline/page.tsx"), "utf8").includes("engineLine(p.engine, mech)"));
    assert.ok(readFileSync(join(ROOT, "src/components/micro/TicketBoard.tsx"), "utf8").includes("engineLine(t.engine, mechanism)"));
    assert.ok(readFileSync(join(ROOT, "src/app/library/page.tsx"), "utf8").includes("lib.micro.map"));
  });
});

describe("ticket board order", () => {
  const tk = (id: string, extra: Record<string, unknown>) => ({ id, question: id, type: "touch_ticket", fields: {}, checks: [], linkable: false, reasons: [], best_bid: 0.5, best_ask: 0.52, ...extra }) as unknown as Ticket;
  const ref = (mid: number) => ({ available: true, touch: { mid, lo: mid - 0.05, hi: mid + 0.05 } });
  it("puts the engine's proposals first, then priced rows by gap, then linked, then the rest", () => {
    const rows = [tk("none", {}), tk("linked", { linkable: true }), tk("small", { linkable: true, reference: ref(0.5) }),
      tk("big", { linkable: true, reference: ref(0.3) }), tk("prop", { linkable: true, reference: ref(0.45), engine: { action: "propose" } })];
    assert.deepEqual(sortTickets(rows).map((t) => t.id), ["prop", "big", "small", "linked", "none"]);
  });
});
