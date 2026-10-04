// The two micro-market mechanisms (date ladders, touch tickets) and the evidence registry that labels them.
// Every status, label and allowed action comes from GET /evidence/mechanisms (backend/app/closed/evidence.py); this
// file holds no label text of its own for a mechanism. Pure (no React), so `node --test` covers it offline.

// ---------------------------------------------------------------------------------------------------------- registry

export interface EvSample { n: number; units: string; also?: { n: number; units: string }[] }
export interface EvNumber {
  label: string; value: number; unit?: string; ci_low: number | null; ci_high: number | null; range_kind?: string; range_desc?: string;
  sample?: EvSample | null; result_file?: string; confirmatory?: boolean; note?: string;
  result_file_on_disk?: boolean; source_branch?: string; source_commit?: string;
}
export interface EvActions {
  mode: string; trade: boolean; proposals: boolean; requires_approval: boolean; requires_acknowledgement: boolean; text: string;
  /** touch entry: sell YES only when the bid is this many points above the central touch reference (S21 book B0) */
  sell_threshold_points?: number;
  side?: string; hedge_offered?: boolean;
}
export interface Mechanism {
  id: string; name: string; status: string; status_label: string; claim: string; actions_allowed: EvActions;
  numbers: EvNumber[]; caveats: string[]; forward_test: { file: string; starts: string; method?: string; code?: string } | null;
}
export interface Registry {
  source_of_truth: string; statuses: Record<string, string>; mechanisms: Mechanism[]; system: EvNumber[];
  contract_types: Record<string, string>; forward_tests_start: string;
  /** contract types whose rows show the options reference for information only, and the entry that explains it */
  reference_for?: Record<string, string>;
  /** S21 book B0 / touch_fresh FORWARD.md: sell YES only when the bid is this many points above the touch reference */
  touch_sell_threshold_points?: number;
  /** engine/hedgecore/BENCH.md micro section: on_tick latency per family, with its sample and tape */
  micro_bench?: MicroBench[];
}

export interface MicroBench { family: string; mean_ns: number; step_mean_ns: number; p50_ns: number; p99_ns: number; p999_ns: number; sample: string; tape: string; result_file: string; note?: string }

/** The decision block on a ladder pair or touch ticket: the C++ micro family that decided it (source "engine"), or the
 *  previous Python rule when the compiled module lacks the micro families (source "python_fallback"). */
export interface EngineDecision {
  family: string; source: "engine" | "python_fallback" | string; preset?: number; action: string; reason: string;
  latency_ns?: number; signal_points?: number | null; sizes?: { rich: number; cheap: number }; limit_prices?: { rich: number | null; cheap: number | null };
  qty?: number; limit_px?: number | null;
}

/** "decided by C++ · ladder_pair #4 · entry · 42 ns · Lead" (status words from the registry entry), or the fallback
 *  said plainly. Null without a block: nothing is claimed. */
export function engineLine(e: EngineDecision | null | undefined, m: Mechanism | null | undefined): string | null {
  if (!e) return null;
  const status = m?.status_label ? ` · ${m.status_label}` : "";
  if (e.source !== "engine") return `decided by the Python fallback (C++ micro families not compiled) · ${e.family} · ${e.reason}${status}`;
  const lat = typeof e.latency_ns === "number" ? ` · ${e.latency_ns.toLocaleString("en-US")} ns` : "";
  return `decided by C++ · ${e.family} #${e.preset ?? "?"} · ${e.reason}${lat}${status}`;
}

export type Tone = "up" | "warn" | "down" | "neutral";

/** Tag tone per registry status code. The words shown are always the registry's `status_label`. */
export function statusTone(status: string | null | undefined): Tone {
  switch (status) {
    case "CONFIRMED_FOUNDATION": return "up";
    case "LEAD": case "OPEN_LEAD": case "UNVALIDATED": return "warn";
    case "FAILED": return "down";
    default: return "neutral";
  }
}

export function mechanismById(reg: Registry | null | undefined, id: string): Mechanism | null {
  return reg?.mechanisms.find((m) => m.id === id) ?? null;
}

/** The mechanism behind a classifier contract type (ladder_rung, touch_ticket, close_above_ticket, other), by the
 *  registry's own contract_types map. Unknown types fall to the registry's "other" entry. */
export function mechanismFor(reg: Registry | null | undefined, contractType: string | null | undefined): Mechanism | null {
  if (!reg) return null;
  const id = reg.contract_types[(contractType ?? "other").toLowerCase()] ?? reg.contract_types.other ?? "other";
  return mechanismById(reg, id);
}

/** The mechanism behind a classifier result: its `mechanism` when that is the 15-minute Bitcoin watch (the classifier
 *  gives such a market type "other"), else its type. */
export function mechanismForResult(reg: Registry | null | undefined, res: { type?: string | null; mechanism?: string | null } | null | undefined): Mechanism | null {
  return mechanismFor(reg, res?.mechanism === "btc_15m_watch" ? "btc_15m_watch" : res?.type);
}

/** The status tag for a mechanism: registry words only. Null when the registry is missing (the UI then shows none). */
export function statusTag(m: Mechanism | null | undefined): { text: string; tone: Tone; title: string } | null {
  if (!m || !m.status_label) return null;
  return { text: m.status_label, tone: statusTone(m.status), title: `${m.name}: ${m.claim}` };
}

const fin = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** A number may be shown only with its range and its sample. */
export function hasRangeAndSample(n: EvNumber | null | undefined): boolean {
  return !!n && fin(n.value) && fin(n.ci_low) && fin(n.ci_high) && !!n.sample && fin(n.sample.n) && n.sample.n > 0 && !!n.sample.units;
}

const MINUS = "−";
function dec(x: number): number {
  const a = Math.abs(x);
  if (a === 0 || Number.isInteger(x)) return 0;
  if (a >= 100) return 1;
  if (a >= 1) return 2;
  return 4;
}
export function fmtSigned(x: number, d = dec(x), sign = true): string {
  const s = Math.abs(x).toFixed(d);
  return (x < 0 ? MINUS : sign && x > 0 ? "+" : "") + Number(s).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** A latency in a readable unit: 39 µs, 3.9 ms (input unit "microseconds" or "nanoseconds"); other units are left as is. */
export function fmtDuration(x: number, unit: string | undefined): string | null {
  const u = (unit ?? "").toLowerCase();
  const us = u.startsWith("micro") ? x : u.startsWith("nano") ? x / 1000 : null;
  if (us === null) return null;
  if (us >= 1000) return `${(us / 1000).toLocaleString("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} ms`;
  if (us >= 1) return `${Math.round(us).toLocaleString("en-US")} µs`;
  return `${Math.round(us * 1000)} ns`;
}

export interface NumberView { label: string; value: string; range: string; rangeKind: string; sample: string; source: string; sourceNote: string | null; confirmatory: boolean; note: string | null }

/** One registry number as text: value, range and sample together. Null (never shown) without a range and a sample. */
export function numberView(n: EvNumber): NumberView | null {
  if (!hasRangeAndSample(n)) return null;
  const s0 = n.sample!;
  const sampleText = [`${s0.n.toLocaleString("en-US")} ${s0.units}`, ...(s0.also ?? []).map((a) => `${a.n.toLocaleString("en-US")} ${a.units}`)].join(" · ");
  const off0 = n.result_file_on_disk === false && n.source_branch ? `on branch ${n.source_branch} @ ${n.source_commit ?? "?"}` : null;
  if (n.range_kind === "percentiles") {
    // A distribution, not a confidence interval: ci_low is the median (p50), ci_high the p99. Never bracketed.
    const f = (x: number) => fmtDuration(x, n.unit) ?? `${fmtSigned(x, dec(x), false)}${n.unit ? ` ${n.unit}` : ""}`;
    return {
      label: n.label, value: `median ${f(n.ci_low!)}`, range: `p99 ${f(n.ci_high!)}`,
      rangeKind: n.range_desc ?? "percentiles (median and p99), not a confidence interval",
      sample: `n = ${sampleText}`, source: n.result_file ?? "", sourceNote: off0, confirmatory: !!n.confirmatory, note: n.note ?? null,
    };
  }
  const d = Math.max(dec(n.value), dec(n.ci_low!), dec(n.ci_high!));
  const census = n.ci_low === n.value && n.ci_high === n.value;
  // Differences and returns carry a sign (+0.0108); counts, ratios and timings do not.
  const sign = n.ci_low! < 0 || n.value < 0 || (!census && !/second|ratio/i.test(n.unit ?? ""));
  const unit = n.unit ? ` ${n.unit}` : "";
  const s = n.sample!;
  const sample = [`${s.n.toLocaleString("en-US")} ${s.units}`, ...(s.also ?? []).map((a) => `${a.n.toLocaleString("en-US")} ${a.units}`)].join(" · ");
  const off = n.result_file_on_disk === false && n.source_branch ? `on branch ${n.source_branch} @ ${n.source_commit ?? "?"}` : null;
  return {
    label: n.label,
    value: `${fmtSigned(n.value, d, sign)}${unit}`,
    range: census ? "no interval" : `[${fmtSigned(n.ci_low!, d, sign)}, ${fmtSigned(n.ci_high!, d, sign)}]`,
    rangeKind: n.range_desc ?? n.range_kind ?? "",
    sample: `n = ${sample}`,
    source: n.result_file ?? "",
    sourceNote: off,
    confirmatory: !!n.confirmatory,
    note: n.note ?? null,
  };
}

/** What a mechanism lets the user do, from its actions_allowed. */
export interface ActionPlan { propose: boolean; approve: boolean; acknowledge: boolean; trade: boolean; text: string }
export function actionPlan(m: Mechanism | null | undefined): ActionPlan {
  const a = m?.actions_allowed;
  if (!a || !m || (m.status === "FAILED" && !a.trade)) return { propose: false, approve: false, acknowledge: false, trade: false, text: a?.text ?? "" };
  return { propose: !!a.proposals, approve: !!a.proposals && !!a.requires_approval, acknowledge: !!a.proposals && !!a.requires_acknowledgement, trade: !!a.trade, text: a.text };
}

/** Approve is enabled only when the plan allows it and, where the mechanism needs one, the acknowledgement is ticked. */
export const approveEnabled = (p: ActionPlan, acked: boolean) => p.approve && (!p.acknowledge || acked);

// ------------------------------------------------------------------------------------------------------------ ladders

export interface Check { check: string; ok: boolean; detail?: string | null }
export interface Rung {
  id: string; question: string; date: string | null; year_source?: string | null; year_corrected?: boolean; token?: string | null;
  fee_rate?: number | null; fee_exponent?: number | null; tick?: number | null; best_bid: number | null; best_ask: number | null;
}
export interface LadderPair {
  rich: string; cheap: string; rich_date: string | null; cheap_date: string | null; nested: boolean; checks: Check[]; reasons: string[];
  bid_rich: number | null; ask_cheap: number | null; edge_points: number | null; violation: boolean; actionable: boolean;
  engine?: EngineDecision;
}
export interface Ladder {
  ladder_id: string; event?: string; event_title: string; template?: string; valid: boolean; reasons: string[];
  rungs: Rung[]; pairs: LadderPair[]; unplaced?: unknown[];
}
export interface EvidenceRef { id: string; status: string; status_label: string; trade_mechanism?: boolean }
export interface LaddersOut {
  ok: boolean; stale?: boolean; error: string | null; as_of?: string; events_read?: number; ladders: Ladder[];
  counts?: { ladders: number; pairs: number; nested_pairs: number; violations: number; actionable: number };
  evidence?: EvidenceRef; elapsed_ms?: number;
}

/** Rungs in date order (the backend sends them ordered; undated rungs go last and stay visible). */
export function rungsInOrder(l: Ladder): Rung[] {
  return [...l.rungs].sort((a, b) => (a.date ?? "9999") < (b.date ?? "9999") ? -1 : (a.date ?? "9999") > (b.date ?? "9999") ? 1 : 0);
}

export type PairState = "actionable" | "violation_not_nested" | "nested" | "not_nested" | "no_book";
export function pairState(p: LadderPair, ladderValid: boolean): PairState {
  if (p.actionable && p.violation && p.nested && ladderValid) return "actionable";
  if (p.violation) return "violation_not_nested";
  if (p.edge_points == null) return "no_book";
  return p.nested && ladderValid ? "nested" : "not_nested";
}

/** Points away from an arbitrage (positive) or the edge after fees and a tick (when the rule is broken). */
export function pairGapText(p: LadderPair): string {
  if (p.edge_points == null) return "no two-sided book";
  return p.edge_points > 0 ? `${fmtSigned(p.edge_points, 2)} pts after fees` : `${fmtSigned(-p.edge_points, 2, false)} pts from an arbitrage`;
}

/** Ladders with an actionable pair first, then by most rungs. */
export function sortLadders(ls: Ladder[]): Ladder[] {
  const score = (l: Ladder) => (l.pairs.some((p) => p.actionable) ? 2 : l.pairs.some((p) => p.violation) ? 1 : 0);
  return [...ls].sort((a, b) => score(b) - score(a) || b.rungs.length - a.rungs.length || a.event_title.localeCompare(b.event_title));
}

export const pct = (x: number | null | undefined) => (x == null || !fin(x) ? "—" : `${(x * 100).toFixed(1)}¢`);

// ------------------------------------------------------------------------------------------------------------ tickets

export interface Band { mid: number | null; lo: number | null; hi: number | null }
export interface OptionsReference {
  available?: boolean; ok?: boolean; reason?: string | null; finish_beyond?: Band; touch?: Band; central?: Band & { kind?: string };
  expiry?: string | null; strikes?: { lo: number; hi: number; width?: number } | null; as_of?: string | null; session_label?: string | null;
  market_open?: boolean; market_phase?: string | null; status?: string | null; method_note?: string | null; notes?: string[];
}
export interface TicketContract {
  ok: boolean; reason?: string | null; expiry?: string | null; expiries_tried?: unknown; option_type?: string | null;
  lower_strike?: number | null; upper_strike?: number | null; long_leg?: string | null; short_leg?: string | null;
}
export interface Ticket {
  id: string; question: string; event_title?: string; type: "touch_ticket" | "close_above_ticket" | string;
  fields: Record<string, unknown>; checks?: Check[]; linkable: boolean; reasons: string[];
  best_bid: number | null; best_ask: number | null; contract?: TicketContract; reference?: OptionsReference | null;
  /** close-above rows: the reference is shown for information, explained by the registry entry `evidence_id` */
  reference_only?: boolean; evidence_id?: string | null;
  /** the touch_ticket_reference decision (only on touch tickets with a reference) */
  engine?: EngineDecision; propose?: boolean;
}
export interface TicketsOut {
  ok: boolean; stale?: boolean; error: string | null; as_of?: string; tickets: Ticket[]; counts?: { tickets: number; linked: number };
  hedge?: string; evidence?: Record<string, EvidenceRef>;
}

export const refAvailable = (r: OptionsReference | null | undefined) => !!r && r.available !== false && r.ok !== false && !!(r.finish_beyond || r.touch);

/** The reference band a ticket is compared with: touch reference for a touch ticket, finish-beyond for close-above. */
export function ticketReference(t: Ticket): Band | null {
  const r = t.reference;
  if (!refAvailable(r)) return null;
  const b = t.type === "touch_ticket" ? r!.touch : r!.finish_beyond;
  return b && fin(b.mid) ? b : null;
}

/** Polymarket price against the reference, in points: mid gap, and the band from bid/ask against the reference band.
 *  Null when either side is missing. Positive = the ticket is priced above the reference. */
export function ticketGap(t: Ticket): { mid: number; lo: number; hi: number } | null {
  const b = ticketReference(t);
  if (!b || !fin(t.best_bid) || !fin(t.best_ask)) return null;
  const pm = (t.best_bid + t.best_ask) / 2;
  const rlo = fin(b.lo) ? b.lo : b.mid!, rhi = fin(b.hi) ? b.hi : b.mid!;
  return { mid: 100 * (pm - b.mid!), lo: 100 * (t.best_bid - rhi), hi: 100 * (t.best_ask - rlo) };
}

/** "Friday's close" and other off-session wording comes from the backend's session_label; this only decides if the
 *  quote is from a closed session (so the board can flag it). */
/** Board order: the engine's proposals first, then rows priced against the reference (largest gap first), then
 *  linked rows, then the rest; touch tickets before close-above within each group. Stable, never mutates. */
export function sortTickets(ts: readonly Ticket[]): Ticket[] {
  const rank = (t: Ticket) => (t.engine?.action === "propose" ? 0 : ticketGap(t) ? 1 : t.linkable ? 2 : 3);
  return ts.map((t, i) => ({ t, i, r: rank(t), g: ticketGap(t)?.mid ?? -Infinity })).sort((a, b) =>
    a.r - b.r || (a.r <= 1 ? b.g - a.g : 0) || (a.t.type === b.t.type ? 0 : a.t.type === "touch_ticket" ? -1 : 1) || a.i - b.i).map((x) => x.t);
}

export const referenceClosed = (r: OptionsReference | null | undefined) => !!r && r.market_open === false;

/** Actions a ticket row may show. Never a hedge: the option-spread hedge for tickets failed (S25) and is not offered. */
export function ticketActions(t: Ticket, reg: Registry | null | undefined): { plan: ActionPlan; hedge: false; mechanism: Mechanism | null } {
  const m = mechanismFor(reg, t.type);
  return { plan: actionPlan(m), hedge: false, mechanism: m };
}

/** A touch-ticket proposal, only inside the tested rule (S21 book B0, touch_fresh FORWARD.md): sell YES at the
 *  traded bid when the bid is at least the registry touch entry's `sell_threshold_points` above the central (touch)
 *  reference mid. Null outside the rule, for any other ticket type, when the registry gives no threshold, or when the
 *  entry does not put proposals behind the acknowledgement gate (fail closed). */
export function touchProposal(t: Ticket, reg: Registry | null | undefined): { side: "sell_yes"; price: number; gapPoints: number; threshold: number } | null {
  const entry = mechanismFor(reg, "touch_ticket");
  const th = entry?.actions_allowed.sell_threshold_points ?? reg?.touch_sell_threshold_points;
  const plan = actionPlan(entry);
  if (t.type !== "touch_ticket" || !t.linkable || !fin(th) || !plan.propose || !plan.acknowledge) return null;
  // The decision is the backend's touch_ticket_reference family (or its labelled Python fallback): no block, no draft.
  if (t.engine?.action !== "propose") return null;
  const b = ticketReference(t);
  if (!b || !fin(t.best_bid)) return null;
  const gapPoints = 100 * (t.best_bid - b.mid!);
  // Registry threshold re-checked: if the backend's family and the registry ever disagree, fail closed.
  return gapPoints >= th - 1e-9 ? { side: "sell_yes", price: t.best_bid, gapPoints, threshold: th } : null;
}

export function ticketStrikes(c: TicketContract | undefined): string {
  if (!c?.ok) return c?.reason ? `not linked: ${c.reason}` : "not linked";
  const t = c.option_type ? `${c.option_type} spread` : "spread";
  return `${c.expiry ?? "?"} · ${c.lower_strike ?? "?"} / ${c.upper_strike ?? "?"} ${t}`;
}

export function ticketField(t: Ticket, k: string): string | null {
  const v = t.fields?.[k];
  return v == null || v === "" ? null : String(v);
}

// ------------------------------------------------------------------------------------------------------ forward + engine

/** Counts every forward section carries: forward-test snapshots (from the start date) and pre-start checks apart. */
export interface ForwardCounts { snapshots_taken: number; pre_start_checks?: number; forward_starts?: string; pre_start_label?: string }

export interface ForwardStatus {
  label: string; forward_starts?: string; pre_start_label?: string;
  ladders: ForwardCounts & { label: string; rule: string; state: string; latest: null | {
    run_utc?: string; snapshot_utc?: string; error?: string; phase?: string; date_ladders?: number; pairs?: number; pairs_with_books?: number; nested_pairs?: number;
    violations_net_of_fees?: { count: number | null; of_pairs_with_books: number | null; nested: number | null; locked_usd: number | null };
    gap_points_to_arb?: { n_pairs: number; median: number; p10: number; p90: number; min: number; max: number } | null;
  } };
  touch: ForwardCounts & { label: string; rule: string; status?: string; state: string; latest: null | { run_utc?: string; phase?: string; markets_listed?: number; eligible_first_weekend?: number; eligible_events?: number; note?: string } };
  recorder: null | { dir: string; heartbeats: Record<string, { age_s: number } & Record<string, unknown>>;
    state?: "live" | "stopped"; age_s?: number; last_update_utc?: string; pid_alive?: boolean | null };
}

/** True when the latest snapshot is a pre-start check (taken before the forward test's start date). */
export const isPreStart = (phase: string | null | undefined) => !!phase && phase.startsWith("pre-start");

/** "N forward-test snapshots" with the pre-start checks counted apart, never added in. */
export function forwardCount(c: ForwardCounts | null | undefined): string | null {
  if (!c) return null;
  const n = c.snapshots_taken ?? 0, pre = c.pre_start_checks ?? 0;
  const main = n > 0 || !c.forward_starts ? `${n} snapshot${n === 1 ? "" : "s"}` : `starts ${c.forward_starts}`;
  return pre > 0 ? `${main} · ${pre} pre-start check${pre === 1 ? "" : "s"} (not part of the forward test)` : main;
}

/** The forward test for a mechanism id: which section of GET /forward/status, as one line. A latest snapshot taken
 *  before the start date is prefixed with its pre-start label. */
export function forwardLine(fw: ForwardStatus | null | undefined, id: string): string | null {
  if (!fw) return null;
  const line = forwardLineRaw(fw, id);
  const x = id === "ladders" ? fw.ladders.latest : id === "touch" ? fw.touch.latest : null;
  return line && x && isPreStart(x.phase) ? `${x.phase}: ${line}` : line;
}

function forwardLineRaw(fw: ForwardStatus, id: string): string | null {
  if (id === "ladders") {
    const l = fw.ladders, x = l.latest;
    if (!x || l.state !== "ok") return `${l.state}`;
    const v = x.violations_net_of_fees;
    const g = x.gap_points_to_arb;
    return `Latest sweep ${x.snapshot_utc ?? x.run_utc ?? "?"}: ${v?.count ?? "?"} violations after fees of ${v?.of_pairs_with_books ?? "?"} pairs with books (${x.date_ladders ?? "?"} ladders)` +
      (g ? `; gap to an arbitrage median ${g.median} pts [p10 ${g.p10}, p90 ${g.p90}], n = ${g.n_pairs} pairs` : "");
  }
  if (id === "touch") {
    const t = fw.touch, x = t.latest;
    if (!x || t.state !== "ok") return t.state;
    return `Latest listing ${x.run_utc ?? "?"}: ${x.markets_listed ?? 0} markets listed, ${x.eligible_first_weekend ?? 0} eligible in ${x.eligible_events ?? 0} events`;
  }
  return null;
}

function hhmm(iso: string): string {
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? "?" : `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
}
function ago(s: number): string {
  return s < 120 ? `${Math.max(0, Math.round(s))}s` : s < 7200 ? `${Math.round(s / 60)}min` : `${Math.round(s / 3600)}h`;
}

/** The recorder state as the backend reports it (GET /forward/status, recorder): live or stopped, honestly. */
export function recorderLine(fw: ForwardStatus | null | undefined): { text: string; short: string; ok: boolean } {
  const r = fw?.recorder;
  if (!r || !r.heartbeats || !Object.keys(r.heartbeats).length) return { text: "recorder: no heartbeat found", short: "recorder: no heartbeat", ok: false };
  const age = typeof r.age_s === "number" ? r.age_s : Math.min(...Object.values(r.heartbeats).map((h) => h.age_s));
  const live = r.state ? r.state === "live" : age < 900;
  if (live) return { text: `recorder: live · last update ${ago(age)} ago`, short: "recorder live", ok: true };
  const when = r.last_update_utc ? hhmm(r.last_update_utc) : "?";
  return { text: `recorder: stopped (last update ${when})`, short: "recorder stopped", ok: false };
}

/** The engine strip's latency figure: the registry's system number for the live feed, with its range and sample. */
export function latencyView(reg: Registry | null | undefined): NumberView | null {
  const n = reg?.system.find((x) => /receive to decision/i.test(x.label));
  return n ? numberView(n) : null;
}

/** "receive→decision median 39 µs · p99 3.9 ms · n = 58,610 book updates (live feed, network excluded)". Null when the
 *  registry has no percentiles number for it (nothing is filled in). */
export function latencyLine(reg: Registry | null | undefined, short = false): string | null {
  const n = reg?.system.find((x) => /receive to decision/i.test(x.label));
  if (!n || n.range_kind !== "percentiles" || n.ci_low == null || n.ci_high == null || !n.sample?.n) return null;
  const med = fmtDuration(n.ci_low, n.unit), p99 = fmtDuration(n.ci_high, n.unit);
  if (!med || !p99) return null;
  if (short) return `receive→decision median ${med}`;
  return `receive→decision median ${med} · p99 ${p99} · n = ${n.sample.n.toLocaleString("en-US")} book updates (live feed, network excluded)`;
}
