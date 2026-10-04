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
          <h2 className="pb-serif" style={{ margin: 0, fontSize: 34, fontWeight: 400, letterSpacing: "-.015em" }}>No bridges yet</h2>
          <p style={{ margin: 0, fontSize: 14, color: "#3C4458", maxWidth: 480 }}>Build one from a market you are worried about, or replay the recorded recession-market weekend on a real backend bridge (you approve it first).</p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
            <Btn href="/build" arrow>Build a bridge</Btn>
            <Btn kind={opening ? "disabled" : "secondary"} onClick={() => void watchWeekend()}>{opening ? "Loading the recorded weekend…" : "Watch the weekend replay"}</Btn>
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
        <span className="pb-mono" style={{ fontSize: 11, letterSpacing: ".08em", color: "#5A627A", paddingRight: 8, whiteSpace: "nowrap" }}>
          {list.length} {list.length === 1 ? "BRIDGE" : "BRIDGES"}
        </span>
        {list.map((b) => {
          const on = b.id === activeId;
          const ticker = b.eq?.t ?? "Bridge";
          const ev = b.q?.ev ?? b.bridgeId;
          return (
            <button key={b.id} type="button" onClick={() => pick(b)} style={{ display: "flex", alignItems: "center", gap: 10, height: 46, padding: "0 16px 0 12px", borderRadius: 999, cursor: "pointer", background: on ? "#0F1626" : "rgba(255,255,255,.55)", color: on ? "#fff" : "#0F1626", border: `1px solid ${on ? "#0F1626" : "rgba(255,255,255,.9)"}`, boxShadow: on ? "0 10px 26px rgba(15,22,38,.22)" : "inset 0 1px 0 #fff,0 8px 24px rgba(40,60,120,.08)", backdropFilter: "blur(20px)", transition: "all .25s ease", minWidth: 0 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", flex: "none", background: on ? "#4ADE80" : "rgba(15,22,38,.25)" }} />
              <span style={{ fontWeight: 600, fontSize: 13, letterSpacing: "-.01em" }}>{ticker}</span>
              <span className="pb-ellipsis" style={{ fontSize: 12.5, opacity: 0.72, maxWidth: 240 }}>{ev}</span>
              <span className="pb-mono pb-tab" style={{ fontSize: 12 }}>{b.mode === "opportunity" ? "options" : "engine"}</span>
            </button>
          );
        })}
        <button type="button" onClick={() => { s.setQuestion(null); router.push("/build"); }} style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 46, padding: "0 16px", borderRadius: 999, cursor: "pointer", border: "1px dashed rgba(15,22,38,.3)", background: "transparent", color: "#3C4458", fontSize: 13, fontWeight: 500 }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>New bridge
        </button>
      </div>
      {active && <LiveBridge key={active.bridgeId} entry={active} />}
    </main>
  );
}

// ---------------------------------------------------------------- live (backend engine over SSE)

const GATES: { reason: string; name: string }[] = [
  { reason: "stale", name: "Staleness Gate" },
  { reason: "below_sigma", name: "Sigma Gate" },
  { reason: "inside_band", name: "No-Trade Band" },
  { reason: "below_fees", name: "Fee Gate" },
  { reason: "rebalance", name: "Delta-Bridge Sizer" },
  { reason: "risk_capped", name: "Position Cap" },
];
/** Closed-market mode: the session clock holds the equity algo while the regular session is closed. */
const SESSION_GATE = { reason: "session_closed", name: "Session Clock" };

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
    ? <Tag tone="replay" title="Ticks come from a recorded file of real market history, not the live market">replay</Tag>
    : source === "live" ? <Tag tone="live" title={`${venue} midpoint, streamed now`}>live</Tag>
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
    status: last === g.reason ? (g.reason === "rebalance" ? "Fired" : "Holding") : st.reasons[g.reason] ? "Armed" : "Watching",
    line: g.reason === "session_closed" ? `${st.reasons[g.reason] ?? 0} ticks held · equities closed` : `${st.reasons[g.reason] ?? 0} decisions · ${g.reason.replace("_", " ")}`,
  }));
  const coverage = Math.min(100, Math.round((shares ? st.hedge / shares : 0) * 100));
  const orders = st.log.filter((l) => l.action === "order" && l.qty !== 0).slice(-8).reverse();
  const trades: TradeCard[] = orders.map((l) => {
    const f = l.fill;
    const filledPx = f && f.status === "filled" && f.fill_px != null ? f.fill_px : null;
    const px = filledPx != null ? ` @ ${filledPx.toFixed(2)}` : spot ? ` @ ~${spot.toFixed(2)}` : "";
    const brokerLine = !f ? (spot ? " Price shown is the last quote, not a broker fill." : "")
      : f.status === "filled" ? ` Filled by ${f.broker ?? "the broker"}${f.price_source ? ` (price: ${f.price_source})` : ""}${f.fee ? `, fee $${f.fee.toFixed(2)}` : ""}.${f.note || f.scope === "replay_sandbox" ? ` ${f.note ?? "Replay sandbox: not your account."}` : ""}`
      : f.status === "rejected" ? ` Broker rejected it${f.reject_reason ? `: ${f.reject_reason}` : ""}.`
      : f.status === "error" ? ` Broker error (${f.error ?? "unknown"}); nothing filled.`
      : f.status === "held" ? ` Held before reaching the broker${f.reject_reason ? `: ${f.reject_reason}` : ""}.`
      : ` Broker status: ${f.status ?? "unknown"}.`;
    const gateLine = f?.gates?.length ? gateSentence(f) : "";
    return {
      id: l.n, side: l.qty > 0 ? "SELL" : "BUY", time: `#${l.n}`,
      head: `${Math.abs(l.qty)} ${ticker ?? ""}${px}`,
      algo: l.family ? `${prettyId(l.family)}${l.preset != null ? ` · preset ${l.preset}` : ""}` : "Delta-Bridge Sizer",
      reason: `YES at ${l.p == null ? "n/a" : Math.round(l.p * 100) + "¢"}; ${l.family ? "algo" : "engine"} ${l.reason.replaceAll("_", " ")}${l.target != null ? `: target hedge ${l.target} sh, was ${l.current} sh` : `: hedge was ${l.current} sh`}${l.signal != null ? ` (signal ${l.signal.toFixed(3)})` : ""}. Decided in ${fmtNs(l.ns)}.${brokerLine}${gateLine ? ` ${gateLine}` : ""}`,
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
    ? ` Hedge capped at the approved ${Math.round(algoInfo.coverage_cap * 100)}% of the position${algoInfo.capped ? ` (the preset's ${Object.entries(algoInfo.capped).map(([k, v]) => `${k} ${v}`).join(", ")} was lowered to it)` : ""}.`
    : "";
  const fitTag = running
    ? <Tag tone="ai" title={`hedgecore.Algo runs ${prettyId(running.family)}${running.preset_index != null ? ` preset #${running.preset_index}` : " with custom params"}: the fit sent with the approved proposal (picked by replaying presets in the C++ engine).${capNote}`}>Running {prettyId(running.family)} · preset {running.preset_index ?? "custom"}</Tag>
    : entry.unapplied
      ? <Tag tone="ai" title={`POST /pipeline/fit picked ${prettyId(entry.unapplied.family)}, but ${entry.unapplied.why}; the engine runs its default delta-bridge spec.`}>Fit: {prettyId(entry.unapplied.family)} (not applied: {entry.unapplied.why})</Tag>
      : null;
  // A replay with no recorded equity price for this ticker: the hedge families hold (fee_unknown) on every tick.
  const holdTag = summary.data?.engine === "algo" && summary.data.equity_price === "none"
    ? <Tag tone="sim" title={`No equity price for ${summary.data.ticker ?? "this ticker"} on this replay (no recorded bars), so the algo's fee gate cannot price a trade and it holds with reason fee_unknown.`}>holding: no equity price on replay</Tag>
    : null;
  // gap_per_share applies only to the legacy Engine; an algo bridge prices its fee gate from the tick's under_px.
  const gateTag = bridgeFeeGateOff(entry.gap, running)
    ? <Tag tone="sim" title="Started on the engine's default spec with gap_per_share = 0 because there was no quote or impact estimate; the legacy Engine's fee gate is off (docs/contracts.md).">fee gate off (no quote/impact)</Tag>
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
        {st.status === "reconnecting" && <div role="alert" style={{ fontSize: 13, color: "#8A5A00" }}>Connection to the backend dropped; reconnecting…</div>}
        {st.error && <div style={{ fontSize: 13, color: "#5A627A" }}>Engine message: {st.error}</div>}
        {replayAlert}
        <OpportunityBridge id={id} summary={summary.data ?? null} st={st} question={question} sourceTag={sourceTag} />
      </>
    );
  }

  return (
    <>
      {summary.error && <Unavailable what={`Bridge ${id}`} error={summary.error} onRetry={retrySummary} />}
      {st.status === "reconnecting" && <div role="alert" style={{ fontSize: 13, color: "#8A5A00" }}>Connection to the backend dropped; reconnecting…</div>}
      {st.error && <div style={{ fontSize: 13, color: "#5A627A" }}>Engine message: {st.error}</div>}
      {replayAlert}
      <ClosedBanner session={session} replay={source === "replay"} hold={holding} />
      <TopRow
        question={question} venues={entry.q?.venues ?? ["Polymarket"]} marketTag={<span style={{ display: "inline-flex", gap: 6 }}>{sourceTag}<Tag tone="neutral">{direction === "down_on_yes" ? "hedging the YES outcome" : "hedging the NO outcome"}</Tag></span>}
        pBig={p == null ? "—" : `${Math.round(p * 100)}¢`} pSpark={st.prices.slice(-60)}
        pSub={pSub.sub}
        volLabel="Ticks received" volValue={st.prices.length.toLocaleString("en-US")}
        orb={st.status === "running" ? "connecting" : "breathing"} nodeLabel={algoRunLabel(running).node}
        nodeLines={<>p50 {fmtNs(p50)} · p99 {fmtNs(p99)}<br />{move ? <>Expected move on YES <span style={{ color: move < 0 ? "#E0485A" : "#22A06B", fontWeight: 600 }}>{fmtPct(move)}</span></> : `${st.decisions} decisions`}</>}
        instShort="Dynamic short hedge" exchange="US" ticker={ticker ?? "—"} name={[card.data?.name, entry.eq?.name].find((n) => n && n !== ticker) ?? ""}
        equityTag={<Tag tone="neutral" title="Equity price is the last quote from GET /equities; it is not streamed on the bridge">last quote</Tag>}
        px={spot ? spot.toFixed(2) : "—"} pxColor="#5A627A" pxDelta={spot ? "Not streamed on this bridge" : "No quote available"} pxSpark={[]}
        driftLabel="Priced-in drift since start (mapping estimate)" drift={priced == null ? "n/a" : fmtPct(priced, 2)}
      />
      <AlgoDock label={running ? "04 · ENGINE GATES · FITTED ALGO" : "04 · ENGINE GATES · DEFAULT SPEC"} algos={algos} tag={<span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>{evTag}{gateTag}{fitTag}{holdTag}{sourceTag}</span>} />
      <WeekendPanel id={id} summary={summary.data ?? null} st={st} replay={source === "replay"} ticker={ticker} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16, alignItems: "stretch" }}>
        <PortfolioPanel
          tag={<Tag tone={scope.tone} title={scope.title}>{scope.name}</Tag>}
          big={`${st.hedge.toLocaleString("en-US")} sh`} bigColor="#0F1626" bigNote={st.brokerHedge != null ? "engine's intended hedge" : "hedge short now (engine)"}
          left={[`Long ${ticker ?? ""}`, `${shares.toLocaleString("en-US")} sh`, spot ? fmtMoney(shares * spot) : "value n/a"]}
          right={["Engine orders", String(orders.length ? st.log.filter((l) => l.action === "order").length : summary.data?.orders ?? 0), `${st.decisions} decisions`]}
          ratio={coverage} ratioLabel={`Coverage (target ${Math.round((summary.data?.target_coverage ?? 0.5) * 100)}%)`}
          footL={st.brokerHedge != null ? `${scope.filledVerb} ${st.brokerHedge.toLocaleString("en-US")} sh short · ${st.fills} fills` : `Status ${st.status}`} footR={`p50 ${fmtNs(p50)} · p99 ${fmtNs(p99)}`}
        />
        <TradesPanel trades={trades} tag={sourceTag} empty={holding ? "No equity orders while the market is closed: the algo holds; the staged plan (hedge B) covers the open." : st.decisions ? `No orders yet — the gates are holding (${st.decisions} decisions).` : "Waiting for the first tick…"} />
      </div>
      {ticker && <LiquidityPanel ticker={ticker} shares={shares} coverage={summary.data?.target_coverage ?? 0.5} counts={gateCounts(st.log.map((l) => l.fill), summary.data)} sandbox={scope.sandbox} />}
      <Label style={{ marginTop: -4 }}>Bridge {id} · {summary.data?.label ?? "engine bridge"}</Label>
    </>
  );
}

/** 08 · Liquidity & capital: the participation caps every order of this bridge is checked against (GET /liquidity),
 *  and how many orders the caps cut or the capital budget refused so far. */
function LiquidityPanel({ ticker, shares, coverage, counts, sandbox }: { ticker: string; shares: number; coverage: number; counts: { liquidity: number; capital: number }; sandbox: boolean }) {
  const hedge = Math.floor(coverage * shares);
  const liq = useAsync(`bliq:${ticker}:${coverage}:${hedge}`, () => getLiquidity(ticker, { coverage, ...(hedge > 0 ? { qty: hedge } : {}) }));
  const view = liq.error ? { ...capacityFromLiquidity(null), reason: `Liquidity unavailable (${liq.error}); orders are not capped and are labelled “unknown”.` } : capacityFromLiquidity(liq.data, hedge);
  // The budget numbers come from GET /capital (CAPITAL_MAX_GROSS_PCT / CAPITAL_MAX_EVENT_PCT), never hard-coded.
  const cap = useAsync(`bcap:${ticker}`, getCapital);
  const capV = cap.data ? capitalView(cap.data) : null;
  const enforce = sandbox ? "This replay fills in a sandbox: the capital budget is evaluated and labelled, not enforced."
    : capV && !capV.read && !capV.checked ? "This broker gives no account read, so the capital budget is not enforced now."
    : capV && !capV.read ? "The account cannot be read right now, so exposure-increasing orders are refused (fail closed)."
    : "An unreadable account refuses exposure-increasing orders (fail closed).";
  return (
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <PanelHead label="08 · LIQUIDITY & CAPITAL">
        <Tag tone={counts.liquidity ? "caution" : "neutral"} title="Orders cut by the participation caps (liquidity_capped)">{counts.liquidity} capped</Tag>
        <Tag tone={counts.capital ? "caution" : "neutral"} title="Orders refused by the account's capital budget (capital_budget)">{counts.capital} refused (capital)</Tag>
      </PanelHead>
      <CapacityCard view={view} title={`PARTICIPATION CAPS · ${ticker} · APPROVED HEDGE ${hedge.toLocaleString("en-US")} SH`} testId="bridge-capacity" />
      <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 10, lineHeight: 1.5 }}>
        Each order is capped per order (10% of the opening 5-minute volume) and per session (1% of ADV, summed over the day), then checked against the capital budget ({budgetPhrase(cap.data?.limits)}). {enforce}
      </div>
    </Glass>
  );
}
