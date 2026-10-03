// AI pipeline screen: the six steps, either mapped from POST /pipeline/fit (classify, shortlist,
// history, tune, explain, ready) or, when the endpoint fails, the prototype's scripted steps (labelled demo).
import type { FitOut } from "./api";
import { fmtPct, prettyId } from "./fmt.ts";

export type OrbState = "connecting" | "working" | "searching" | "composing" | "breathing" | "listening";
export interface PipeStep { key: string; name: string; orb: OrbState; text: string }

export interface PipeContext {
  question: string; venues: string[]; yes: number; vol: string;
  ticker: string; held: number;
  move: number; rev: number | null; brand: number | null; why: string;
  shortlisted?: string[];   // family ids from GET /library for the fitted class
}

const scoreLabel = (division: string) => (division === "opportunity" ? "net P&L per unit risk" : "hedge variance reduction");
const fmtScore = (s: number | null, division: string) =>
  s == null || !Number.isFinite(s) ? "n/a" : division === "opportunity" ? s.toFixed(3) : `${(s * 100).toFixed(1)}%`;
const fmtParams = (p: Record<string, number> | undefined) =>
  p && Object.keys(p).length ? Object.entries(p).map(([k, v]) => `${k}=${Number.isInteger(v) ? v : +v.toFixed(4)}`).join(", ") : "defaults";

export function fitSteps(fit: FitOut, c: PipeContext): PipeStep[] {
  const cls = prettyId(String(fit.event_class || "unsupported"));
  const fam = fit.family ? prettyId(fit.family) : "no family";
  const alts = (fit.alternatives ?? []).filter((a) => a && a.family);
  const short = c.shortlisted?.length ? c.shortlisted : [fit.family, ...alts.map((a) => a.family)].filter((x): x is string => !!x);
  const history =
    fit.ticks_source === "live_history" ? `${fit.n_ticks.toLocaleString("en-US")} ticks of real ${c.venues.join(" + ")} price history, aligned to ${c.ticker} bars. Missing book depth stays empty, never invented.`
    : fit.ticks_source === "replay" ? `Offline: ${fit.n_ticks.toLocaleString("en-US")} ticks from a recorded replay file (not live history).`
    : `No usable price history for this market, so presets were not replayed; the family default is used.`;
  return [
    { key: "classify", name: "Classifying the event", orb: "searching", text: `${c.question.replace(/\?$/, "")} → ${cls} (${fit.llm === "gemini" ? "Gemini" : "keyword rules"}). Division: ${fit.division}.` },
    { key: "shortlist", name: "Shortlisting algo families", orb: "connecting", text: short.length ? `${short.length} ${short.length === 1 ? "family covers" : "families cover"} ${cls}: ${short.slice(0, 5).map(prettyId).join(", ")}${short.length > 5 ? "…" : ""}.` : `No compiled family covers ${cls}.` },
    { key: "history", name: "Loading price history", orb: "working", text: history },
    { key: "tune", name: "Tuning presets on replay", orb: "searching", text: fit.family ? `${fam} preset #${fit.preset_index ?? 0} · ${scoreLabel(String(fit.division))} ${fmtScore(fit.score, String(fit.division))} · ${fmtParams(fit.params)}.${alts.length ? ` Runners-up: ${alts.slice(0, 3).map((a) => `${prettyId(a.family)} ${fmtScore(a.score ?? null, String(fit.division))}`).join(", ")}.` : ""}` : "Nothing to tune." },
    { key: "explain", name: "Explaining the fit", orb: "composing", text: fit.rationale || "No rationale returned." },
    { key: "ready", name: "Bridge ready", orb: "listening", text: `${c.ticker} → ${fam}. Next: a proposal you approve, then the engine runs it on the bridge.` },
  ];
}

export function demoSteps(c: PipeContext): PipeStep[] {
  return [
    { key: "classify", name: "Parsing question", orb: "searching", text: `Resolution: ${c.question.replace("Will ", "").replace("?", "")} — sources: ${c.venues.join(" + ")}. Current YES ${c.yes}¢, 24h vol ${c.vol}.` },
    { key: "shortlist", name: "Mapping exposure", orb: "connecting", text: `${c.ticker}: ${c.held.toLocaleString("en-US")} sh across 3 lots (2 long-term). Fee schedule and account type loaded.` },
    { key: "history", name: "Estimating impact", orb: "working", text: `Revenue ${c.rev == null ? "n/a" : fmtPct(c.rev)}, brand ${c.brand == null ? "n/a" : fmtPct(c.brand)} → expected move on YES ${fmtPct(c.move)} (confidence 0.71). ${c.why}` },
    { key: "tune", name: "Searching algo library", orb: "searching", text: "1,284 algorithms scored on σ regime, venue latency, fee drag and tax fit. 61 pass; 6 compose." },
    { key: "explain", name: "Composing the chain", orb: "composing", text: "Sigma Gate → Book-Imbalance Reader → Delta-Bridge v3 → Vol-Adaptive Slicer / Meridian TWAP → Tax-Lot Optimizer → Fee-Aware Router." },
    { key: "ready", name: "Backtesting on comps", orb: "listening", text: `NYC LL18 and Barcelona 2028 ban: this chain would have captured 71% of ${c.ticker}'s event drawdown at 0.09% cost.` },
  ];
}

