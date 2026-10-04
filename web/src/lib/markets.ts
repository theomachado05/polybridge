import type { Direction, Market } from "./api";
import { fmtK } from "./fmt.ts";

export interface Question {
  id: string;
  ev: string;
  q: string;
  venues: string[];
  yes: number;
  vol: string;
  volN: number;
  resolves?: string;
  touches: string[];
  real: Market;
}

export interface Impact {
  t: string;
  move: number;
  rev: number | null;
  brand: number | null;
  why: string;
  direction?: Direction;
  real?: boolean;
  directionSource?: "mapping" | "user" | "recording";
}

export interface EquityPick extends Impact { name: string; px: number | null; held: number }

export interface Instrument {
  id: string; kind: string; name: string; cover: string; cost: string; tax: string; fit: string; rec: boolean; short: string; phrase: string;
}

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

export const HEDGE_INSTRUMENTS = (spot: number | null): Instrument[] => [
  {
    id: "shares", kind: "DYNAMIC HEDGE", name: "Short shares that the engine resizes when the probability changes",
    cover: "Changes with Δp", cost: spot ? `last quote $${spot.toFixed(2)}` : "quote unavailable",
    tax: "Live bridges do not use tax-lot or wash-sale rules",
    fit: "The engine runs this hedge. It sizes a short position to the probability of the adverse outcome.",
    rec: false, short: "Dynamic short hedge", phrase: "a dynamic short hedge",
  },
];

export const FEATURED_REPLAY = { source: "polymarket", id: "4620900", ticker: "TLT" } as const;
export const isFeaturedReplay = (q: Pick<Question, "id">): boolean => q.id === `${FEATURED_REPLAY.source}:${FEATURED_REPLAY.id}`;
export function featuredFirst<T extends Pick<Question, "id">>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => Number(isFeaturedReplay(b)) - Number(isFeaturedReplay(a)));
}

export const WEEKEND_REPLAY = {
  source: "polymarket",
  id: "516710",
  token_id: "104173557214744537570424345347209544585775842950109756851652855913015295701992",
  question: "US recession in 2025?",
  recorded: "us-recession-in-2025-weekend-2025-04-04.jsonl",
  ticker: "SPY",
  direction: "down_on_yes",
  query: "US recession in 2025",
} as const;
export const isWeekendReplay = (m: Pick<Market, "source" | "id"> | null | undefined): boolean =>
  !!m && m.source === WEEKEND_REPLAY.source && String(m.id) === WEEKEND_REPLAY.id;

export function weekendQuestion(rows: readonly Market[] | null | undefined): Question {
  const hit = (rows ?? []).find((m) => isWeekendReplay(m));
  const m: Market = hit
    ? { ...hit, recorded: hit.recorded ?? WEEKEND_REPLAY.recorded, token_id: hit.token_id ?? WEEKEND_REPLAY.token_id }
    : { source: WEEKEND_REPLAY.source, id: WEEKEND_REPLAY.id, question: WEEKEND_REPLAY.question, yes_price: null, volume_24h: 0,
        end_date: null, url: null, token_id: WEEKEND_REPLAY.token_id, recorded: WEEKEND_REPLAY.recorded };
  return { ...questionFromMarket(m), touches: [WEEKEND_REPLAY.ticker] };
}

export function weekendPick(holding: { name?: string | null; spot?: number | null; shares?: number } | null): EquityPick {
  return {
    t: WEEKEND_REPLAY.ticker, move: 0, rev: null, brand: null, real: true,
    why: "The recording gives the direction. A recession YES is adverse for SPY (down on YES). This market has no impact estimate.",
    direction: WEEKEND_REPLAY.direction, directionSource: "recording",
    name: holding?.name ?? WEEKEND_REPLAY.ticker, px: holding?.spot ?? null, held: holding?.shares ?? 0,
  };
}

export function isOpenMarket(m: Pick<Market, "end_date" | "yes_price">, now: number = Date.now()): boolean {
  const end = m.end_date ? Date.parse(m.end_date) : NaN;
  if (Number.isFinite(end) && end < now) return false;
  if (m.yes_price != null && (m.yes_price <= 0.01 || m.yes_price >= 0.99)) return false;
  return true;
}

export function isListedMarket(m: Pick<Market, "end_date" | "yes_price" | "recorded">, now: number = Date.now()): boolean {
  return isOpenMarket(m, now) || !!m.recorded;
}

export function isRecordedOnly(m: Pick<Market, "end_date" | "yes_price" | "recorded"> | null | undefined, now: number = Date.now()): boolean {
  return !!m && !!m.recorded && !isOpenMarket(m, now);
}

export function topImpact<T extends Pick<Impact, "t" | "move">>(impacts: readonly T[], held: (t: string) => boolean = () => false): T | undefined {
  return [...impacts].sort((a, b) => Math.abs(b.move) - Math.abs(a.move) || Number(held(b.t)) - Number(held(a.t)))[0];
}
