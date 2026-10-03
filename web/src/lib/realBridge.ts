// Opening a live bridge on the backend: proposal → approval → POST /bridges (market-event path, contracts.md).
// Pure (API injected) so it is unit-tested offline. Callers must only invoke it on an explicit user action.
import * as http from "./api.ts";
import type { Direction, FitOut, Proposal } from "./api";
import type { EquityPick, Question } from "./demo";
import { isRecordedOnly } from "./demo.ts";
import { prettyId } from "./fmt.ts";
import { isEvidenceError } from "./risk.ts";

export interface Settings {
  broker: string | null; conns: string[]; account: "Taxable" | "IRA"; rate: string; taxState: string; maxHedge: string;
  markets: Record<string, boolean>; guards: { edge: boolean; wash: boolean; auto: boolean };
}

export type BridgeApi = Pick<typeof http, "approveProposal" | "createProposal" | "getEquity" | "listProposals" | "startBridge">;
const defaultApi: BridgeApi = http;

/** $/share per unit of probability for the engine's fee gate; 0 (no spot or no impact estimate) turns the gate off. */
export const gapPerShare = (spot: number | null | undefined, move: number | null | undefined) =>
  spot && move ? (spot * Math.abs(move)) / 100 : 0;

/** True when a live bridge for this pick would start with the engine's fee gate off (contracts.md). `gap_per_share`
 *  applies only to the legacy Engine: a bridge that runs a hedgecore algo (a runnable AI fit) prices orders with its
 *  own FeeGate from the tick's `under_px` (a replay supplies it from recorded bars), so its gate is never "off" for
 *  want of a quote here. Pass the fit approval will send (`runnableFit`), or null when the default spec runs. */
export const feeGateOff = (q: Question, eq: EquityPick, fit: AppliedFit | null = null) =>
  !!q.real && !fit && gapPerShare(eq.px, eq.move) === 0;

/** The Bridge screen's "fee gate off" tag: only a bridge on the legacy Engine (no algo running) started with
 *  gap_per_share = 0. `running` is the algo the bridge runs (null on the legacy Engine); `gap` is what it was
 *  started with (null when unknown, e.g. a bridge opened from its URL or an opportunity bridge). */
export const bridgeFeeGateOff = (gap: number | null | undefined, running: AppliedFit | null) => gap === 0 && !running;

/** The open live hedge bridge Build may reuse for this pick, or undefined. It must match the market, the ticker AND
 *  the hedge A choice: a bridge started with hedge A on is never handed back to a pick that has it off (the default),
 *  nor the reverse, so the bridge always runs what the approval box said. Opportunity bridges are never reused here. */
export function reusableBridge<B extends { kind: string; mode?: string; q?: { id: string } | null; eq?: { t: string } | null; pmHedge?: boolean; override?: boolean }>(
  bridges: readonly B[], qId: string, ticker: string, closedPmHedge: boolean, actOnUnvalidated = false): B | undefined {
  return bridges.find((b) => b.kind === "live" && b.mode !== "opportunity" && b.q?.id === qId && b.eq?.t === ticker
    && (b.pmHedge === true) === closedPmHedge && (b.override === true) === actOnUnvalidated);
}

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

/** The exact terms a hedge proposal is created (or reused) with: the bridge runs what was approved, so the approval
 *  step and the bridge start must agree on every one of them. */
export interface HedgeTerms {
  ticker: string; market: { source: string; id: string; token_id?: string | null }; direction: Direction;
  shares_held: number; target_coverage: number; fit: AppliedFit | null; closedPmHedge: boolean; actOnUnvalidated: boolean;
}
export interface HedgeOpts { closedPmHedge?: boolean; actOnUnvalidated?: boolean }

export function hedgeTerms(q: Question, eq: EquityPick, maxHedge: string, fit: AppliedFit | null = null, opts: HedgeOpts = {}): HedgeTerms {
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  if (!eq.direction) throw new Error(`${eq.t} is not in this market's mapping, so the adverse outcome is unknown`);
  const cap = Math.min(1, (parseInt(maxHedge, 10) || 100) / 100);
  // With a fit, target_coverage is the user's Max hedge: the backend caps the algo's coverage at it and clips every
  // sell beyond it (contracts.md), so the approved proposal bounds what is hedged. Without a fit the default Engine
  // hedges target_coverage itself: half the position, never above Max hedge.
  return {
    ticker: eq.t, market: { source: m.source, id: m.id, token_id: m.token_id }, direction: eq.direction,
    shares_held: eq.held || 500, target_coverage: fit ? cap : Math.min(0.5, cap), fit,
    closedPmHedge: opts.closedPmHedge === true, actOnUnvalidated: opts.actOnUnvalidated === true,
  };
}

/** Proposals the backend's evidence gate refused at bridge start. The stored evidence on such a proposal can still read
 *  "validated" (it was approved while validated, then the evidence file flipped; POST /bridges re-checks but does not
 *  rewrite the proposal), so reusing it would 409 on every retry. Kept for this page session. */
const evidenceRefused = new Set<string>();
/** Never reuse proposal `id` again (its bridge start failed the evidence gate); the next try proposes again. */
export const markEvidenceRefused = (id: string) => { evidenceRefused.add(id); };

/** A proposal a bridge can start from: not one approved WITHOUT the acknowledgement on an unvalidated market (the
 *  backend refuses that bridge with 409 EVIDENCE_UNVALIDATED), and not one whose bridge start that gate refused. */
export const bridgeable = (p: Proposal) => !evidenceRefused.has(p.id) && !(p.status === "approved" && p.evidence?.validated === false && !p.ack_unvalidated);

/** The error a failed bridge start reports. An evidence refusal says the proposal is dropped (it is no longer reused);
 *  any other failure keeps the approved proposal for the next try (POST /bridges is idempotent per proposal). */
function startFailure(last: unknown, proposalId: string): Error {
  const why = last instanceof Error ? last.message : "the backend refused to start a bridge";
  if (isEvidenceError(last)) {
    markEvidenceRefused(proposalId);
    return new Error(`${why}; proposal ${proposalId} is not reused: the next try proposes again and reads the evidence afresh`);
  }
  return new Error(`${why}; proposal ${proposalId} stays approved and is reused on the next try`);
}

const matchesTerms = (p: Proposal, t: HedgeTerms) => p.ticker === t.ticker && p.family === "hedge" && p.market?.source === t.market.source
  && p.market?.id === t.market.id && (p.direction ?? "down_on_yes") === t.direction && sameAlgo(p, t.fit)
  && sameNum(p.target_coverage, t.target_coverage) && sameNum(p.shares_held, t.shares_held)
  && (p.closed_pm_hedge === true) === t.closedPmHedge && (p.act_on_unvalidated === true) === t.actOnUnvalidated;

/** The proposal for these terms: an approved one (still bridgeable), else a pending one, else a new one. Never approves:
 *  the approval step reads its `evidence` and `capacity` before the user decides. */
export async function prepareHedgeProposal(t: HedgeTerms, api: Pick<BridgeApi, "createProposal" | "listProposals"> = defaultApi): Promise<Proposal> {
  const mine = (await api.listProposals().catch(() => [] as Proposal[])).filter((p) => matchesTerms(p, t) && bridgeable(p));
  const found = mine.find((p) => p.status === "approved") ?? mine.find((p) => p.status === "proposed");
  if (found) return found;
  const algo = t.fit ? { algo: { family: t.fit.family, preset_index: t.fit.preset_index ?? undefined, source: "ai_fit" as const } } : {};
  return api.createProposal({ ticker: t.ticker, market: t.market, direction: t.direction, shares_held: t.shares_held, target_coverage: t.target_coverage,
    ...algo, ...(t.closedPmHedge ? { closed_pm_hedge: true } : {}), ...(t.actOnUnvalidated ? { act_on_unvalidated: true } : {}) });
}

/** Proposal → approval → engine bridge on the real backend (market-event path, contracts.md).
 *  Reuses an earlier proposal for the same terms instead of creating one per run: an approved one (POST /bridges is
 *  idempotent per proposal, so this re-attaches to its bridge, or finally starts the bridge if an earlier attempt failed
 *  after approval), else a pending one, which is approved here. `ackUnvalidated` is the user's explicit acknowledgement
 *  of an unvalidated market (the evidence gate); without it the backend answers 409 EVIDENCE_UNVALIDATED on such a market. */
export async function startRealBridge(q: Question, eq: EquityPick, maxHedge: string, api: BridgeApi = defaultApi,
  fit: AppliedFit | null = null, opts: HedgeOpts & { ackUnvalidated?: boolean } = {}): Promise<{ bridgeId: string; gap: number; applied: AppliedFit | null }> {
  const { approveProposal, getEquity, startBridge } = api;
  const t = hedgeTerms(q, eq, maxHedge, fit, opts);
  let spot = eq.px;
  if (!spot) spot = await getEquity(eq.t).then((c) => c.implied_move?.spot ?? null, () => null);
  const prop = await prepareHedgeProposal(t, api);
  const ok = prop.status === "approved" ? prop : await approveProposal(prop.id, opts.ackUnvalidated === true);
  const gap = gapPerShare(spot, eq.move);
  const sources: ("replay" | "live")[] = t.market.token_id ? ["replay", "live"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    const run = fit ? { family: fit.family, ...(fit.preset_index != null ? { preset_index: fit.preset_index } : {}) } : {};
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: gap, direction: t.direction, market: t.market, ...run })).bridge_id, gap, applied: fit }; }
    catch (e) { last = e; if (isEvidenceError(e)) break; }  // the gate answers the same for every source
  }
  throw startFailure(last, ok.id);
}

// ---------------------------------------------------------------- Opportunity division (options)

/** The Opportunity division's option families: the only opportunity families a bridge runs (contracts.md). */
export const OPTION_FAMILIES = ["binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity"] as const;

/** An opportunity fit worth offering: an options family with a real (replay-scored) score and a preset. A rules pick
 *  (score null) is not offered, so the UI never presents an unscored guess as an opportunity. When the division's top
 *  pick is not an options family (e.g. no_bid_seller, which trades prediction-market legs and never runs on a bridge),
 *  the best-scored options family among the alternatives is offered instead, and `instead_of` names the top pick. */
export function opportunityFit(fit: (Pick<FitOut, "family" | "preset_index" | "division" | "score"> & { alternatives?: FitOut["alternatives"] }) | null | undefined):
  (AppliedFit & { score: number; instead_of?: string }) | null {
  if (!fit || fit.division !== "opportunity") return null;
  const isOption = (f: string | null | undefined) => !!f && (OPTION_FAMILIES as readonly string[]).includes(f);
  const scored = (x: number | null | undefined): x is number => typeof x === "number" && Number.isFinite(x);
  if (isOption(fit.family)) {
    if (fit.preset_index == null || !scored(fit.score)) return null;
    return { family: fit.family!, preset_index: fit.preset_index, score: fit.score };
  }
  const alt = (fit.alternatives ?? []).find((a) => isOption(a.family) && a.preset_index != null && scored(a.score));
  if (!alt) return null;
  return { family: alt.family, preset_index: alt.preset_index!, score: alt.score as number, ...(fit.family ? { instead_of: fit.family } : {}) };
}

export interface OpportunityCaps { max_contracts: number; max_notional: number }
export const DEFAULT_OPP_CAPS: OpportunityCaps = { max_contracts: 10, max_notional: 10_000 };

/** The opportunity proposal for this pick (options family + risk caps): approved (still bridgeable), else pending, else
 *  new. Never approves: the Opportunity card reads its `evidence` first. */
export async function prepareOpportunityProposal(q: Question, ticker: string, fit: AppliedFit,
  api: Pick<BridgeApi, "createProposal" | "listProposals"> = defaultApi, caps: OpportunityCaps = DEFAULT_OPP_CAPS): Promise<Proposal> {
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const mine = (await api.listProposals().catch(() => [] as Proposal[]))
    .filter((p) => p.ticker === ticker && p.family === "opportunity" && sameMarket(p, m) && sameAlgo(p, fit)
      && p.max_contracts === caps.max_contracts && p.max_notional === caps.max_notional && bridgeable(p));
  const found = mine.find((p) => p.status === "approved") ?? mine.find((p) => p.status === "proposed");
  if (found) return found;
  return api.createProposal({ ticker, market, division: "opportunity", ...caps,
    algo: { family: fit.family, preset_index: fit.preset_index ?? undefined, source: "ai_fit" } });
}

/** Opportunity proposal → approval (with the evidence acknowledgement when given) → POST /bridges. */
export async function startOpportunityBridge(q: Question, ticker: string, fit: AppliedFit, api: BridgeApi = defaultApi,
  caps: OpportunityCaps = DEFAULT_OPP_CAPS, opts: { ackUnvalidated?: boolean } = {}): Promise<{ bridgeId: string; applied: AppliedFit }> {
  const { approveProposal, startBridge } = api;
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const prop = await prepareOpportunityProposal(q, ticker, fit, api, caps);
  const ok = prop.status === "approved" ? prop : await approveProposal(prop.id, opts.ackUnvalidated === true);
  // A resolved market listed for its recording has no live book: replay it directly (no failed live attempt first).
  const sources: ("replay" | "live")[] = isRecordedOnly(m) ? ["replay"] : m.token_id || m.source === "kalshi" ? ["live", "replay"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: 0, market })).bridge_id, applied: fit }; }
    catch (e) { last = e; if (isEvidenceError(e)) break; }  // the gate answers the same for every source
  }
  throw startFailure(last, ok.id);
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
