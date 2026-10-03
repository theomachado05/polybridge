"use client";

// Opportunity (options) bridge: the PM-vs-options gap, the option legs the algo traded, and the approved risk caps.
// Every number says what it is: PM price measured, options-implied probability estimated, option fills simulated.
import type { BridgeSummary } from "@/lib/api";
import { fmtMoney, fmtNs, prettyId } from "@/lib/fmt";
import { gapPts, optionFillText, probPct } from "@/lib/opportunity";
import { quantile, type StreamState } from "@/lib/useBridgeStream";
import { Glass, Label, Spark, Tag, panel } from "@/components/pb";
import { TradesPanel, type TradeCard } from "./parts";

export function OpportunityBridge({ id, summary, st, question, sourceTag }: {
  id: string; summary: BridgeSummary | null; st: StreamState; question: string; sourceTag: React.ReactNode;
}) {
  const view = st.options ?? summary?.pm_vs_options ?? null;
  const algo = summary?.algo ?? null;
  const pos = st.optionPosition ?? summary?.option_position ?? 0;
  const risk = st.riskUsed ?? summary?.risk_used ?? 0;
  const maxN = summary?.max_notional ?? null, maxC = summary?.max_contracts ?? null;
  const detail = summary?.options_detail ?? null;
  const p50 = quantile(st.lat, 0.5), p99 = quantile(st.lat, 0.99);
  const orders = st.log.filter((l) => l.action === "order" && l.fill).slice(-8).reverse();
  const trades: TradeCard[] = orders.map((l) => {
    const f = l.fill!;
    const t = optionFillText(f);
    return {
      id: l.n, side: f.status === "filled" ? (f.side === "sell" ? "SELL" : "BUY") : "HOLD", time: `#${l.n}`, head: t.head,
      algo: l.family ? `${prettyId(l.family)}${l.preset != null ? ` · preset ${l.preset}` : ""}` : "options algo",
      reason: `${l.reason.replaceAll("_", " ")}${l.signal != null ? ` (signal ${l.signal.toFixed(3)})` : ""}, decided in ${fmtNs(l.ns)}. ${t.detail}`,
    };
  });
  const dataTag = summary?.option_data === "live_chain"
    ? <Tag tone="live" title="Option fields from the Massive chain snapshot (refreshed about once a minute)">live option chain</Tag>
    : summary?.option_data === "recorded"
      ? <Tag tone="replay" title="Option fields come from the replay recording">recorded option data</Tag>
      : <Tag tone="neutral" title={detail?.reason ?? "No options-implied value on the ticks yet"}>no option data yet</Tag>;
  const simTag = <Tag tone="sim" title={summary?.fills_label ?? "Option fills are simulated"}>simulated fills</Tag>;
  return (
    <>
      <Glass style={{ ...panel, display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <Label>01 · OPPORTUNITY · {summary?.ticker ?? ""}</Label>
          <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>{sourceTag}{dataTag}{simTag}
            {algo && <Tag tone="ai" title="The options family approved with the proposal (AI fit)">Running {prettyId(algo.family)} · preset {algo.preset_index ?? "custom"}</Tag>}
          </span>
        </div>
        <div className="pb-serif pb-pretty" style={{ fontSize: 22, lineHeight: 1.35 }}>{question}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 14, marginTop: 4 }}>
          <Stat k="PM YES (MEASURED)" v={probPct(view?.pm_mid)} />
          <Stat k="OPTIONS-IMPLIED (ESTIMATE)" v={probPct(view?.opt_implied_prob)} />
          <Stat k="GAP PM − OPTIONS" v={gapPts(view?.gap)} color={view?.gap == null ? "#8A92A8" : view.gap > 0 ? "#22A06B" : "#E0485A"} />
          <Stat k="STRUCTURE MID" v={view?.opt_mid != null ? view.opt_mid.toFixed(2) : "n/a"} />
          <div><div className="pb-mono" style={{ fontSize: 10.5, color: "#5A627A" }}>GAP HISTORY</div>{st.gaps.length > 1 ? <Spark data={st.gaps.slice(-60)} color="#2B57D6" w={150} h={40} /> : <div style={{ fontSize: 12, color: "#8A92A8" }}>waiting for ticks</div>}</div>
        </div>
        {detail && (
          <div style={{ fontSize: 12, color: "#5A627A" }}>
            {detail.supported === false ? `Options estimate unavailable: ${detail.reason ?? "unsupported question"}.`
              : detail.expiry ? `${detail.underlying_used ?? ""} strikes ${detail.k_lo}/${detail.k_hi}, expiry ${detail.expiry}. Options-implied values are risk-neutral estimates, not measured probabilities.` : ""}
          </div>
        )}
      </Glass>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16, alignItems: "stretch" }}>
        <Glass style={{ ...panel, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Label>02 · OPTION POSITION</Label>{simTag}</div>
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-.03em" }}>{pos > 0 ? "+" : ""}{pos} <span style={{ fontSize: 14, color: "#5A627A", fontWeight: 400 }}>{summary?.option_structure?.kind?.replaceAll("_", " ") ?? "structures"}</span></div>
          {summary?.option_structure?.legs && (
            <div className="pb-mono" style={{ fontSize: 11.5, color: "#3C4458", lineHeight: 1.6 }}>
              {summary.option_structure.legs.map((lg) => <div key={lg.ticker}>{lg.sign > 0 ? "+" : "−"} {lg.ticker}</div>)}
            </div>
          )}
          <div style={{ fontSize: 12.5, color: "#3C4458" }}>
            Risk used {fmtMoney(risk)}{maxN != null ? ` of ${fmtMoney(maxN)} approved` : ""} · max {maxC ?? "n/a"} structures open
          </div>
          <div style={{ fontSize: 12, color: "#5A627A" }}>{st.decisions} decisions · p50 {fmtNs(p50)} · p99 {fmtNs(p99)} · status {st.status}</div>
        </Glass>
        <TradesPanel trades={trades} tag={simTag} empty={st.decisions ? `No option orders yet — the algo is holding (${st.decisions} decisions).` : "Waiting for the first tick…"} />
      </div>
      <Label style={{ marginTop: -4 }}>Bridge {id} · {summary?.label ?? "opportunity bridge"}</Label>
    </>
  );
}

function Stat({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <div>
      <div className="pb-mono" style={{ fontSize: 10.5, color: "#5A627A", letterSpacing: ".04em" }}>{k}</div>
      <div className="pb-tab" style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-.02em", color }}>{v}</div>
    </div>
  );
}
