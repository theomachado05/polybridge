"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getBridge, getEquity } from "@/lib/api";
import { INSTRUMENTS } from "@/lib/demo";
import { fmtK, fmtMoney, fmtNs, fmtPct, prettyId } from "@/lib/fmt";
import { useAsync } from "@/lib/hooks";
import { simCover, simPnl } from "@/lib/sim";
import { brokerLabel, useStore, type BridgeEntry } from "@/lib/store";
import { quantile, useBridgeStream } from "@/lib/useBridgeStream";
import { Btn, DemoTag, Glass, Label, Orb, Tag, upColor } from "@/components/pb";
import { AlgoDock, PortfolioPanel, TopRow, TradesPanel, type DockAlgo, type TradeCard } from "./parts";

type LiveEntry = Extract<BridgeEntry, { kind: "live" }>;
type DemoEntry = Extract<BridgeEntry, { kind: "demo" }>;

export function BridgeScreen({ routeBridgeId }: { routeBridgeId?: string }) {
  const router = useRouter();
  const s = useStore();
  const virtual: LiveEntry | null = routeBridgeId && !s.bridges.some((b) => b.kind === "live" && b.bridgeId === routeBridgeId)
    ? { id: `live:${routeBridgeId}`, kind: "live", bridgeId: routeBridgeId, q: null, eq: null, inst: "shares", fit: null, gap: null } : null;
  const list = virtual ? [...s.bridges, virtual] : s.bridges;
  const activeId = routeBridgeId ? `live:${routeBridgeId}` : s.activeId && list.some((b) => b.id === s.activeId) ? s.activeId : list[0]?.id ?? null;
  const active = list.find((b) => b.id === activeId) ?? null;
  const demos = list.filter((b): b is DemoEntry => b.kind === "demo");
  const total = demos.reduce((a, b) => a + simPnl(b.sim), 0);

  // `/bridge?demo=1` seeds the three demo bridges (the prototype's startScreen tweak, for stage demos).
  const { seedDemo } = s;
  const empty = list.length === 0;
  useEffect(() => {
    if (empty && new URLSearchParams(window.location.search).get("demo") === "1") seedDemo();
  }, [empty, seedDemo]);

  if (!list.length) {
    return (
      <main className="pb-page" style={{ maxWidth: 760, paddingTop: 40, paddingBottom: 80, textAlign: "center" }}>
        <Glass style={{ padding: "36px 30px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <Orb state="breathing" size={90} ink="#1E2A4A" />
          <h2 className="pb-serif" style={{ margin: 0, fontSize: 34, fontWeight: 400, letterSpacing: "-.015em" }}>No bridges yet</h2>
          <p style={{ margin: 0, fontSize: 14, color: "#3C4458", maxWidth: 480 }}>Build one from a market you are worried about, or watch the demo bridges run on simulated prices.</p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
            <Btn href="/build" arrow>Build a bridge</Btn>
            <Btn kind="secondary" onClick={s.seedDemo}>Watch a demo bridge</Btn>
          </div>
        </Glass>
      </main>
    );
  }

  const pick = (b: BridgeEntry) => {
    s.setActive(b.id);
    if (routeBridgeId) router.push(b.kind === "live" ? `/bridge/${b.bridgeId}` : "/bridge");
  };

  return (
    <main className="pb-page" style={{ maxWidth: 1400, paddingTop: 8, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16, animationDuration: ".5s" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", paddingBottom: 16, borderBottom: "1px solid rgba(15,22,38,.16)" }}>
        <span className="pb-mono" style={{ fontSize: 11, letterSpacing: ".08em", color: "#5A627A", paddingRight: 8, whiteSpace: "nowrap" }}>
          {list.length} {list.length === 1 ? "BRIDGE" : "BRIDGES"}{demos.length > 0 && <> · <span style={{ color: upColor(total) }}>{fmtMoney(total, true)}</span> TODAY{demos.length < list.length ? " (DEMO)" : ""}</>}
        </span>
        {active?.kind === "demo" && <DemoTag what="demo chain" title="The prototype's simulated bridge: simulated prices and the design's sample algo chain." />}
        {list.map((b) => {
          const on = b.id === activeId;
          const ticker = b.kind === "demo" ? b.eq.t : b.eq?.t ?? "Bridge";
          const ev = b.kind === "demo" ? b.q.ev : b.q?.ev ?? b.bridgeId;
          const pn = b.kind === "demo" ? simPnl(b.sim) : null;
          const firing = b.kind === "demo" && b.sim.tick - b.sim.lastTradeTick <= 2;
          return (
            <button key={b.id} type="button" onClick={() => pick(b)} style={{ display: "flex", alignItems: "center", gap: 10, height: 46, padding: "0 16px 0 12px", borderRadius: 999, cursor: "pointer", background: on ? "#0F1626" : "rgba(255,255,255,.55)", color: on ? "#fff" : "#0F1626", border: `1px solid ${on ? "#0F1626" : "rgba(255,255,255,.9)"}`, boxShadow: on ? "0 10px 26px rgba(15,22,38,.22)" : "inset 0 1px 0 #fff,0 8px 24px rgba(40,60,120,.08)", backdropFilter: "blur(20px)", transition: "all .25s ease", minWidth: 0 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", flex: "none", background: firing || (b.kind === "live" && on) ? "#4ADE80" : on ? "rgba(255,255,255,.5)" : "rgba(15,22,38,.25)" }} />
              <span style={{ fontWeight: 600, fontSize: 13, letterSpacing: "-.01em" }}>{ticker}</span>
              <span className="pb-ellipsis" style={{ fontSize: 12.5, opacity: 0.72, maxWidth: 240 }}>{ev}</span>
              <span className="pb-mono pb-tab" style={{ fontSize: 12, color: pn == null ? undefined : on ? (pn >= 0 ? "#7EE0B0" : "#FF8A96") : upColor(pn) }}>{pn == null ? "engine" : fmtMoney(pn, true)}</span>
            </button>
          );
        })}
        <button type="button" onClick={() => { s.setQuestion(null); router.push("/build"); }} style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 46, padding: "0 16px", borderRadius: 999, cursor: "pointer", border: "1px dashed rgba(15,22,38,.3)", background: "transparent", color: "#3C4458", fontSize: 13, fontWeight: 500 }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>New bridge
        </button>
      </div>
      {active?.kind === "demo" && s.bridgeNote && <div style={{ fontSize: 12.5, color: "#5A627A", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><DemoTag what="simulated" />{s.bridgeNote}</div>}
      {active?.kind === "demo" && <DemoBridge entry={active} account={s.settings.account} />}
      {active?.kind === "live" && <LiveBridge key={active.bridgeId} entry={active} />}
    </main>
  );
}

// ---------------------------------------------------------------- demo (prototype simulator)

function DemoBridge({ entry, account }: { entry: DemoEntry; account: string }) {
  const sim = entry.sim, eq = entry.eq, q = entry.q;
  const since = sim.tick - sim.lastTradeTick, firing = since <= 2, urgentLast = sim.lastAlgo === "Vol-Adaptive Slicer";
  const jit = (i: number) => Math.sin(sim.tick * 0.7 + i * 1.3);
  const lastQty = sim.trades[0]?.qty ?? 0;
  const defs: [string, string][] = [["Sigma Gate", "gate"], ["Book-Imbalance Reader", "read"], ["Delta-Bridge v3", "map"], [urgentLast || !sim.lastAlgo ? "Vol-Adaptive Slicer" : "Meridian TWAP", "exec"], ["Tax-Lot Optimizer", "tax"], ["Fee-Aware Router", "route"]];
  const algos: DockAlgo[] = defs.map(([name, kind], i) => {
    const on = firing ? kind !== "gate" || since === 0 : kind === "gate" || kind === "read";
    const size = kind === "exec" ? `${lastQty || 64} sh` : kind === "tax" ? `${sim.shares.toLocaleString("en-US")} sh` : kind === "route" ? "2 venues" : "—";
    return { name, active: on, status: firing ? (kind === "exec" ? "Executing" : kind === "gate" ? "Passed" : "Fired") : kind === "gate" ? "Watching" : kind === "read" ? "Reading" : "Armed", line: `σ ${Math.round(sim.vol * 100 + jit(i) * 1.5)}% · ${size} · ${Math.round(28 + i * 4 + jit(i + 3) * 5)} ms` };
  });
  const longValue = sim.shares * sim.px, pnl = simPnl(sim);
  const pxD = sim.px - sim.base, up = pxD >= 0, ratio = simCover(sim), priced = sim.impact * (sim.p - sim.p0) * 100;
  const insts = INSTRUMENTS(sim.base, account);
  const inst = insts.find((i) => i.id === entry.inst) ?? insts[0];
  const trades: TradeCard[] = sim.trades.map((t) => ({ id: t.id, side: t.side, time: t.time, head: `${t.qty} ${t.ticker} @ ${t.px}`, algo: t.algo, reason: t.reason }));
  const demo = <DemoTag what="simulated" title="Prototype simulator: probability random walk and mean-reverting price; not a market feed." />;
  return (
    <>
      <TopRow
        question={q.q} venues={q.venues} pBig={`${Math.round(sim.p * 100)}¢`} pSpark={sim.phist}
        pSub={`Kalshi ${Math.round(sim.pk * 100)}¢ · ${Math.abs(sim.pk - sim.p) > 0.012 ? "diverging from Polymarket" : "confirming Polymarket"}`}
        volLabel="24h volume" volValue={fmtK(sim.volPoly)} marketTag={demo}
        orb="connecting" nodeLabel="02 · DELTA-BRIDGE V3"
        nodeLines={<>Rev {eq.rev == null ? "n/a" : fmtPct(eq.rev)} · Brand {eq.brand == null ? "n/a" : fmtPct(eq.brand)}<br />Expected move on YES <span style={{ color: eq.move < 0 ? "#E0485A" : "#22A06B", fontWeight: 600 }}>{fmtPct(eq.move)}</span></>}
        instShort={inst.short} exchange="NASDAQ" ticker={eq.t} name={eq.name}
        px={sim.px.toFixed(2)} pxColor={up ? "#22A06B" : "#E0485A"} pxSpark={sim.hist}
        pxDelta={`${up ? "+" : "−"}${Math.abs(pxD).toFixed(2)} (${up ? "+" : "−"}${Math.abs((pxD / sim.base) * 100).toFixed(2)}%)`}
        driftLabel="Priced-in drift from market" drift={fmtPct(priced, 2)}
      />
      <AlgoDock label="04 · 6 OF 1,284 ALGOS" algos={algos} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16, alignItems: "stretch" }}>
        <PortfolioPanel
          tag={demo}
          big={fmtMoney(pnl, true)} bigColor={pnl >= 0 ? "#22A06B" : "#E0485A"} bigNote="net today"
          left={[`Long ${eq.t}`, `${sim.shares.toLocaleString("en-US")} sh`, fmtMoney(longValue)]}
          right={["Hedge short", `${sim.hedge.toLocaleString("en-US")} sh`, `avg ${sim.hedgeAvg.toFixed(2)}`]}
          ratio={ratio}
          footL={`Fees $${sim.fees.toFixed(2)} · ${sim.tradeCount} fills`}
          footR={account === "IRA" ? "IRA · no tax drag" : `ST gains avoided · est. $${Math.round(380 + sim.tradeCount * 11)} saved`}
        />
        <TradesPanel trades={trades} tag={demo} />
      </div>
    </>
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

function LiveBridge({ entry }: { entry: LiveEntry }) {
  const s = useStore();
  const id = entry.bridgeId;
  const summary = useAsync(`b:${id}`, () => getBridge(id));
  const st = useBridgeStream(id, summary.data?.source ?? null);
  const ticker = summary.data?.ticker ?? entry.eq?.t ?? null;
  const card = useAsync(ticker ? `e:${ticker}` : null, () => getEquity(ticker!));
  const source = st.source ?? summary.data?.source ?? null;
  const direction = summary.data?.direction ?? entry.eq?.direction ?? "down_on_yes";
  const shares = summary.data?.shares_held ?? entry.eq?.held ?? 0;
  const acct = brokerLabel(s.account);

  const sourceTag = source === "replay"
    ? <Tag tone="replay" title="Ticks come from a recorded file of real market history, not the live market">replay</Tag>
    : source === "live" ? <Tag tone="live" title="Polymarket midpoint, streamed now">live</Tag>
    : <Tag tone="neutral">{st.status}</Tag>;
  const p = st.lastP, p0 = st.prices[0] ?? null;
  const spot = card.data?.implied_move?.spot ?? entry.eq?.px ?? null;
  const move = entry.eq?.move ?? null;
  const priced = move != null && p != null && p0 != null ? move * (p - p0) : null;
  const p50 = quantile(st.lat, 0.5), p99 = quantile(st.lat, 0.99);
  const last = st.lastReason;
  const algos: DockAlgo[] = GATES.map((g) => ({
    name: g.name, active: last === g.reason,
    status: last === g.reason ? (g.reason === "rebalance" ? "Fired" : "Holding") : st.reasons[g.reason] ? "Armed" : "Watching",
    line: `${st.reasons[g.reason] ?? 0} decisions · ${g.reason.replace("_", " ")}`,
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
      : ` Broker status: ${f.status ?? "unknown"}.`;
    return {
      id: l.n, side: l.qty > 0 ? "SELL" : "BUY", time: `#${l.n}`,
      head: `${Math.abs(l.qty)} ${ticker ?? ""}${px}`,
      algo: "Delta-Bridge Sizer",
      reason: `YES at ${l.p == null ? "n/a" : Math.round(l.p * 100) + "¢"}; engine ${l.reason.replace("_", " ")}: target hedge ${l.target} sh, was ${l.current} sh. Decided in ${fmtNs(l.ns)}.${brokerLine}`,
    };
  });
  // POST /bridges takes no family or preset: the engine runs its default delta-bridge spec. The AI fit is shown
  // beside it, labelled as not applied.
  const fitTag = entry.fit
    ? <Tag tone="ai" title={`POST /pipeline/fit picked ${prettyId(entry.fit.family)}${entry.fit.preset_index != null ? " preset #" + entry.fit.preset_index : ""}. The bridge API does not take a preset yet, so the engine runs its default spec.`}>AI fit: {prettyId(entry.fit.family)} (not applied yet)</Tag>
    : null;
  const gateTag = entry.gap === 0
    ? <Tag tone="sim" title="Started with gap_per_share = 0 because there was no quote or impact estimate; the engine's fee gate is off (docs/contracts.md).">fee gate off (no quote/impact)</Tag>
    : null;
  const question = entry.q?.q ?? summary.data?.label ?? `Bridge ${id}`;

  return (
    <>
      {summary.error && <div role="alert" style={{ fontSize: 13, color: "#C8323F" }}>Could not load bridge {id}: {summary.error}</div>}
      {st.status === "reconnecting" && <div role="alert" style={{ fontSize: 13, color: "#8A5A00" }}>Connection to the backend dropped; reconnecting…</div>}
      {st.error && <div style={{ fontSize: 13, color: "#5A627A" }}>Engine message: {st.error}</div>}
      <TopRow
        question={question} venues={entry.q?.venues ?? ["Polymarket"]} marketTag={<span style={{ display: "inline-flex", gap: 6 }}>{sourceTag}<Tag tone="neutral">{direction === "down_on_yes" ? "hedging the YES outcome" : "hedging the NO outcome"}</Tag></span>}
        pBig={p == null ? "—" : `${Math.round(p * 100)}¢`} pSpark={st.prices.slice(-60)}
        pSub={`YES ${source === "replay" ? "from the replay file" : "Polymarket midpoint"} · Kalshi not streamed on this bridge`}
        volLabel="Ticks received" volValue={st.prices.length.toLocaleString("en-US")}
        orb={st.status === "running" ? "connecting" : "breathing"} nodeLabel="02 · ENGINE · DEFAULT DELTA-BRIDGE SPEC"
        nodeLines={<>p50 {fmtNs(p50)} · p99 {fmtNs(p99)}<br />{move ? <>Expected move on YES <span style={{ color: move < 0 ? "#E0485A" : "#22A06B", fontWeight: 600 }}>{fmtPct(move)}</span></> : `${st.decisions} decisions`}</>}
        instShort="Dynamic short hedge" exchange="US" ticker={ticker ?? "—"} name={[card.data?.name, entry.eq?.name].find((n) => n && n !== ticker) ?? ""}
        equityTag={<Tag tone="neutral" title="Equity price is the last quote from GET /equities; it is not streamed on the bridge">last quote</Tag>}
        px={spot ? spot.toFixed(2) : "—"} pxColor="#5A627A" pxDelta={spot ? "Not streamed on this bridge" : "No quote available"} pxSpark={[]}
        driftLabel="Priced-in drift since start (mapping estimate)" drift={priced == null ? "n/a" : fmtPct(priced, 2)}
      />
      <AlgoDock label="04 · ENGINE GATES · DEFAULT SPEC" algos={algos} tag={<span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>{gateTag}{fitTag}{sourceTag}</span>} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: 16, alignItems: "stretch" }}>
        <PortfolioPanel
          tag={<Tag tone={acct.tone} title="Account that receives the engine's orders (GET /account)">{acct.name}</Tag>}
          big={`${st.hedge.toLocaleString("en-US")} sh`} bigColor="#0F1626" bigNote={st.brokerHedge != null ? "engine's intended hedge" : "hedge short now (engine)"}
          left={[`Long ${ticker ?? ""}`, `${shares.toLocaleString("en-US")} sh`, spot ? fmtMoney(shares * spot) : "value n/a"]}
          right={["Engine orders", String(orders.length ? st.log.filter((l) => l.action === "order").length : summary.data?.orders ?? 0), `${st.decisions} decisions`]}
          ratio={coverage} ratioLabel={`Coverage (target ${Math.round((summary.data?.target_coverage ?? 0.5) * 100)}%)`}
          footL={st.brokerHedge != null ? `Broker filled ${st.brokerHedge.toLocaleString("en-US")} sh short · ${st.fills} fills` : `Status ${st.status}`} footR={`p50 ${fmtNs(p50)} · p99 ${fmtNs(p99)}`}
        />
        <TradesPanel trades={trades} tag={sourceTag} empty={st.decisions ? `No orders yet — the gates are holding (${st.decisions} decisions).` : "Waiting for the first tick…"} />
      </div>
      <Label style={{ marginTop: -4 }}>Bridge {id} · {summary.data?.label ?? "engine bridge"}</Label>
    </>
  );
}
