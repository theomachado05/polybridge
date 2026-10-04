import * as http from "./api.ts";
import type { Direction, FitOut, Proposal } from "./api";
import type { EquityPick, Question } from "./markets";
import { isRecordedOnly } from "./markets.ts";
import { prettyId } from "./fmt.ts";
import { isEvidenceError } from "./risk.ts";

export interface Settings {
  broker: string | null; conns: string[]; account: "Taxable" | "IRA"; rate: string; taxState: string; maxHedge: string;
  markets: Record<string, boolean>; guards: { edge: boolean; wash: boolean; auto: boolean };
}

export type BridgeApi = Pick<typeof http, "approveProposal" | "createProposal" | "getEquity" | "listProposals" | "startBridge">;
const defaultApi: BridgeApi = http;

export const gapPerShare = (spot: number | null | undefined, move: number | null | undefined) =>
  spot && move ? (spot * Math.abs(move)) / 100 : 0;

export const feeGateOff = (_q: Question, eq: EquityPick, fit: AppliedFit | null = null) =>
  !fit && gapPerShare(eq.px, eq.move) === 0;

export const bridgeFeeGateOff = (gap: number | null | undefined, running: AppliedFit | null) => gap === 0 && !running;

export function reusableBridge<B extends { kind: string; mode?: string; q?: { id: string } | null; eq?: { t: string } | null; pmHedge?: boolean; override?: boolean }>(
  bridges: readonly B[], qId: string, ticker: string, closedPmHedge: boolean, actOnUnvalidated = false): B | undefined {
  return bridges.find((b) => b.kind === "live" && b.mode !== "opportunity" && b.q?.id === qId && b.eq?.t === ticker
    && (b.pmHedge === true) === closedPmHedge && (b.override === true) === actOnUnvalidated);
}

const sameMarket = (p: Proposal, m: Question["real"]) => p.market?.source === m.source && p.market?.id === m.id;

export interface AppliedFit { family: string; preset_index: number | null }

export function runnableFit(fit: Pick<FitOut, "family" | "preset_index" | "division"> | null | undefined): AppliedFit | null {
  if (!fit || !fit.family || fit.division !== "hedge" || fit.preset_index == null) return null;
  return { family: fit.family, preset_index: fit.preset_index };
}

export function algoRunLabel(fit: AppliedFit | null): { node: string; sentence: string } {
  if (!fit) return { node: "Engine: default delta-bridge spec", sentence: "the engine's default delta-bridge spec" };
  const fam = prettyId(fit.family);
  const preset = fit.preset_index != null ? `preset #${fit.preset_index}` : "custom parameters";
  return { node: `Fitted algo: ${fam}, ${preset}`, sentence: `the fitted ${fam} algo (${preset})` };
}

const sameAlgo = (p: Proposal, want: AppliedFit | null) =>
  want ? p.algo?.family === want.family && (p.algo?.preset_index ?? null) === want.preset_index : !p.algo;

const sameNum = (a: number | null | undefined, b: number) => typeof a === "number" && Math.abs(a - b) < 1e-9;

export function fitDirection(_q: unknown, eq: Pick<EquityPick, "direction">): Direction | null {
  return eq.direction ?? null;
}

export interface HedgeTerms {
  ticker: string; market: { source: string; id: string; token_id?: string | null }; direction: Direction;
  shares_held: number; target_coverage: number; fit: AppliedFit | null; closedPmHedge: boolean; actOnUnvalidated: boolean;
}
export interface HedgeOpts { closedPmHedge?: boolean; actOnUnvalidated?: boolean }

export function hedgeTerms(q: Question, eq: EquityPick, maxHedge: string, fit: AppliedFit | null = null, opts: HedgeOpts = {}): HedgeTerms {
  const m = q.real;
  if (!eq.direction) throw new Error(`${eq.t} is not in the mapping for this market, so the adverse outcome is not known. On Build, say which outcome hurts it.`);
  const cap = Math.min(1, (parseInt(maxHedge, 10) || 100) / 100);
  return {
    ticker: eq.t, market: { source: m.source, id: m.id, token_id: m.token_id }, direction: eq.direction,
    shares_held: eq.held || 500, target_coverage: fit ? cap : Math.min(0.5, cap), fit,
    closedPmHedge: opts.closedPmHedge === true, actOnUnvalidated: opts.actOnUnvalidated === true,
  };
}

const evidenceRefused = new Set<string>();
export const markEvidenceRefused = (id: string) => { evidenceRefused.add(id); };

export const bridgeable = (p: Proposal) => !evidenceRefused.has(p.id) && !(p.status === "approved" && p.evidence?.validated === false && !p.ack_unvalidated);

function startFailure(last: unknown, proposalId: string): Error {
  const why = last instanceof Error ? last.message.replace(/\.$/, "") : "The backend did not start the bridge";
  if (isEvidenceError(last)) {
    markEvidenceRefused(proposalId);
    return new Error(`${why}. Proposal ${proposalId} is not reused. Try again to make a new proposal with the current evidence.`);
  }
  return new Error(`${why}. Try again: proposal ${proposalId} stays approved and is reused on the next try.`);
}

const matchesTerms = (p: Proposal, t: HedgeTerms) => p.ticker === t.ticker && p.family === "hedge" && p.market?.source === t.market.source
  && p.market?.id === t.market.id && (p.direction ?? "down_on_yes") === t.direction && sameAlgo(p, t.fit)
  && sameNum(p.target_coverage, t.target_coverage) && sameNum(p.shares_held, t.shares_held)
  && (p.closed_pm_hedge === true) === t.closedPmHedge && (p.act_on_unvalidated === true) === t.actOnUnvalidated;

export async function prepareHedgeProposal(t: HedgeTerms, api: Pick<BridgeApi, "createProposal" | "listProposals"> = defaultApi): Promise<Proposal> {
  const mine = (await api.listProposals().catch(() => [] as Proposal[])).filter((p) => matchesTerms(p, t) && bridgeable(p));
  const found = mine.find((p) => p.status === "approved") ?? mine.find((p) => p.status === "proposed");
  if (found) return found;
  const algo = t.fit ? { algo: { family: t.fit.family, preset_index: t.fit.preset_index ?? undefined, source: "ai_fit" as const } } : {};
  return api.createProposal({ ticker: t.ticker, market: t.market, direction: t.direction, shares_held: t.shares_held, target_coverage: t.target_coverage,
    ...algo, ...(t.closedPmHedge ? { closed_pm_hedge: true } : {}), ...(t.actOnUnvalidated ? { act_on_unvalidated: true } : {}) });
}

export async function startRealBridge(q: Question, eq: EquityPick, maxHedge: string, api: BridgeApi = defaultApi,
  fit: AppliedFit | null = null, opts: HedgeOpts & { ackUnvalidated?: boolean; proposal?: Proposal | null } = {}): Promise<{ bridgeId: string; gap: number; applied: AppliedFit | null }> {
  const { approveProposal, getEquity, startBridge } = api;
  const t = hedgeTerms(q, eq, maxHedge, fit, opts);
  let spot = eq.px;
  if (!spot) spot = await getEquity(eq.t).then((c) => c.implied_move?.spot ?? null, () => null);
  const given = opts.proposal && opts.proposal.ticker.toUpperCase() === t.ticker && opts.proposal.market?.id === t.market.id && bridgeable(opts.proposal) ? opts.proposal : null;
  const prop = given ?? await prepareHedgeProposal(t, api);
  const ok = prop.status === "approved" ? prop : await approveProposal(prop.id, opts.ackUnvalidated === true);
  const gap = gapPerShare(spot, eq.move);
  const sources: ("replay" | "live")[] = t.market.token_id ? ["replay", "live"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    const run = fit ? { family: fit.family, ...(fit.preset_index != null ? { preset_index: fit.preset_index } : {}) } : {};
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: gap, direction: t.direction, market: t.market, ...run })).bridge_id, gap, applied: fit }; }
    catch (e) { last = e; if (isEvidenceError(e)) break; }
  }
  throw startFailure(last, ok.id);
}

export const OPTION_FAMILIES = ["binary_vs_spread_arb", "vol_vs_pm_move", "eightk_opportunity"] as const;

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

export async function prepareOpportunityProposal(q: Question, ticker: string, fit: AppliedFit,
  api: Pick<BridgeApi, "createProposal" | "listProposals"> = defaultApi, caps: OpportunityCaps = DEFAULT_OPP_CAPS): Promise<Proposal> {
  const m = q.real;
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const mine = (await api.listProposals().catch(() => [] as Proposal[]))
    .filter((p) => p.ticker === ticker && p.family === "opportunity" && sameMarket(p, m) && sameAlgo(p, fit)
      && p.max_contracts === caps.max_contracts && p.max_notional === caps.max_notional && bridgeable(p));
  const found = mine.find((p) => p.status === "approved") ?? mine.find((p) => p.status === "proposed");
  if (found) return found;
  return api.createProposal({ ticker, market, division: "opportunity", ...caps,
    algo: { family: fit.family, preset_index: fit.preset_index ?? undefined, source: "ai_fit" } });
}

export async function startOpportunityBridge(q: Question, ticker: string, fit: AppliedFit, api: BridgeApi = defaultApi,
  caps: OpportunityCaps = DEFAULT_OPP_CAPS, opts: { ackUnvalidated?: boolean } = {}): Promise<{ bridgeId: string; applied: AppliedFit }> {
  const { approveProposal, startBridge } = api;
  const m = q.real;
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const prop = await prepareOpportunityProposal(q, ticker, fit, api, caps);
  const ok = prop.status === "approved" ? prop : await approveProposal(prop.id, opts.ackUnvalidated === true);
  const sources: ("replay" | "live")[] = isRecordedOnly(m) ? ["replay"] : m.token_id || m.source === "kalshi" ? ["live", "replay"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: 0, market })).bridge_id, applied: fit }; }
    catch (e) { last = e; if (isEvidenceError(e)) break; }
  }
  throw startFailure(last, ok.id);
}

export const REPLAY_SANDBOX_SENTENCE = "On a recorded replay (the default here) its orders fill in an isolated replay sandbox, not this account.";

export function fillScopeLabel(scope: string | null | undefined, acct: { name: string; tone: "sim" | "paper" | "demo" }):
  { sandbox: boolean; name: string; tone: "replay" | "sim" | "paper" | "demo"; title: string; filledVerb: string } {
  return scope === "replay_sandbox"
    ? { sandbox: true, name: "replay sandbox, not your account", tone: "replay", title: "Replay bridges fill orders in an isolated sandbox (sim-replay), never in your account.", filledVerb: "Sandbox filled" }
    : { sandbox: false, name: acct.name, tone: acct.tone, title: "This account gets the engine orders (GET /account).", filledVerb: "Broker filled" };
}

export const liveVenue = (source: string | null | undefined) => (source === "kalshi" ? "Kalshi" : "Polymarket");

export interface ReplayInfo {
  file?: string | null; market_id?: string | null; market_source?: string | null; market_token_id?: string | null; known?: boolean;
}

export function replayInfo(summary: { replay_file?: string | null; replay_market?: { source?: string | null; id?: string | null; token_id?: string | null } | null } | null | undefined): ReplayInfo | null {
  if (!summary) return null;
  const m = summary.replay_market;
  return {
    file: summary.replay_file ?? null, market_id: m?.id ?? null, market_source: m?.source ?? null, market_token_id: m?.token_id ?? null,
    known: "replay_market" in summary ? m != null : undefined,
  };
}

export function replayMismatch(replay: ReplayInfo | null | undefined, marketSource?: string | null, marketId?: string | null, marketTokenId?: string | null): boolean {
  const rec = [replay?.market_id, replay?.market_token_id].filter((x): x is string => !!x);
  const ours = [marketId, marketTokenId].filter((x): x is string => !!x);
  if (!rec.length || !ours.length) return false;
  if (replay?.market_source && marketSource && replay.market_source !== marketSource) return true;
  return !rec.some((k) => ours.includes(k));
}

export function priceSubtitle(source: string | null | undefined, marketSource: string | null | undefined,
  replay?: ReplayInfo | null, marketId?: string | null, marketTokenId?: string | null):
  { sub: string; mismatch: boolean } {
  if (source === "replay") {
    return { sub: `YES from replay ${replay?.file ?? "file"}. Recorded history, not the live market.`, mismatch: replayMismatch(replay, marketSource, marketId, marketTokenId) };
  }
  const venue = liveVenue(marketSource);
  return { sub: `YES ${venue} midpoint${venue === "Kalshi" ? "" : " · Kalshi not streamed on this bridge"}`, mismatch: false };
}

export function replayNotice(source: string | null | undefined, requestedSource: string | null | undefined, replay: ReplayInfo | null | undefined,
  market?: { source?: string | null; id?: string | null; token_id?: string | null } | null): { tone: "warn" | "info"; text: string } | null {
  if (source !== "replay") return null;
  const file = replay?.file ? `the recording ${replay.file}` : "a recording";
  const fellBack = requestedSource === "live" ? `The live feed was not available, so this bridge uses ${file}. ` : "";
  if (replayMismatch(replay, market?.source, market?.id, market?.token_id)) {
    const rec = `${replay?.market_source ? replay.market_source + ":" : ""}${replay?.market_id ?? replay?.market_token_id}`;
    return { tone: "warn", text: `${fellBack}CAUTION: Do not read this replay${replay?.file ? ` (${replay.file})` : ""} as data for this question. It records a different market (${rec}), and its prices and trades come from that recording.` };
  }
  if (replay?.known === false) {
    return { tone: "info", text: `${fellBack}${replay.file ?? "This replay file"} has no .meta.json sidecar, so the backend cannot confirm its market. It plays because the request or the file name points to this market.` };
  }
  if (!fellBack) return null;
  const rec = replay?.known && (replay.market_id || replay.market_token_id)
    ? `It records this market (${replay.market_source ? replay.market_source + ":" : ""}${replay.market_id ?? replay.market_token_id}).` : "";
  return { tone: "info", text: (fellBack + rec).trim() };
}
