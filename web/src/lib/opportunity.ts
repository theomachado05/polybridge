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
