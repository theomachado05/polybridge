// Pipeline screen: the six steps mapped from POST /pipeline/fit (classify, shortlist, history, tune, explain, ready),
// or, when no fit can run, the real facts of the pick and the engine's default spec (never scripted numbers).
import type { FitOut } from "./api";
import { aiLabel, aiStatus, classifiedByGemini } from "./ai.ts";
import { fmtPct, prettyId } from "./fmt.ts";

export type OrbState = "connecting" | "working" | "searching" | "composing" | "breathing" | "listening";
export interface PipeStep { key: string; name: string; orb: OrbState; text: string }

export interface PipeContext {
  question: string; venues: string[]; yes: number; vol: string;
  ticker: string; held: number;
  move: number; rev: number | null; brand: number | null; why: string;
  shortlisted?: string[];   // family ids from GET /library for the fitted class
  heldReal?: number;        // shares actually held (real path)
  libraryTotal?: number;    // preset count GET /library reports (no number is shown without it)
  noDirection?: boolean;    // live market, ticker outside its mapping: no hedge was fitted (adverse outcome unknown)
}

type ScoredFit = Pick<FitOut, "division" | "score" | "n_ticks"> &
  Partial<Pick<FitOut, "score_basis" | "score_raw" | "score_vs_static" | "avg_hedge_ratio">>;
const VS_STATIC = "hedge_var_reduction_vs_static";
const fin = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);
/** One-decimal percent; a nonzero value too small to show reads "<0.1%" / "-<0.1%" rather than a misleading "0.0%". */
const pct1 = (v: number) => (v !== 0 && Math.abs(v) < 0.0005 ? `${v < 0 ? "-" : ""}<0.1%` : `${(v * 100).toFixed(1)}%`);
const signedPct = (v: number) => (v > 0 ? `+${pct1(v)}` : pct1(v));
/** The ranking basis of a fit: the vs-static hedge score, the opportunity score, or a legacy hedge score (an older
 *  backend that ranked by raw variance reduction and sent no score_basis). */
const basisOf = (f: Pick<ScoredFit, "division" | "score_basis" | "score_vs_static">) =>
  f.division === "opportunity" ? "opportunity" : f.score_basis === VS_STATIC || fin(f.score_vs_static) ? "vs_static" : "legacy";
/** What the tune step calls the score, per ranking basis (the vs-static headline names itself). */
const scoreLabel = (basis: "opportunity" | "vs_static" | "legacy") =>
  basis === "opportunity" ? "net P&L per unit risk" : basis === "vs_static" ? "signal vs a static hedge" : "hedge variance reduction";
const fmtScore = (s: number | null | undefined, basis: "opportunity" | "vs_static" | "legacy") =>
  !fin(s) ? "n/a" : basis === "opportunity" ? s.toFixed(3) : basis === "vs_static" ? `${signedPct(s)} vs static` : pct1(s);
/** Fit scores are tuned and scored on the same history a replay bridge then plays back: in-sample, not a forecast. */
export const IN_SAMPLE_NOTE = "The score comes from the same history that the bridge replays (in-sample). It is not a forecast or an out-of-sample result.";
/** Why the hedge headline is the vs-static number: any static short of a fraction h earns 1 - (1 - h)^2 of the raw cut. */
export const VS_STATIC_NOTE = "The rank uses the variance cut that is more than a static hedge of the same average size. The prediction-market signal adds this cut. The raw variance reduction mostly shows how much of the position has a hedge, thus the app shows it but does not rank by it.";
/** Shown, in a neutral tone, when even the best preset did no better than a static hedge of the same size. */
export const NO_SIGNAL_TEXT = "the PM signal adds nothing over a static hedge on this history";
/** A plain fit score (opportunity, or a legacy hedge score), labelled in-sample. */
export const hedgeScoreText = (s: number | null, division: string) =>
  s == null || !Number.isFinite(s) ? "n/a"
  : division === "opportunity" ? `${s.toFixed(3)} in-sample` : `${(s * 100).toFixed(1)}% var. reduction (in-sample replay)`;

export interface FitScoreView {
  /** "positive": the signal beat a static hedge; "neutral": it did not, or the score is not a vs-static number. */
  tone: "positive" | "neutral";
  /** False for an unscored (rules) pick. */
  scored: boolean;
  /** True when this is a vs-static hedge score at or below 0. */
  noSignal: boolean;
  /** The headline: "signal adds 5.7% vs a static hedge (in-sample replay, 1,440 ticks)". */
  headline: string;
  /** Compact form for badges: "signal adds 5.7% vs a static hedge" / "PM signal adds nothing over a static hedge". */
  short: string;
  /** Raw variance reduction and average hedge ratio (hedge vs-static fits only). */
  secondary: string | null;
  /** Hover text: the headline, the secondary numbers and the in-sample / ranking caveats. */
  title: string;
}

/** How a fit's score is shown everywhere (Build card, pipeline, Library badge). For a hedge the headline is what the
 *  PM signal adds over a static hedge of the same average size; the raw cut and the hedge ratio are secondary. */
/** Below this, "signal adds" is shown in neutral tone: the ranking takes the best of many presets in-sample. */
export const SIGNAL_NOISE_FLOOR = 0.01;

export function fitScoreView(f: ScoredFit): FitScoreView {
  const basis = basisOf(f);
  const ticks = f.n_ticks > 0 ? `, ${f.n_ticks.toLocaleString("en-US")} ticks` : "";
  if (basis === "vs_static") {
    const vs = fin(f.score_vs_static) ? f.score_vs_static : f.score;
    if (!fin(vs)) return { tone: "neutral", scored: false, noSignal: false, headline: "not scored on replay", short: "not scored on replay", secondary: null, title: "The replay did not score a preset against a static hedge on the history of this market." };
    const parts = [
      vs <= 0 ? `${signedPct(vs)} vs static` : null,
      fin(f.score_raw) ? `raw variance reduction ${pct1(f.score_raw)}` : null,
      fin(f.avg_hedge_ratio) ? `average hedge ratio ${pct1(f.avg_hedge_ratio)}` : null,
    ].filter((x): x is string => !!x);
    const secondary = parts.length ? parts.join(" · ") : null;
    const noise = vs > 0 && vs < SIGNAL_NOISE_FLOOR;  // a few tenths of a percent is within selection noise (best of many presets)
    const headline = vs > 0 ? `signal adds ${pct1(vs)} vs a static hedge${noise ? ", within noise" : ""} (in-sample replay${ticks})` : `${NO_SIGNAL_TEXT} (in-sample replay${ticks})`;
    return {
      tone: vs >= SIGNAL_NOISE_FLOOR ? "positive" : "neutral", scored: true, noSignal: vs <= 0, headline,
      short: vs > 0 ? `signal adds ${pct1(vs)} vs a static hedge` : "PM signal adds nothing over a static hedge",
      secondary, title: [headline + ".", secondary ? secondary + "." : null, VS_STATIC_NOTE, IN_SAMPLE_NOTE].filter(Boolean).join(" "),
    };
  }
  if (!fin(f.score)) return { tone: "neutral", scored: false, noSignal: false, headline: "not scored on replay", short: "not scored on replay", secondary: null, title: "The replay did not score this family. Rules selected its default preset." };
  const headline = hedgeScoreText(f.score, String(f.division));
  return {
    tone: "neutral", scored: true, noSignal: false, headline,
    short: basis === "opportunity" ? `${f.score.toFixed(3)} net P&L / risk` : `${pct1(f.score)} variance reduction`,
    secondary: null, title: `${headline}. ${IN_SAMPLE_NOTE}`,
  };
}
const fmtParams = (p: Record<string, number> | undefined) =>
  p && Object.keys(p).length ? Object.entries(p).map(([k, v]) => `${k}=${Number.isInteger(v) ? v : +v.toFixed(4)}`).join(", ") : "defaults";

function tuneText(fit: FitOut, fam: string, alts: FitOut["alternatives"]): string {
  const basis = basisOf(fit);
  const v = fitScoreView(fit);
  const scored = fin(fit.score);
  const score = !scored ? "not scored on replay"
    : basis === "vs_static" ? `${v.headline}${v.secondary ? ` · ${v.secondary}` : ""}`
    : `${scoreLabel(basis)} ${fmtScore(fit.score, basis)} (in-sample: scored on the history it replays, not a forecast)`;
  const runners = alts.length ? ` Runners-up: ${alts.slice(0, 3).map((a) => scored ? `${prettyId(a.family)} ${fmtScore(a.score ?? null, basis)}` : prettyId(a.family)).join(", ")}.` : "";
  const note = basis === "vs_static" && scored ? ` ${VS_STATIC_NOTE}` : "";
  return `${fam} preset #${fit.preset_index ?? 0} · ${score} · ${fmtParams(fit.params)}.${runners}${note}`;
}

export function fitSteps(fit: FitOut, c: PipeContext): PipeStep[] {
  const ai = aiStatus(fit);
  const cls = prettyId(String(fit.event_class || "unsupported"));
  const fam = fit.family ? prettyId(fit.family) : "no family";
  const alts = (fit.alternatives ?? []).filter((a) => a && a.family);
  const short = c.shortlisted?.length ? c.shortlisted : [fit.family, ...alts.map((a) => a.family)].filter((x): x is string => !!x);
  const history =
    fit.ticks_source === "live_history" ? `${fit.n_ticks.toLocaleString("en-US")} ticks of real ${c.venues.join(" + ")} price history, aligned to ${c.ticker} bars. Missing book depth stays empty. The app does not invent it.`
    : fit.ticks_source === "replay" ? `Offline mode: ${fit.n_ticks.toLocaleString("en-US")} ticks from a recorded replay file (not live history).`
    : `No usable price history for this market. The engine did not replay presets and uses the family default.`;
  return [
    { key: "classify", name: "Classifying the event", orb: "searching", text: `${c.question.replace(/\?$/, "")} → ${cls} (${classifiedByGemini(fit) ? aiLabel(ai).replace(/^AI · /, "") : "keyword rules"}). Division: ${fit.division}.` },
    { key: "shortlist", name: "Selecting algo families", orb: "connecting", text: short.length ? `${short.length} ${short.length === 1 ? "family covers" : "families cover"} ${cls}: ${short.slice(0, 5).map(prettyId).join(", ")}${short.length > 5 ? "…" : ""}.` : `No compiled family covers ${cls}.` },
    { key: "history", name: "Loading price history", orb: "working", text: history },
    { key: "tune", name: "Tuning presets on replay", orb: "searching", text: fit.family ? tuneText(fit, fam, alts) : "No family to tune." },
    { key: "explain", name: "Explaining the fit", orb: "composing", text: fit.rationale || "The fit did not give a rationale." },
    { key: "ready", name: "Ready for your approval", orb: "listening", text: `${ai.live ? "AI fit" : "Fit (rules + C++ replay)"} for ${c.ticker}: ${fam}${fit.family ? (fit.division === "hedge" && fit.preset_index != null ? ` preset #${fit.preset_index}. The proposal includes it. After you approve, the bridge runs this family and preset` : ` (${fit.division} family. A hedge bridge does not run it and uses the default delta-bridge spec of the engine)`) : ""}. Next, approve a proposal to start the engine.` },
  ];
}

/** The steps when no fit can run for a live pick: the fit failed (the screen shows the error and a retry) or the
 *  outcome that hurts the ticker is unknown. Real facts only; approving then runs the engine's default spec. */
export function noFitSteps(c: PipeContext): PipeStep[] {
  const held = c.heldReal ? `${c.heldReal.toLocaleString("en-US")} shares held` : `no position, sized to a ${c.held.toLocaleString("en-US")}-share notional`;
  return [
    { key: "classify", name: "Reading the market", orb: "searching", text: `${c.question.replace(/\?$/, "")} on ${c.venues.join(" and ")}${c.yes ? `. YES ${c.yes}¢, 24-hour volume ${c.vol}` : ""}.` },
    { key: "shortlist", name: "Mapping exposure", orb: "connecting", text: `${c.ticker}: ${held}.` },
    { key: "history", name: "Estimating impact", orb: "working", text: c.move ? `Mapping estimate: expected move on YES ${fmtPct(c.move)}. ${c.why}` : `This market has no impact estimate for ${c.ticker}. The engine hedges on probability only (fee gate off).` },
    { key: "tune", name: "Tuning presets on replay", orb: "searching", text: c.noDirection ? `No hedge fit: ${c.ticker} is not in this market's mapping and you did not say which outcome hurts it. Thus no presets were scored.` : "The fit did not answer, thus no presets were scored. If you approve, the engine runs its default delta-bridge spec." },
    { key: "explain", name: "Composing the chain", orb: "composing", text: "Staleness → Sigma gate → No-trade band → Fee gate → Delta-bridge sizer → Position cap (hedgecore Engine, default spec)." },
    { key: "ready", name: "Ready for your approval", orb: "listening", text: c.noDirection ? `The engine cannot orient a hedge for ${c.ticker} until you say which outcome hurts it (on Build).` : `Next, approve a proposal for ${c.ticker}. The engine then runs its default delta-bridge spec on the recorded replay or the live feed of the market.` },
  ];
}
