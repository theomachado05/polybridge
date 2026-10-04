"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { getBridge, getCapital, getEquity, getLiquidity } from "@/lib/api";
import { fmtMoney, fmtNs, fmtPct, prettyId } from "@/lib/fmt";
import { useAsync, useRetry } from "@/lib/hooks";
import { algoRunLabel, brokerLabel, useStore, type BridgeEntry } from "@/lib/store";
import { bridgeFeeGateOff, fillScopeLabel, liveVenue, priceSubtitle, replayInfo, replayNotice } from "@/lib/realBridge";
import { quantile, useBridgeStream } from "@/lib/useBridgeStream";
import { Btn, Glass, Orb, Tag, Unavailable } from "@/components/pb";
import { AlgoDock, PortfolioPanel, SectionHead, TopRow, TradesPanel, type DockAlgo, type TradeCard } from "./parts";
import { OpportunityBridge } from "./OpportunityBridge";
import { ClosedBanner, WeekendPanel } from "./WeekendPanel";
import { sessionClosed } from "@/lib/closed";
import { budgetPhrase, capacityFromLiquidity, capitalView, evidenceLabelBadge, fillBadges, gateCounts, gateSentence } from "@/lib/risk";
import { BadgeTag, CapacityCard } from "@/components/risk/RiskBits";

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
      <main className="pb-page" style={{ maxWidth: 760, paddingTop: "var(--sp-7)", paddingBottom: "var(--sp-8)", textAlign: "center" }}>
        <Glass style={{ padding: "var(--sp-7) var(--sp-6)", display: "flex", flexDirection: "column", alignItems: "center", gap: "var(--sp-4)" }}>
          <Orb state="breathing" size={80} ink="#14182B" />
          <h1 className="pb-h3">No bridges</h1>
          <p className="pb-body pb-pretty" style={{ margin: 0, maxWidth: 480 }}>Build a bridge from a market that is a risk to you. Or replay the recorded recession-market weekend on a backend bridge. You approve the bridge first.</p>
          <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap", justifyContent: "center", marginTop: "var(--sp-2)" }}>
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
    <main className="pb-page" style={{ paddingTop: "var(--sp-5)", paddingBottom: "var(--sp-8)", display: "grid", gridTemplateColumns: "minmax(0,1fr)", gap: "var(--sp-6)" }}>
      <nav aria-label="Bridges" style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap", paddingBottom: "var(--sp-4)", borderBottom: "1px solid var(--border)" }}>
        <span className="pb-small" style={{ paddingRight: "var(--sp-2)", whiteSpace: "nowrap" }}>
          {list.length} {list.length === 1 ? "bridge" : "bridges"}
        </span>
        {list.map((b) => {
          const on = b.id === activeId;
          const ticker = b.eq?.t ?? "Bridge";
          const ev = b.q?.ev ?? b.bridgeId;
          return (
            <button key={b.id} type="button" className="pb-chip" data-on={on} onClick={() => pick(b)} style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", minWidth: 0 }} aria-pressed={on}>
              <span className="pb-ticker">{ticker}</span>
              <span className="pb-ellipsis" style={{ maxWidth: 240, opacity: 0.8 }}>{ev}</span>
              <span style={{ fontSize: "var(--fs-12)", opacity: 0.7 }}>{b.mode === "opportunity" ? "options" : "engine"}</span>
            </button>
          );
        })}
        <Btn variant="ghost" size="sm" onClick={() => { s.setQuestion(null); router.push("/build"); }}>Build a bridge</Btn>
      </nav>
      {active && <LiveBridge key={active.bridgeId} entry={active} />}
    </main>
  );
}

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
      qty: Math.abs(l.qty), what: ticker ?? "", px: filledPx != null ? filledPx.toFixed(2) : spot ? `~${spot.toFixed(2)}` : undefined,
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
    ? <div role="alert" className="pb-small" style={{ color: "var(--warn)" }}>{notice.text}</div>
    : <div role="status" className="pb-small">{notice.text}</div>);

  if (summary.data?.division === "opportunity" || (!summary.data && entry.mode === "opportunity")) {
    return (
      <>
        {summary.error && <Unavailable what={`Bridge ${id}`} error={summary.error} onRetry={retrySummary} />}
        {st.status === "reconnecting" && <div role="alert" className="pb-small" style={{ color: "var(--warn)" }}>The connection to the backend stopped. The system tries to connect again.</div>}
        {st.error && <div className="pb-small">Engine message: {st.error}</div>}
        {replayAlert}
        <OpportunityBridge id={id} summary={summary.data ?? null} st={st} question={question} sourceTag={sourceTag} />
      </>
    );
  }

  return (
    <>
      {summary.error && <Unavailable what={`Bridge ${id}`} error={summary.error} onRetry={retrySummary} />}
      {st.status === "reconnecting" && <div role="alert" className="pb-small" style={{ color: "var(--warn)" }}>The connection to the backend stopped. The system tries to connect again.</div>}
      {st.error && <div className="pb-small">Engine message: {st.error}</div>}
      {replayAlert}
      <ClosedBanner session={session} replay={source === "replay"} hold={holding} />
      <TopRow
        question={question} venues={entry.q?.venues ?? ["Polymarket"]} marketTag={<span style={{ display: "inline-flex", gap: "var(--sp-2)" }}>{sourceTag}<Tag tone="neutral">{direction === "down_on_yes" ? "hedge against YES" : "hedge against NO"}</Tag></span>}
        pBig={p == null ? "n/a" : `${Math.round(p * 100)}¢`} pSpark={st.prices.slice(-60)}
        pSub={pSub.sub}
        volLabel="Ticks received" volValue={st.prices.length.toLocaleString("en-US")}
        orb={st.status === "running" ? "connecting" : "breathing"} nodeLabel={algoRunLabel(running).node}
        nodeLines={<>p50 {fmtNs(p50)}, p99 {fmtNs(p99)}<br />{move ? <>Expected move on YES <span style={{ color: move < 0 ? "var(--down)" : "var(--up)", fontWeight: 600 }}>{fmtPct(move)}</span></> : `${st.decisions} decisions`}</>}
        instShort="Dynamic short hedge" exchange="US" ticker={ticker ?? "n/a"} name={[card.data?.name, entry.eq?.name].find((n) => n && n !== ticker) ?? ""}
        equityTag={<Tag tone="neutral" title="The equity price is the last quote from GET /equities. The bridge does not stream it.">last quote</Tag>}
        px={spot ? spot.toFixed(2) : "n/a"} pxColor="var(--text-2)" pxDelta={spot ? "The bridge does not stream this price" : "No quote is available"} pxSpark={[]}
        driftLabel="Priced-in drift since start (mapping estimate)" drift={priced == null ? "n/a" : fmtPct(priced, 2)}
      />
      <PortfolioPanel
        tag={<Tag tone={scope.tone} title={scope.title}>{scope.name}</Tag>}
        big={`${st.hedge.toLocaleString("en-US")} sh`} bigColor="var(--ink)" bigNote={st.brokerHedge != null ? "hedge that the engine intends" : "current short hedge (engine)"}
        left={[`Long ${ticker ?? ""}`, `${shares.toLocaleString("en-US")} sh`, spot ? fmtMoney(shares * spot) : "value n/a"]}
        right={["Engine orders", String(orders.length ? st.log.filter((l) => l.action === "order").length : summary.data?.orders ?? 0), `${st.decisions} decisions`]}
        ratio={coverage} ratioLabel={`Coverage (target ${Math.round((summary.data?.target_coverage ?? 0.5) * 100)}%)`}
        footL={st.brokerHedge != null ? `${scope.filledVerb} ${st.brokerHedge.toLocaleString("en-US")} sh short, ${st.fills} fills` : `Status: ${st.status}`} footR={`p50 ${fmtNs(p50)}, p99 ${fmtNs(p99)}`}
      />
      <WeekendPanel id={id} summary={summary.data ?? null} st={st} replay={source === "replay"} ticker={ticker} />
      <AlgoDock label={running ? "Engine gates, fitted algo" : "Engine gates, default spec"} algos={algos} tag={<>{evTag}{gateTag}{fitTag}{holdTag}{sourceTag}</>} />
      <TradesPanel trades={trades} tag={sourceTag} empty={holding ? "The market is closed, so the algo holds and sends no equity orders. The staged plan (hedge B) covers the open." : st.decisions ? `No orders yet. The gates hold the hedge (${st.decisions} decisions).` : "No ticks yet. Wait for the first tick."} />
      {ticker && <LiquidityPanel ticker={ticker} shares={shares} coverage={summary.data?.target_coverage ?? 0.5} counts={gateCounts(st.log.map((l) => l.fill), summary.data)} sandbox={scope.sandbox} />}
      <div className="pb-small" style={{ color: "var(--faint)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)" }}>Bridge <span className="pb-code">{id}</span>: {summary.data?.label ?? "engine bridge"}</div>
    </>
  );
}

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
    <section style={{ minWidth: 0 }}>
      <SectionHead title="Liquidity and capital">
        <Tag tone={counts.liquidity ? "caution" : "neutral"} title="Orders that the participation caps decreased (liquidity_capped)">{counts.liquidity} capped</Tag>
        <Tag tone={counts.capital ? "caution" : "neutral"} title="Orders that the capital budget of the account refused (capital_budget)">{counts.capital} refused (capital)</Tag>
      </SectionHead>
      <CapacityCard view={view} title={`Participation caps for ${ticker}, approved hedge ${hedge.toLocaleString("en-US")} sh`} testId="bridge-capacity" />
      <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-3)", maxWidth: 880 }}>
        The system caps each order at 10% of the opening 5-minute volume. It caps the total for each session at 1% of ADV. Then it compares each order with the capital budget ({budgetPhrase(cap.data?.limits)}). {enforce}
      </div>
    </section>
  );
}
