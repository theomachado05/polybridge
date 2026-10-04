// View logic for the risk controls the backend enforces: the evidence gate, the liquidity participation caps, the
// capital budget and the broker account (Webull paper). Pure and dependency-free so `node --test` covers it; the
// screens only render what these functions return. Every number keeps its source and freshness, and the UI never
// upgrades a backend verdict (an unvalidated market stays unvalidated; an unknown cap stays unknown).
import type {
  AccountOut, BrokerOrder, BrokerPosition, Capacity, CapitalLimits, CapitalOut, EvidenceStatus, Freshness, LiquidityEquity, ReconcileStatus,
} from "./api.ts";
import type { SessionView } from "./closed.ts";
import type { Mechanism } from "./micro.ts";

export type Tone = "measured" | "caution" | "neutral" | "sim" | "paper" | "live" | "replay" | "ai" | "demo";
export interface Badge { tone: Tone; text: string; title?: string }

const MINUS = "−";
const fin = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** $1,234 / $12.5k / $191.2M / $35.2B; "n/a" when unknown. */
export function usd(x: number | null | undefined, opts: { compact?: boolean; sign?: boolean } = {}): string {
  if (!fin(x)) return "n/a";
  const s = x < 0 ? MINUS : opts.sign ? "+" : "";
  const a = Math.abs(x);
  if (opts.compact !== false && a >= 1e9) return `${s}$${(a / 1e9).toFixed(1)}B`;
  if (opts.compact !== false && a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  if (opts.compact && a >= 1e4) return `${s}$${(a / 1e3).toFixed(1)}k`;
  return `${s}$${a.toLocaleString("en-US", { maximumFractionDigits: a >= 100 ? 0 : 2 })}`;
}
export const shares = (x: number | null | undefined) => (fin(x) ? `${Math.round(x).toLocaleString("en-US")} sh` : "n/a");
export const bp = (x: number | null | undefined, d = 1) => (fin(x) ? `${x.toFixed(d)} bp` : "n/a");
export const pctOf = (x: number | null | undefined, d = 0) => (fin(x) ? `${(x * 100).toFixed(d)}%` : "n/a");

// ------------------------------------------------------------------ evidence gate

export interface EvidenceGateView {
  /** False when the backend did not report the evidence (an older backend): the backend still decides at approval. */
  known: boolean;
  validated: boolean;
  /** Approval needs the explicit acknowledgement (checkbox) before the Approve button enables. */
  needsAck: boolean;
  badge: Badge;
  reason: string;
}

export function evidenceGate(ev: EvidenceStatus | null | undefined): EvidenceGateView {
  if (!ev) {
    return { known: false, validated: false, needsAck: false, reason: "The backend did not give the evidence status for this market.",
      badge: { tone: "neutral", text: "evidence not reported" } };
  }
  const reason = ev.evidence ?? (ev.validated ? "This market passed its out-of-sample test." : "This market has no out-of-sample record.");
  if (ev.validated) {
    return { known: true, validated: true, needsAck: false, reason, badge: { tone: "measured", text: "validated", title: reason } };
  }
  return { known: true, validated: false, needsAck: true, reason, badge: { tone: "caution", text: "unvalidated estimate", title: reason } };
}

/** The acknowledgement the user ticks before approving on an unvalidated market. Honest: it says what is missing,
 *  what will run anyway and how it is labelled. */
export function ackCopy(ticker: string, kind: "hedge" | "opportunity" = "hedge", opts: { override?: boolean } = {}): string {
  const runs = kind === "opportunity" ? "the options algo will trade on it" : `the ${ticker} hedge will use it`;
  const base = `I understand that the signal of this market has not passed its out-of-sample test for ${ticker}. It is an unvalidated estimate, but ${runs}. The app will label each decision and fill “unvalidated (acknowledged)”.`;
  // The backend: approving a proposal that sets act_on_unvalidated with the acknowledgement also confirms the override.
  return opts.override && kind === "hedge" ? `${base} ${OVERRIDE_ACK_COPY}` : base;
}

/** The gate of the generic AI fit flow (/build/fit). The fit itself is unvalidated (registry entry generic_ai_fit: its
 *  walk-forward test failed), so the acknowledgement is always needed, whatever the market's own closed-gap evidence
 *  says; a "validated" market badge is never shown as the fit's status. The badge words are the registry's. */
export function fitEvidenceGate(market: EvidenceGateView | null | undefined, fit: Mechanism | null | undefined): EvidenceGateView {
  const fitWhy = fit ? `${fit.name}: ${fit.claim}` : "The evidence registry was not read, so the generic AI fit is treated as unvalidated.";
  const mkt = market?.known
    ? ` This market's own closed-gap evidence (${market.badge.text}) is about the expected gap at a closure, not about this fit.`
    : "";
  return {
    known: true, validated: false, needsAck: true, reason: `${fitWhy}${mkt}`,
    badge: { tone: "caution", text: fit?.status_label || "unvalidated", title: fit?.actions_allowed.text ?? fitWhy },
  };
}

/** The acknowledgement for the generic AI fit: the fit's own status first, then the market's (when it is unvalidated
 *  too, the backend's own acknowledgement is part of the same tick). */
export function fitAckCopy(ticker: string, fit: Mechanism | null | undefined, market: EvidenceGateView | null | undefined,
  opts: { override?: boolean } = {}): string {
  const fitLine = `I understand that the generic AI fit is not validated (${fit?.status_label || "unvalidated"}) and that the ${ticker} hedge will use it anyway.`;
  return market?.needsAck ? `${fitLine} ${ackCopy(ticker, "hedge", opts)}` : opts.override ? `${fitLine} ${OVERRIDE_ACK_COPY}` : fitLine;
}

/** What the acknowledgement also confirms when the Weekend-mode override is on (POST /proposals/{id}/approve 409 text). */
export const OVERRIDE_ACK_COPY = "This also confirms the closed-market override. Staged plans (hedge B) on this market are labelled “override”, and no plan executes until I click Approve plan.";
/** The approval box line shown whenever the override is on, acknowledged or not. */
export const OVERRIDE_ON_LINE = "Override on: the app labels staged plans on this market “override”.";

/** The closed-market override: stage hedge B on a market whose expected gap is not validated. */
export const OVERRIDE_COPY = "Stage the weekend hedge (hedge B) on this market, although its expected gap is not validated. The app labels each staged plan “override”. No plan executes until you click Approve plan.";

/** Badge for the `evidence` label every decision / fill / staged / hedge_a event carries. */
export function evidenceLabelBadge(label: string | null | undefined): Badge | null {
  if (!label) return null;
  if (label === "validated") return { tone: "measured", text: "validated", title: "The signal of this market passed its out-of-sample test." };
  if (label.startsWith("unvalidated")) return { tone: "caution", text: "unvalidated · acknowledged", title: "You approved this with the acknowledgement that the signal of this market did not pass its out-of-sample test." };
  if (label === "override") return { tone: "caution", text: "override · unvalidated", title: "Closed-market override: the plan is staged on a market with an expected gap that is not validated." };
  return { tone: "neutral", text: label };
}

/** True for the backend's evidence refusals (409 EVIDENCE_UNVALIDATED at approval / bridge start, EVIDENCE_GATE when staging). */
export const isEvidenceError = (e: unknown) => {
  const m = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  return /EVIDENCE_(UNVALIDATED|GATE)/.test(m);
};

// ------------------------------------------------------------------ gates on fills (liquidity, capital)

export interface GateEntry { reason?: string; limit?: string; limit_qty?: number; capped_from?: number; rule?: string; enforced?: boolean; breaches?: string[] }
export interface GatedFill {
  status?: string; reject_reason?: string | null; gates?: GateEntry[] | null; evidence?: string | null; capped_from?: number;
  liquidity?: { status?: string; rule?: string; limit_qty?: number; note?: string } | null;
  capital?: { ok?: boolean; enforced?: boolean; checked?: boolean; scope?: string; note?: string | null; breaches?: { kind?: string; detail?: string }[] | null } | null;
}

const LIMIT_NAME: Record<string, string> = {
  per_order_open5: "10% of the opening 5-min volume",
  per_day_adv: "1% of ADV per day",
  volume: "10% of the contract's volume",
  open_interest: "5% of open interest",
};
export const bindingLabel = (b: string | null | undefined) => (b ? LIMIT_NAME[b] ?? b.replaceAll("_", " ") : "n/a");

const breachName = (k: string) => ({
  gross_hedge_notional: "gross hedge budget", event_exposure: "per-event budget", buying_power: "buying power",
  maintenance_margin: "maintenance margin", account_unreadable: "account unreadable", check_failed: "check failed",
} as Record<string, string>)[k] ?? k.replaceAll("_", " ");

/** The badges a trade card shows: the evidence label, and each gate that capped or refused the order. */
export function fillBadges(f: GatedFill | null | undefined, decisionEvidence?: string | null): Badge[] {
  const out: Badge[] = [];
  const ev = evidenceLabelBadge(f?.evidence ?? decisionEvidence);
  if (ev) out.push(ev);
  if (!f) return out;
  const gates = f.gates ?? [];
  for (const g of gates) {
    if (g.reason === "liquidity_capped") {
      const from = fin(g.capped_from) ? Math.round(g.capped_from) : null, to = fin(g.limit_qty) ? Math.floor(g.limit_qty) : null;
      out.push({ tone: "caution", text: `liquidity capped${from != null && to != null ? ` · ${from.toLocaleString("en-US")}→${to.toLocaleString("en-US")}` : ""}`,
        title: `Participation cap: ${g.rule ?? bindingLabel(g.limit)}. Later orders get the remaining quantity.` });
    } else if (g.reason === "capital_budget") {
      const what = (g.breaches ?? []).map(breachName).join(", ");
      out.push(g.enforced === false
        ? { tone: "neutral", text: "capital budget · advisory", title: `This order would go over the account budget (${what || "budget"}). The replay sandbox does not enforce the budget.` }
        : { tone: "caution", text: "capital budget · refused", title: `The app rejected this order before it went to the broker: ${what || "budget"}.` });
    }
  }
  const rr = f.reject_reason ?? "";
  if (!gates.some((g) => g.reason === "liquidity_capped") && rr.startsWith("liquidity_capped")) out.push({ tone: "caution", text: "liquidity capped", title: rr });
  if (!gates.some((g) => g.reason === "capital_budget") && rr.startsWith("capital_budget")) out.push({ tone: "caution", text: "capital budget · refused", title: rr });
  return out;
}

/** One sentence for the trade log: why a gate capped or refused this order (empty when none did). */
export function gateSentence(f: GatedFill | null | undefined): string {
  if (!f) return "";
  const parts: string[] = [];
  for (const g of f.gates ?? []) {
    if (g.reason === "liquidity_capped") {
      parts.push(`Liquidity cap (${g.rule ?? bindingLabel(g.limit)}) cut it from ${fin(g.capped_from) ? Math.round(g.capped_from) : "?"} to ${fin(g.limit_qty) ? Math.floor(g.limit_qty) : "?"}.`);
    } else if (g.reason === "capital_budget") {
      const what = (g.breaches ?? []).map(breachName).join(", ") || "the budget";
      parts.push(g.enforced === false ? `It would go over ${what}. This is advisory only in the replay sandbox.` : `Capital budget refused it (${what}).`);
    }
  }
  if (!parts.length && f.reject_reason && /^(liquidity_capped|capital_budget)/.test(f.reject_reason)) parts.push(`Held: ${f.reject_reason}.`);
  return parts.join(" ");
}

// ------------------------------------------------------------------ liquidity & capacity

export interface CapacityRow { k: string; v: string; sub?: string; warn?: boolean }
export interface CapacityView {
  available: boolean;
  reason?: string;
  rows: CapacityRow[];
  binding: string;
  /** "fits in one order at the open" / "needs N orders" / "unknown". */
  verdict: Badge;
  sources: string[];
  stale: boolean;
}

function freshnessText(f: Freshness | null | undefined): { text: string; stale: boolean } {
  if (!f) return { text: "age unknown", stale: false };
  const age = fin(f.age_s) ? (f.age_s < 60 ? `${Math.round(f.age_s)} s old` : `${Math.round(f.age_s / 60)} min old`) : "";
  const stale = !!f.cache_stale || f.staleness === "stale_cache";
  return { text: stale ? `stale cache${age ? ` (${age})` : ""}: last good value, the refresh did not complete` : f.staleness === "fresh" ? "fresh" : age || f.staleness || "cached", stale };
}

const spreadSource = (s: string | null | undefined) =>
  s === "quote" ? "Massive last NBBO quote" : s === "corwin_schultz_estimate" ? "Corwin-Schultz estimate (no quote)" : s ?? "unknown";

/** The capacity card from a proposal's capacity block (the hedge at its approved size) — Build approval step. */
export function capacityFromProposal(c: Capacity | null | undefined): CapacityView {
  const e = c?.equity;
  if (!c || c.error && !e) return { available: false, reason: c?.error ?? "This proposal has no capacity data.", rows: [], binding: "n/a", verdict: { tone: "neutral", text: "capacity unknown" }, sources: [], stale: false };
  if (!e) return { available: false, reason: c.options?.note ?? "This proposal has no equity leg.", rows: [], binding: "n/a", verdict: { tone: "neutral", text: "caps per structure at bridge start" }, sources: [], stale: false };
  if (!e.available) return { available: false, reason: e.reason ?? "Liquidity data is not available. The app does not cap orders and labels them “unknown”.", rows: [], binding: "n/a", verdict: { tone: "neutral", text: "caps unknown" }, sources: [], stale: false };
  const fr = freshnessText(e.freshness);
  const inside = e.inside_caps;
  const rows: CapacityRow[] = [
    { k: "HEDGE AT APPROVED SIZE", v: shares(e.hedge_shares), sub: e.hedge_notional_usd != null ? `${usd(e.hedge_notional_usd)} notional` : undefined },
    { k: "MAX ORDER", v: shares(e.max_order_shares), sub: "per order at the open", warn: inside === false },
    { k: "MAX POSITION / DAY", v: shares(e.per_day_shares), sub: "1% of 20-day ADV" },
    { k: "EST. COST", v: bp(e.est_cost_bp, 2), sub: e.cost ? `${bp(e.cost.half_spread_bp, 2)} half-spread + ${bp(e.cost.impact_bp, 2)} impact` : undefined },
    { k: "BOOK-SIZE CAPACITY", v: usd(e.book_usd_capacity), sub: `holding with a hedge that fits one order at the open${fin(e.book_usd_within_one_session) ? `, ${usd(e.book_usd_within_one_session)} in one session` : ""}` },
    { k: "SESSIONS NEEDED", v: fin(e.sessions_needed) ? String(e.sessions_needed) : "n/a", sub: fin(e.orders_at_open_needed) ? `${e.orders_at_open_needed} order${e.orders_at_open_needed === 1 ? "" : "s"} at the open` : undefined, warn: fin(e.sessions_needed) && e.sessions_needed > 1 },
  ];
  const verdict: Badge = inside === true
    ? { tone: "measured", text: "inside the caps", title: "The full hedge fits one order at the open." }
    : inside === false ? { tone: "caution", text: "above one order's cap", title: e.note ?? "The app caps orders (liquidity_capped). Later orders get the remaining quantity." }
    : { tone: "neutral", text: "caps unknown" };
  const sources = [
    `Price, ADV, σ: Massive daily bars (${c.source === "cache" ? "cached" : "live"}; ${fr.text})`,
    `Spread: ${spreadSource(e.spread_source)}${fin(e.spread_bp) ? ` (${bp(e.spread_bp, 2)})` : ""}`,
    "Opening volume: Massive 5-minute bars (09:30 ET, median of 20 sessions)",
  ];
  return { available: true, rows, binding: bindingLabel(e.binding), verdict, sources, stale: fr.stale };
}

/** The capacity card from GET /liquidity/{ticker} (Bridge screen and the Build preview). `hedgeShares` is the hedge the
 *  bridge is approved for (coverage x shares), when known. */
export function capacityFromLiquidity(l: LiquidityEquity | null | undefined, hedgeShares?: number | null): CapacityView {
  if (!l) return { available: false, reason: "The app reads the liquidity data…", rows: [], binding: "n/a", verdict: { tone: "neutral", text: "no data yet" }, sources: [], stale: false };
  if (!l.available) return { available: false, reason: l.reason ?? "Liquidity data is not available. The app does not cap orders and labels them “unknown”.", rows: [], binding: "n/a", verdict: { tone: "neutral", text: "caps unknown" }, sources: [], stale: false };
  const fr = freshnessText(l.freshness);
  const inside = fin(hedgeShares) && fin(l.max_order_shares) ? hedgeShares <= l.max_order_shares : null;
  const rows: CapacityRow[] = [
    { k: "MAX ORDER", v: shares(l.max_order_shares), sub: "per order at the open", warn: inside === false },
    { k: "MAX POSITION / DAY", v: shares(l.max_position_shares ?? l.per_day_shares), sub: "1% of 20-day ADV" },
    { k: "EST. COST", v: bp(l.est_cost_bp, 2), sub: l.cost ? `at ${shares(l.cost.qty)}: ${bp(l.cost.half_spread_bp, 2)} half-spread + ${bp(l.cost.impact_bp, 2)} impact` : undefined },
    { k: "BOOK-SIZE CAPACITY", v: usd(l.capacity?.book_usd), sub: `at ${pctOf(l.capacity?.coverage)} coverage${fin(l.capacity?.book_usd_within_one_session) ? `, ${usd(l.capacity!.book_usd_within_one_session)} in one session` : ""}` },
    { k: "ADV", v: fin(l.adv_shares) ? shares(l.adv_shares) : "n/a", sub: fin(l.adv_usd) ? usd(l.adv_usd) : undefined },
    { k: "DAILY σ", v: pctOf(l.sigma_daily, 2), sub: "last 20 daily returns" },
  ];
  const verdict: Badge = inside === true ? { tone: "measured", text: "hedge inside the caps" }
    : inside === false ? { tone: "caution", text: "hedge above one order's cap", title: "The app caps orders (liquidity_capped). Later orders get the remaining quantity." }
    : { tone: "neutral", text: "per-order caps active" };
  const sp = l.sources?.spread;
  const sources = [
    `Daily bars: ${l.sources?.daily_bars?.source ?? "Massive"}${l.sources?.daily_bars?.as_of ? ` as of ${l.sources.daily_bars.as_of.slice(0, 10)}` : ""} (${fr.text})`,
    `Spread: ${spreadSource(l.spread_source)}${fin(l.spread_bp) ? ` (${bp(l.spread_bp, 2)})` : ""}${sp?.note ? ` (${sp.note})` : ""}`,
    `Opening volume: ${l.sources?.open5?.source ?? "Massive 5-minute bars"}`,
  ];
  return { available: true, rows, binding: bindingLabel(l.binding), verdict, sources, stale: fr.stale };
}

/** Prediction-market depth line for the capacity card (max order within 2 cents of the mid, both sides). */
export function pmDepthLine(c: Capacity | null | undefined): string | null {
  const pm = c?.pm;
  if (!pm) return null;
  if (!pm.available) return `Prediction market book: not available (${pm.reason ?? "no book"}).`;
  const mo = pm.max_order_contracts, d2 = pm.depth;
  const at2 = (side: "buy" | "sell") => d2?.[side]?.["2c"]?.usd;
  return `Prediction market book (${pm.source ?? "venue"}): max order ${fin(mo?.buy) ? mo!.buy!.toLocaleString("en-US") : "n/a"} buy / ${fin(mo?.sell) ? mo!.sell!.toLocaleString("en-US") : "n/a"} sell contracts (50% of depth within 2¢, with ${usd(at2("buy"))} / ${usd(at2("sell"))} resting).`;
}

/** The capital line of a proposal: does the full hedge fit the account budget? */
export function capitalFitView(c: Capacity | null | undefined): { badge: Badge; lines: string[] } {
  const k = c?.capital;
  if (!k) return { badge: { tone: "neutral", text: "capital not checked" }, lines: ["The app does the capital check only for live proposals."] };
  if (!k.checked || k.fits == null) return { badge: { tone: "neutral", text: "capital not checked" }, lines: [k.note ?? "The app did not check the account budget."] };
  const lines: string[] = [];
  if (k.gross) lines.push(`Gross hedge ${usd(k.gross.now)} → ${usd(k.gross.after)} of ${usd(k.gross.limit_usd)} (${pctOf(k.limits?.max_gross_hedge_pct)} of equity)`);
  if (k.event) lines.push(`This event ${usd(k.event.now)} → ${usd(k.event.after)} of ${usd(k.event.limit_usd)} (${pctOf(k.limits?.max_event_pct)} of equity)`);
  if (k.buying_power) lines.push(`Buying power needed ${usd(k.buying_power.required)} of ${usd(k.buying_power.available)} (${k.buying_power.basis ?? "basis"})`);
  for (const b of k.breaches ?? []) lines.push(`Breach: ${breachName(b.kind)}${b.detail ? `: ${b.detail}` : ""}`);
  return { badge: k.fits ? { tone: "measured", text: "fits the capital budget" } : { tone: "caution", text: "breaches the capital budget", title: "The app rejects an order that increases exposure and goes over a budget (capital_budget)." }, lines };
}

// ------------------------------------------------------------------ capital usage (Portfolio)

export interface Meter { k: string; used: number | null; limit: number | null; frac: number | null; text: string; warn: boolean }
export interface CapitalView {
  read: boolean;
  /** False: the broker has no account read, so the budget is not enforced (not fail-closed). */
  checked: boolean;
  /** The live read failed and the backend served its last good read. */
  stale: Badge | null;
  /** Header tag: breaches, "within budget" (only on a real read) or "budget not checked". */
  status: Badge;
  error: string | null;
  /** How orders are gated right now, worded by the actual case. */
  enforcement: string;
  tiles: CapacityRow[];
  meters: Meter[];
  events: Meter[];
  breaches: string[];
  note: string;
}

function meter(k: string, used: number | null | undefined, limit: number | null | undefined): Meter {
  const u = fin(used) ? used : null, l = fin(limit) ? limit : null;
  const frac = u != null && l ? u / l : null;
  return { k, used: u, limit: l, frac, text: `${usd(u)} of ${usd(l)}${frac != null ? ` · ${(frac * 100).toFixed(frac < 0.1 && frac > 0 ? 1 : 0)}%` : ""}`, warn: frac != null && frac > 0.8 };
}

/** The capital budget in words, from the limits the backend enforces (GET /capital `limits`, CAPITAL_MAX_GROSS_PCT /
 *  CAPITAL_MAX_EVENT_PCT); no numbers when the limits are not known, so the copy never disagrees with the gate. */
export function budgetPhrase(lim: Pick<CapitalLimits, "max_gross_hedge_pct" | "max_event_pct"> | null | undefined): string {
  if (!lim || !fin(lim.max_gross_hedge_pct) || !fin(lim.max_event_pct)) return "gross hedge, per-event and buying-power limits";
  return `gross hedge ≤ ${pctOf(lim.max_gross_hedge_pct)} of equity, one event ≤ ${pctOf(lim.max_event_pct)}, buying power`;
}

export function capitalView(c: CapitalOut | null | undefined): CapitalView {
  if (!c) return { read: false, checked: false, stale: null, status: { tone: "neutral", text: "budget not read" }, error: "The app reads the capital budget…", enforcement: "", tiles: [], meters: [], events: [], breaches: [], note: "" };
  const read = c.account_read !== false && fin(c.equity);
  // account_checked is false when the broker has no account read; older payloads: a failed read carries the
  // account_unreadable breach, so its absence on an unread account means "not checked".
  const checked = c.account_checked ?? (read || (c.breaches ?? []).some((b) => b.kind === "account_unreadable"));
  const tiles: CapacityRow[] = [
    { k: "EQUITY", v: usd(c.equity, { compact: false }), sub: c.account_label ? `${c.account_label}${c.account_type ? ` (${c.account_type})` : ""}` : undefined },
    { k: "BUYING POWER", v: usd(c.buying_power, { compact: false }), sub: c.buying_power_basis ? `Basis: ${c.buying_power_basis}` : undefined },
    { k: "GROSS HEDGE NOTIONAL", v: usd(c.gross_hedge_notional, { compact: false }), sub: `Equity hedge ${usd(c.equity_hedge_usd)}, staged ${usd(c.staged_pending_usd)}, options ${usd(c.option_risk_usd)}` },
    { k: "MARGIN USED (INITIAL)", v: usd(c.margin?.initial_required, { compact: false }), sub: `Maintenance ${usd(c.margin?.maintenance_required)}, excess ${usd(c.margin?.excess_over_maintenance)}` },
  ];
  const lim = c.limits;
  const meters = [meter(`Gross hedge (≤ ${pctOf(lim?.max_gross_hedge_pct)} of equity)`, c.gross_hedge_notional, c.gross_limit_usd)];
  if (fin(c.equity) && c.margin) meters.push(meter("Maintenance margin (≤ equity)", c.margin.maintenance_required, c.equity));
  const events = (c.events ?? []).map((e) => meter(e.event, e.total_usd, e.limit_usd));
  const breaches = (c.breaches ?? []).map((b) => `${breachName(b.kind)}${b.event ? ` (${b.event})` : ""}${fin(b.after_usd) && fin(b.limit_usd) ? `: ${usd(b.after_usd)} vs limit ${usd(b.limit_usd)}` : b.detail ? `: ${b.detail}` : ""}`);
  const why = c.account_error ? ` (${c.account_error})` : "";
  const error = read ? null
    : checked ? `Account unreadable${why}: exposure-increasing orders are refused (fail closed).`
    : `Capital budget not checked${why}: this broker gives no account read, so orders are not checked against the budget.`;
  const enforcement = read
    ? `The app rejects an order before it goes to the broker if the order would go over a budget (capital_budget). If the app cannot read the account, it rejects these orders also (fail closed).${c.account_stale ? " The last live read did not complete. These values are from the last good read." : ""}`
    : checked ? "The account read failed, so every exposure-increasing order is refused until it can be read again (fail closed)."
    : "Nothing is enforced against the capital budget until the broker gives account data.";
  const age = fin(c.account_age_s) ? ` · ${Math.round(c.account_age_s)}s old` : "";
  const stale: Badge | null = c.account_stale ? { tone: "caution", text: `stale${age}`, title: `The live account read did not complete${why}. The values are from the last good read.` } : null;
  const status: Badge = breaches.length
    ? { tone: "caution", text: `${breaches.length} breach${breaches.length === 1 ? "" : "es"}`, title: breaches.join("\n") }
    : read ? { tone: "measured", text: "within budget" }
    : { tone: "neutral", text: "budget not checked", title: c.account_error ?? undefined };
  return { read, checked, stale, status, error, enforcement, tiles, meters, events, breaches, note: c.note ?? "" };
}

// ------------------------------------------------------------------ broker account (Webull paper)

/** The nav / Portfolio account pill: "Webull paper · Individual Margin · market closed". */
export function accountPill(a: AccountOut | null | undefined, session?: Pick<SessionView, "equities_open"> | null): { text: string; tone: Tone; title: string } {
  if (!a) return { text: "Account not available", tone: "demo", title: "The app cannot read the account." };
  const webull = (a.broker ?? "").toLowerCase().includes("webull");
  const name = webull ? "Webull paper" : "Simulated account";
  const open = session?.equities_open ?? a.market_open;
  const parts = [name, ...(a.account_label ? [a.account_label] : []), ...(open == null ? [] : [open ? "market open" : "market closed"])];
  return { text: parts.join(" · "), tone: webull ? "paper" : "sim", title: a.note ?? (webull ? "Webull paper account on the sandbox host. It accepts orders from 09:30 to 16:00 ET." : "Simulated account in the app.") };
}

/** Which Webull figure BUYING POWER is: webull.py uses an explicit buying_power / stock_buying_power when Webull sends
 *  one and the overnight figure (else intraday) only as a fallback, so the label follows the numbers. */
function bpBasis(a: AccountOut): string | undefined {
  if (fin(a.overnight_buying_power) && a.buying_power === a.overnight_buying_power) return "overnight figure";
  if (fin(a.day_buying_power) && a.buying_power === a.day_buying_power && !fin(a.overnight_buying_power)) return "intraday figure";
  return undefined;
}

export function accountRows(a: AccountOut | null | undefined): CapacityRow[] {
  if (!a) return [];
  const rows: CapacityRow[] = [
    { k: "CASH", v: usd(a.cash, { compact: false }) },
    { k: "EQUITY", v: usd(a.equity, { compact: false }) },
    { k: "BUYING POWER", v: usd(a.buying_power, { compact: false }), sub: bpBasis(a) },
  ];
  if (fin(a.day_buying_power)) rows.push({ k: "DAY BUYING POWER", v: usd(a.day_buying_power, { compact: false }) });
  if (fin(a.option_buying_power)) rows.push({ k: "OPTION BUYING POWER", v: usd(a.option_buying_power, { compact: false }) });
  if (fin(a.market_value)) rows.push({ k: "MARKET VALUE", v: usd(a.market_value, { compact: false }) });
  if (fin(a.unrealized_pnl)) rows.push({ k: "UNREALIZED P&L", v: usd(a.unrealized_pnl, { compact: false, sign: true }) });
  if (fin(a.maintenance_margin)) rows.push({ k: "MAINTENANCE MARGIN", v: usd(a.maintenance_margin, { compact: false }) });
  if (a.day_trades_left != null) rows.push({ k: "DAY TRADES LEFT", v: String(a.day_trades_left).toLowerCase() });
  return rows;
}

/** Broker positions vs demo seed rows (GET /positions?include_demo=true labels each row by `account`). */
export function splitPositions(ps: BrokerPosition[]): { broker: BrokerPosition[]; demo: BrokerPosition[] } {
  const isDemo = (p: BrokerPosition) => p.broker === "demo" || p.account === "demo holdings";
  return { broker: ps.filter((p) => !isDemo(p) && p.qty !== 0), demo: ps.filter(isDemo) };
}

export const ORIGIN_LABEL: Record<string, string> = { polybridge: "placed here", webull_open: "open at Webull", webull_history: "Webull history" };

/** Order history rows, newest first, with where each came from and the broker's own status word. */
export function orderRows(os: BrokerOrder[]): { key: string; when: string; side: string; qty: number; symbol: string; status: string; px: string; origin: string; title: string }[] {
  const ts = (o: BrokerOrder) => Date.parse(o.filled_at ?? o.created_at ?? "") || 0;
  return [...os].sort((a, b) => ts(b) - ts(a)).map((o) => {
    const px = o.fill_px ?? o.filled_px ?? o.avg_fill_px ?? o.limit_px ?? null;
    const when = o.filled_at ?? o.created_at ?? null;
    return {
      key: o.id, when: when ? when.replace("T", " ").slice(0, 16) : "n/a", side: o.side.toUpperCase(), qty: o.qty, symbol: o.symbol,
      status: `${o.status ?? "unknown"}${o.broker_status && o.broker_status.toLowerCase() !== (o.status ?? "").toLowerCase() ? ` (${o.broker_status})` : ""}`,
      px: px == null ? "mkt" : px.toFixed(2), origin: o.origin ? ORIGIN_LABEL[o.origin] ?? o.origin : "",
      title: [o.reject_reason, o.note].filter(Boolean).join(" · "),
    };
  });
}

/** One line on the order reconciler: running / idle (why) / stopped, passes and the last result. */
export function reconcileView(r: ReconcileStatus | null | undefined): { badge: Badge; line: string } {
  if (!r) return { badge: { tone: "neutral", text: "reconcile n/a" }, line: "The reconciler status is not available." };
  if (r.supported === false) return { badge: { tone: "neutral", text: "no reconciler" }, line: `${r.broker ?? "This broker"} fills orders in the app. There is nothing to reconcile.` };
  const lr = r.last_result;
  const last = lr ? ` Last pass: ${lr.checked ?? 0} tracked, ${lr.open_at_webull ?? 0} open at Webull, ${lr.updated ?? 0} updated.` : "";
  const errs = r.errors ? ` Errors: ${r.errors}${r.last_error ? ` (last: ${r.last_error})` : ""}.` : "";
  if (!r.running) return { badge: { tone: "neutral", text: "reconciler stopped" }, line: `The reconciler starts at the first broker request when BROKER=webull.${last}${errs}` };
  if (r.state === "idle") return { badge: { tone: "sim", text: "reconciler idle" }, line: `${r.idle_reason ?? "The reconciler is idle."} Passes: ${r.passes ?? 0}.${last}${errs}` };
  return { badge: { tone: "live", text: "reconciling" }, line: `The reconciler runs every ${r.interval_s ?? 15} s during the regular session. Passes: ${r.passes ?? 0}.${last}${errs}` };
}

// ------------------------------------------------------------------ staged plans (hedge B)

/** Badges on a staged order: its evidence gate ("validated" / "override") and any capital or liquidity decision. */
export function stagedBadges(o: { evidence_gate?: string | null; evidence?: string | null; reason?: string | null; decisions?: { code: string; detail?: string | null }[] | null; liquidity?: { status?: string; rule?: string } | null; capital?: { ok?: boolean; enforced?: boolean } | null }): Badge[] {
  const out: Badge[] = [];
  const ev = evidenceLabelBadge(o.evidence_gate ?? o.evidence);
  if (ev) out.push(ev);
  const codes = new Set((o.decisions ?? []).map((d) => d.code));
  const detail = (c: string) => (o.decisions ?? []).find((d) => d.code === c)?.detail ?? undefined;
  if (codes.has("LIQUIDITY_CAPPED") || o.liquidity?.status === "capped") out.push({ tone: "caution", text: "liquidity capped", title: detail("LIQUIDITY_CAPPED") ?? o.liquidity?.rule });
  if (o.reason === "CAPITAL_BUDGET" || codes.has("CAPITAL_BUDGET") || (o.capital && o.capital.ok === false && o.capital.enforced !== false)) out.push({ tone: "caution", text: "capital budget", title: detail("CAPITAL_BUDGET") ?? "Rejected: the order would go over the capital budget of the account." });
  else if (codes.has("CAPITAL_BUDGET_ADVISORY")) out.push({ tone: "neutral", text: "capital budget · advisory", title: detail("CAPITAL_BUDGET_ADVISORY") });
  return out;
}

/** How many orders the participation caps cut and the capital budget refused, from the fills seen on the stream
 *  (the summary's counters are read once; the larger of the two is shown). */
export function gateCounts(fills: (GatedFill | null | undefined)[], summary?: { liquidity_capped?: number; capital_refused?: number } | null): { liquidity: number; capital: number } {
  let liquidity = 0, capital = 0;
  for (const f of fills) {
    if (!f) continue;
    const gs = f.gates ?? [];
    if (gs.some((g) => g.reason === "liquidity_capped") || (f.reject_reason ?? "").startsWith("liquidity_capped")) liquidity++;
    if (gs.some((g) => g.reason === "capital_budget" && g.enforced !== false) || (f.reject_reason ?? "").startsWith("capital_budget")) capital++;
  }
  return { liquidity: Math.max(liquidity, summary?.liquidity_capped ?? 0), capital: Math.max(capital, summary?.capital_refused ?? 0) };
}
