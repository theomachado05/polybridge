"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { getBridge, getCapital, getEquity, getLiquidity } from "@/lib/api";
import { fmtMoney, fmtNs, fmtPct, prettyId } from "@/lib/fmt";
import { useAsync, useRetry } from "@/lib/hooks";
import { algoRunLabel, brokerLabel, useStore, type BridgeEntry } from "@/lib/store";
import { bridgeFeeGateOff, fillScopeLabel, liveVenue, priceSubtitle, replayInfo, replayNotice } from "@/lib/realBridge";
import { quantile, useBridgeStream } from "@/lib/useBridgeStream";
import { Btn, Glass, Label, Orb, Tag, Unavailable } from "@/components/pb";
import { AlgoDock, PortfolioPanel, TopRow, TradesPanel, type DockAlgo, type TradeCard } from "./parts";
import { OpportunityBridge } from "./OpportunityBridge";
import { ClosedBanner, WeekendPanel } from "./WeekendPanel";
import { sessionClosed } from "@/lib/closed";
import { budgetPhrase, capacityFromLiquidity, capitalView, evidenceLabelBadge, fillBadges, gateCounts, gateSentence } from "@/lib/risk";
import { BadgeTag, CapacityCard, PanelHead } from "@/components/risk/RiskBits";

type LiveEntry = BridgeEntry;

export function BridgeScreen({ routeBridgeId }: { routeBridgeId?: string }) {
  const router = useRouter();
  const s = useStore();
  const virtual: LiveEntry | null = routeBridgeId && !s.bridges.some((b) => b.kind === "live" && b.bridgeId === routeBridgeId)
    ? { id: `live:${routeBridgeId}`, kind: "live", bridgeId: routeBridgeId, q: null, eq: null, inst: "shares", fit: null, gap: null } : null;
  const list = virtual ? [...s.bridges, virtual] : s.bridges;
  const activeId = routeBridgeId ? `live:${routeBridgeId}` : s.activeId && list.some((b) => b.id === s.activeId) ? s.activeId : list[0]?.id ?? null;
  const active = list.find((b) => b.id === activeId) ?? null;
  const [opening, setOpening] = useState(false);
  const watchWeekend = async () => {
    if (opening) return;
    setOpening(true);
    try { await s.openWeekendReplay(); router.push("/build"); } finally { setOpening(false); }
  };

  if (!list.length) {
    return (
      <main className="pb-page" style={{ maxWidth: 760, paddingTop: 40, paddingBottom: 80, textAlign: "center" }}>
        <Glass style={{ padding: "36px 30px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <Orb state="breathing" size={90} ink="#1E2A4A" />
          <h2 className="pb-serif" style={{ margin: 0, fontSize: 34, fontWeight: 400, letterSpacing: "-.015em" }}>No bridges</h2>
          <p style={{ margin: 0, fontSize: 14, color: "#3C4458", maxWidth: 480 }}>Build a bridge from a market that is a risk to you. Or replay the recorded recession-market weekend on a backend bridge. You approve the bridge first.</p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
            <Btn href="/build">Build a bridge</Btn>
            <Btn kind={opening ? "disabled" : "secondary"} onClick={() => void watchWeekend()}>{opening ? "Wait for the replay" : "Watch the weekend replay"}</Btn>
          </div>
        </Glass>
      </main>
    );
  }

  const pick = (b: BridgeEntry) => {
    s.setActive(b.id);
    if (routeBridgeId) router.push(`/bridge/${b.bridgeId}`);
  };

  return (
    <main className="pb-page" style={{ maxWidth: 1400, paddingTop: 8, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16, animationDuration: ".5s" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", paddingBottom: 16, borderBottom: "1px solid rgba(15,22,38,.16)" }}>
        <span style={{ fontSize: 13, color: "#5A627A", paddingRight: 8, whiteSpace: "nowrap" }}>
          {list.length} {list.length === 1 ? "bridge" : "bridges"}
        </span>
        {list.map((b) => {
          const on = b.id === activeId;
          const ticker = b.eq?.t ?? "Bridge";
          const ev = b.q?.ev ?? b.bridgeId;
          return (
            <button key={b.id} type="button" onClick={() => pick(b)} style={{ display: "flex", alignItems: "center", gap: 10, height: 46, padding: "0 16px 0 12px", borderRadius: 999, cursor: "pointer", background: on ? "#0F1626" : "rgba(255,255,255,.55)", color: on ? "#fff" : "#0F1626", border: `1px solid ${on ? "#0F1626" : "rgba(15,22,38,.14)"}`, minWidth: 0 }} aria-pressed={on}>
              <span style={{ fontWeight: 600, fontSize: 13, letterSpacing: "-.01em" }}>{ticker}</span>
              <span className="pb-ellipsis" style={{ fontSize: 12.5, opacity: 0.72, maxWidth: 240 }}>{ev}</span>
              <span className="pb-tab" style={{ fontSize: 12, opacity: 0.72 }}>{b.mode === "opportunity" ? "options" : "engine"}</span>
            </button>
          );
        })}
        <button type="button" onClick={() => { s.setQuestion(null); router.push("/build"); }} style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 46, padding: "0 16px", borderRadius: 999, cursor: "pointer", border: "1px dashed rgba(15,22,38,.3)", background: "transparent", color: "#3C4458", fontSize: 13, fontWeight: 500 }}>
          Build a bridge
        </button>
      </div>
      {active && <LiveBridge key={active.bridgeId} entry={active} />}
    </main>
  );
}

// ---------------------------------------------------------------- live (backend engine over SSE)

const GATES: { reason: string; name: string }[] = [
  { reason: "stale", name: "Staleness gate" },
  { reason: "below_sigma", name: "Sigma gate" },
  { reason: "inside_band", name: "No-trade band" },
  { reason: "below_fees", name: "Fee gate" },
  { reason: "rebalance", name: "Delta-bridge sizer" },
  { reason: "risk_capped", name: "Position cap" },
];
/** Closed-market mode: the session clock holds the equity algo while the regular session is closed. */
const SESSION_GATE = { reason: "session_closed", name: "Session clock" };

function LiveBridge({ entry }: { entry: LiveEntry }) {
  const s = useStore();
  const id = entry.bridgeId;
  const [summaryTry, retrySummary] = useRetry();
  const first = useAsync(`b:${id}:${summaryTry}`, () => getBridge(id));
  const st = useBridgeStream(id, first.data?.source ?? null);
  // A live bridge that fell back to a replay mid-run: refetch the summary once so replay_file / replay_market are known.
  const fellBack = st.source === "replay" && first.data != null && first.data.source !== "replay";
  const refetched = useAsync(fellBack ? `b:${id}:replay` : null, () => getBridge(id));
  const summary = refetched.data ? refetched : first;
  const ticker = summary.data?.ticker ?? entry.eq?.t ?? null;
  const card = useAsync(ticker ? `e:${ticker}` : null, () => getEquity(ticker!));
  const source = st.source ?? summary.data?.source ?? null;
  const direction = summary.data?.direction ?? entry.eq?.direction ?? "down_on_yes";
  const shares = summary.data?.shares_held ?? entry.eq?.held ?? 0;
  const acct = brokerLabel(s.account);
  const scope = fillScopeLabel(summary.data?.account_scope, acct);
  const mkt = entry.q?.real ?? summary.data?.market ?? null;
  const venue = liveVenue(mkt?.source);
  // The market on screen, with its YES token id from the summary when the entry's market lacks it (sidecars may name either).
  const shown = mkt ? { source: mkt.source, id: mkt.id, token_id: mkt.token_id ?? summary.data?.market?.token_id ?? null } : null;
  const replay = replayInfo(summary.data);
  const pSub = priceSubtitle(source, shown?.source, replay, shown?.id, shown?.token_id);
  const notice = replayNotice(source, summary.data?.requested_source, replay, shown);

  const sourceTag = source === "replay"
    ? <Tag tone="replay" title="The ticks come from a recorded file of market history, not from the live market.">replay</Tag>
    : source === "live" ? <Tag tone="live" title={`${venue} midpoint from the live stream.`}>live</Tag>
    : <Tag tone="neutral">{st.status}</Tag>;
  const p = st.lastP, p0 = st.prices[0] ?? null;
  const spot = card.data?.implied_move?.spot ?? entry.eq?.px ?? null;
  const move = entry.eq?.move ?? null;
  const priced = move != null && p != null && p0 != null ? move * (p - p0) : null;
  const p50 = quantile(st.lat, 0.5), p99 = quantile(st.lat, 0.99);
  const last = st.lastReason;
  const session = st.closed?.session ?? summary.data?.session ?? null;
  const marketClosed = sessionClosed(session);
  const holding = marketClosed && (st.closed?.hold ?? summary.data?.closed_mode?.hold ?? false);
  const gates = st.reasons.session_closed || holding ? [SESSION_GATE, ...GATES] : GATES;
  const algos: DockAlgo[] = gates.map((g) => ({
    name: g.name, active: last === g.reason,
    status: last === g.reason ? (g.reason === "rebalance" ? "Fired" : "Holds") : st.reasons[g.reason] ? "Triggered" : "Not triggered",
    line: g.reason === "session_closed" ? `${st.reasons[g.reason] ?? 0} ticks held, equities closed` : `${st.reasons[g.reason] ?? 0} decisions, ${g.reason.replace("_", " ")}`,
  }));
  const coverage = Math.min(100, Math.round((shares ? st.hedge / shares : 0) * 100));
  const orders = st.log.filter((l) => l.action === "order" && l.qty !== 0).slice(-8).reverse();
  const trades: TradeCard[] = orders.map((l) => {
    const f = l.fill;
    const filledPx = f && f.status === "filled" && f.fill_px != null ? f.fill_px : null;
    const px = filledPx != null ? ` @ ${filledPx.toFixed(2)}` : spot ? ` @ ~${spot.toFixed(2)}` : "";
    const brokerLine = !f ? (spot ? " The price is the last quote, not a broker fill." : "")
      : f.status === "filled" ? ` ${f.broker ?? "The broker"} filled the order${f.price_source ? ` (price: ${f.price_source})` : ""}${f.fee ? `, fee $${f.fee.toFixed(2)}` : ""}.${f.note || f.scope === "replay_sandbox" ? ` ${f.note ?? "Replay sandbox, not your account."}` : ""}`
      : f.status === "rejected" ? ` The broker rejected the order${f.reject_reason ? `: ${f.reject_reason}` : ""}.`
      : f.status === "error" ? ` Broker error (${f.error ?? "unknown"}). The order did not fill.`
      : f.status === "held" ? ` The system held the order before it went to the broker${f.reject_reason ? `: ${f.reject_reason}` : ""}.`
      : ` Broker status: ${f.status ?? "unknown"}.`;
    const gateLine = f?.gates?.length ? gateSentence(f) : "";
    return {
      id: l.n, side: l.qty > 0 ? "SELL" : "BUY", time: `#${l.n}`,
      head: `${Math.abs(l.qty)} ${ticker ?? ""}${px}`,
      algo: l.family ? `${prettyId(l.family)}${l.preset != null ? `, preset ${l.preset}` : ""}` : "Delta-bridge sizer",
      reason: `YES at ${l.p == null ? "n/a" : Math.round(l.p * 100) + "¢"}. ${l.family ? "Algo" : "Engine"} reason: ${l.reason.replaceAll("_", " ")}${l.signal != null ? ` (signal ${l.signal.toFixed(3)})` : ""}. ${l.target != null ? `Target hedge ${l.target} sh, previous hedge ${l.current} sh.` : `Hedge before the order: ${l.current} sh.`} Decision time ${fmtNs(l.ns)}.${brokerLine}${gateLine ? ` ${gateLine}` : ""}`,
      tags: fillBadges(f, l.evidence),
    };
  });
  // The fit is sent with the proposal and POST /bridges, and hedgecore.Algo runs that family and preset. The
  // backend's summary is the truth (engine "algo"); the entry's fit covers the moment before the summary loads.
  const running = summary.data?.engine === "algo" && summary.data.algo
    ? { family: summary.data.algo.family, preset_index: summary.data.algo.preset_index ?? null }
    : summary.data?.engine === "legacy" ? null : entry.fit;
  const algoInfo = summary.data?.engine === "algo" ? summary.data.algo : null;
  const capNote = algoInfo?.coverage_cap != null
    ? ` The hedge cap is the approved ${Math.round(algoInfo.coverage_cap * 100)}% of the position${algoInfo.capped ? `. The system decreased these preset values to the cap: ${Object.entries(algoInfo.capped).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}.`
    : "";
  const fitTag = running
    ? <Tag tone="ai" title={`hedgecore.Algo runs ${prettyId(running.family)}${running.preset_index != null ? ` preset #${running.preset_index}` : " with custom parameters"}. This is the fit from the approved proposal. The fit replayed presets in the C++ engine to select it.${capNote}`}>Runs {prettyId(running.family)}, preset {running.preset_index ?? "custom"}</Tag>
    : entry.unapplied
      ? <Tag tone="ai" title={`POST /pipeline/fit selected ${prettyId(entry.unapplied.family)}, but ${entry.unapplied.why}. The engine runs its default delta-bridge spec.`}>Fit: {prettyId(entry.unapplied.family)} (not applied: {entry.unapplied.why})</Tag>
      : null;
  // A replay with no recorded equity price for this ticker: the hedge families hold (fee_unknown) on every tick.
  const holdTag = summary.data?.engine === "algo" && summary.data.equity_price === "none"
    ? <Tag tone="sim" title={`This replay has no equity price for ${summary.data.ticker ?? "this ticker"} (no recorded bars). Thus the fee gate cannot calculate a trade price, and the algo holds with reason fee_unknown.`}>holds: no equity price in replay</Tag>
    : null;
  // gap_per_share applies only to the legacy Engine; an algo bridge prices its fee gate from the tick's under_px.
  const gateTag = bridgeFeeGateOff(entry.gap, running)
    ? <Tag tone="sim" title="The bridge started on the default engine spec with gap_per_share = 0 because no quote or impact estimate was available. Thus the fee gate of the legacy Engine is off (docs/contracts.md).">fee gate off (no quote or impact)</Tag>
    : null;
  const question = entry.q?.q ?? summary.data?.label ?? `Bridge ${id}`;
  const evLabel = evidenceLabelBadge(summary.data?.evidence_label ?? st.log.findLast((l) => l.evidence)?.evidence ?? null);
  const evTag = evLabel ? <BadgeTag b={{ ...evLabel, title: summary.data?.evidence?.evidence ?? evLabel.title }} /> : null;
  const replayAlert = notice && (notice.tone === "warn"
    ? <div role="alert" style={{ fontSize: 13, color: "#8A5A00" }}>{notice.text}</div>
    : <div role="status" style={{ fontSize: 13, color: "#5A627A" }}>{notice.text}</div>);

  if (summary.data?.division === "opportunity" || (!summary.data && entry.mode === "opportunity")) {
    return (
      <>
        {summary.error && <Unavailable what={`Bridge ${id}`} error={summary.error} onRetry={retrySummary} />}
        {st.status === "reconnecting" && <div role="alert" style={{ fontSize: 13, color: "#8A5A00" }}>The connection to the backend stopped. The system tries to connect again.</div>}
        {st.error && <div style={{ fontSize: 13, color: "#5A627A" }}>Engine message: {st.error}</div>}
        {replayAlert}
        <OpportunityBridge id={id} summary={summary.data ?? null} st={st} question={question} sourceTag={sourceTag} />
      </>
    );
  }

  return (
    <>
      {summary.error && <Unavailable what={`Bridge ${id}`} error={summary.error} onRetry={retrySummary} />}
      {st.status === "reconnecting" && <div role="alert" style={{ fontSize: 13, color: "#8A5A00" }}>The connection to the backend stopped. The system tries to connect again.</div>}
      {st.error && <div style={{ fontSize: 13, color: "#5A627A" }}>Engine message: {st.error}</div>}
      {replayAlert}
      <ClosedBanner session={session} replay={source === "replay"} hold={holding} />
      <TopRow
        question={question} venues={entry.q?.venues ?? ["Polymarket"]} marketTag={<span style={{ display: "inline-flex", gap: 6 }}>{sourceTag}<Tag tone="neutral">{direction === "down_on_yes" ? "hedge against YES" : "hedge against NO"}</Tag></span>}
        pBig={p == null ? "n/a" : `${Math.round(p * 100)}¢`} pSpark={st.prices.slice(-60)}
        pSub={pSub.sub}
        volLabel="Ticks received" volValue={st.prices.length.toLocaleString("en-US")}
        orb={st.status === "running" ? "connecting" : "breathing"} nodeLabel={algoRunLabel(running).node}
        nodeLines={<>p50 {fmtNs(p50)}, p99 {fmtNs(p99)}<br />{move ? <>Expected move on YES <span style={{ color: move < 0 ? "#E0485A" : "#22A06B", fontWeight: 600 }}>{fmtPct(move)}</span></> : `${st.decisions} decisions`}</>}
        instShort="Dynamic short hedge" exchange="US" ticker={ticker ?? "n/a"} name={[card.data?.name, entry.eq?.name].find((n) => n && n !== ticker) ?? ""}
        equityTag={<Tag tone="neutral" title="The equity price is the last quote from GET /equities. The bridge does not stream it.">last quote</Tag>}
        px={spot ? spot.toFixed(2) : "n/a"} pxColor="#5A627A" pxDelta={spot ? "The bridge does not stream this price" : "No quote is available"} pxSpark={[]}
        driftLabel="Priced-in drift since start (mapping estimate)" drift={priced == null ? "n/a" : fmtPct(priced, 2)}
      />
      <AlgoDock label={running ? "Engine gates, fitted algo" : "Engine gates, default spec"} algos={algos} tag={<span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>{evTag}{gateTag}{fitTag}{holdTag}{sourceTag}</span>} />
      <WeekendPanel id={id} summary={summary.data ?? null} st={st} replay={source === "replay"} ticker={ticker} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16, alignItems: "stretch" }}>
        <PortfolioPanel
          tag={<Tag tone={scope.tone} title={scope.title}>{scope.name}</Tag>}
          big={`${st.hedge.toLocaleString("en-US")} sh`} bigColor="#0F1626" bigNote={st.brokerHedge != null ? "hedge that the engine intends" : "current short hedge (engine)"}
          left={[`Long ${ticker ?? ""}`, `${shares.toLocaleString("en-US")} sh`, spot ? fmtMoney(shares * spot) : "value n/a"]}
          right={["Engine orders", String(orders.length ? st.log.filter((l) => l.action === "order").length : summary.data?.orders ?? 0), `${st.decisions} decisions`]}
          ratio={coverage} ratioLabel={`Coverage (target ${Math.round((summary.data?.target_coverage ?? 0.5) * 100)}%)`}
          footL={st.brokerHedge != null ? `${scope.filledVerb} ${st.brokerHedge.toLocaleString("en-US")} sh short, ${st.fills} fills` : `Status: ${st.status}`} footR={`p50 ${fmtNs(p50)}, p99 ${fmtNs(p99)}`}
        />
        <TradesPanel trades={trades} tag={sourceTag} empty={holding ? "The market is closed, so the algo holds and sends no equity orders. The staged plan (hedge B) covers the open." : st.decisions ? `No orders yet. The gates hold the hedge (${st.decisions} decisions).` : "No ticks yet. Wait for the first tick."} />
      </div>
      {ticker && <LiquidityPanel ticker={ticker} shares={shares} coverage={summary.data?.target_coverage ?? 0.5} counts={gateCounts(st.log.map((l) => l.fill), summary.data)} sandbox={scope.sandbox} />}
      <Label style={{ marginTop: -4 }}>Bridge {id}: {summary.data?.label ?? "engine bridge"}</Label>
    </>
  );
}

/** 08 · Liquidity & capital: the participation caps every order of this bridge is checked against (GET /liquidity),
 *  and how many orders the caps cut or the capital budget refused so far. */
function LiquidityPanel({ ticker, shares, coverage, counts, sandbox }: { ticker: string; shares: number; coverage: number; counts: { liquidity: number; capital: number }; sandbox: boolean }) {
  const hedge = Math.floor(coverage * shares);
  const liq = useAsync(`bliq:${ticker}:${coverage}:${hedge}`, () => getLiquidity(ticker, { coverage, ...(hedge > 0 ? { qty: hedge } : {}) }));
  const view = liq.error ? { ...capacityFromLiquidity(null), reason: `Liquidity data is not available (${liq.error}). The system does not cap orders and labels them “unknown”.` } : capacityFromLiquidity(liq.data, hedge);
  // The budget numbers come from GET /capital (CAPITAL_MAX_GROSS_PCT / CAPITAL_MAX_EVENT_PCT), never hard-coded.
  const cap = useAsync(`bcap:${ticker}`, getCapital);
  const capV = cap.data ? capitalView(cap.data) : null;
  const enforce = sandbox ? "This replay fills in a sandbox. The system calculates and labels the capital budget but does not enforce it."
    : capV && !capV.read && !capV.checked ? "This broker does not give account data, so the system does not enforce the capital budget now."
    : capV && !capV.read ? "The system cannot read the account now, so it refuses orders that increase exposure (fail closed)."
    : "If the system cannot read the account, it refuses orders that increase exposure (fail closed).";
  return (
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <PanelHead label="Liquidity and capital">
        <Tag tone={counts.liquidity ? "caution" : "neutral"} title="Orders that the participation caps decreased (liquidity_capped)">{counts.liquidity} capped</Tag>
        <Tag tone={counts.capital ? "caution" : "neutral"} title="Orders that the capital budget of the account refused (capital_budget)">{counts.capital} refused (capital)</Tag>
      </PanelHead>
      <CapacityCard view={view} title={`Participation caps for ${ticker}, approved hedge ${hedge.toLocaleString("en-US")} sh`} testId="bridge-capacity" />
      <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 10, lineHeight: 1.5 }}>
        The system caps each order at 10% of the opening 5-minute volume. It caps the total for each session at 1% of ADV. Then it compares each order with the capital budget ({budgetPhrase(cap.data?.limits)}). {enforce}
      </div>
    </Glass>
  );
}
