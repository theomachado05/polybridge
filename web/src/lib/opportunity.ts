// Pure helpers for the Opportunity (options) bridge view; unit-tested offline.
import type { FillInfo, OptionLegFill } from "./bridgeStream.ts";

/** "+3.2 pts" / "−1.0 pts" for a PM − options gap in probability units; "n/a" when either side is missing. */
export function gapPts(gap: number | null | undefined): string {
  if (gap == null || !Number.isFinite(gap)) return "n/a";
  const v = gap * 100;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} pts`;
}

export const probPct = (p: number | null | undefined) => (p == null || !Number.isFinite(p) ? "n/a" : `${(p * 100).toFixed(1)}%`);

/** One line per option leg: "BUY 2 O:NVDA261218C00145000 @ 8.10 (quote 8.00 ± 0.10)". */
export function legLine(l: OptionLegFill): string {
  const px = l.fill_px != null ? ` @ ${l.fill_px.toFixed(2)}` : "";
  const q = l.quote_mid != null ? ` (quote ${l.quote_mid.toFixed(2)}${l.quote_half_spread != null ? ` ± ${l.quote_half_spread.toFixed(2)}` : ""})` : " (no quote: broker price)";
  return `${l.side.toUpperCase()} ${l.qty} ${l.ticker}${px}${q}`;
}

/** Head and explanation of one option fill ("fill" SSE event of an opportunity bridge). Always says it is simulated. */
export function optionFillText(f: FillInfo): { head: string; detail: string } {
  const what = `${f.qty ?? 0} ${f.structure ? f.structure.replaceAll("_", " ") : "option structure"}${(f.qty ?? 0) === 1 ? "" : "s"}`;
  const px = f.status === "filled" && f.fill_px != null ? ` @ ${f.fill_px.toFixed(2)}/sh net` : "";
  const cap = f.capped_from != null ? ` Risk cap (${f.cap ?? "cap"}) clipped it from ${f.capped_from}.` : "";
  const routed = f.routed ? ` Routed to the ${f.routed}.` : "";
  const status = f.status === "filled" ? `Simulated fill by ${f.broker ?? "the simulator"}${f.fee ? `, fees $${f.fee.toFixed(2)}` : ""}.`
    : f.status === "held" ? `Held: ${f.reject_reason ?? "risk cap"}.`
    : f.status === "rejected" ? `Rejected: ${f.reject_reason ?? "unknown"}.`
    : f.status === "error" ? `Broker error (${f.error ?? f.reject_reason ?? "unknown"}); nothing filled.` : `Status: ${f.status ?? "unknown"}.`;
  const legs = (f.legs ?? []).map(legLine).join("; ");
  return { head: `${what}${px}`, detail: `${status}${cap}${routed}${legs ? ` Legs: ${legs}.` : ""}${f.price_note ? ` ${f.price_note}.` : ""}` };
}

/** Plain-language pitch per options family, used when the library's own `idea` text is not loaded. */
const OPTION_FAMILY_PITCH: Record<string, string> = {
  binary_vs_spread_arb: "Trade the gap between this market's price and the options-implied probability of the same threshold, with a call or put spread; exit when the gap closes.",
  vol_vs_pm_move: "When this market reprices but options implied volatility has not moved, buy a straddle; when IV spikes while the market is quiet, sell it.",
  eightk_opportunity: "A strong 8-K filing opens an event window; if this market's adverse probability confirms the filing's direction, sell a cash-secured put or buy a put spread.",
};

/** What the offered options family does: the library's `idea` when known, else the built-in pitch for that family. */
export function optionFamilyIdea(family: string | null | undefined, libraryIdea?: string | null): string {
  if (libraryIdea && libraryIdea.trim()) return libraryIdea.trim().replace(/\.?$/, ".");
  return (family && OPTION_FAMILY_PITCH[family]) || "Trade this market against listed options.";
}

/** The honest caveat for an opportunity replay score: the replay's option prices are estimates from bar closes. */
export const OPP_REPLAY_NOTE = "Replay score on this market's history; the replay's option prices are estimates from hourly or daily bar closes of the option legs, not quotes. Option fills are simulated.";

/** The `idea` text of one family from a GET /library answer (either shape), or null. */
export function libraryIdea(lib: { families?: { id: string; idea?: string }[] } | { id: string; idea?: string }[] | null | undefined, family: string | null | undefined): string | null {
  if (!lib || !family) return null;
  const fams = Array.isArray(lib) ? lib : lib.families ?? [];
  return fams.find((f) => f.id === family)?.idea ?? null;
}
