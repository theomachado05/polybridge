// Opening a live bridge on the backend: proposal → approval → POST /bridges (market-event path, contracts.md).
// Pure (API injected) so it is unit-tested offline. Callers must only invoke it on an explicit user action.
import * as http from "./api.ts";
import type { Direction, FitOut, Proposal } from "./api";
import type { EquityPick, Question } from "./demo";
import { prettyId } from "./fmt.ts";

export interface Settings {
  broker: string | null; conns: string[]; account: "Taxable" | "IRA"; rate: string; taxState: string; maxHedge: string;
  markets: Record<string, boolean>; guards: { edge: boolean; wash: boolean; auto: boolean };
}

export type BridgeApi = Pick<typeof http, "approveProposal" | "createProposal" | "getEquity" | "listProposals" | "startBridge">;
const defaultApi: BridgeApi = http;

/** $/share per unit of probability for the engine's fee gate; 0 (no spot or no impact estimate) turns the gate off. */
export const gapPerShare = (spot: number | null | undefined, move: number | null | undefined) =>
  spot && move ? (spot * Math.abs(move)) / 100 : 0;

/** True when a live bridge for this pick would start with the engine's fee gate off (contracts.md). */
export const feeGateOff = (q: Question, eq: EquityPick) => !!q.real && gapPerShare(eq.px, eq.move) === 0;

const sameMarket = (p: Proposal, m: NonNullable<Question["real"]>) => p.market?.source === m.source && p.market?.id === m.id;

/** The algo a bridge runs: a catalog family plus the preset the AI fit picked. */
export interface AppliedFit { family: string; preset_index: number | null }

/** The fit a bridge can run, or null: only a hedge-division family with a preset runs on a bridge (the backend
 *  refuses option and prediction-market families with 422; contracts.md). */
export function runnableFit(fit: Pick<FitOut, "family" | "preset_index" | "division"> | null | undefined): AppliedFit | null {
  if (!fit || !fit.family || fit.division !== "hedge" || fit.preset_index == null) return null;
  return { family: fit.family, preset_index: fit.preset_index };
}

/** What a hedge bridge runs, in words: the AI-fit family and preset (hedgecore.Algo), or, with no runnable fit, the
 *  engine's default delta-bridge spec. `node` is the Bridge screen's centre label; `sentence` reads in running text. */
export function algoRunLabel(fit: AppliedFit | null): { node: string; sentence: string } {
  if (!fit) return { node: "02 · ENGINE · DEFAULT DELTA-BRIDGE SPEC", sentence: "the engine's default delta-bridge spec" };
  const fam = prettyId(fit.family);
  const preset = fit.preset_index != null ? `preset #${fit.preset_index}` : "custom params";
  return { node: `02 · AI FIT · ${fam.toUpperCase()} · ${preset.toUpperCase()}`, sentence: `the AI-fit ${fam} algo (${preset})` };
}

/** A proposal is reusable only when it was approved for exactly this algo (or both have none): a bridge runs what
 *  the proposal was approved with, and the backend answers 409 to a different family or preset. */
const sameAlgo = (p: Proposal, want: AppliedFit | null) =>
  want ? p.algo?.family === want.family && (p.algo?.preset_index ?? null) === want.preset_index : !p.algo;

const sameNum = (a: number | null | undefined, b: number) => typeof a === "number" && Math.abs(a - b) < 1e-9;

/** The direction a hedge fit may be oriented with, or null when it is unknown. On a live market only the mapping
 *  says which outcome hurts the stock; guessing from a zero move would tune the hedge against an arbitrary side.
 *  Demo markets keep the prototype's sign-of-move rule. */
export function fitDirection(q: Pick<Question, "real">, eq: Pick<EquityPick, "direction" | "move">): Direction | null {
  if (eq.direction) return eq.direction;
  if (q.real) return null;
  return eq.move < 0 ? "down_on_yes" : "up_on_yes";
}

/** Proposal → approval → engine bridge on the real backend (market-event path, contracts.md).
 *  Reuses an earlier proposal for the same ticker, market, direction, algo, coverage and shares instead of creating one per run: an
 *  approved one (POST /bridges is idempotent per proposal, so this re-attaches to its bridge, or finally starts
 *  the bridge if an earlier attempt failed after approval), else a pending one, which is approved here. */
export async function startRealBridge(q: Question, eq: EquityPick, maxHedge: string, api: BridgeApi = defaultApi,
  fit: AppliedFit | null = null): Promise<{ bridgeId: string; gap: number; applied: AppliedFit | null }> {
  const { approveProposal, createProposal, getEquity, listProposals, startBridge } = api;
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  if (!eq.direction) throw new Error(`${eq.t} is not in this market's mapping, so the adverse outcome is unknown`);
  let spot = eq.px;
  if (!spot) spot = await getEquity(eq.t).then((c) => c.implied_move?.spot ?? null, () => null);
  const cap = Math.min(1, (parseInt(maxHedge, 10) || 100) / 100);
  // With a fit, target_coverage is the user's Max hedge: the backend caps the algo's coverage at it and clips every
  // sell beyond it (contracts.md), so the approved proposal bounds what is hedged. Without a fit the default Engine
  // hedges target_coverage itself: half the position, never above Max hedge.
  const coverage = fit ? cap : Math.min(0.5, cap);
  const sharesHeld = eq.held || 500;
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  // Reuse only a proposal approved for exactly these terms: the bridge runs what was approved, so an older approval
  // at another coverage or position size would hedge more (or less) than the screen says.
  const mine = (await listProposals().catch(() => [] as Proposal[]))
    .filter((p) => p.ticker === eq.t && p.family === "hedge" && sameMarket(p, m) && (p.direction ?? "down_on_yes") === eq.direction
      && sameAlgo(p, fit) && sameNum(p.target_coverage, coverage) && sameNum(p.shares_held, sharesHeld));
  const approved = mine.find((p) => p.status === "approved");
  const pending = mine.find((p) => p.status === "proposed");
  let ok: Proposal;
  if (approved) ok = approved;
  else if (pending) ok = await approveProposal(pending.id);
  else {
    const algo = fit ? { algo: { family: fit.family, preset_index: fit.preset_index ?? undefined, source: "ai_fit" as const } } : {};
    const prop = await createProposal({ ticker: eq.t, market, direction: eq.direction, shares_held: sharesHeld, target_coverage: coverage, ...algo });
    ok = prop.status === "approved" ? prop : await approveProposal(prop.id);
  }
  const gap = gapPerShare(spot, eq.move);
  const sources: ("replay" | "live")[] = m.token_id ? ["replay", "live"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    const run = fit ? { family: fit.family, ...(fit.preset_index != null ? { preset_index: fit.preset_index } : {}) } : {};
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: gap, direction: eq.direction, market, ...run })).bridge_id, gap, applied: fit }; }
    catch (e) { last = e; }
  }
  const why = last instanceof Error ? last.message : "the backend refused to start a bridge";
  throw new Error(`${why}; proposal ${ok.id} stays approved and is reused on the next try`);
}

// ---------------------------------------------------------------- Opportunity division (options)

/** The Opportunity division's option families: the only opportunity families a bridge runs (contracts.md). */
export const OPTION_FAMILIES = ["binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity"] as const;

/** An opportunity fit worth offering: an options family with a real (replay-scored) score and a preset. A rules pick
 *  (score null) is not offered, so the UI never presents an unscored guess as an opportunity. */
export function opportunityFit(fit: Pick<FitOut, "family" | "preset_index" | "division" | "score"> | null | undefined): (AppliedFit & { score: number }) | null {
  if (!fit || fit.division !== "opportunity" || !fit.family || fit.preset_index == null) return null;
  if (!(OPTION_FAMILIES as readonly string[]).includes(fit.family)) return null;
  if (typeof fit.score !== "number" || !Number.isFinite(fit.score)) return null;
  return { family: fit.family, preset_index: fit.preset_index, score: fit.score };
}

export interface OpportunityCaps { max_contracts: number; max_notional: number }
export const DEFAULT_OPP_CAPS: OpportunityCaps = { max_contracts: 10, max_notional: 10_000 };

/** Opportunity proposal (options family + risk caps) → approval → POST /bridges. Reuses an approved or pending
 *  proposal for the same ticker, market, algo and caps (the bridge runs exactly what was approved). */
export async function startOpportunityBridge(q: Question, ticker: string, fit: AppliedFit, api: BridgeApi = defaultApi,
  caps: OpportunityCaps = DEFAULT_OPP_CAPS): Promise<{ bridgeId: string; applied: AppliedFit }> {
  const { approveProposal, createProposal, listProposals, startBridge } = api;
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const mine = (await listProposals().catch(() => [] as Proposal[]))
    .filter((p) => p.ticker === ticker && p.family === "opportunity" && sameMarket(p, m) && sameAlgo(p, fit)
      && p.max_contracts === caps.max_contracts && p.max_notional === caps.max_notional);
  const approved = mine.find((p) => p.status === "approved");
  const pending = mine.find((p) => p.status === "proposed");
  let ok: Proposal;
  if (approved) ok = approved;
  else if (pending) ok = await approveProposal(pending.id);
  else {
    const prop = await createProposal({ ticker, market, division: "opportunity", ...caps,
      algo: { family: fit.family, preset_index: fit.preset_index ?? undefined, source: "ai_fit" } });
    ok = prop.status === "approved" ? prop : await approveProposal(prop.id);
  }
  const sources: ("replay" | "live")[] = m.token_id || m.source === "kalshi" ? ["live", "replay"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: 0, market })).bridge_id, applied: fit }; }
    catch (e) { last = e; }
  }
  const why = last instanceof Error ? last.message : "the backend refused to start a bridge";
  throw new Error(`${why}; proposal ${ok.id} stays approved and is reused on the next try`);
}

// ---------------------------------------------------------------- where a bridge's orders fill, in words

/** Every web bridge tries a recorded replay first, and the backend fills replay bridges in an isolated sandbox. */
export const REPLAY_SANDBOX_SENTENCE = "On a recorded replay (the default here) its orders fill in an isolated replay sandbox, not this account.";

/** The Bridge screen's position-panel label: the replay sandbox when the backend says the bridge is sandboxed
 *  (summary.account_scope), else the GET /account broker. */
export function fillScopeLabel(scope: string | null | undefined, acct: { name: string; tone: "sim" | "paper" | "demo" }):
  { sandbox: boolean; name: string; tone: "replay" | "sim" | "paper" | "demo"; title: string; filledVerb: string } {
  return scope === "replay_sandbox"
    ? { sandbox: true, name: "replay sandbox · not your account", tone: "replay", title: "Replay bridges fill in an isolated sandbox (sim-replay), never your account", filledVerb: "Sandbox filled" }
    : { sandbox: false, name: acct.name, tone: acct.tone, title: "Account that receives the engine's orders (GET /account)", filledVerb: "Broker filled" };
}

/** The venue a live bridge streams: the market's own (Kalshi markets stream Kalshi; contracts.md, ticks.py). */
export const liveVenue = (source: string | null | undefined) => (source === "kalshi" ? "Kalshi" : "Polymarket");

/** What a replay bridge's summary says about its file: the file name and the market its .meta.json sidecar records.
 *  `known: false` means the backend reported replay_market as null (no sidecar: the file's market is unknown);
 *  undefined means an older backend that does not report it. */
export interface ReplayInfo {
  file?: string | null; market_id?: string | null; market_source?: string | null; market_token_id?: string | null; known?: boolean;
}

/** ReplayInfo from a bridge summary's replay_file / replay_market (null replay_market: no sidecar). */
export function replayInfo(summary: { replay_file?: string | null; replay_market?: { source?: string | null; id?: string | null; token_id?: string | null } | null } | null | undefined): ReplayInfo | null {
  if (!summary) return null;
  const m = summary.replay_market;
  return {
    file: summary.replay_file ?? null, market_id: m?.id ?? null, market_source: m?.source ?? null, market_token_id: m?.token_id ?? null,
    known: "replay_market" in summary ? m != null : undefined,
  };
}

/** True when the recording names a different market than the one on screen. Same rule as the backend's sidecar check:
 *  the same venue, and the same market id or the same (YES) token id. Unknown on either side: no mismatch claimed. */
export function replayMismatch(replay: ReplayInfo | null | undefined, marketSource?: string | null, marketId?: string | null, marketTokenId?: string | null): boolean {
  const rec = [replay?.market_id, replay?.market_token_id].filter((x): x is string => !!x);
  const ours = [marketId, marketTokenId].filter((x): x is string => !!x);
  if (!rec.length || !ours.length) return false;
  if (replay?.market_source && marketSource && replay.market_source !== marketSource) return true;
  return !rec.some((k) => ours.includes(k));
}

/** The Bridge screen's probability subtitle. On a replay it names the recorded file when the backend reports it,
 *  and flags when that recording belongs to another market than the one on screen. */
export function priceSubtitle(source: string | null | undefined, marketSource: string | null | undefined,
  replay?: ReplayInfo | null, marketId?: string | null, marketTokenId?: string | null):
  { sub: string; mismatch: boolean } {
  if (source === "replay") {
    return { sub: `YES from replay ${replay?.file ?? "file"} · recorded history, not the live market`, mismatch: replayMismatch(replay, marketSource, marketId, marketTokenId) };
  }
  const venue = liveVenue(marketSource);
  return { sub: `YES ${venue} midpoint${venue === "Kalshi" ? "" : " · Kalshi not streamed on this bridge"}`, mismatch: false };
}

/** The alert the Bridge screen shows about a replay's recording, if any: "warn" when the recording names another market
 *  (the backend refuses that at start, so this is defensive), "info" when it has no sidecar (market unknown) or when a
 *  live bridge fell back to a recording. Null on a live bridge or a recording of this market. */
export function replayNotice(source: string | null | undefined, requestedSource: string | null | undefined, replay: ReplayInfo | null | undefined,
  market?: { source?: string | null; id?: string | null; token_id?: string | null } | null): { tone: "warn" | "info"; text: string } | null {
  if (source !== "replay") return null;
  const file = replay?.file ? `the recording ${replay.file}` : "a recording";
  const fellBack = requestedSource === "live" ? `The live feed was unavailable, so this bridge fell back to ${file}. ` : "";
  if (replayMismatch(replay, market?.source, market?.id, market?.token_id)) {
    const rec = `${replay?.market_source ? replay.market_source + ":" : ""}${replay?.market_id ?? replay?.market_token_id}`;
    return { tone: "warn", text: `${fellBack}This replay${replay?.file ? ` (${replay.file})` : ""} was recorded on another market (${rec}), not the question shown here; its prices and trades are a playback of that recording.` };
  }
  if (replay?.known === false) {
    return { tone: "info", text: `${fellBack}${replay.file ?? "This replay file"} has no .meta.json sidecar, so the backend cannot confirm which market it records; it plays only because the request (or the file's own name) points at this market.` };
  }
  if (!fellBack) return null;
  const rec = replay?.known && (replay.market_id || replay.market_token_id)
    ? `It records this market (${replay.market_source ? replay.market_source + ":" : ""}${replay.market_id ?? replay.market_token_id}).` : "";
  return { tone: "info", text: (fellBack + rec).trim() };
}
