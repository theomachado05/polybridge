// Voice drives the screen: every client tool result becomes {route, storeUpdate, announcement, scrollTo}, so the
// screen lands exactly where the mouse flow would have put it (same store state, same route) and the user can carry
// on with the mouse. Pure, so every tool (and every error) is unit-tested offline. An error never navigates away.
import type { Direction, FitOut, Market, Proposal } from "./api.ts";
import type { ToolReply } from "./voice.ts";

export const SCREENS = ["landing", "build", "pipeline", "bridge", "portfolio", "library", "profile", "connect"] as const;
export type Screen = (typeof SCREENS)[number];
/** The generic AI fit flow (Build → Connect → fit → approval). /pipeline is the ladder board; the screen name
 *  "pipeline" stays as it is in backend/app/agent/tools.py SCREENS so the navigate tool's enum matches. */
export const FIT_PATH = "/build/fit";
export const SCREEN_PATH: Record<Screen, string> = {
  landing: "/", build: "/build", pipeline: "/pipeline", bridge: "/bridge", portfolio: "/portfolio", library: "/library",
  profile: "/profile", connect: "/connect",
};
const SCREEN_NAME: Record<Screen, string> = {
  landing: "the home screen", build: "Build", pipeline: "the ladder board", bridge: "the ticket board and your bridges", portfolio: "your portfolio",
  library: "the algo library", profile: "your profile", connect: "Connect",
};

/** Element ids the screens carry so voice can smooth-scroll to the panel it is talking about. */
export const VOICE_ANCHOR = {
  steps: "voice-steps", approval: "voice-approval", account: "voice-account", positions: "voice-positions",
} as const;

/** What the store does for a tool result (StoreProvider.applyVoice), mirroring the mouse flow. */
export type StoreUpdate =
  /** Build step 1 with the query typed in (the mouse: edit the question, type the topic). */
  | { kind: "search"; query: string }
  /** The fit for this market + ticker lands in the store, as if Build had picked them and the pipeline had fitted. */
  | { kind: "fit"; market: Market; ticker: string; direction: Direction | null; sharesHeld: number | null; fit: FitOut }
  /** This proposal (pending or approved) is the one the pipeline's approval panel shows and approves. */
  | { kind: "proposal"; proposal: Proposal; market: Market }
  /** A bridge voice started: listed on the Bridge screen and active. */
  | { kind: "bridge"; bridgeId: string; proposalId: string | null }
  /** Re-read GET /account and GET /portfolio. */
  | { kind: "account" };

export interface VoiceDrive { route: string | null; storeUpdate: StoreUpdate | null; announcement: string; scrollTo: string | null }

const obj = (x: unknown): Record<string, unknown> => (x && typeof x === "object" && !Array.isArray(x) ? (x as Record<string, unknown>) : {});
const str = (x: unknown): string | null => (typeof x === "string" && x.trim() ? x.trim() : null);
const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const dir = (x: unknown): Direction | null => (x === "down_on_yes" || x === "up_on_yes" ? x : null);
const isScreen = (x: unknown): x is Screen => typeof x === "string" && (SCREENS as readonly string[]).includes(x);

/** The search rows of a search_markets reply (to resolve the market a later fit or propose names). */
export function searchedMarkets(reply: ToolReply): Market[] {
  const ms = obj(reply.data).markets;
  return reply.ok && Array.isArray(ms) ? (ms.filter((m) => str(obj(m).id) && str(obj(m).source)) as Market[]) : [];
}

/** The market row for (source, id): the searched row when the agent found it by search, else a minimal row with
 *  only what the agent knows (no invented price or volume: null and 0, as the backend reports an unknown). */
export function resolveMarket(source: string | null, id: string, tokenId: string | null, question: string | null, known: readonly Market[] = []): Market {
  const src = source === "kalshi" ? "kalshi" : "polymarket";
  const hit = known.find((m) => m.source === src && String(m.id) === id);
  if (hit) return hit;
  return { source: src, id, question: question ?? `Market ${id}`, yes_price: null, volume_24h: 0, end_date: null, url: null, token_id: tokenId };
}

const TOOL_WHAT: Record<string, string> = {
  search_markets: "The market search", fit: "The fit", propose: "The proposal", approve: "The approval", start_bridge: "Starting the bridge",
  bridge_status: "The bridge check", account: "Reading the account", positions: "Reading the positions", navigate: "Opening that screen",
};

/** The pill's text while a tool runs. */
export function voiceStartLabel(tool: string, args: Record<string, unknown> | null | undefined): string {
  const a = obj(args);
  switch (tool) {
    case "search_markets": return str(a.q) ? `Searching markets for “${str(a.q)}”…` : "Searching markets…";
    case "fit": return `Fitting ${str(a.ticker)?.toUpperCase() ?? "a hedge"}…`;
    case "propose": return `Drafting a proposal${str(a.ticker) ? ` for ${str(a.ticker)!.toUpperCase()}` : ""}…`;
    case "approve": return a.confirm === true ? "Approving the proposal…" : "Checking the approval…";
    case "start_bridge": return a.confirm === true ? "Starting the bridge…" : "Checking the bridge start…";
    case "bridge_status": return "Checking the bridge…";
    case "account": return "Opening your account…";
    case "positions": return "Opening your positions…";
    case "navigate": return isScreen(a.screen) ? `Opening ${SCREEN_NAME[a.screen]}` : "Opening a screen…";
    default: return "Working…";
  }
}

const stay = (announcement: string): VoiceDrive => ({ route: null, storeUpdate: null, announcement, scrollTo: null });

/** One tool result → where the screen goes. `known`: the rows of the last search, to resolve a market by id. */
export function voiceDrive(tool: string, args: Record<string, unknown> | null | undefined, reply: ToolReply, known: readonly Market[] = []): VoiceDrive {
  const a = obj(args);
  const what = TOOL_WHAT[tool] ?? "That step";
  if (!reply.ok) {
    // Never navigate away on an error: the screen stays where the user is.
    return stay(reply.needs_confirmation ? "Waiting for your spoken yes" : `${what} did not work · staying here`);
  }
  const d = obj(reply.data);
  switch (tool) {
    case "search_markets": {
      const query = str(a.q);
      if (!query) return stay("Searched markets");
      const n = searchedMarkets(reply).length;
      return { route: "/build", storeUpdate: { kind: "search", query }, scrollTo: null,
        announcement: n ? `Showing markets for “${query}”` : `No markets for “${query}”` };
    }
    case "fit": {
      const ticker = str(a.ticker)?.toUpperCase();
      const id = str(a.market_id);
      if (!ticker || !reply.data) return stay("Fit done");
      if (!id) return stay(`Fitted ${ticker} · name a market to see its steps`);
      const market = resolveMarket(str(a.market_source), id, str(a.token_id), str(a.question), known);
      const score = num(d.score);
      return {
        route: FIT_PATH, scrollTo: VOICE_ANCHOR.steps,
        storeUpdate: { kind: "fit", market, ticker, direction: dir(a.direction), sharesHeld: num(a.shares_held), fit: reply.data as FitOut },
        announcement: `${ticker} fit ready${score == null ? " · unscored" : ` · score ${score.toFixed(2)}`}`,
      };
    }
    case "propose":
    case "approve": {
      const p = reply.data as Proposal | null;
      const m = obj(p?.market);
      const id = str(m.id);
      if (!p || !str(p.id)) return stay(tool === "approve" ? "Approved" : "Proposal drafted");
      const label = tool === "approve" ? `Proposal ${p.id} approved` : `Proposal ${p.id} is waiting for your approval`;
      // A proposal from filing tags (no market) or an opportunity has no hedge approval panel: say it, stay.
      if (!id || p.family !== "hedge") return stay(label);
      if (tool === "approve" && a.confirm !== true) return stay(label);
      const market = resolveMarket(str(m.source), id, str(m.token_id), null, known);
      return { route: FIT_PATH, storeUpdate: { kind: "proposal", proposal: p, market }, announcement: label, scrollTo: VOICE_ANCHOR.approval };
    }
    case "start_bridge": {
      const bid = str(d.bridge_id);
      if (!bid || a.confirm !== true) return stay("Bridge started");
      return { route: `/bridge/${encodeURIComponent(bid)}`, storeUpdate: { kind: "bridge", bridgeId: bid, proposalId: str(a.proposal_id) },
        announcement: `Bridge ${bid} is live`, scrollTo: null };
    }
    case "bridge_status": {
      const bid = str(a.bridge_id) ?? str(d.bridge_id) ?? str(d.id);
      if (!bid) return stay("Checked the bridge");
      return { route: `/bridge/${encodeURIComponent(bid)}`, storeUpdate: null, announcement: `Showing bridge ${bid}`, scrollTo: null };
    }
    case "account":
      return { route: "/portfolio", storeUpdate: { kind: "account" }, announcement: "Opening your account", scrollTo: VOICE_ANCHOR.account };
    case "positions":
      return { route: "/portfolio", storeUpdate: { kind: "account" }, announcement: "Opening your positions", scrollTo: VOICE_ANCHOR.positions };
    case "navigate": {
      const screen = isScreen(d.screen) ? d.screen : isScreen(a.screen) ? a.screen : null;
      if (!screen) return stay("Opening that screen did not work · staying here");
      const bid = screen === "bridge" ? str(d.bridge_id) ?? str(a.bridge_id) : null;
      const route = bid ? `/bridge/${encodeURIComponent(bid)}` : SCREEN_PATH[screen];
      return { route, storeUpdate: null, announcement: bid ? `Opening bridge ${bid}` : `Opening ${SCREEN_NAME[screen]}`, scrollTo: null };
    }
    default:
      return stay("Done");
  }
}

/** `navigate` runs in the browser only (no backend call): a reply in the backend's shape, for the agent to read. */
export function navigateReply(args: Record<string, unknown> | null | undefined): ToolReply {
  const a = obj(args);
  if (!isScreen(a.screen)) {
    return { ok: false, tool: "navigate", summary: `I cannot open ${str(a.screen) ?? "that"}. I can open: ${SCREENS.join(", ")}.`, data: null };
  }
  const bid = a.screen === "bridge" ? str(a.bridge_id) : null;
  return { ok: true, tool: "navigate", summary: `The screen now shows ${bid ? `bridge ${bid}` : SCREEN_NAME[a.screen]}.`, data: { screen: a.screen, bridge_id: bid } };
}
