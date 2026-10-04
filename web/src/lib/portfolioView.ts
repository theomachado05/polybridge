// Pure helpers for the Portfolio screen (unit-tested offline).

interface SessionBridge { kind: string; bridgeId?: string; mode?: string; q?: { real?: unknown } | null; eq?: { t: string } | null }
interface HoldingHedge { ticker: string; hedge: { status: string; bridge_id?: string | null } }

/** The engine bridge hedging this holding: the backend's word (GET /portfolio hedge.status "bridging") first, else a
 *  live hedge bridge this session opened for the ticker on a real market. GET /portfolio is re-read on each visit,
 *  but the session's own bridge keeps the row honest while that refresh is in flight. Options bridges are not hedges
 *  of the holding. */
export function engineBridgeFor(h: HoldingHedge, bridges: readonly SessionBridge[]): string | null {
  if (h.hedge.status === "bridging" && h.hedge.bridge_id) return h.hedge.bridge_id;
  const mine = bridges.find((b) => b.kind === "live" && b.mode !== "opportunity" && !!b.q?.real && b.eq?.t === h.ticker && !!b.bridgeId);
  return mine?.bridgeId ?? null;
}
