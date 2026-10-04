// The two micro-market mechanisms (date ladders, touch tickets) and the evidence registry that labels them.
// Every status, label and allowed action comes from GET /evidence/mechanisms (backend/app/closed/evidence.py); this
// file holds no label text of its own for a mechanism. Pure (no React), so `node --test` covers it offline.

// ---------------------------------------------------------------------------------------------------------- registry

export interface EvSample { n: number; units: string; also?: { n: number; units: string }[] }
export interface EvNumber {
  label: string; value: number; unit?: string; ci_low: number | null; ci_high: number | null; range_kind?: string;
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

export interface NumberView { label: string; value: string; range: string; rangeKind: string; sample: string; source: string; sourceNote: string | null; confirmatory: boolean; note: string | null }

/** One registry number as text: value, range and sample together. Null (never shown) without a range and a sample. */
export function numberView(n: EvNumber): NumberView | null {
  if (!hasRangeAndSample(n)) return null;
  const d = Math.max(dec(n.value), dec(n.ci_low!), dec(n.ci_high!));
  const census = n.ci_low === n.value && n.ci_high === n.value;
  // Differences and returns carry a sign (+0.0108); counts, ratios and timings do not.
  const sign = n.ci_low! < 0 || n.value < 0 || (!census && !/second|ratio/i.test(n.unit ?? "") && !/percentile|p99/i.test(n.range_kind ?? ""));
  const unit = n.unit ? ` ${n.unit}` : "";
  const s = n.sample!;
  const sample = [`${s.n.toLocaleString("en-US")} ${s.units}`, ...(s.also ?? []).map((a) => `${a.n.toLocaleString("en-US")} ${a.units}`)].join(" · ");
  const off = n.result_file_on_disk === false && n.source_branch ? `on branch ${n.source_branch} @ ${n.source_commit ?? "?"}` : null;
  return {
    label: n.label,
    value: `${fmtSigned(n.value, d, sign)}${unit}`,
    range: census ? "no interval" : `[${fmtSigned(n.ci_low!, d, sign)}, ${fmtSigned(n.ci_high!, d, sign)}]`,
    rangeKind: n.range_kind ?? "",
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
  const b = ticketReference(t);
  if (!b || !fin(t.best_bid)) return null;
  const gapPoints = 100 * (t.best_bid - b.mid!);
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
  recorder: null | { dir: string; heartbeats: Record<string, { age_s: number } & Record<string, unknown>> };
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

export function recorderLine(fw: ForwardStatus | null | undefined): { text: string; ok: boolean } {
  const hb = fw?.recorder?.heartbeats;
  if (!hb || !Object.keys(hb).length) return { text: "recorder: no heartbeat", ok: false };
  const age = Math.min(...Object.values(hb).map((h) => h.age_s));
  return { text: `recorder: heartbeat ${age < 120 ? `${Math.round(age)} s ago` : `${Math.round(age / 60)} min ago`}`, ok: age < 300 };
}

/** The engine strip's latency figure: the registry's system number for the live feed, with its range and sample. */
export function latencyView(reg: Registry | null | undefined): NumberView | null {
  const n = reg?.system.find((x) => /receive to decision/i.test(x.label));
  return n ? numberView(n) : null;
}
