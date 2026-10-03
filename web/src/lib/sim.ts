// The prototype's per-bridge market simulator, ported 1:1 (PolyBridge.dc.html initSim/stepSim/makeTrade).
// Used only for bridges labelled "demo"; real bridges come from the backend SSE stream.
// Pure: the random source and the clock are injected so the offline tests are deterministic.
import { fmtK, fmtPct, fmtTime } from "./fmt.ts";

export type Rng = () => number;

export interface Trade { id: number; time: string; ts: number; side: "SELL" | "BUY"; qty: number; px: string; ticker: string; algo: string; reason: string; color: string }

export interface Sim {
  ticker: string; base: number; p0: number; impact: number; shares: number; tick: number;
  p: number; pk: number; pAtHedge: number; px: number; hist: number[]; phist: number[];
  vol: number; volPoly: number; hedge: number; hedgeAvg: number; realized: number; fees: number;
  lastTradeTick: number; lastAlgo: string | null; tradeCount: number; trades: Trade[];
}

export function gauss(rng: Rng): number {
  let u = 0, v = 0;
  while (!u) u = rng();
  while (!v) v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

interface TradeIn {
  id: number; time: Date; side: "SELL" | "BUY"; qty: number; px: number; dp: number; p: number; pk: number;
  vol: number; volPoly: number; algoName: string; slices: number; lat: number; fee: number; ticker: string; impact: number;
}

export function makeTrade(o: TradeIn): Trade {
  const sign = o.dp > 0 ? "+" : "−", cents = Math.abs(o.dp * 100).toFixed(1), drift = o.impact * o.dp * 100;
  const confirm = Math.abs(o.pk - o.p) > 0.012 ? "diverging — sized at 70%" : "confirming";
  const reason = `Polymarket YES ${sign}${cents}¢ on ${fmtK(Math.round(o.volPoly))} volume; Kalshi ${Math.round(o.pk * 100)}¢ ${confirm}. Delta-Bridge expects ${o.ticker} drift ${fmtPct(drift, 2)}. ${o.side === "SELL" ? "Added" : "Trimmed"} hedge via ${o.algoName}: σ ${Math.round(o.vol * 100)}%, ${o.slices} slices, ${o.lat} ms. Fee $${o.fee.toFixed(2)}, ${o.side === "BUY" ? "LT lot picked" : "no wash-sale"}.`;
  return { id: o.id, time: fmtTime(o.time), ts: o.time.getTime(), side: o.side, qty: o.qty, px: o.px.toFixed(2), ticker: o.ticker, algo: o.algoName, reason, color: o.side === "SELL" ? "#E0485A" : "#22A06B" };
}

/** yesCents: market YES price in cents; movePct: expected % move on YES; held: shares (0 → 500 notional). */
export function initSim(o: { ticker: string; px: number; held: number; yesCents: number; volN: number; movePct: number }, rng: Rng = Math.random, now = Date.now()): Sim {
  const base = o.px, p0 = Math.min(0.9, Math.max(0.05, o.yesCents / 100 || 0.5));
  const impact = (Math.abs(o.movePct) / 100) * Math.sign(o.movePct || -1), shares = o.held || 500;
  const hist: number[] = [], phist: number[] = [];
  let px = base, p = p0;
  for (let i = 0; i < 60; i++) {
    p = Math.min(0.9, Math.max(0.05, p + gauss(rng) * 0.003));
    px += (base * (1 + impact * (p - p0)) - px) * 0.3 + gauss(rng) * base * 0.0004;
    hist.push(px); phist.push(p);
  }
  const mk = (t: Omit<TradeIn, "ticker" | "impact">) => makeTrade({ ...t, ticker: o.ticker, impact });
  return {
    ticker: o.ticker, base, p0, impact, shares, tick: 0, p, pk: p + 0.008, pAtHedge: p, px, hist, phist, vol: 0.31, volPoly: o.volN,
    hedge: Math.round(shares * 0.38), hedgeAvg: base * 1.004, realized: shares * 0.18, fees: 4.12, lastTradeTick: -9, lastAlgo: null, tradeCount: 7,
    trades: [
      mk({ id: -1, time: new Date(now - 214000), side: "SELL", qty: Math.round(shares * 0.053), px: base * 1.0024, dp: 0.018, p: p0 + 0.01, pk: p0 + 0.02, vol: 0.3, volPoly: o.volN * 1.3, algoName: "Vol-Adaptive Slicer", slices: 3, lat: 41, fee: 0.42 }),
      mk({ id: -2, time: new Date(now - 611000), side: "BUY", qty: Math.round(shares * 0.032), px: base * 0.9986, dp: -0.014, p: p0 - 0.01, pk: p0 - 0.01, vol: 0.29, volPoly: o.volN * 0.9, algoName: "Meridian TWAP", slices: 5, lat: 38, fee: 0.33 }),
    ],
  };
}

export function stepSim(s: Sim, rng: Rng = Math.random, now = Date.now()): Sim {
  const hedgeDir = s.impact < 0 ? 1 : -1; // negative impact: the hedge is short when p rises
  const jump = rng() < 0.08 ? (rng() < 0.5 ? -1 : 1) * (0.012 + rng() * 0.03) : 0;
  const p = Math.min(0.92, Math.max(0.03, s.p + gauss(rng) * 0.0025 + jump));
  const pk = Math.min(0.92, Math.max(0.03, p + gauss(rng) * 0.005 + 0.008));
  const fair = s.base * (1 + s.impact * (p - s.p0));
  const px = s.px + (fair - s.px) * 0.35 + gauss(rng) * s.base * 0.0004;
  const hist = [...s.hist.slice(1), px], phist = [...s.phist.slice(1), p];
  const vol = Math.max(0.18, Math.min(0.62, s.vol + gauss(rng) * 0.008 + Math.abs(jump) * 1.5 - (s.vol - 0.3) * 0.05));
  const volPoly = Math.max(12000, Math.round(s.volPoly + gauss(rng) * s.p0 * 5000 + Math.abs(jump) * 300000));
  let { trades, hedge, hedgeAvg, fees, lastAlgo, pAtHedge, lastTradeTick, realized, tradeCount } = s;
  const tick = s.tick + 1, dp = p - s.pAtHedge;
  if (Math.abs(dp) > 0.011 && tick - lastTradeTick > 2) {
    const qty = Math.max(4, Math.round(s.shares * Math.abs(s.impact) * 100 * Math.abs(dp) * (0.9 + rng() * 0.3)));
    const side = dp * hedgeDir > 0 ? "SELL" : "BUY";
    const urgent = Math.abs(dp) > 0.025 || vol > 0.4;
    const algoName = urgent ? "Vol-Adaptive Slicer" : "Meridian TWAP";
    const slices = urgent ? Math.max(2, Math.round(qty / 25)) : Math.max(3, Math.round(qty / 12));
    const lat = Math.round(34 + rng() * 18), fee = +(qty * 0.0035 + 0.2).toFixed(2);
    trades = [makeTrade({ id: tick, time: new Date(now), side, qty, px, dp, p, pk, vol, volPoly, algoName, slices, lat, fee, ticker: s.ticker, impact: s.impact }), ...trades].slice(0, 8);
    if (side === "SELL") { hedgeAvg = (hedge * hedgeAvg + qty * px) / (hedge + qty); hedge += qty; }
    else { const q = Math.min(qty, hedge); realized += (hedgeAvg - px) * q; hedge -= q; }
    fees = +(fees + fee).toFixed(2); lastAlgo = algoName; pAtHedge = p; lastTradeTick = tick; tradeCount += 1;
  }
  return { ...s, tick, p, pk, px, hist, phist, vol, volPoly, trades, hedge, hedgeAvg, fees, lastAlgo, pAtHedge, lastTradeTick, realized, tradeCount };
}

export const simPnl = (s: Sim) => (s.px - s.base) * s.shares + (s.hedgeAvg - s.px) * s.hedge + s.realized;
export const simCover = (s: Sim) => Math.min(100, Math.round((s.hedge / s.shares) * 100));

/** Deterministic PRNG for tests (mulberry32). */
export function seeded(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
