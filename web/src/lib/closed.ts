import { fmtMoney } from "./fmt.ts";

export type Phase = "regular" | "pre_market" | "after_hours" | "overnight" | "weekend" | "holiday";

export interface SessionView {
  at?: string | null;
  at_et?: string | null;
  phase: Phase | string;
  closed?: boolean;
  equities_open?: boolean;
  label?: string | null;
  next_open?: string | null;
  next_open_et?: string | null;
  next_premarket?: string | null;
  next_premarket_et?: string | null;
  next_extended_open?: string | null;
  next_extended_open_et?: string | null;
  last_close?: string | null;
  closure_kind?: string | null;
}

export interface ClosureView {
  pm_move_pp: number | null;
  since: string | null;
  status: string;
  p_close: number | null;
  p_now: number | null;
  high_pp?: number | null;
  low_pp?: number | null;
  n_points?: number;
  kind?: string | null;
}

export interface GapView {
  bp: number | null;
  band: [number, number] | null;
  band_level?: number;
  n: number;
  rate_source: string;
  rate_bp_per_pp?: number;
  validated: boolean;
  status: string;
  evidence: string | null;
  active: boolean;
  oriented_move_pp?: number | null;
  basis_ticker?: string;
  reasons?: string[];
}

export interface ClosedTick { session: SessionView | null; closure: ClosureView | null; expected_gap: GapView | null; hold?: boolean }

export type StagedStatus = "staged" | "approved" | "working" | "filled" | "cancelled" | "rejected" | "skipped";
export interface StagedDecision { at: string; code: string; detail?: string | null }
export interface StagedOrder {
  id: string;
  status: StagedStatus | string;
  proposal_id?: string;
  bridge_id?: string | null;
  ticker?: string;
  side?: "sell" | "buy";
  qty: number;
  approved_qty?: number | null;
  planned_qty?: number;
  session_target: "pre_market" | "regular_open" | "regular_now" | string;
  execute_at: string;
  extended_hours?: boolean;
  clock?: "wall" | "replay";
  filled_qty?: number;
  fill_px?: number | null;
  reason?: string | null;
  estimate?: { gap_bp?: number; band_bp?: number[]; n_closures?: number; rate_source?: string; validated?: boolean; status?: string; evidence?: string } | null;
  current?: { gap_bp?: number } | null;
  decisions?: StagedDecision[];
  label?: string;
  evidence_gate?: "validated" | "override" | string | null;
  evidence?: string | null;
  liquidity?: { status?: string; rule?: string; limit_qty?: number; note?: string } | null;
  capital?: { ok?: boolean; enforced?: boolean; checked?: boolean; note?: string | null; breaches?: { kind?: string; detail?: string }[] | null } | null;
}

export interface TimelineRow { at: string; at_et: string; event: string; detail?: string | null; staged_id?: string; qty?: number; filled_qty?: number; fill_px?: number | null; phase?: string }

export interface EvidenceLine { label?: string; verdict?: string; vr0?: number; vr0_ci?: number[]; default?: boolean; research_only?: boolean; replication_verdict?: string; window?: string; catchup?: number; catchup_ci?: number[]; net_gap_pt?: number; net_gap_ci_pt?: number[]; pre_market_variant?: { verdict?: string; vr0?: number; vr0_ci?: number[] } }
export interface ClosedLabels { hedge_a?: EvidenceLine; hedge_b?: EvidenceLine; opportunity?: EvidenceLine }

export interface ClosurePnl {
  since: string | null; s_close: number; s_now: number; shares_held: number; unhedged_usd: number;
  carried_hedge_shares: number; carried_hedge_usd: number; staged_short_shares: number; staged_usd: number;
  algo_short_shares: number; algo_usd: number; hedge_a_usd: number | null; hedge_a_estimate: boolean;
  hedged_usd: number; vs_no_hedge_usd: number; price_source: string; price_note?: string | null; note?: string;
}

export interface ClosedModeSummary {
  hold?: boolean; session_hold?: boolean; holds?: number;
  evidence?: { validated?: boolean; status?: string; market?: string | null; evidence?: string } | null;
  labels?: ClosedLabels | null;
  plan?: StagedOrder | null; plan_note?: string | null;
  staged_orders?: StagedOrder[];
  pnl?: ClosurePnl | null;
  last_expected_gap?: GapView | null;
  timeline?: TimelineRow[];
  hedge_a_error?: string | null;
  error?: string;
}

export interface HedgeASummary {
  enabled: boolean; label?: string; estimate?: boolean; contracts?: number; mark?: number | null; pnl_usd?: number | null;
  equity_equiv_shares?: number; sim_equity_equiv_shares?: number; counts_toward_cap?: boolean; fills?: number; rate_bp_per_pp?: number; rate_source?: string;
  last_fill?: { side?: string; qty?: number; fill_px?: number; reason?: string } | null;
}

export const PHASE_LABEL: Record<Phase, string> = {
  regular: "Regular", pre_market: "Pre-market", after_hours: "After-hours", overnight: "Overnight", weekend: "Weekend", holiday: "Holiday",
};
const PHASE_DOT: Record<Phase, string> = {
  regular: "#4ADE80", pre_market: "#FBBF24", after_hours: "#FBBF24", overnight: "#9A7BFF", weekend: "#9A7BFF", holiday: "#9A7BFF",
};

export const isPhase = (p: unknown): p is Phase => typeof p === "string" && p in PHASE_LABEL;

export function sessionClosed(s: SessionView | null | undefined): boolean {
  if (!s) return false;
  if (typeof s.closed === "boolean") return s.closed;
  if (typeof s.equities_open === "boolean") return !s.equities_open;
  return isPhase(s.phase) && s.phase !== "regular";
}

export function sessionPill(s: SessionView | null | undefined): { text: string; dot: string; title: string } | null {
  if (!s || !isPhase(s.phase)) return null;
  return { text: PHASE_LABEL[s.phase], dot: PHASE_DOT[s.phase], title: `US equities (NYSE) now: ${s.label || PHASE_LABEL[s.phase]}` };
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export function etDayTime(iso: string | null | undefined): { day: string; hm: string } | null {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso) : null;
  if (!m) return null;
  const day = DAYS[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()];
  return { day, hm: `${m[4]}:${m[5]}` };
}

export function fmtEt(iso: string | null | undefined, withDate = false): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    ...(withDate ? { day: "numeric", month: "short", year: "numeric" } : {}),
  }).formatToParts(d);
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${g("weekday")}${withDate ? ` ${g("day")} ${g("month")} ${g("year")}` : ""} ${g("hour")}:${g("minute")} ET`;
}

export function closedHeadline(s: SessionView | null | undefined): string | null {
  if (!s || !sessionClosed(s)) return null;
  if (s.label && s.label.trim()) return s.label.trim();
  const open = etDayTime(s.next_open_et);
  if (!open) return "Market closed";
  if (s.phase === "pre_market") return `Pre-market · regular open ${open.hm} ET`;
  const pre = etDayTime(s.next_premarket_et ?? s.next_extended_open_et);
  const head = s.phase === "after_hours" ? "After-hours" : "Market closed";
  const preOk = pre && (s.next_premarket ?? s.next_extended_open ?? "") < (s.next_open ?? "");
  return `${head} · reopens ${open.day} ${open.hm} ET${preOk ? ` / pre-market ${pre!.hm}` : ""}`;
}

const fin = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

export function normalizeGap(g: Record<string, unknown> | null | undefined): GapView | null {
  if (!g || typeof g !== "object") return null;
  const bp = (fin(g.bp) ? g.bp : fin(g.expected_gap_bp) ? g.expected_gap_bp : null) as number | null;
  const bandRaw = (Array.isArray(g.band) ? g.band : Array.isArray(g.band_bp) ? g.band_bp : null) as unknown[] | null;
  const band = bandRaw && bandRaw.length === 2 && fin(bandRaw[0]) && fin(bandRaw[1]) ? [bandRaw[0], bandRaw[1]] as [number, number] : null;
  const n = (fin(g.n) ? g.n : fin(g.n_closures) ? g.n_closures : 0) as number;
  const rateSource = String(g.rate_source ?? g.label ?? "pooled");
  return {
    bp, band, n, rate_source: rateSource,
    band_level: fin(g.band_level) ? g.band_level : undefined,
    rate_bp_per_pp: fin(g.rate_bp_per_pp) ? g.rate_bp_per_pp : undefined,
    validated: g.validated === true, status: typeof g.status === "string" ? g.status : "unvalidated estimate",
    evidence: typeof g.evidence === "string" ? g.evidence : null,
    active: g.active === true || (g.active == null && bp != null),
    oriented_move_pp: fin(g.oriented_move_pp) ? g.oriented_move_pp : null,
    basis_ticker: typeof g.basis_ticker === "string" ? g.basis_ticker : undefined,
    reasons: Array.isArray(g.reasons) ? g.reasons.map(String) : undefined,
  };
}

export const UNVALIDATED_REASON = "No out-of-sample test passes for this market. Thus the expected gap is an unvalidated estimate. The 10-market replication was not accurate.";

export function gapBadge(g: GapView | null | undefined): { validated: boolean; text: "validated" | "unvalidated estimate"; reason: string } {
  const validated = !!g && g.validated === true && g.status === "validated" && g.rate_source === "market";
  return { validated, text: validated ? "validated" : "unvalidated estimate", reason: g?.evidence || UNVALIDATED_REASON };
}

const MINUS = "−";
const signed = (x: number, d: number) => (x > 0 ? "+" : x < 0 ? MINUS : "") + Math.abs(x).toFixed(d);

export const fmtBp = (bp: number | null | undefined, d = 1) => (fin(bp) ? `${signed(bp, d)} bp` : "n/a");
export const fmtPp = (pp: number | null | undefined, d = 1) => (fin(pp) ? `${signed(pp, d)} pts` : "n/a");

export function bandText(g: GapView | null | undefined): string {
  if (!g) return "no expected gap";
  const lvl = g.band_level != null ? `${Math.round(g.band_level * 100)}% ` : "";
  const band = g.band ? `${lvl}band ${signed(g.band[0], 1)} to ${signed(g.band[1], 1)} bp` : "no band (no move yet)";
  const src = g.rate_source === "market" ? "this market's rate" : "pooled rate";
  return `${band} · ${g.n} ${g.n === 1 ? "closure" : "closures"}, ${src}`;
}

export function weekendExposure(value: number | null | undefined, g: GapView | null | undefined): { usd: number; lo: number | null; hi: number | null } | null {
  if (!fin(value) || !g || !fin(g.bp)) return null;
  const k = value / 1e4;
  return { usd: g.bp * k, lo: g.band ? Math.min(g.band[0], g.band[1]) * k : null, hi: g.band ? Math.max(g.band[0], g.band[1]) * k : null };
}

const PENDING = ["staged", "approved", "working"];

export function stagedActions(o: Pick<StagedOrder, "status">): { approve: boolean; cancel: boolean } {
  return { approve: o.status === "staged", cancel: PENDING.includes(o.status) };
}

export function executionText(o: Pick<StagedOrder, "session_target" | "execute_at">): string {
  const at = fmtEt(o.execute_at);
  if (o.session_target === "pre_market") return `pre-market ${at}`;
  if (o.session_target === "regular_open") return `the ${at} open`;
  if (o.session_target === "regular_now") return "now (regular session)";
  return at;
}

export function stagedStatusText(o: StagedOrder): string {
  switch (o.status) {
    case "staged": return "waits for your approval";
    case "approved": return `approved · executes at ${executionText(o)}`;
    case "working": return "sent to the broker";
    case "filled": return `filled ${fin(o.filled_qty) ? o.filled_qty : o.qty}${fin(o.fill_px) ? ` @ ${o.fill_px.toFixed(2)}` : ""}`;
    case "cancelled": return `cancelled${o.reason ? ` (${o.reason.replaceAll("_", " ").toLowerCase()})` : ""}`;
    case "rejected": return `rejected${o.reason ? ` (${o.reason.replaceAll("_", " ").toLowerCase()})` : ""}`;
    case "skipped": return `skipped${o.reason ? ` (${o.reason.replaceAll("_", " ").toLowerCase()})` : ""}`;
    default: return String(o.status);
  }
}

export function newerOrder(a: StagedOrder | undefined, b: StagedOrder | undefined): StagedOrder | undefined {
  if (!a) return b;
  if (!b) return a;
  return (b.decisions?.length ?? 0) >= (a.decisions?.length ?? 0) ? b : a;
}

export function mergeOrders(...lists: (readonly StagedOrder[] | Record<string, StagedOrder> | null | undefined)[]): StagedOrder[] {
  const by = new Map<string, StagedOrder>();
  for (const l of lists) {
    if (!l) continue;
    for (const o of Array.isArray(l) ? l : Object.values(l)) {
      if (o && o.id) by.set(o.id, newerOrder(by.get(o.id), o)!);
    }
  }
  return [...by.values()].sort((x, y) => (y.decisions?.[0]?.at ?? "").localeCompare(x.decisions?.[0]?.at ?? ""));
}

const EVENT_TEXT: Record<string, string> = {
  close: "Market close", open: "Market open, handoff to the algo", plan: "Plan staged (hedge B)", plan_refused: "Plan refused", plan_skipped: "Plan skipped",
  staged_staged: "Plan staged", staged_approved: "Approved", staged_working: "Sent to the broker", staged_filled: "Filled",
  staged_cancelled: "Cancelled", staged_rejected: "Rejected", staged_skipped: "Skipped", hedge_a: "Hedge A (estimate)",
};
export const timelineTitle = (ev: string) => EVENT_TEXT[ev] ?? ev.replaceAll("_", " ");

export function appendTimeline(rows: TimelineRow[], row: TimelineRow | null | undefined, max = 200): TimelineRow[] {
  if (!row || !row.event) return rows;
  if (rows.some((r) => r.at === row.at && r.event === row.event && (r.staged_id ?? null) === (row.staged_id ?? null))) return rows;
  const out = [...rows, row];
  return out.length > max ? out.slice(out.length - max) : out;
}

export const HEDGE_A_TITLE = "estimate, not protection";

export function hedgeAView(h: HedgeASummary | null | undefined): { title: string; label: string; contracts: number; equivShares: number; pnl: number | null } | null {
  if (!h || h.enabled !== true) return null;
  return {
    title: `Hedge A · ${HEDGE_A_TITLE}`,
    label: h.label || HEDGE_A_FALLBACK,
    contracts: fin(h.contracts) ? h.contracts : 0,
    equivShares: fin(h.sim_equity_equiv_shares) ? h.sim_equity_equiv_shares : fin(h.equity_equiv_shares) ? h.equity_equiv_shares : 0,
    pnl: fin(h.pnl_usd) ? h.pnl_usd : null,
  };
}

const pctCi = (x?: number, ci?: number[]) => (fin(x) ? `${signed(x * 100, 1)}%${ci && ci.length === 2 && fin(ci[0]) && fin(ci[1]) ? ` (95% CI ${signed(ci[0] * 100, 1)}% to ${signed(ci[1] * 100, 1)}%)` : ""}` : null);

export const HEDGE_A_FALLBACK = "Estimate only, not protection. This is a simulated prediction-market leg because there is no Polymarket trading account. Research R1 found no evidence that a PM contract held over a closure decreases the open-gap loss (variance reduction +4.8%, 95% CI −0.8% to +10.0%). On the 10-market replication panel, it increased the variance. Hedge A stays off until you select it.";
export const HEDGE_B_FALLBACK = "Default closed-market action: an equity order staged for the first tradable time. The system sends it only after you approve it. Research R1: it decreased the P&L variance after the open by 11.4% (95% CI +5.1% to +18.1%). It works by timing, not direction. It executes after the gap, so it cannot remove the gap.";

export function weekendModeCopy(labels: ClosedLabels | null | undefined): { hedgeB: string; hedgeA: string; hedgeBStat: string | null; hedgeAStat: string | null } {
  const b = labels?.hedge_b, a = labels?.hedge_a;
  return {
    hedgeB: b?.label || HEDGE_B_FALLBACK,
    hedgeA: a?.label || HEDGE_A_FALLBACK,
    hedgeBStat: pctCi(b?.vr0, b?.vr0_ci),
    hedgeAStat: pctCi(a?.vr0, a?.vr0_ci),
  };
}

export const OPPORTUNITY_FALLBACK = "Research only, not a trade recommendation. At the Monday open, options showed 0.44 of the weekend PM move (CI 0.33 to 0.57). But the gap that remains after option costs is NULL (+0.79 pt, CI −1.21 to +2.78, R3).";

export function opportunityView(line: EvidenceLine | null | undefined, research?: { status?: string; verdict?: string | null } | null): { title: string; text: string; verdict: string; trade: false } {
  const verdict = String(research?.verdict ?? line?.verdict ?? "NULL");
  return { title: "Opportunity at the open · research only", text: line?.label || OPPORTUNITY_FALLBACK, verdict: `R3 ${verdict}`, trade: false };
}

export function pnlRows(p: ClosurePnl | null | undefined): { k: string; v: number; note?: string }[] {
  if (!p) return [];
  const rows: { k: string; v: number; note?: string }[] = [{ k: "Holding, no hedge", v: p.unhedged_usd }];
  if (p.carried_hedge_shares) rows.push({ k: `Hedge carried from the close (${Math.round(p.carried_hedge_shares)} sh)`, v: p.carried_hedge_usd });
  if (p.staged_short_shares) rows.push({ k: `Staged order, hedge B (${Math.round(p.staged_short_shares)} sh)`, v: p.staged_usd });
  if (p.algo_short_shares) rows.push({ k: `Algo after the open (${Math.round(Math.abs(p.algo_short_shares))} sh)`, v: p.algo_usd });
  if (p.hedge_a_estimate && fin(p.hedge_a_usd)) rows.push({ k: "Hedge A (estimate)", v: p.hedge_a_usd, note: "simulated PM leg" });
  return rows;
}

export type StagedHedgeState = "none" | "awaiting" | "approved" | "working" | "filled";

export function stagedHedgeText(orders: readonly StagedOrder[]): { state: StagedHedgeState; badge: string; text: string } {
  const live = orders.filter((o) => PENDING.includes(o.status) || (o.status === "filled") || (fin(o.filled_qty) && o.filled_qty > 0));
  if (!live.length) return { state: "none", badge: "No staged order", text: "No order is staged for the open." };
  const parts = live.map((o) => `${o.side === "buy" ? "Buy" : "Sell"} ${o.qty.toLocaleString("en-US")}: ${stagedStatusText(o)}`);
  const text = `${parts.join(". ")}. Hedge B trades after the gap and cannot remove it.`;
  const filled = live.find((o) => o.status === "filled" || (fin(o.filled_qty) && o.filled_qty > 0));
  if (filled) return { state: "filled", badge: "Hedge B filled (after the gap)", text };
  const working = live.find((o) => o.status === "working");
  if (working) return { state: "working", badge: "Hedge B sent (after the gap)", text };
  const approved = live.find((o) => o.status === "approved");
  if (approved) return { state: "approved", badge: `Hedge B approved · executes ${executionText(approved)} (after the gap)`, text };
  return { state: "awaiting", badge: "Hedge B waits for approval", text };
}

export interface ExposureRowLite { kind: "holding" | "bridge"; ticker: string; marketId: string | null; value: number | null; gap: GapView | null; replay: boolean }
export function exposureTotal(rows: readonly ExposureRowLite[]): { usd: number; lo: number | null; hi: number | null; validated: boolean; rows: number } | null {
  const held = rows.filter((r) => r.kind === "holding");
  const covered = (r: ExposureRowLite) => r.kind === "bridge" && held.some((h) => h.ticker === r.ticker && (r.marketId == null || h.marketId == null || h.marketId === r.marketId));
  let usd = 0, lo: number | null = 0, hi: number | null = 0, n = 0, validated = true;
  for (const r of rows) {
    if (r.replay || covered(r)) continue;
    const x = weekendExposure(r.value, r.gap);
    if (!x) continue;
    n += 1; usd += x.usd;
    lo = lo != null && x.lo != null ? lo + x.lo : null;
    hi = hi != null && x.hi != null ? hi + x.hi : null;
    if (!gapBadge(r.gap).validated) validated = false;
  }
  return n ? { usd, lo, hi, validated, rows: n } : null;
}

export function currentGap(nowRaw: Record<string, unknown> | null | undefined, lastRaw: Record<string, unknown> | null | undefined,
  closed: boolean, closureSince: string | null | undefined): { gap: GapView | null; past: boolean } {
  const now = normalizeGap(nowRaw);
  if (now && now.active) return { gap: now, past: false };
  const last = normalizeGap(lastRaw);
  if (!last) return { gap: now, past: false };
  if (!closed) return { gap: last, past: true };
  const at = Date.parse(String(lastRaw?.at ?? "")), since = Date.parse(String(closureSince ?? ""));
  if (Number.isFinite(at) && Number.isFinite(since) && at >= since) return { gap: last, past: false };
  return { gap: now, past: false };
}

export function pnlTotals(p: ClosurePnl | null | undefined): { k: string; v: number }[] {
  if (!p) return [];
  const vs = (x: number) => fmtMoney(x, true);
  if (p.hedge_a_estimate && fin(p.hedge_a_usd)) {
    const vNo = p.vs_no_hedge_usd - p.hedge_a_usd;
    return [
      { k: `Hedged total, without hedge A (${vs(vNo)} vs no hedge)`, v: p.hedged_usd - p.hedge_a_usd },
      { k: `With hedge A estimate, simulated (${vs(p.vs_no_hedge_usd)} vs no hedge)`, v: p.hedged_usd },
    ];
  }
  return [{ k: `Hedged total (${vs(p.vs_no_hedge_usd)} vs no hedge)`, v: p.hedged_usd }];
}

export function splitOrders(orders: readonly StagedOrder[]): { active: StagedOrder[]; folded: number; foldedText: string | null } {
  const isActive = (o: StagedOrder) => PENDING.includes(o.status) || o.status === "filled" || (fin(o.filled_qty) && o.filled_qty > 0);
  const active = orders.filter(isActive), rest = orders.filter((o) => !isActive(o));
  if (!rest.length) return { active, folded: 0, foldedText: null };
  const counts = new Map<string, number>();
  for (const o of rest) {
    const k = `${o.status}${o.reason ? ` (${o.reason.replaceAll("_", " ").toLowerCase()})` : ""}`;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  return { active, folded: rest.length, foldedText: [...counts].map(([k, n]) => `${n} ${k}`).join(" · ") };
}
