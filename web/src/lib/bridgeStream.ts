// Pure reducer for a bridge's SSE stream (tick, decision, position, fill, status, error); unit-tested offline.
export const REASONS = ["stale", "below_sigma", "inside_band", "below_fees", "rebalance", "risk_capped"] as const;
/** A broker fill for one engine order ("fill" SSE event, broker stream). */
export interface FillInfo {
  broker?: string | null; side?: string; qty?: number; filled_qty?: number; status?: string; fill_px?: number | null; fee?: number | null;
  price_source?: string | null; reject_reason?: string | null; note?: string | null; scope?: string | null; error?: string | null;
  /** Opportunity bridges: one multi-leg option order (all legs or none), always a simulated fill. */
  instrument?: string; structure?: string; simulated?: boolean; fill_model?: string; routed?: string;
  capped_from?: number; cap?: string; unit_risk?: number; price_note?: string;
  legs?: OptionLegFill[];
}
export interface OptionLegFill {
  ticker: string; side: string; qty: number; status: string; fill_px: number | null; fee?: number | null;
  quote_mid?: number | null; quote_half_spread?: number | null; mark_source?: string | null;
}
/** PM YES mid vs the options-implied probability on one tick (an estimate, labelled as such in the UI). */
export interface OptionsView { pm_mid: number | null; opt_implied_prob: number | null; gap: number | null; opt_mid?: number | null; opt_iv?: number | null; eightk_score?: number | null }
export interface LogEntry {
  n: number; p: number | null; action: string; reason: string; qty: number; target: number | null; current: number; ns: number; fill?: FillInfo;
  /** Set when hedgecore.Algo decided (the fitted family): its family, preset and the signal that triggered it. */
  family?: string | null; preset?: number | null; signal?: number | null;
}
export interface StreamState {
  prices: number[];
  lastP: number | null;
  reasons: Record<string, number>;
  lastReason: string | null;
  lat: number[];
  hedge: number;
  coverage: number;
  /** What the broker actually filled (broker stream); null when the backend does not report it. */
  brokerHedge: number | null;
  broker: string | null;
  fills: number;
  log: LogEntry[];
  decisions: number;
  status: "connecting" | "running" | "reconnecting" | "finished" | "stopped";
  source: string | null;
  error: string | null;
  /** Opportunity bridges: the latest PM-vs-options view, the gap history and the open option structures. */
  options: OptionsView | null;
  gaps: number[];
  optionPosition: number | null;
  riskUsed: number | null;
}
type Ev =
  | { k: "open" } | { k: "drop" }
  | { k: "tick"; p: number; options?: OptionsView | null }
  | { k: "decision"; d: { action: string; reason: string; order_qty: number; target_hedge: number | null; current_hedge: number; latency_ns: number;
      engine?: "algo" | "legacy"; family?: string | null; preset?: number | null; signal?: number | null } }
  | { k: "position"; hedge?: number; coverage?: number; broker_hedge?: number; broker?: string | null; option_position?: number; risk_used?: number }
  | { k: "fill"; f: FillInfo }
  | { k: "status"; status: string; source?: string }
  | { k: "error"; message: string };

export const init: StreamState = { prices: [], lastP: null, reasons: {}, lastReason: null, lat: [], hedge: 0, coverage: 0, brokerHedge: null, broker: null, fills: 0, log: [], decisions: 0, status: "connecting", source: null, error: null, options: null, gaps: [], optionPosition: null, riskUsed: null };
const cap = <T,>(a: T[], n: number) => (a.length > n ? a.slice(a.length - n) : a);

export type { Ev as StreamEvent };
export function reduce(s: StreamState, e: Ev): StreamState {
  switch (e.k) {
    case "open": return { ...init, status: "running", source: s.source };  // the server replays history on connect
    case "drop": return s.status === "finished" || s.status === "stopped" ? s : { ...s, status: "reconnecting" };
    case "tick": {
      const o = e.options ?? null;
      const gaps = o && typeof o.gap === "number" ? cap([...s.gaps, o.gap], 300) : s.gaps;
      return { ...s, prices: cap([...s.prices, e.p], 300), lastP: e.p, options: o ?? s.options, gaps };
    }
    case "decision": {
      const d = e.d;
      const entry: LogEntry = { n: s.decisions + 1, p: s.lastP, action: d.action, reason: d.reason, qty: d.order_qty, target: d.target_hedge ?? null, current: d.current_hedge, ns: d.latency_ns,
        ...(d.family ? { family: d.family, preset: d.preset ?? null, signal: d.signal ?? null } : {}) };
      return { ...s, decisions: s.decisions + 1, lastReason: d.reason, reasons: { ...s.reasons, [d.reason]: (s.reasons[d.reason] ?? 0) + 1 }, lat: cap([...s.lat, d.latency_ns], 2000), log: cap([...s.log, entry], 200) };
    }
    case "position": return {
      ...s, hedge: e.hedge ?? s.hedge, coverage: e.coverage ?? s.coverage,
      brokerHedge: typeof e.broker_hedge === "number" ? e.broker_hedge : s.brokerHedge, broker: e.broker ?? s.broker,
      optionPosition: typeof e.option_position === "number" ? e.option_position : s.optionPosition,
      riskUsed: typeof e.risk_used === "number" ? e.risk_used : s.riskUsed,
    };
    case "fill": {
      // A fill follows its order's decision: attach it to the newest order that has none yet.
      const i = s.log.findLastIndex((l) => l.action === "order" && !l.fill);
      const log = i < 0 ? s.log : s.log.map((l, j) => (j === i ? { ...l, fill: e.f } : l));
      return { ...s, log, fills: s.fills + 1, broker: e.f.broker ?? s.broker };
    }
    case "status": return { ...s, status: e.status === "finished" ? "finished" : e.status === "stopped" ? "stopped" : "running", source: e.source ?? s.source };
    case "error": return { ...s, error: e.message };
  }
}

export function quantile(xs: number[], f: number): number | null {
  if (!xs.length) return null;
  const a = [...xs].sort((x, y) => x - y);
  return a[Math.min(a.length - 1, Math.floor(f * a.length))];
}
