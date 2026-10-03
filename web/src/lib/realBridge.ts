// Opening a live bridge on the backend: proposal → approval → POST /bridges (market-event path, contracts.md).
// Pure (API injected) so it is unit-tested offline. Callers must only invoke it on an explicit user action.
import * as http from "./api.ts";
import type { Proposal } from "./api";
import type { EquityPick, Question } from "./demo";

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

/** Proposal → approval → engine bridge on the real backend (market-event path, contracts.md).
 *  Reuses an earlier proposal for the same ticker, market and direction instead of creating one per run: an
 *  approved one (POST /bridges is idempotent per proposal, so this re-attaches to its bridge, or finally starts
 *  the bridge if an earlier attempt failed after approval), else a pending one, which is approved here. */
export async function startRealBridge(q: Question, eq: EquityPick, maxHedge: string, api: BridgeApi = defaultApi): Promise<{ bridgeId: string; gap: number }> {
  const { approveProposal, createProposal, getEquity, listProposals, startBridge } = api;
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  if (!eq.direction) throw new Error(`${eq.t} is not in this market's mapping, so the adverse outcome is unknown`);
  let spot = eq.px;
  if (!spot) spot = await getEquity(eq.t).then((c) => c.implied_move?.spot ?? null, () => null);
  const cap = Math.min(1, (parseInt(maxHedge, 10) || 100) / 100);
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const mine = (await listProposals().catch(() => [] as Proposal[]))
    .filter((p) => p.ticker === eq.t && p.family === "hedge" && sameMarket(p, m) && (p.direction ?? "down_on_yes") === eq.direction);
  const approved = mine.find((p) => p.status === "approved");
  const pending = mine.find((p) => p.status === "proposed");
  let ok: Proposal;
  if (approved) ok = approved;
  else if (pending) ok = await approveProposal(pending.id);
  else {
    const prop = await createProposal({ ticker: eq.t, market, direction: eq.direction, shares_held: eq.held || 500, target_coverage: Math.min(0.5, cap) });
    ok = prop.status === "approved" ? prop : await approveProposal(prop.id);
  }
  const gap = gapPerShare(spot, eq.move);
  const sources: ("replay" | "live")[] = m.token_id ? ["replay", "live"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    try { return { bridgeId: (await startBridge({ proposal_id: ok.id, source, gap_per_share: gap, direction: eq.direction, market })).bridge_id, gap }; }
    catch (e) { last = e; }
  }
  const why = last instanceof Error ? last.message : "the backend refused to start a bridge";
  throw new Error(`${why}; proposal ${ok.id} stays approved and is reused on the next try`);
}
