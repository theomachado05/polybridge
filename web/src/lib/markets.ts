// Markets, picks and the hedge menu the Build flow works with. Every question comes from the backend
// (GET /markets/search, GET /portfolio markets); every impact from POST /map. Nothing here is sample data.
import type { Direction, Market } from "./api";
import { fmtK } from "./fmt.ts";

export interface Question {
  id: string;
  ev: string;           // short phrase: "If {ev}."
  q: string;            // full question
  venues: string[];
  yes: number;          // YES price in cents (0 when the backend reports none; check real.yes_price)
  vol: string;
  volN: number;
  resolves?: string;
  touches: string[];
  real: Market;         // the backend's market row
}

export interface Impact {
  t: string;
  move: number;         // expected % move on YES (0: unknown)
  rev: number | null;
  brand: number | null;
  why: string;
  direction?: Direction;
  real?: boolean;       // from POST /map
  /** Who set `direction`: the mapping (POST /map), the user's own answer, or a recording's sidecar. */
  directionSource?: "mapping" | "user" | "recording";
}

export interface EquityPick extends Impact { name: string; px: number | null; held: number }

export interface Instrument {
  id: string; kind: string; name: string; cover: string; cost: string; tax: string; fit: string; rec: boolean; short: string; phrase: string;
}

/** A GET /markets/search row as a wizard question. Tickers come later from POST /map. */
export function questionFromMarket(m: Market): Question {
  const ev = m.question.replace(/^will\s+/i, "").replace(/\?\s*$/, "");
  return {
    id: `${m.source}:${m.id}`,
    ev: ev.charAt(0).toLowerCase() + ev.slice(1),
    q: m.question,
    venues: [m.source === "kalshi" ? "Kalshi" : "Polymarket"],
    yes: m.yes_price == null ? 0 : Math.round(m.yes_price * 100),
    vol: fmtK(m.volume_24h || 0),
    volN: m.volume_24h || 0,
    resolves: m.end_date ?? undefined,
    touches: [],
    real: m,
  };
}

/** The engine runs exactly one hedge on a bridge: a short-shares delta bridge. No invented strikes, costs or tax
 *  claims; option structures are priced from real quotes on Build (GET /options/hedge-quote) for comparison only. */
export const HEDGE_INSTRUMENTS = (spot: number | null): Instrument[] => [
  {
    id: "shares", kind: "DYNAMIC HEDGE", name: "Short shares · re-sized by the engine as the probability moves",
    cover: "Scales with Δp", cost: spot ? `last quote $${spot.toFixed(2)}` : "quote unavailable",
    tax: "No tax-lot or wash-sale logic on live bridges yet",
    fit: "The hedge the engine runs today: a short position sized to the adverse-outcome probability.",
    rec: false, short: "Dynamic short hedge", phrase: "a dynamic short hedge",
  },
];

/** The TLT replay market (`make dev-tlt` and a bridge on it replay backend/replays/another-fed-hike-2026-history.jsonl):
 *  "Another Fed rate hike in 2026?" hedging TLT. Build lists it first among the held-market rows. */
export const FEATURED_REPLAY = { source: "polymarket", id: "4620900", ticker: "TLT" } as const;
export const isFeaturedReplay = (q: Pick<Question, "id">): boolean => q.id === `${FEATURED_REPLAY.source}:${FEATURED_REPLAY.id}`;
/** The same rows with the featured replay market moved to the front (the others keep their order). */
export function featuredFirst<T extends Pick<Question, "id">>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => Number(isFeaturedReplay(b)) - Number(isFeaturedReplay(a)));
}

/** The validated recession-market weekend, the closed-market demo (`make dev` default). Identity and orientation
 *  come from the recording's sidecar, backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl.meta.json:
 *  Polymarket 516710 and its YES token, `equity: "SPY"`, `weekend.sign: -1` (a recession YES is adverse for SPY,
 *  i.e. down_on_yes). The backend's replay index (app/data/replay_index.json) maps this market to that file, so a
 *  bridge on it replays the recorded weekend; its expected gap is the one market whose out-of-sample record passes. */
export const WEEKEND_REPLAY = {
  source: "polymarket",
  id: "516710",
  token_id: "104173557214744537570424345347209544585775842950109756851652855913015295701992",
  question: "US recession in 2025?",
  recorded: "us-recession-in-2025-weekend-2025-04-04.jsonl",
  ticker: "SPY",
  direction: "down_on_yes",
  /** The search that finds the market's own row (live search, else the backend's recordings when offline). */
  query: "US recession in 2025",
} as const;
export const isWeekendReplay = (m: Pick<Market, "source" | "id"> | null | undefined): boolean =>
  !!m && m.source === WEEKEND_REPLAY.source && String(m.id) === WEEKEND_REPLAY.id;

/** The weekend market as a Build question: the backend's own search row when it returns one (its final price and
 *  dates), else the recording's identity with no price (shown as "—", never invented). */
export function weekendQuestion(rows: readonly Market[] | null | undefined): Question {
  const hit = (rows ?? []).find((m) => isWeekendReplay(m));
  const m: Market = hit
    ? { ...hit, recorded: hit.recorded ?? WEEKEND_REPLAY.recorded, token_id: hit.token_id ?? WEEKEND_REPLAY.token_id }
    : { source: WEEKEND_REPLAY.source, id: WEEKEND_REPLAY.id, question: WEEKEND_REPLAY.question, yes_price: null, volume_24h: 0,
        end_date: null, url: null, token_id: WEEKEND_REPLAY.token_id, recorded: WEEKEND_REPLAY.recorded };
  return { ...questionFromMarket(m), touches: [WEEKEND_REPLAY.ticker] };
}

/** The weekend's SPY pick. The direction is the recording's (sidecar sign −1), labelled as such; held shares come from
 *  GET /portfolio (0 → the hedge is sized to a 500-share notional, as everywhere else). */
export function weekendPick(holding: { name?: string | null; spot?: number | null; shares?: number } | null): EquityPick {
  return {
    t: WEEKEND_REPLAY.ticker, move: 0, rev: null, brand: null, real: true,
    why: "Direction from the recording: a recession YES is adverse for SPY (down on YES). No impact size is estimated for this market.",
    direction: WEEKEND_REPLAY.direction, directionSource: "recording",
    name: holding?.name ?? WEEKEND_REPLAY.ticker, px: holding?.spot ?? null, held: holding?.shares ?? 0,
  };
}

/** False for a market that has ended or is effectively settled (YES at ≤1¢ or ≥99¢): no hedge is worth proposing on
 *  it, so step 1 never lists it as a live market. An unknown end date or price keeps the market. */
export function isOpenMarket(m: Pick<Market, "end_date" | "yes_price">, now: number = Date.now()): boolean {
  const end = m.end_date ? Date.parse(m.end_date) : NaN;
  if (Number.isFinite(end) && end < now) return false;
  if (m.yes_price != null && (m.yes_price <= 0.01 || m.yes_price >= 0.99)) return false;
  return true;
}

/** A market Build lists: an open one, or a resolved one the backend has a recording of (its replay is the demo). */
export function isListedMarket(m: Pick<Market, "end_date" | "yes_price" | "recorded">, now: number = Date.now()): boolean {
  return isOpenMarket(m, now) || !!m.recorded;
}

/** A resolved (or settled-price) market listed only because the backend has its recording. */
export function isRecordedOnly(m: Pick<Market, "end_date" | "yes_price" | "recorded"> | null | undefined, now: number = Date.now()): boolean {
  return !!m && !!m.recorded && !isOpenMarket(m, now);
}

/** The impact the mapping names first: the largest move, a held ticker winning ties. */
export function topImpact<T extends Pick<Impact, "t" | "move">>(impacts: readonly T[], held: (t: string) => boolean = () => false): T | undefined {
  return [...impacts].sort((a, b) => Math.abs(b.move) - Math.abs(a.move) || Number(held(b.t)) - Number(held(a.t)))[0];
}
