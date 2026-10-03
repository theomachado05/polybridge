"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { approveProposal, createProposal, startBridge, type Direction, type Market, type Proposal } from "@/lib/api";
import { Badge, Btn, ErrorText } from "./ui";

const REPLAY_MARKET = { source: "polymarket", id: "fed-hike-25bps-oct-2026" };

export function ProposePanel({ ticker, tags, shares, onShares, market, spot, mappedImpact, direction, strategy }: {
  ticker: string; tags: string[] | null; shares: number; onShares: (n: number) => void;
  market: Market | null; spot: number | null; mappedImpact: number | null; direction: Direction; strategy: string | null;
}) {
  const router = useRouter();
  const [coverage, setCoverage] = useState(0.5);
  const [prop, setProp] = useState<Proposal | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<"live" | "replay">(market?.token_id ? "live" : "replay");

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const [manualImpact, setManualImpact] = useState("");
  const impact = mappedImpact ?? (Number(manualImpact) > 0 ? Number(manualImpact) : null);
  const gap = spot && impact ? (spot * Math.abs(impact)) / 100 : 0;
  const live = source === "live" && market?.token_id;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>Shares held <input type="number" min={1} value={shares} onChange={(e) => onShares(Math.max(0, Number(e.target.value)))} className="ml-1 w-24 rounded-lg border border-white/80 bg-white/80 px-2 py-1" /></label>
        <label>Coverage {Math.round(coverage * 100)}% <input type="range" min={0.1} max={1} step={0.1} value={coverage} onChange={(e) => setCoverage(Number(e.target.value))} /></label>
      </div>
      {strategy && <p className="text-xs text-slate-600">Selected hedge: {strategy.replaceAll("_", " ")} (the pre-registered family decides what the engine runs).</p>}
      {!prop && (
        <>
          <Btn disabled={busy || !tags?.length || shares <= 0} onClick={() => run(async () => setProp(await createProposal({ ticker, tags: tags ?? [], shares_held: shares, target_coverage: coverage })))}>Propose</Btn>
          {!tags?.length && <p className="text-xs text-slate-500">Pick a filing (or search a filing type) so the hedge family can be decided.</p>}
        </>
      )}
      {prop && (
        <div className="space-y-2">
          <p className="text-sm">Proposal {prop.id}: <Badge tone={prop.status === "approved" ? "good" : "warn"}>{prop.status}</Badge> <Badge>{prop.family}</Badge> {prop.strategy}</p>
          {prop.status === "proposed" && <Btn disabled={busy} onClick={() => run(async () => setProp(await approveProposal(prop.id)))}>Approve</Btn>}
          {prop.status === "approved" && prop.family === "opportunity" && (
            <p className="text-sm text-slate-700">Opportunity proposals are executed as a single simulated options order, not by the hedging engine.</p>
          )}
          {prop.status === "approved" && prop.family === "hedge" && (
            <div className="flex flex-wrap items-center gap-3">
              <select aria-label="Tick source" value={source} onChange={(e) => setSource(e.target.value as "live" | "replay")} className="rounded-lg border border-white/80 bg-white/80 px-2 py-1 text-sm">
                <option value="live" disabled={!market?.token_id}>Live (Polymarket midpoint)</option>
                <option value="replay">Replay (recorded Fed hike market)</option>
              </select>
              {mappedImpact == null && (
                <label className="text-sm">Impact % <input type="number" min={0} step={0.1} value={manualImpact} onChange={(e) => setManualImpact(e.target.value)} className="ml-1 w-20 rounded-lg border border-white/80 bg-white/80 px-2 py-1" /></label>
              )}
              <Btn disabled={busy || gap <= 0} onClick={() => run(async () => {
                const r = await startBridge({ proposal_id: prop.id, source, gap_per_share: gap, direction,
                  market: live && market ? { source: market.source, id: market.id, token_id: market.token_id } : REPLAY_MARKET });
                router.push(`/bridge/${r.bridge_id}`);
              })}>Start bridge</Btn>
            </div>
          )}
          {prop.status === "approved" && prop.family === "hedge" && gap <= 0 && (
            <p className="text-xs text-amber-700">No impact estimate for {ticker}: pick a mapped market or enter the event&apos;s impact % (and make sure the stock has a spot price).</p>
          )}
        </div>
      )}
      {err && <ErrorText>{err}</ErrorText>}
    </div>
  );
}
