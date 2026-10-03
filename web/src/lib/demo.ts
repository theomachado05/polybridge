// The design prototype's data (design/design_handoff_polybridge/PolyBridge.dc.html), used whenever an
// endpoint is missing or fails. Every screen that shows it carries a "demo data" label.
import type { Direction, Market } from "./api";
import { fmtK } from "./fmt.ts";

export interface Question {
  id: string;
  ev: string;           // short phrase: "If {ev}."
  q: string;            // full question
  venues: string[];
  yes: number;          // YES price in cents
  vol: string;
  volN: number;
  resolves?: string;
  cat?: string;
  touches: string[];
  real?: Market;        // set when the row came from GET /markets/search
}

export interface Impact {
  t: string;
  move: number;         // expected % move on YES
  rev: number | null;
  brand: number | null;
  why: string;
  direction?: Direction;
  real?: boolean;       // from POST /map
}

export interface EqInfo { name: string; px: number | null; held: number }

export interface EquityPick extends Impact { name: string; px: number | null; held: number }

export const QUESTIONS: Question[] = [
  { id: "ca-str", ev: "California bans short-term rentals before 2027", q: "Will California ban short-term rentals statewide before 2027?", venues: ["Polymarket", "Kalshi"], yes: 23, vol: "48.2k", volN: 48200, resolves: "Dec 31, 2026", cat: "Regulation", touches: ["ABNB", "EXPE", "BKNG", "MAR", "HLT"] },
  { id: "fed-dec", ev: "the Fed cuts rates in December", q: "Will the Fed cut rates at the December meeting?", venues: ["Kalshi", "Polymarket"], yes: 62, vol: "2.4M", volN: 2400000, resolves: "Dec 10, 2026", cat: "Macro", touches: ["JPM", "BAC", "KRE"] },
  { id: "tiktok", ev: "TikTok is banned in the US", q: "Will TikTok be banned in the US before July 2027?", venues: ["Polymarket"], yes: 31, vol: "910k", volN: 910000, resolves: "Jul 1, 2027", cat: "Tech", touches: ["META", "SNAP", "GOOGL"] },
  { id: "chips", ev: "new chip export controls hit China", q: "Will new US chip export controls on China take effect this year?", venues: ["Polymarket", "Kalshi"], yes: 44, vol: "1.1M", volN: 1100000, resolves: "Dec 31, 2026", cat: "Politics", touches: ["NVDA", "AMD", "ASML"] },
  { id: "fsd", ev: "Tesla gets unsupervised FSD in California", q: "Will Tesla get unsupervised FSD approval in California in 2026?", venues: ["Polymarket"], yes: 18, vol: "620k", volN: 620000, resolves: "Dec 31, 2026", cat: "Regulation", touches: ["TSLA", "UBER"] },
  { id: "drugs", ev: "Medicare price caps expand to 30+ drugs", q: "Will Medicare price caps expand to 30+ drugs by 2027?", venues: ["Kalshi"], yes: 57, vol: "340k", volN: 340000, resolves: "Jan 15, 2027", cat: "Politics", touches: ["PFE", "MRK", "LLY"] },
  { id: "dma", ev: "the EU fines Apple €5B+ under the DMA", q: "Will the EU fine Apple over €5B under the DMA in 2026?", venues: ["Polymarket"], yes: 27, vol: "415k", volN: 415000, resolves: "Dec 31, 2026", cat: "Regulation", touches: ["AAPL"] },
  { id: "shutdown", ev: "the US government shuts down before Jan 31", q: "Will the US government shut down before Jan 31?", venues: ["Kalshi", "Polymarket"], yes: 36, vol: "3.1M", volN: 3100000, resolves: "Jan 31, 2027", cat: "Politics", touches: ["LMT", "BAH", "SPY"] },
];

export const EQ: Record<string, EqInfo> = {
  ABNB: { name: "Airbnb Inc", px: 128.4, held: 1200 }, EXPE: { name: "Expedia Group", px: 171.2, held: 0 }, BKNG: { name: "Booking Holdings", px: 4810.5, held: 0 }, MAR: { name: "Marriott International", px: 262.1, held: 300 }, HLT: { name: "Hilton Worldwide", px: 241.8, held: 0 },
  JPM: { name: "JPMorgan Chase", px: 228.6, held: 400 }, BAC: { name: "Bank of America", px: 46.1, held: 0 }, KRE: { name: "Regional Banks ETF", px: 61.4, held: 0 },
  META: { name: "Meta Platforms", px: 612.3, held: 150 }, SNAP: { name: "Snap Inc", px: 9.8, held: 0 }, GOOGL: { name: "Alphabet", px: 182.4, held: 0 },
  NVDA: { name: "NVIDIA", px: 134.2, held: 600 }, AMD: { name: "Advanced Micro Devices", px: 158.7, held: 0 }, ASML: { name: "ASML Holding", px: 742.1, held: 0 },
  TSLA: { name: "Tesla", px: 318.4, held: 200 }, UBER: { name: "Uber Technologies", px: 78.9, held: 0 },
  PFE: { name: "Pfizer", px: 27.3, held: 0 }, MRK: { name: "Merck & Co", px: 101.2, held: 0 }, LLY: { name: "Eli Lilly", px: 812.6, held: 50 },
  AAPL: { name: "Apple Inc", px: 231.5, held: 800 }, LMT: { name: "Lockheed Martin", px: 468.2, held: 0 }, BAH: { name: "Booz Allen Hamilton", px: 118.4, held: 0 }, SPY: { name: "S&P 500 ETF", px: 571.3, held: 0 },
};

export const IMPACTS: Record<string, Impact[]> = {
  "ca-str": [
    { t: "ABNB", move: -3.2, rev: -1.0, brand: -5.0, why: "CA ≈ 9% of nights; 18-month phase-in. Brand hit sized on NYC Local Law 18 comps." },
    { t: "EXPE", move: -0.8, rev: -0.4, brand: -1.2, why: "Vrbo exposure to CA coastal markets; hotel bookings offset part of it." },
    { t: "BKNG", move: -0.4, rev: -0.2, brand: -0.5, why: "Alternative accommodations ≈ 35% of nights, but CA is a small slice." },
    { t: "MAR", move: 0.6, rev: 0.4, brand: 0.0, why: "Hotel share gain in LA, SF and San Diego as STR supply exits." },
    { t: "HLT", move: 0.5, rev: 0.3, brand: 0.0, why: "Same share-gain story; smaller CA footprint than Marriott." },
  ],
  "fed-dec": [
    { t: "JPM", move: -0.9, rev: -0.6, brand: 0.0, why: "NII compresses ~25 bps per cut; deposit beta lags." },
    { t: "BAC", move: -1.4, rev: -1.1, brand: 0.0, why: "Most asset-sensitive of the money-center banks." },
    { t: "KRE", move: 1.1, rev: 0.6, brand: 0.0, why: "Regionals gain on CRE refinancing relief and curve steepening." },
  ],
  tiktok: [
    { t: "META", move: 2.4, rev: 1.6, brand: 0.5, why: "Reels captures ~40% of displaced US short-video minutes in prior outages." },
    { t: "SNAP", move: 3.8, rev: 2.1, brand: 0.6, why: "Highest relative beneficiary; Spotlight ad load has headroom." },
    { t: "GOOGL", move: 0.6, rev: 0.4, brand: 0.0, why: "Shorts upside diluted across the Alphabet base." },
  ],
  chips: [
    { t: "NVDA", move: -2.1, rev: -1.4, brand: -0.5, why: "China ≈ 13% of data-center revenue; H20-class SKUs most exposed." },
    { t: "AMD", move: -1.6, rev: -0.9, brand: -0.3, why: "MI308 exposure; smaller base than NVDA." },
    { t: "ASML", move: -1.2, rev: -0.8, brand: 0.0, why: "DUV servicing revenue in China at risk." },
  ],
};

export function demoImpacts(q: Question): Impact[] {
  return IMPACTS[q.id] ?? q.touches.map((t, i) => ({ t, move: -(1.8 - i * 0.5), rev: -(1.0 - i * 0.3), brand: -(1.5 - i * 0.4), why: "Estimated from sector beta to the event; low-confidence until more book depth." }));
}

export interface Instrument {
  id: string; kind: string; name: string; cover: string; cost: string; tax: string; fit: string; rec: boolean; short: string; phrase: string;
}
export const INSTRUMENTS = (px: number, acct: string): Instrument[] => [
  { id: "shares", kind: "DYNAMIC HEDGE", name: "Short shares · delta re-hedged tick by tick", cover: "Scales with Δp", cost: "$0.0035/sh + 0.3% borrow", tax: acct === "IRA" ? "No wash-sale concern" : "Lot-aware · avoids wash sales", fit: "Lowest latency — the algo stack adjusts size every tick as the market moves.", rec: true, short: "Dynamic short hedge", phrase: "a dynamic short hedge" },
  { id: "puts", kind: "OPTIONS", name: `Put spread · ${Math.round(px * 0.93)}/${Math.round(px * 0.86)}`, cover: "Defined to −14%", cost: `≈ $${(px * 0.0165).toFixed(2)} debit`, tax: "Equity option · §1256 n/a", fit: "Fixed cost, capped payoff. Good when borrow is scarce.", rec: false, short: `Put spread ${Math.round(px * 0.93)}/${Math.round(px * 0.86)}`, phrase: `a ${Math.round(px * 0.93)}/${Math.round(px * 0.86)} put spread` },
  { id: "collar", kind: "OPTIONS", name: `Collar · ${Math.round(px * 0.93)}P / ${Math.round(px * 1.09)}C`, cover: "Floor −7%, cap +9%", cost: "≈ zero cost", tax: acct === "IRA" ? "Fine in IRA" : "May pause holding period", fit: "Cheapest protection if you can give up upside into the event.", rec: false, short: "Zero-cost collar", phrase: "a zero-cost collar" },
  { id: "contract", kind: "DIRECT", name: "Buy YES on Polymarket", cover: "Pays only on resolution", cost: "Market price per $1", tax: "Treatment unclear", fit: "Not a price hedge — the stock moves before the contract resolves.", rec: false, short: "Direct YES contract", phrase: "a direct YES contract" },
];

export interface DemoAlgo { id: string; name: string; fam: string; role: string; tunes: string }
export const ALGOS: DemoAlgo[] = [
  { id: "PB-0001", name: "Sigma Gate", fam: "Gate", role: "Decides whether a probability move clears the noise floor before anything else runs.", tunes: "σ window · threshold" },
  { id: "PB-0007", name: "Jump Detector", fam: "Gate", role: "Flags discontinuous moves in the contract (news, resolution leaks) and shortens every downstream horizon.", tunes: "jump size · decay" },
  { id: "PB-0112", name: "Book-Imbalance Reader", fam: "Reader", role: "Reads bid/ask depth on Polymarket and Kalshi to tell real conviction from thin prints.", tunes: "depth levels · venue weights" },
  { id: "PB-0118", name: "Venue Divergence", fam: "Reader", role: "Measures the Polymarket–Kalshi spread and shrinks size when the venues disagree.", tunes: "spread tolerance" },
  { id: "PB-0131", name: "Volume Surge Monitor", fam: "Reader", role: "Scales confidence with 24h volume relative to the contract’s own history.", tunes: "lookback · surge ratio" },
  { id: "PB-0240", name: "Delta-Bridge v3", fam: "Impact", role: "Maps a change in probability into expected equity drift through revenue, brand and regulatory channels.", tunes: "channel weights · confidence" },
  { id: "PB-0244", name: "Comp Backtester", fam: "Impact", role: "Scores the chain against historical analogues — NYC LL18, Barcelona 2028, prior rate cycles.", tunes: "comp set · horizon" },
  { id: "PB-0251", name: "Priced-In Estimator", fam: "Impact", role: "Estimates how much of the event the stock has already absorbed, so only the residual is hedged.", tunes: "beta window" },
  { id: "PB-0402", name: "Vol-Adaptive Slicer", fam: "Execution", role: "Splits the parent order into child slices sized by realized σ; faster when the tape is moving.", tunes: "σ · slice count · latency" },
  { id: "PB-0407", name: "Meridian TWAP", fam: "Execution", role: "Time-weighted fills for low-urgency hedges; minimizes footprint over a chosen window.", tunes: "window · participation" },
  { id: "PB-0415", name: "Liquidity Seeker", fam: "Execution", role: "Works hidden size across dark and lit venues when spreads widen.", tunes: "min fill · venues" },
  { id: "PB-0611", name: "Tax-Lot Optimizer", fam: "Tax", role: "Picks the lots to sell or cover so gains stay long-term and wash-sale windows are respected.", tunes: "holding period · wash window" },
  { id: "PB-0618", name: "Wash-Sale Sentinel", fam: "Tax", role: "Blocks any fill that would disallow a loss inside the 30-day window.", tunes: "window" },
  { id: "PB-0702", name: "Fee-Aware Router", fam: "Routing", role: "Routes each child order to the venue with the lowest all-in cost for your fee schedule.", tunes: "fee table · borrow rate" },
  { id: "PB-0709", name: "Edge-vs-Cost Gate", fam: "Routing", role: "Cancels the trade when expected edge is smaller than commissions plus borrow.", tunes: "min edge" },
];
export const IN_CHAIN = new Set(["Sigma Gate", "Book-Imbalance Reader", "Delta-Bridge v3", "Vol-Adaptive Slicer", "Meridian TWAP", "Tax-Lot Optimizer", "Fee-Aware Router"]);
export const DEMO_ALGO_COUNT = 1284;

export const LOGO = (d: string) => `https://www.google.com/s2/favicons?domain=${d}&sz=128`;
export interface Broker { id: string; name: string; sub: string; domain: string; logo: string }
export const BROKERS: Broker[] = [
  { id: "webull", name: "Webull", sub: "$0 commission · primary", domain: "webull.com" },
  { id: "alpaca", name: "Alpaca", sub: "API · $0 commission", domain: "alpaca.markets" },
  { id: "ibkr", name: "Interactive Brokers", sub: "$0.0035/sh tiered", domain: "interactivebrokers.com" },
  { id: "schwab", name: "Schwab", sub: "$0 equities", domain: "schwab.com" },
  { id: "robinhood", name: "Robinhood", sub: "Options · $0", domain: "robinhood.com" },
].map((b) => ({ ...b, logo: LOGO(b.domain) }));

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
