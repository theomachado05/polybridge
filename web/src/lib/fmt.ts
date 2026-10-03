// Pure formatting helpers shared by the screens, the demo simulator and the offline tests.
// Kept dependency-free so `node --test` can import it directly.

export const MINUS = "−";

export const fmtPct = (n: number, d = 1) => (n > 0 ? "+" : n < 0 ? MINUS : "") + Math.abs(n).toFixed(d) + "%";

export const fmtK = (n: number) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n)));

export const fmtMoney = (n: number, sign = false) =>
  (n < 0 ? MINUS : sign ? "+" : "") + "$" + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

export const fmtTime = (d: Date) => d.toLocaleTimeString("en-US", { hour12: false });

export const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");

export const fmtNs = (ns: number | null | undefined) =>
  ns == null || !Number.isFinite(ns) ? "n/a" : ns >= 1e6 ? (ns / 1e6).toFixed(1) + " ms" : ns >= 1e3 ? (ns / 1e3).toFixed(1) + " µs" : Math.round(ns) + " ns";

/** SVG path for a sparkline in a w×h box (the prototype's `path`). */
export function sparkPath(arr: number[], w: number, h: number): string {
  if (arr.length < 2) return "";
  const min = Math.min(...arr), max = Math.max(...arr), span = Math.max(1e-6, max - min);
  return arr.map((v, i) => `${i ? "L" : "M"}${((i / (arr.length - 1)) * w).toFixed(1)} ${(h - 4 - ((v - min) / span) * (h - 8)).toFixed(1)}`).join(" ");
}

/** "equity_delta_bridge" -> "Equity Delta Bridge". */
export const prettyId = (id: string) => id.split(/[_\-\s]+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
