import type { ClosedTick, HedgeASummary, StagedOrder, TimelineRow } from "./closed.ts";
import type { GateEntry } from "./risk.ts";
import { appendTimeline, newerOrder } from "./closed.ts";
export const REASONS = ["stale", "below_sigma", "inside_band", "below_fees", "rebalance", "risk_capped"] as const;
export interface FillInfo {
  broker?: string | null; side?: string; qty?: number; filled_qty?: number; status?: string; fill_px?: number | null; fee?: number | null;
  price_source?: string | null; reject_reason?: string | null; note?: string | null; scope?: string | null; error?: string | null;
  instrument?: string; structure?: string; simulated?: boolean; fill_model?: string; routed?: string;
  capped_from?: number; cap?: string; unit_risk?: number; price_note?: string;
  legs?: OptionLegFill[];
  evidence?: string | null;
  gates?: GateEntry[] | null;
  liquidity?: { status?: string; limit?: string; limit_qty?: number; rule?: string; note?: string } | null;
  capital?: { ok?: boolean; enforced?: boolean; checked?: boolean; scope?: string; note?: string | null; breaches?: { kind?: string; detail?: string }[] | null } | null;
}
export interface OptionLegFill {
  ticker: string; side: string; qty: number; status: string; fill_px: number | null; fee?: number | null;
  quote_mid?: number | null; quote_half_spread?: number | null; mark_source?: string | null;
}
export interface OptionsView { pm_mid: number | null; opt_implied_prob: number | null; gap: number | null; opt_mid?: number | null; opt_iv?: number | null; eightk_score?: number | null }
export interface LogEntry {
  n: number; p: number | null; action: string; reason: string; qty: number; target: number | null; current: number; ns: number; fill?: FillInfo;
  family?: string | null; preset?: number | null; signal?: number | null;
  evidence?: string | null;
}
export interface StagedRefusal { reason: string; detail: string | null; evidence: string | null }
export interface StreamState {
  prices: number[];
  lastP: number | null;
  reasons: Record<string, number>;
  lastReason: string | null;
  lat: number[];
  hedge: number;
  coverage: number;
  brokerHedge: number | null;
  broker: string | null;
  fills: number;
  log: LogEntry[];
  decisions: number;
  status: "connecting" | "running" | "reconnecting" | "finished" | "stopped";
  source: string | null;
  error: string | null;
  options: OptionsView | null;
  lastPriced: OptionsView | null;
  gaps: number[];
  optionPosition: number | null;
  riskUsed: number | null;
  closed: ClosedTick | null;
  staged: Record<string, StagedOrder>;
  timeline: TimelineRow[];
  hedgeA: HedgeASummary | null;
  refusal: StagedRefusal | null;
}
type Ev =
  | { k: "open" } | { k: "drop" }
  | { k: "tick"; p: number; options?: OptionsView | null; closed?: ClosedTick | null }
  | { k: "decision"; d: { action: string; reason: string; order_qty: number; target_hedge: number | null; current_hedge: number; latency_ns: number | null;
      engine?: "algo" | "legacy"; family?: string | null; preset?: number | null; signal?: number | null; evidence?: string | null } }
  | { k: "position"; hedge?: number; coverage?: number; broker_hedge?: number; broker?: string | null; option_position?: number; risk_used?: number }
  | { k: "fill"; f: FillInfo }
  | { k: "status"; status: string; source?: string }
  | { k: "error"; message: string }
  | { k: "staged"; d: { event?: string; order?: StagedOrder; timeline?: TimelineRow | null; reason?: string; detail?: string | null; evidence?: string | null } }
  | { k: "session" | "handoff"; d: { event?: string; timeline?: TimelineRow | null } }
  | { k: "hedge_a"; d: { summary?: HedgeASummary } };

export const init: StreamState = { prices: [], lastP: null, reasons: {}, lastReason: null, lat: [], hedge: 0, coverage: 0, brokerHedge: null, broker: null, fills: 0, log: [], decisions: 0, status: "connecting", source: null, error: null, options: null, lastPriced: null, gaps: [], optionPosition: null, riskUsed: null, closed: null, staged: {}, timeline: [], hedgeA: null, refusal: null };
const cap = <T,>(a: T[], n: number) => (a.length > n ? a.slice(a.length - n) : a);
function capLog(a: LogEntry[], n: number): LogEntry[] {
  if (a.length <= n) return a;
  const i = a.findIndex((l) => l.action !== "order");
  return i < 0 ? a.slice(a.length - n) : [...a.slice(0, i), ...a.slice(i + 1)];
}

export type { Ev as StreamEvent };
export function reduce(s: StreamState, e: Ev): StreamState {
  switch (e.k) {
    case "open": return { ...init, status: "running", source: s.source };
    case "drop": return s.status === "finished" || s.status === "stopped" ? s : { ...s, status: "reconnecting" };
    case "tick": {
      const o = e.options ?? null;
      const gaps = o && typeof o.gap === "number" ? cap([...s.gaps, o.gap], 300) : s.gaps;
      const lastPriced = o && typeof o.opt_implied_prob === "number" ? o : s.lastPriced;
      return { ...s, prices: cap([...s.prices, e.p], 300), lastP: e.p, options: o ?? s.options, lastPriced, gaps, closed: e.closed ?? s.closed };
    }
    case "decision": {
      const d = e.d;
      const ns = typeof d.latency_ns === "number" && Number.isFinite(d.latency_ns) ? d.latency_ns : null;
      const entry: LogEntry = { n: s.decisions + 1, p: s.lastP, action: d.action, reason: d.reason, qty: d.order_qty ?? 0, target: d.target_hedge ?? null, current: d.current_hedge ?? s.hedge, ns: ns ?? Number.NaN,
        ...(d.family ? { family: d.family, preset: d.preset ?? null, signal: d.signal ?? null } : {}), ...(d.evidence ? { evidence: d.evidence } : {}) };
      return { ...s, decisions: s.decisions + 1, lastReason: d.reason, reasons: { ...s.reasons, [d.reason]: (s.reasons[d.reason] ?? 0) + 1 }, lat: ns == null ? s.lat : cap([...s.lat, ns], 2000), log: capLog([...s.log, entry], 200) };
    }
    case "position": return {
      ...s, hedge: e.hedge ?? s.hedge, coverage: e.coverage ?? s.coverage,
      brokerHedge: typeof e.broker_hedge === "number" ? e.broker_hedge : s.brokerHedge, broker: e.broker ?? s.broker,
      optionPosition: typeof e.option_position === "number" ? e.option_position : s.optionPosition,
      riskUsed: typeof e.risk_used === "number" ? e.risk_used : s.riskUsed,
    };
    case "fill": {
      const i = s.log.findLastIndex((l) => l.action === "order" && !l.fill);
      const log = i < 0 ? s.log : s.log.map((l, j) => (j === i ? { ...l, fill: e.f } : l));
      return { ...s, log, fills: s.fills + 1, broker: e.f.broker ?? s.broker };
    }
    case "status": return { ...s, status: e.status === "finished" ? "finished" : e.status === "stopped" ? "stopped" : "running", source: e.source ?? s.source };
    case "error": return { ...s, error: e.message };
    case "staged": {
      const o = e.d.order;
      const staged = o && o.id ? { ...s.staged, [o.id]: newerOrder(s.staged[o.id], o)! } : s.staged;
      const refusal = e.d.event === "refused" ? { reason: e.d.reason ?? "EVIDENCE_GATE", detail: e.d.detail ?? null, evidence: e.d.evidence ?? null } : s.refusal;
      return { ...s, staged, refusal, timeline: appendTimeline(s.timeline, e.d.timeline) };
    }
    case "session": case "handoff": return { ...s, timeline: appendTimeline(s.timeline, e.d.timeline) };
    case "hedge_a": return e.d.summary ? { ...s, hedgeA: e.d.summary } : s;
  }
}

export function quantile(xs: number[], f: number): number | null {
  if (!xs.length) return null;
  const a = [...xs].sort((x, y) => x - y);
  return a[Math.min(a.length - 1, Math.floor(f * a.length))];
}

export interface SandboxFill {
  n: number; side: "SELL" | "BUY"; qty: number; px: number | null; fee: number | null; status: string;
  what: string; family: string | null; preset: number | null; broker: string | null;
  priceNote: string | null;
  reject: string | null; gates: GateEntry[]; evidence: string | null;
}

export function sandboxFills(log: LogEntry[]): SandboxFill[] {
  const out: SandboxFill[] = [];
  for (const l of log) {
    const f = l.fill;
    if (!f || f.scope !== "replay_sandbox") continue;
    const side = f.side ? (f.side.toLowerCase() === "sell" ? "SELL" : "BUY") : l.qty > 0 ? "SELL" : "BUY";
    const qty = f.filled_qty ?? f.qty ?? Math.abs(l.qty);
    out.push({
      n: l.n, side, qty, px: f.fill_px ?? null, fee: f.fee ?? null, status: f.status ?? "unknown",
      what: f.instrument === "option" ? `option ${f.structure ?? "structure"}` : "sh",
      family: l.family ?? null, preset: l.preset ?? null, broker: f.broker ?? null, priceNote: f.price_note ?? null,
      reject: f.reject_reason ?? null, gates: f.gates ?? [], evidence: f.evidence ?? l.evidence ?? null,
    });
  }
  return out.reverse();
}
