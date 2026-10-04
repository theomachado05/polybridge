"use client";

import { useState } from "react";
import { BridgeScreen } from "@/components/bridge/BridgeScreen";
import { TicketBoard } from "@/components/micro/TicketBoard";
import { PageHead, StatusTag, useRegistry } from "@/components/micro/parts";
import { mechanismFor } from "@/lib/micro";
import { useStore } from "@/lib/store";
import { Unavailable } from "@/components/pb";

type BridgeTab = "tickets" | "bridges";

/** Bridge: the ticket board (touch and close-above tickets against the options chain), and the running engine
 *  bridges (opened from the generic AI fit on Build). Opens on the running bridges when there are any. */
export default function BridgePage() {
  const s = useStore();
  const reg = useRegistry();
  const [pick, setPick] = useState<BridgeTab | null>(null);
  const tab: BridgeTab = pick ?? (s.bridges.length ? "bridges" : "tickets");
  const touch = mechanismFor(reg.data, "touch_ticket");
  const tabs = (
    <div className="pb-tabs" role="tablist" aria-label="Bridge views">
      {(["tickets", "bridges"] as const).map((t) => (
        <button key={t} type="button" role="tab" aria-selected={tab === t} className="pb-chip" data-on={tab === t} onClick={() => setPick(t)}>
          {t === "tickets" ? "Ticket board" : `Running bridges${s.bridges.length ? ` (${s.bridges.length})` : ""}`}
        </button>
      ))}
    </div>
  );
  if (tab === "bridges") {
    return (
      <>
        <div className="pb-page" style={{ paddingTop: "var(--sp-5)" }}>{tabs}</div>
        <BridgeScreen />
      </>
    );
  }
  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-5)", paddingBottom: "var(--sp-8)", display: "flex", flexDirection: "column", gap: "var(--sp-5)" }}>
      {tabs}
      <PageHead kicker="02 · Ticket board" title="“Will it hit” tickets against the options chain" tag={<StatusTag m={touch} />}>
        {touch?.claim}
      </PageHead>
      {reg.error && <Unavailable what="The evidence registry (GET /evidence/mechanisms)" error={reg.error} onRetry={reg.retry} compact />}
      <TicketBoard reg={reg.data} />
    </main>
  );
}
