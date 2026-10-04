interface SessionBridge { kind: string; bridgeId?: string; mode?: string; q?: { real?: unknown } | null; eq?: { t: string } | null }
interface HoldingHedge { ticker: string; hedge: { status: string; bridge_id?: string | null } }

export function engineBridgeFor(h: HoldingHedge, bridges: readonly SessionBridge[]): string | null {
  if (h.hedge.status === "bridging" && h.hedge.bridge_id) return h.hedge.bridge_id;
  const mine = bridges.find((b) => b.kind === "live" && b.mode !== "opportunity" && !!b.q?.real && b.eq?.t === h.ticker && !!b.bridgeId);
  return mine?.bridgeId ?? null;
}
