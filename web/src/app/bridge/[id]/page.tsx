"use client";

import { useParams } from "next/navigation";
import { getBridge, getEquity, listProposals } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useBridgeStream } from "@/lib/useBridgeStream";
import { BridgeEquityCard } from "@/components/BridgeEquityCard";
import { EngineNode } from "@/components/EngineNode";
import { PositionPanel } from "@/components/PositionPanel";
import { PriceCard } from "@/components/PriceCard";
import { StagePills } from "@/components/StagePills";
import { TradeLog } from "@/components/TradeLog";
import { Badge, ErrorText, Nav } from "@/components/ui";

export default function BridgePage() {
  const { id } = useParams<{ id: string }>();
  const summary = useAsync(`b:${id}`, () => getBridge(id));
  const s = useBridgeStream(id, summary.data?.source ?? null);
  const ticker = summary.data?.ticker ?? null;
  const equity = useAsync(ticker ? `e:${ticker}` : null, () => getEquity(ticker!));
  const props = useAsync(summary.data ? `p:${summary.data.proposal_id}` : null, async () => (await listProposals()).find((p) => p.id === summary.data!.proposal_id) ?? null);
  const source = s.source ?? summary.data?.source ?? null;
  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-6xl space-y-5 px-6 py-6">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">Bridge {id}</h1>
          {source === "replay" && <Badge tone="warn" title="Ticks come from a recording, not the live market">Replay</Badge>}
          {source === "live" && <Badge tone="good">Live</Badge>}
          <Badge tone={s.status === "running" ? "info" : s.status === "stopped" ? "bad" : "neutral"}>{s.status}</Badge>
        </div>
        {summary.error && <ErrorText>Could not load bridge: {summary.error}</ErrorText>}
        {s.status === "reconnecting" && <ErrorText>Connection to the backend dropped; reconnecting...</ErrorText>}
        {s.error && <ErrorText>Engine message: {s.error}</ErrorText>}
        <div className="grid items-stretch gap-4 md:grid-cols-3">
          <PriceCard prices={s.prices} last={s.lastP} source={source} />
          <EngineNode lat={s.lat} decisions={s.decisions} status={s.status} />
          <BridgeEquityCard ticker={ticker} card={equity} />
        </div>
        <StagePills reasons={s.reasons} last={s.lastReason} />
        <div className="grid gap-4 md:grid-cols-[1fr_2fr]">
          <PositionPanel shares={props.data?.shares_held ?? null} targetCoverage={props.data?.target_coverage ?? null} hedge={s.hedge} coverage={s.coverage} />
          <TradeLog log={s.log} />
        </div>
      </main>
    </>
  );
}
