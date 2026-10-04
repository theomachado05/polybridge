"use client";

import { useRouter } from "next/navigation";
import { getOrders, type BrokerOrder, type Holding } from "@/lib/api";
import { fmtMoney, fmtTime } from "@/lib/fmt";
import { mappingLabel } from "@/lib/ai";
import { useAsync, useRetry } from "@/lib/hooks";
import { brokerLabel, useStore } from "@/lib/store";
import { Btn, Glass, Orb, Tag, Unavailable } from "@/components/pb";
import { SandboxFillsPanel } from "@/components/SandboxFills";
import { engineBridgeFor } from "@/lib/portfolioView";
import { WeekendExposurePanel } from "@/components/WeekendExposure";
import { BrokerAccountPanel, CapitalPanel } from "@/components/risk/AccountPanels";
import { VOICE_ANCHOR } from "@/lib/voiceDrive";
import { accountPill } from "@/lib/risk";

interface Row {
  t: string; name: string; shares: number; px: number | null; verdict: string | null;
  engineBridge: string | null; touching: number;
  /** Broker book for this ticker (not the demo shares) and whether the broker can short it now. */
  brokerQty?: number | null; canShort?: boolean | null; shortReason?: string | null;
}
interface Fill { key: string; ts: number; time: string; side: string; color: string; qty: number; ticker: string; px: string; via: string }

const card = { padding: "var(--sp-5)", minWidth: 0 } as const;
const faint = { fontSize: "var(--fs-12)", color: "var(--faint)", lineHeight: 1.4 } as const;
const empty = { padding: "var(--sp-3) 0" } as const;
const twoCol = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: "var(--sp-5)", alignItems: "start" } as const;
const fillPx = (o: BrokerOrder) => o.fill_px ?? o.filled_px ?? o.avg_fill_px ?? o.limit_px ?? null;

export default function Portfolio() {
  const router = useRouter();
  const s = useStore();
  const [ordersTry, retryOrders] = useRetry();
  const orders = useAsync(`orders:${ordersTry}`, () => getOrders());
  const acct = brokerLabel(s.account);
  const pill = accountPill(s.account.data, s.session.data);
  const holdingsLabel = s.portfolio.data?.holdings_label ?? null;
  const liveIds = s.bridges.map((b) => b.bridgeId);
  const hedgeIds = s.bridges.flatMap((b) => (b.mode !== "opportunity" ? [b.bridgeId] : []));
  const realHoldings: Holding[] | null = s.portfolio.status === "ok" && s.portfolio.data ? s.portfolio.data.holdings : null;

  const rows: Row[] = (realHoldings ?? []).map((h) => {
    const v = h.filings.find((f) => f.verdict && f.verdict.kind !== "none")?.verdict ?? null;
    return {
      t: h.ticker, name: h.name ?? h.ticker, shares: h.shares, px: h.spot,
      verdict: v ? `8-K ${v.tag}: ${v.label.replace("_", " ")} (${v.kind})` : null,
      engineBridge: engineBridgeFor(h, s.bridges),
      touching: h.markets.length, brokerQty: h.broker_qty, canShort: h.can_short, shortReason: h.short_reason,
    };
  });

  const priced = rows.map((r) => ({ ...r, livePx: r.px, value: r.px != null ? r.shares * r.px : null }));
  const summed = priced.reduce((a, r) => a + (r.value ?? 0), 0);
  const anyPriced = priced.some((r) => r.value != null);
  const totalValue = s.portfolio.data?.total_value != null ? s.portfolio.data.total_value : anyPriced ? summed : null;
  const filled = (orders.data ?? []).filter((o) => !o.status || /fill/i.test(o.status));
  const orderFees = (orders.data ?? []).reduce((a, o) => a + (o.fee ?? 0), 0);
  // Account fees and fills only, and coverage from the real exposure figures.
  const exposures = (realHoldings ?? []).filter((h) => h.exposure);
  const isBridged = (h: Holding) => h.hedge.status === "bridging" || engineBridgeFor(h, s.bridges) != null;
  const realCover = exposures.length
    ? Math.round((exposures.filter(isBridged).length / exposures.length) * 100) : 0;
  const stats: [string, string][] = [
    ["Bridged exposures", exposures.length ? `${realCover}%` : "n/a"],
    ["Account fees", orders.data ? `$${orderFees.toFixed(2)}` : "n/a"],
    ["Account fills", orders.data ? String(filled.length) : "n/a"],
  ];

  const fills: Fill[] = [
    ...filled.map((o) => {
      const when = o.filled_at ?? o.created_at;
      const ts = when ? Date.parse(when) : 0;
      const px = fillPx(o);
      return { key: `o:${o.id}`, ts, time: ts ? fmtTime(new Date(ts)) : "n/a", side: o.side.toUpperCase(), color: o.side === "sell" ? "var(--down)" : "var(--up)", qty: o.qty, ticker: o.symbol, px: px == null ? "market" : px.toFixed(2), via: o.tag ? `Bridge ${o.tag}` : acct.name };
    }),
  ].sort((a, b) => b.ts - a.ts).slice(0, 7);

  const bridgeIt = (t: string) => { s.setQuestion(null); s.setQuery(t); router.push("/build"); };

  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: 96, display: "flex", flexDirection: "column", gap: "var(--sp-5)" }}>
      <header className="pb-header" style={{ alignItems: "flex-end" }}>
        <div>
          <div className="pb-label" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap", fontSize: "var(--fs-13)" }}>
            Portfolio
            <span data-testid="account-pill"><Tag tone={pill.tone} title={pill.title}>{pill.text}</Tag></span>
          </div>
          <div className="pb-figure" style={{ marginTop: "var(--sp-3)" }}>{totalValue == null ? "n/a" : fmtMoney(totalValue)}</div>
          <div className="pb-small" style={{ marginTop: "var(--sp-2)" }}>
            {!realHoldings ? (s.portfolio.status === "loading" ? "The app reads your holdings…" : "Holdings not available.") : totalValue == null ? "Total equity value not available (no quotes)." : `Total equity value${s.portfolio.data?.total_value == null ? " (only holdings with a price)" : ""}.`}
            {s.account.status === "ok" && s.account.data && <> Cash: <span className="pb-num">{fmtMoney(s.account.data.cash)}</span>.</>}
          </div>
        </div>
        <dl style={{ display: "flex", gap: "var(--sp-6)", flexWrap: "wrap", margin: 0 }}>
          {stats.map(([k, v]) => (
            <div key={k}>
              <dt className="pb-label">{k}</dt>
              <dd className="pb-num" style={{ margin: "var(--sp-1) 0 0", fontSize: "var(--fs-20)", fontWeight: 500, color: "var(--ink)" }}>{v}</dd>
            </div>
          ))}
        </dl>
      </header>

      <Glass style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
          <h2 className="pb-h4">Holdings</h2>
          {holdingsLabel && <Tag tone="demo" title="The hedges use these demo holdings to calculate their size. The broker account does not contain them, and its totals do not include them.">{holdingsLabel}</Tag>}
        </div>
        <div className="pb-table-scroll" style={{ marginTop: "var(--sp-3)" }}>
          <table className="pb-table" style={{ minWidth: 760 }}>
            <thead>
              <tr>
                <th>Position</th><th style={{ textAlign: "right" }}>Shares</th><th style={{ textAlign: "right" }}>Price</th><th style={{ textAlign: "right" }}>Value</th><th style={{ textAlign: "right" }}>Day change</th><th style={{ paddingLeft: "var(--sp-6)" }}>Bridge</th>
              </tr>
            </thead>
            <tbody>
              {priced.map((h) => {
                const bridged = !!h.engineBridge;
                const brokerNote = h.brokerQty !== undefined ? `Broker: ${h.brokerQty == null ? "n/a" : `${h.brokerQty.toLocaleString("en-US")} sh`}${h.canShort === false ? ", short: no" : h.canShort ? ", short: yes" : ""}` : "";
                const sub = h.engineBridge ? `Engine bridge ${h.engineBridge}` : `${h.touching} ${h.touching === 1 ? "market affects" : "markets affect"} it`;
                const open = () => {
                  if (h.engineBridge) router.push(`/bridge/${h.engineBridge}`);
                  else bridgeIt(h.t);
                };
                return (
                  <tr key={h.t}>
                    <td style={{ padding: "var(--sp-3) var(--sp-3) var(--sp-3) 0", maxWidth: 320 }}>
                      <div className="pb-ticker" style={{ fontSize: "var(--fs-14)" }}>{h.t}</div>
                      <div className="pb-ellipsis" style={faint} title={h.verdict ?? undefined}>{h.name}{h.verdict ? `, ${h.verdict}` : ""}</div>
                    </td>
                    <td className="pb-num">{h.shares.toLocaleString("en-US")}</td>
                    <td className="pb-num">{h.livePx == null ? "n/a" : "$" + h.livePx.toFixed(2)}</td>
                    <td className="pb-num" style={{ color: "var(--ink)", fontWeight: 500 }}>{h.value == null ? "n/a" : fmtMoney(h.value)}</td>
                    <td className="pb-num" style={{ color: "var(--faint)" }} title="The portfolio data does not include the day change.">n/a</td>
                    <td style={{ paddingLeft: "var(--sp-6)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)" }}>
                        <Btn variant={bridged ? "ghost" : "secondary"} size="sm" onClick={open}>{bridged ? "Open bridge" : "Make bridge"}</Btn>
                        <div style={{ minWidth: 0 }}>
                          <div className="pb-ellipsis" style={faint}>{sub}</div>
                          {brokerNote && <div className="pb-ellipsis" style={{ ...faint, color: h.canShort === false ? "var(--warn)" : "var(--faint)" }} title={h.shortReason ?? undefined}>{brokerNote}</div>}
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {s.portfolio.status === "loading" && !realHoldings && <div className="pb-small" style={{ ...empty, display: "flex", gap: "var(--sp-3)", alignItems: "center" }}><Orb state="working" size={20} />The app reads your holdings…</div>}
          {s.portfolio.status === "error" && !realHoldings && <Unavailable what="Holdings" error={s.portfolio.error} onRetry={s.refreshAccount} style={empty} />}
          {realHoldings && realHoldings.length === 0 && <div className="pb-small" style={empty}>This account has no holdings.</div>}
        </div>
        {realHoldings && <div className="pb-pretty" style={{ ...faint, marginTop: "var(--sp-4)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)" }}>The broker account section below shows the positions, balances, and orders at the broker. These holdings are not part of the broker account.</div>}
      </Glass>

      <div style={twoCol}>
        <Glass style={card}>
          <h2 className="pb-h4">Exposure by event</h2>
          <div style={{ display: "flex", flexDirection: "column", marginTop: "var(--sp-3)" }}>
            {(realHoldings ?? []).filter((h) => h.exposure).map((h, i, all) => (
              <button key={`x:${h.ticker}`} type="button" className="pb-row" onClick={() => bridgeIt(h.ticker)} style={{ cursor: "pointer", display: "block", width: "100%", padding: "var(--sp-3) 0", border: 0, borderBottom: i < all.length - 1 ? "1px solid var(--border)" : 0, background: "none", font: "inherit", color: "inherit", textAlign: "left" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", fontSize: "var(--fs-13)" }}>
                  <span style={{ minWidth: 0 }}><span className="pb-ticker">{h.ticker}</span> <span style={{ color: "var(--text-2)" }}>{h.exposure!.market.question}</span></span>
                  <span className="pb-num" style={{ flex: "none", color: "var(--down)", fontWeight: 500 }}>{fmtMoney(-Math.abs(h.exposure!.remaining_usd))} at risk</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap", marginTop: "var(--sp-2)", ...faint }}>
                  {(() => { const ml = mappingLabel(h.exposure!.source ?? "precomputed"); return ml && <Tag tone="ai" title={`${ml.title} ${h.exposure!.label}`}>{ml.text}</Tag>; })()}
                  <span><span className="pb-num">{h.exposure!.impact_pct.toFixed(1)}%</span> impact on {h.exposure!.direction === "up_on_yes" ? "NO" : "YES"}. Status: {isBridged(h) ? "bridged" : "no hedge"}.</span>
                </div>
              </button>
            ))}
            {realHoldings && !realHoldings.some((h) => h.exposure) && <div className="pb-small" style={empty}>No holding has a mapped event exposure. Click “Make bridge” on a holding to make one.</div>}
            {!realHoldings && s.portfolio.status === "error" && <div className="pb-small" style={empty}>This section uses the holdings data, which is not available.</div>}
          </div>
        </Glass>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-5)", minWidth: 0 }}>
          <Glass style={card}>
            <h2 className="pb-h4">Recent fills</h2>
            <div style={{ display: "flex", flexDirection: "column", marginTop: "var(--sp-3)" }}>
              {orders.error && <Unavailable what="Orders" error={orders.error} onRetry={retryOrders} compact style={empty} />}
              {!orders.error && !orders.loading && fills.length === 0 && <div className="pb-small" style={empty}>There are no fills.</div>}
              {fills.map((f) => (
                <div key={f.key} style={{ display: "grid", gridTemplateColumns: "64px 44px minmax(0,1fr)", gap: "var(--sp-3)", alignItems: "center", padding: "var(--sp-2) 0", borderBottom: "1px solid var(--border)", fontSize: "var(--fs-13)" }}>
                  <span className="pb-num" style={{ color: "var(--faint)" }}>{f.time}</span>
                  <span style={{ fontSize: "var(--fs-12)", fontWeight: 600, color: f.color }}>{f.side}</span>
                  <span className="pb-ellipsis" style={{ minWidth: 0, fontVariantNumeric: "tabular-nums" }}>{f.qty} {f.ticker} at {f.px} <span style={{ color: "var(--faint)" }}>({f.via})</span></span>
                </div>
              ))}
            </div>
          </Glass>
          <SandboxFillsPanel bridgeIds={liveIds} onOpen={(id) => router.push(`/bridge/${id}`)} />
        </div>
      </div>
      <div id={VOICE_ANCHOR.account} style={{ ...twoCol, scrollMarginTop: 90 }}>
        <BrokerAccountPanel account={s.account.data} accountError={s.account.error} session={s.session.data} refreshKey="portfolio" />
        <CapitalPanel refreshKey="portfolio" />
      </div>
      <WeekendExposurePanel holdings={realHoldings} bridgeIds={hedgeIds} session={s.session.data} onOpen={(id) => router.push(`/bridge/${id}`)} />
    </main>
  );
}
