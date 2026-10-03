"use client";

import { useRouter } from "next/navigation";
import { getOrders, getPositions, type BrokerOrder, type Holding } from "@/lib/api";
import { EQ, QUESTIONS } from "@/lib/demo";
import { fmtMoney, fmtTime } from "@/lib/fmt";
import { useAsync } from "@/lib/hooks";
import { simCover, simPnl } from "@/lib/sim";
import { brokerLabel, useStore, type BridgeEntry } from "@/lib/store";
import { DemoTag, Glass, Label, Tag, upColor } from "@/components/pb";
import { SandboxFillsPanel } from "@/components/SandboxFills";
import { engineBridgeFor } from "@/lib/portfolioView";
import { WeekendExposurePanel } from "@/components/WeekendExposure";

type DemoEntry = Extract<BridgeEntry, { kind: "demo" }>;
interface Row {
  t: string; name: string; shares: number; px: number | null; verdict: string | null;
  demo: DemoEntry | null; engineBridge: string | null; touching: number; real: boolean;
}
interface Fill { key: string; ts: number; time: string; side: string; color: string; qty: number; ticker: string; px: string; via: string; demo: boolean }

const cols = "minmax(0,1.4fr) 70px 90px 100px 90px minmax(150px,1.2fr)";
const num = { fontFamily: "var(--mono)", fontSize: 12.5, textAlign: "right" as const };
const fillPx = (o: BrokerOrder) => o.fill_px ?? o.filled_px ?? o.avg_fill_px ?? o.limit_px ?? null;

export default function Portfolio() {
  const router = useRouter();
  const s = useStore();
  const orders = useAsync("orders", () => getOrders());
  const positions = useAsync("positions", getPositions);
  const acct = brokerLabel(s.account);
  const demos = s.bridges.filter((b): b is DemoEntry => b.kind === "demo");
  const liveIds = s.bridges.flatMap((b) => (b.kind === "live" ? [b.bridgeId] : []));
  const hedgeIds = s.bridges.flatMap((b) => (b.kind === "live" && b.mode !== "opportunity" ? [b.bridgeId] : []));
  const realHoldings: Holding[] | null = s.portfolio.status === "ok" && s.portfolio.data ? s.portfolio.data.holdings : null;
  // Demo bridges attach only to the sample (EQ) holdings. On the real path they never touch real rows or totals:
  // they are listed separately, labelled, and their simulated P&L, fees and fills stay out of the real figures.
  const demoFor = (t: string) => (realHoldings ? null : demos.find((b) => b.eq.t === t) ?? null);

  const rows: Row[] = realHoldings
    ? realHoldings.map((h) => {
        const v = h.filings.find((f) => f.verdict && f.verdict.kind !== "none")?.verdict ?? null;
        return {
          t: h.ticker, name: h.name ?? h.ticker, shares: h.shares, px: h.spot, real: true,
          verdict: v ? `8-K ${v.tag}: ${v.label.replace("_", " ")} (${v.kind})` : null,
          demo: demoFor(h.ticker), engineBridge: engineBridgeFor(h, s.bridges),
          touching: h.markets.length,
        };
      })
    : Object.keys(EQ).filter((t) => EQ[t].held).map((t) => ({
        t, name: EQ[t].name, shares: EQ[t].held, px: EQ[t].px, verdict: null, demo: demoFor(t), engineBridge: null, real: false,
        touching: QUESTIONS.filter((x) => x.touches.includes(t)).length,
      }));

  const priced = rows.map((r) => {
    const px = r.demo ? r.demo.sim.px : r.px;
    const value = px != null ? r.shares * px : null;
    return { ...r, livePx: px, value, day: r.demo ? simPnl(r.demo.sim) : null };
  });
  const summed = priced.reduce((a, r) => a + (r.value ?? 0), 0);
  const anyPriced = priced.some((r) => r.value != null);
  const totalValue = realHoldings && s.portfolio.data?.total_value != null ? s.portfolio.data.total_value : anyPriced ? summed : null;
  const demoPnl = demos.reduce((a, b) => a + simPnl(b.sim), 0);
  const demoFees = demos.reduce((a, b) => a + b.sim.fees, 0);
  const demoFills = demos.reduce((a, b) => a + b.sim.tradeCount, 0);
  const demoCover = demos.length ? Math.round(demos.reduce((a, b) => a + b.sim.hedge / b.sim.shares, 0) / demos.length * 100) : 0;
  const filled = (orders.data ?? []).filter((o) => !o.status || /fill/i.test(o.status));
  const orderFees = (orders.data ?? []).reduce((a, o) => a + (o.fee ?? 0), 0);
  // Real path: account fees/fills only, and coverage from the real exposure figures. Sample path: all simulated.
  const exposures = (realHoldings ?? []).filter((h) => h.exposure);
  const isBridged = (h: Holding) => h.hedge.status === "bridging" || engineBridgeFor(h, s.bridges) != null;
  const realCover = exposures.length
    ? Math.round((exposures.filter(isBridged).length / exposures.length) * 100) : 0;
  const stats: [string, string, boolean][] = realHoldings
    ? [["Exposures bridged", exposures.length ? `${realCover}%` : "—", false], ["Fees (account)", `$${orderFees.toFixed(2)}`, false], ["Fills (account)", String(filled.length), false]]
    : [["Event exposure covered", `${demoCover}%`, true], ["Fees today", `$${(demoFees + orderFees).toFixed(2)}`, true], ["Fills today", String(demoFills + filled.length), true]];

  const fills: Fill[] = [
    ...filled.map((o) => {
      const when = o.filled_at ?? o.created_at;
      const ts = when ? Date.parse(when) : 0;
      const px = fillPx(o);
      return { key: `o:${o.id}`, ts, time: ts ? fmtTime(new Date(ts)) : "—", side: o.side.toUpperCase(), color: o.side === "sell" ? "#C8323F" : "#15804F", qty: o.qty, ticker: o.symbol, px: px == null ? "mkt" : px.toFixed(2), via: o.tag ? `bridge ${o.tag}` : acct.name, demo: false };
    }),
    ...demos.flatMap((b) => b.sim.trades.map((t) => ({ key: `d:${b.id}:${t.id}`, ts: t.ts, time: t.time, side: t.side, color: t.side === "SELL" ? "#C8323F" : "#15804F", qty: t.qty, ticker: t.ticker, px: t.px, via: t.algo, demo: true }))),
  ].sort((a, b) => b.ts - a.ts).slice(0, 7);

  const bridgeIt = (t: string) => { s.setQuestion(null); s.setQuery(t); router.push("/build"); };
  const hedgePositions = (positions.data ?? []).filter((p) => p.qty !== 0);

  return (
    <main className="pb-page" style={{ maxWidth: 1400, paddingTop: 18, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pb-header">
        <div>
          <div className="pb-label" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            PORTFOLIO · {acct.name.toUpperCase()}
            <Tag tone={acct.tone} title="GET /account">{acct.tone === "paper" ? "Webull paper" : acct.tone === "sim" ? "simulated" : "no account endpoint"}</Tag>
            {!realHoldings && <DemoTag what="sample holdings" />}
          </div>
          <h2 className="pb-h2">{totalValue == null ? "—" : fmtMoney(totalValue)}</h2>
          <div className="pb-lede">
            {totalValue == null ? "Total equity value unavailable (no quotes)" : `Total equity value${realHoldings && s.portfolio.data?.total_value == null ? " (priced holdings only)" : ""}`}
            {(!realHoldings || demos.length > 0) && <> · <span style={{ fontWeight: 600, color: upColor(demoPnl) }}>{fmtMoney(demoPnl, true)}</span> simulated across {demos.length} demo {demos.length === 1 ? "bridge" : "bridges"}{realHoldings ? " (not in the total)" : ""}</>}
            {s.account.status === "ok" && s.account.data && <> · cash {fmtMoney(s.account.data.cash)}</>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {stats.map(([k, v, sim]) => (
            <div key={k} className="pb-sub" style={{ padding: "12px 16px", minWidth: 140 }}>
              <div style={{ fontSize: 11, color: "#5A627A", display: "flex", gap: 6, alignItems: "center" }}>{k}{sim && <DemoTag what="sim" />}</div>
              <div className="pb-tab" style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-.02em", marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16 }}>
        <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
          <Label>01 · HOLDINGS</Label>
          <div className="pb-table-scroll">
            <div style={{ minWidth: 640 }}>
              <div style={{ display: "grid", gridTemplateColumns: cols, gap: 14, padding: "16px 0 8px", borderBottom: "1px solid rgba(15,22,38,.14)", fontSize: 11, color: "#5A627A" }}>
                <span>Position</span><span style={{ textAlign: "right" }}>Shares</span><span style={{ textAlign: "right" }}>Price</span><span style={{ textAlign: "right" }}>Value</span><span style={{ textAlign: "right" }}>Today</span><span>Bridge</span>
              </div>
              {priced.map((h) => {
                const bridged = !!h.demo || !!h.engineBridge;
                const sub = h.demo ? `${h.demo.q.ev} · ${simCover(h.demo.sim)}% covered` : h.engineBridge ? `engine bridge ${h.engineBridge}` : `${h.touching} ${h.touching === 1 ? "market touches" : "markets touch"} this`;
                const open = () => {
                  if (h.engineBridge) router.push(`/bridge/${h.engineBridge}`);
                  else if (h.demo) { s.setActive(h.demo.id); router.push("/bridge"); }
                  else bridgeIt(h.t);
                };
                return (
                  <div key={h.t} style={{ display: "grid", gridTemplateColumns: cols, gap: 14, alignItems: "center", padding: "13px 0", borderBottom: "1px solid rgba(15,22,38,.07)" }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.02em" }}>{h.t}</div>
                      <div className="pb-ellipsis" style={{ fontSize: 12, color: "#5A627A" }} title={h.verdict ?? undefined}>{h.name}{h.verdict ? ` · ${h.verdict}` : ""}</div>
                    </div>
                    <span style={num}>{h.shares.toLocaleString("en-US")}</span>
                    <span style={num}>{h.livePx == null ? "—" : "$" + h.livePx.toFixed(2)}</span>
                    <span style={num}>{h.value == null ? "—" : fmtMoney(h.value)}</span>
                    <span style={{ ...num, color: h.day == null ? "#8A92A8" : upColor(h.day) }}>{h.day == null ? "—" : fmtMoney(h.day, true)}</span>
                    <div style={{ minWidth: 0 }}>
                      <button type="button" onClick={open} style={{ display: "inline-block", padding: "4px 10px", borderRadius: 999, fontSize: 11.5, fontWeight: 600, cursor: "pointer", border: 0, background: bridged ? "rgba(34,160,107,.12)" : "#0F1626", color: bridged ? "#15804F" : "#fff" }}>{bridged ? "Bridged" : "Bridge it"}</button>
                      <div className="pb-ellipsis" style={{ fontSize: 11, color: "#5A627A", marginTop: 4 }}>{sub}</div>
                    </div>
                  </div>
                );
              })}
              {realHoldings && demos.length > 0 && (
                <>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "16px 0 6px", fontSize: 11, color: "#5A627A" }}>
                    DEMO BRIDGES <DemoTag what="simulated" title="Prototype simulator positions; not your holdings and not in the totals above." />
                  </div>
                  {demos.map((b) => {
                    const pn = simPnl(b.sim);
                    return (
                      <div key={b.id} style={{ display: "grid", gridTemplateColumns: cols, gap: 14, alignItems: "center", padding: "11px 0", borderBottom: "1px solid rgba(15,22,38,.07)", opacity: 0.85 }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.02em" }}>{b.eq.t} <span style={{ fontSize: 11, fontWeight: 500, color: "#5A627A" }}>sim</span></div>
                          <div className="pb-ellipsis" style={{ fontSize: 12, color: "#5A627A" }}>{b.q.ev}</div>
                        </div>
                        <span style={num}>{b.sim.shares.toLocaleString("en-US")}</span>
                        <span style={num}>${b.sim.px.toFixed(2)}</span>
                        <span style={num}>{fmtMoney(b.sim.shares * b.sim.px)}</span>
                        <span style={{ ...num, color: upColor(pn) }}>{fmtMoney(pn, true)}</span>
                        <div style={{ minWidth: 0 }}>
                          <button type="button" onClick={() => { s.setActive(b.id); router.push("/bridge"); }} style={{ display: "inline-block", padding: "4px 10px", borderRadius: 999, fontSize: 11.5, fontWeight: 600, cursor: "pointer", border: 0, background: "rgba(15,22,38,.06)", color: "#3C4458" }}>Demo bridge</button>
                          <div className="pb-ellipsis" style={{ fontSize: 11, color: "#5A627A", marginTop: 4 }}>{simCover(b.sim)}% covered (simulated)</div>
                        </div>
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          </div>
          {positions.data && (
            <div style={{ marginTop: 14, fontSize: 12, color: "#5A627A", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Tag tone={acct.tone}>{acct.name}</Tag>
              {hedgePositions.length ? hedgePositions.map((p) => `${p.symbol} ${p.qty > 0 ? "+" : "−"}${Math.abs(p.qty).toLocaleString("en-US")}${p.asset && p.asset !== "equity" ? " " + p.asset : ""}`).join(" · ") : "No open positions in the account yet."}
            </div>
          )}
        </Glass>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Glass style={{ padding: "22px 26px" }}>
            <Label>02 · EXPOSURE BY EVENT</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 16 }}>
              {demos.map((x) => {
                const pn = simPnl(x.sim), ratio = simCover(x.sim);
                return (
                  <div key={x.id} role="button" tabIndex={0} onClick={() => { s.setActive(x.id); router.push("/bridge"); }} style={{ cursor: "pointer" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
                      <span className="pb-ellipsis" style={{ minWidth: 0 }}><span style={{ fontWeight: 600 }}>{x.eq.t}</span> <span style={{ color: "#5A627A" }}>· {x.q.ev}</span>{realHoldings && <> <DemoTag what="sim" /></>}</span>
                      <span className="pb-mono" style={{ fontSize: 12, flex: "none", color: upColor(pn) }}>{fmtMoney(pn, true)}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                      <div className="pb-bar" style={{ flex: 1 }}><div style={{ width: `${ratio}%` }} /></div>
                      <span style={{ fontSize: 11, color: "#5A627A", flex: "none", width: 72, textAlign: "right" }}>{ratio}% covered</span>
                    </div>
                  </div>
                );
              })}
              {(realHoldings ?? []).filter((h) => h.exposure).map((h) => (
                <div key={`x:${h.ticker}`} role="button" tabIndex={0} onClick={() => bridgeIt(h.ticker)} style={{ cursor: "pointer" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
                    <span className="pb-ellipsis" style={{ minWidth: 0 }}><span style={{ fontWeight: 600 }}>{h.ticker}</span> <span style={{ color: "#5A627A" }}>· {h.exposure!.market.question}</span></span>
                    <span className="pb-mono" style={{ fontSize: 12, flex: "none", color: "#C8323F" }}>{fmtMoney(-Math.abs(h.exposure!.remaining_usd))} at risk</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, fontSize: 11, color: "#5A627A" }}>
                    <Tag tone="ai" title={h.exposure!.label}>AI estimate</Tag>
                    {h.exposure!.impact_pct.toFixed(1)}% impact on {h.exposure!.direction === "up_on_yes" ? "NO" : "YES"} · {isBridged(h) ? "bridged" : "not hedged"}
                  </div>
                </div>
              ))}
              {!demos.length && !(realHoldings ?? []).some((h) => h.exposure) && <div style={{ fontSize: 13, color: "#5A627A" }}>No bridges yet. Use “Bridge it” on a holding.</div>}
            </div>
          </Glass>
          <Glass style={{ padding: "22px 26px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
              <Label>03 · RECENT FILLS</Label>
              {orders.error && <DemoTag what="no orders endpoint" title={`GET /orders failed: ${orders.error}`} />}
            </div>
            <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
              {fills.length === 0 && <div style={{ fontSize: 13, color: "#5A627A", padding: "8px 0" }}>No fills yet.</div>}
              {fills.map((f) => (
                <div key={f.key} style={{ display: "grid", gridTemplateColumns: "62px 44px minmax(0,1fr)", gap: 12, alignItems: "center", padding: "9px 0", borderBottom: "1px solid rgba(15,22,38,.07)", fontSize: 12.5 }}>
                  <span className="pb-mono" style={{ fontSize: 11.5, color: "#5A627A" }}>{f.time}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: f.color }}>{f.side}</span>
                  <span className="pb-ellipsis" style={{ minWidth: 0 }}>{f.qty} {f.ticker} @ {f.px} <span style={{ color: "#5A627A" }}>· {f.via}{f.demo ? " · demo" : ""}</span></span>
                </div>
              ))}
            </div>
          </Glass>
          <SandboxFillsPanel bridgeIds={liveIds} onOpen={(id) => router.push(`/bridge/${id}`)} />
        </div>
      </div>
      <WeekendExposurePanel holdings={realHoldings} bridgeIds={hedgeIds} session={s.session.data} onOpen={(id) => router.push(`/bridge/${id}`)} />
    </main>
  );
}
