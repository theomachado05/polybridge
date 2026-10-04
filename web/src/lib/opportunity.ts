import type { FillInfo, OptionLegFill } from "./bridgeStream.ts";

export function gapPts(gap: number | null | undefined): string {
  if (gap == null || !Number.isFinite(gap)) return "n/a";
  const v = gap * 100;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} pts`;
}

export const probPct = (p: number | null | undefined) => (p == null || !Number.isFinite(p) ? "n/a" : `${(p * 100).toFixed(1)}%`);

export function legLine(l: OptionLegFill): string {
  const px = l.fill_px != null ? ` @ ${l.fill_px.toFixed(2)}` : "";
  const q = l.quote_mid != null ? ` (quote ${l.quote_mid.toFixed(2)}${l.quote_half_spread != null ? ` ± ${l.quote_half_spread.toFixed(2)}` : ""})` : " (no quote: broker price)";
  return `${l.side.toUpperCase()} ${l.qty} ${l.ticker}${px}${q}`;
}

export function optionFillText(f: FillInfo): { head: string; detail: string } {
  const what = `${f.qty ?? 0} ${f.structure ? f.structure.replaceAll("_", " ") : "option structure"}${(f.qty ?? 0) === 1 ? "" : "s"}`;
  const px = f.status === "filled" && f.fill_px != null ? ` @ ${f.fill_px.toFixed(2)}/sh net` : "";
  const cap = f.capped_from != null ? ` The risk cap (${f.cap ?? "cap"}) clipped it from ${f.capped_from}.` : "";
  const routed = f.routed ? ` Sent to the ${f.routed}.` : "";
  const status = f.status === "filled" ? `Simulated fill by ${f.broker ?? "the simulator"}${f.fee ? `, fees $${f.fee.toFixed(2)}` : ""}.`
    : f.status === "held" ? `Held: ${f.reject_reason ?? "risk cap"}.`
    : f.status === "rejected" ? `Rejected: ${f.reject_reason ?? "unknown"}.`
    : f.status === "error" ? `Broker error (${f.error ?? f.reject_reason ?? "unknown"}). No order filled.` : `Status: ${f.status ?? "unknown"}.`;
  const legs = (f.legs ?? []).map(legLine).join("; ");
  return { head: `${what}${px}`, detail: `${status}${cap}${routed}${legs ? ` Legs: ${legs}.` : ""}${f.price_note ? ` ${f.price_note}.` : ""}` };
}

const OPTION_FAMILY_PITCH: Record<string, string> = {
  binary_vs_spread_arb: "Trade the gap between the price of this market and the options-implied probability of the same threshold with a call or put spread. Close the trade when the gap closes.",
  vol_vs_pm_move: "If this market price changes but the implied volatility (IV) of the options does not change, buy a straddle. If IV increases quickly and the market price is stable, sell the straddle.",
  eightk_opportunity: "A strong 8-K filing starts an event window. If the adverse probability of this market agrees with the direction of the filing, sell a cash-secured put or buy a put spread.",
};

export function optionFamilyIdea(family: string | null | undefined, libraryIdea?: string | null): string {
  if (libraryIdea && libraryIdea.trim()) return libraryIdea.trim().replace(/\.?$/, ".");
  return (family && OPTION_FAMILY_PITCH[family]) || "Trade this market against listed options.";
}

export const OPP_REPLAY_NOTE = "The replay score comes from the history of this market. The option prices in the replay are estimates from hourly or daily bar closes of the option legs, not quotes. Option fills are simulated.";

export function libraryIdea(lib: { families?: { id: string; idea?: string }[] } | { id: string; idea?: string }[] | null | undefined, family: string | null | undefined): string | null {
  if (!lib || !family) return null;
  const fams = Array.isArray(lib) ? lib : lib.families ?? [];
  return fams.find((f) => f.id === family)?.idea ?? null;
}
