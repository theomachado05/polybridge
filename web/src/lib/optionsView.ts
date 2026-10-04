import type { ChainContract, HedgeQuoteOut, HedgeStrategy, HedgeStrategyId, LiveChainOut, OptionMark, QuoteLeg } from "./api.ts";
import { bp, usd, type Badge } from "./risk.ts";

const fin = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const px = (x: number | null | undefined) => (fin(x) ? x.toFixed(2) : "n/a");

export interface LadderRow { strike: number; call: ChainContract | null; put: ChainContract | null; atm: boolean; callItm: boolean; putItm: boolean }

export function ladder(chain: Pick<LiveChainOut, "contracts" | "underlying_price"> | null | undefined): LadderRow[] {
  if (!chain?.contracts?.length) return [];
  const by = new Map<number, LadderRow>();
  const spot = chain.underlying_price?.price ?? null;
  for (const c of chain.contracts) {
    const r = by.get(c.strike) ?? { strike: c.strike, call: null, put: null, atm: false, callItm: false, putItm: false };
    if (c.right === "call") r.call = c; else r.put = c;
    by.set(c.strike, r);
  }
  const rows = [...by.values()].sort((a, b) => a.strike - b.strike);
  if (fin(spot)) {
    let best = rows[0];
    for (const r of rows) if (Math.abs(r.strike - spot) < Math.abs(best.strike - spot)) best = r;
    best.atm = true;
    for (const r of rows) { r.callItm = r.strike < spot; r.putItm = r.strike > spot; }
  }
  return rows;
}

export type GreekMark = "" | "c" | "c*";
export const GREEK_LEGEND = "c = computed (Black–Scholes from the mark). c* = Massive greeks, with the missing values computed. No mark = Massive values.";
export function greekMarks(c: Pick<ChainContract, "iv" | "delta" | "iv_source" | "greeks_source"> | null): { iv: GreekMark; delta: GreekMark } {
  if (!c) return { iv: "", delta: "" };
  const g = c.greeks_source;
  return {
    iv: fin(c.iv) && c.iv_source === "computed" ? "c" : "",
    delta: !fin(c.delta) ? "" : g === "computed" ? "c" : g === "massive+computed" ? "c*" : "",
  };
}

export function optionFillBadge(a: { broker?: string; options_supported?: boolean; options_route?: string | null } | null | undefined): Badge {
  if (!a) return { tone: "neutral", text: "fills: account n/a", title: "The account data is not available. The app does not know where option orders fill." };
  if (a.options_supported) return { tone: "paper", text: "Webull paper fills", title: `Option orders go to ${a.options_route ?? a.broker ?? "the broker"} (WEBULL_OPTIONS=1).` };
  return { tone: "sim", text: "simulated fills", title: `The simulator fills option orders.${(a.broker ?? "").includes("webull") ? " Webull paper options are off unless WEBULL_OPTIONS=1." : ""}` };
}

export function sideCells(c: ChainContract | null): { bid: string; ask: string; iv: string; delta: string; oi: string; vol: string; title: string; stale: boolean; marks: { iv: GreekMark; delta: GreekMark } } {
  if (!c) return { bid: "n/a", ask: "n/a", iv: "n/a", delta: "n/a", oi: "n/a", vol: "n/a", title: "not listed in this window", stale: false, marks: { iv: "", delta: "" } };
  const n = (x: number | null | undefined) => (fin(x) ? Math.round(x).toLocaleString("en-US") : "n/a");
  const src = c.quote_source === "massive_last_nbbo" ? "last NBBO (15-min delayed)" : c.mark_source === "fmv" ? "Massive fair value (no quote)" : c.quote_source ?? c.mark_source ?? "unknown";
  return {
    bid: px(c.bid), ask: px(c.ask), iv: fin(c.iv) ? `${(c.iv * 100).toFixed(1)}%` : "n/a", delta: fin(c.delta) ? c.delta.toFixed(2) : "n/a",
    oi: n(c.open_interest), vol: n(c.volume),
    title: `${c.ticker} · ${src} · IV ${c.iv_source ?? "n/a"} · greeks ${c.greeks_source ?? "n/a"}${c.liquidity_flags?.length ? ` · ${c.liquidity_flags.map(flagLabel).join(", ")}` : ""}${c.stale ? ` · stale${c.stale_reason ? `: ${c.stale_reason}` : ""}` : ""}`,
    stale: !!c.stale, marks: greekMarks(c),
  };
}

export function chainLabel(chain: LiveChainOut | null | undefined): Badge {
  if (!chain) return { tone: "neutral", text: "no chain yet" };
  if (!chain.available) return { tone: "neutral", text: "chain unavailable", title: chain.reason ?? undefined };
  const f = chain.freshness;
  const quoted = fin(f?.n_quoted) ? `${f!.n_quoted}/${chain.n_contracts ?? chain.contracts.length} quoted` : "";
  if (chain.market_open === false) return { tone: "sim", text: `last close${quoted ? ` · ${quoted}` : ""}`, title: chain.snapshot_label ?? "Market closed: these prices are from the last session. You cannot trade at these prices now." };
  return { tone: f?.n_stale ? "caution" : "live", text: `delayed NBBO${quoted ? ` · ${quoted}` : ""}${f?.n_stale ? ` · ${f.n_stale} stale` : ""}`, title: "Massive last NBBO, 15 minutes delayed." };
}

const FLAG: Record<string, string> = {
  low_open_interest: "low OI", thin_open_interest: "thin OI", size_vs_open_interest: "size vs OI", no_volume_last_session: "no volume",
  wide_spread: "wide spread", very_wide_spread: "very wide spread", estimated_spread: "estimated spread", stale_quote: "stale quote",
  borrow_rate_assumed: "borrow rate assumed", hard_to_borrow: "hard to borrow", ssr: "short-sale rule", no_quote: "no quote",
};
export const flagLabel = (f: string) => FLAG[f] ?? f.replaceAll("_", " ");

export const STRATEGY_NAME: Record<HedgeStrategyId, string> = {
  short_stock: "Short stock", protective_put: "Protective put", collar: "Collar", put_spread: "Put spread",
};
export const STRATEGY_ORDER: HedgeStrategyId[] = ["short_stock", "protective_put", "collar", "put_spread"];

export interface HedgeRow {
  id: HedgeStrategyId; name: string; available: boolean; reason: string | null; rank: number | null; cheapest: boolean;
  upfront: string; upfrontBp: string; expected: string; expectedBp: string; protection: string; upside: string; capital: string;
  ratio: string; liquidity: Badge; flags: string[]; legs: string[];
}

const liqBadge = (s: HedgeStrategy): Badge => {
  const g = s.liquidity ?? "unknown";
  return { tone: g === "liquid" ? "measured" : g === "thin" ? "caution" : g === "illiquid" ? "caution" : "neutral", text: g, title: (s.liquidity_flags ?? []).map(flagLabel).join(", ") || undefined };
};

export function legLine(l: QuoteLeg): string {
  const src = l.spread_source === "nbbo" ? "NBBO" : l.spread_source === "estimated" ? "estimated spread" : l.spread_source ?? "";
  return `${l.side === "sell" ? MINUS_SIGN : "+"}${l.contracts} ${l.right} ${l.strike} ${l.expiry} · bid ${px(l.bid)} × ask ${px(l.ask)}${src ? ` (${src})` : ""} · mid ${px(l.mid)}${l.stale ? " · stale" : ""}`;
}
const MINUS_SIGN = "−";

export function hedgeRows(hq: HedgeQuoteOut | null | undefined): HedgeRow[] {
  if (!hq?.strategies) return [];
  const order = hq.ranking?.order ?? [];
  return STRATEGY_ORDER.filter((id) => hq.strategies![id]).map((id) => {
    const s = hq.strategies![id]!;
    const rank = order.indexOf(id);
    const floor = s.protection?.floor_price, floorPct = s.protection?.floor_pct;
    const cap = s.upside?.cap_price, capPct = s.upside?.cap_pct;
    const capital = s.capital
      ? [fin(s.capital.cash_upfront_usd) && s.capital.cash_upfront_usd ? `${usd(s.capital.cash_upfront_usd)} cash` : null, fin(s.capital.margin_initial_usd) && s.capital.margin_initial_usd ? `${usd(s.capital.margin_initial_usd)} initial margin` : null].filter(Boolean).join(" + ") || "none"
      : "n/a";
    return {
      id, name: STRATEGY_NAME[id], available: s.available, reason: s.reason ?? null, rank: rank >= 0 ? rank + 1 : null, cheapest: hq.ranking?.cheapest === id,
      upfront: usd(s.upfront_usd, { compact: false }), upfrontBp: bp(s.upfront_bp, 1),
      expected: usd(s.expected_cost_usd, { compact: false }), expectedBp: bp(s.expected_cost_bp, 2),
      protection: fin(floor) ? `floor ${floor.toFixed(2)}${fin(floorPct) ? ` (${(floorPct * 100).toFixed(1)}%)` : ""}` : "none",
      upside: fin(cap) ? `capped at ${cap.toFixed(2)}${fin(capPct) ? ` (${capPct >= 0 ? "+" : ""}${(capPct * 100).toFixed(1)}%)` : ""}` : "uncapped",
      capital, ratio: fin(s.hedge_ratio) ? `${(s.hedge_ratio * 100).toFixed(0)}% delta-hedged` : "n/a",
      liquidity: liqBadge(s), flags: (s.liquidity_flags ?? []).map(flagLabel), legs: (s.legs ?? []).map(legLine),
    };
  });
}

export function hedgeNotes(hq: HedgeQuoteOut | null | undefined): string[] {
  if (!hq) return [];
  const out: string[] = [];
  if (hq.market_open === false) out.push("Market closed: the prices are from the last session close. You cannot trade at these prices now.");
  if (hq.expiry_covers_horizon === false && hq.expiry) out.push(`No listed expiry covers the ${hq.horizon_days}-day horizon. The option hedges use ${hq.expiry} and would need rolling.`);
  if (hq.assumptions?.borrow_rate_assumed) out.push(`Borrow fee assumed at ${((hq.assumptions.borrow_rate_annual ?? 0.003) * 100).toFixed(2)}%/yr (Massive and Webull do not give a borrow fee).`);
  out.push("The ranking uses only the expected trading friction. It ignores the upside each hedge gives up and the depth of its protection.");
  return out;
}

export function markLine(m: OptionMark | null | undefined): { text: string; tone: Badge["tone"]; title: string } {
  if (!m) return { text: "marking…", tone: "neutral", title: "" };
  if (!m.available || !fin(m.mark)) return { text: `no mark${m.reason ? ` (${m.reason})` : ""}`, tone: "neutral", title: m.reason ?? "" };
  const src = m.spread_source === "nbbo" ? "NBBO" : m.spread_source === "estimated" ? "estimated spread" : m.spread_source === "settlement" ? "settlement estimate" : m.spread_source ?? "";
  const hs = fin(m.half_spread) ? ` ± ${m.half_spread.toFixed(2)}` : "";
  const lastClose = m.market_open === false || (m.as_of_label ?? "").startsWith("last close");
  return {
    text: `mark ${m.mark.toFixed(2)}${hs}${src ? ` · ${src}` : ""}${lastClose ? " · last close" : ""}${m.stale ? " · stale" : ""}`,
    tone: m.stale || m.cache_stale ? "caution" : m.spread_source === "nbbo" && !lastClose ? "measured" : "sim",
    title: `${m.as_of_label ?? ""}${fin(m.exit_long) ? ` · exit long ${m.exit_long.toFixed(2)}` : ""}${fin(m.exit_short) ? ` · exit short ${m.exit_short.toFixed(2)}` : ""}${m.expired ? " · expired" : ""}`.replace(/^ · /, ""),
  };
}
