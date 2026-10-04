"use client";

import { useRouter } from "next/navigation";
import { getOrders, type BrokerOrder, type Holding } from "@/lib/api";
import { fmtMoney, fmtTime } from "@/lib/fmt";
import { mappingLabel } from "@/lib/ai";
import { useAsync, useRetry } from "@/lib/hooks";
import { brokerLabel, useStore } from "@/lib/store";
import { Glass, Label, Orb, Tag, Unavailable } from "@/components/pb";
import { SandboxFillsPanel } from "@/components/SandboxFills";
import { engineBridgeFor } from "@/lib/portfolioView";
import { WeekendExposurePanel } from "@/components/WeekendExposure";
import { BrokerAccountPanel, CapitalPanel } from "@/components/risk/AccountPanels";
import { accountPill } from "@/lib/risk";

interface Row {
  t: string; name: string; shares: number; px: number | null; verdict: string | null;
  engineBridge: string | null; touching: number;
  /** Broker book for this ticker (not the demo shares) and whether the broker can short it now. */
  brokerQty?: number | null; canShort?: boolean | null; shortReason?: string | null;
}
interface Fill { key: string; ts: number; time: string; side: string; color: string; qty: number; ticker: string; px: string; via: string }

const cols = "minmax(0,1.4fr) 70px 90px 100px 90px minmax(150px,1.2fr)";
const num = { fontFamily: "var(--mono)", fontSize: 12.5, textAlign: "right" as const };
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
    ["Exposures bridged", exposures.length ? `${realCover}%` : "—"],
    ["Fees (account)", orders.data ? `$${orderFees.toFixed(2)}` : "—"],
    ["Fills (account)", orders.data ? String(filled.length) : "—"],
  ];

  const fills: Fill[] = [
    ...filled.map((o) => {
      const when = o.filled_at ?? o.created_at;
      const ts = when ? Date.parse(when) : 0;
      const px = fillPx(o);
      return { key: `o:${o.id}`, ts, time: ts ? fmtTime(new Date(ts)) : "—", side: o.side.toUpperCase(), color: o.side === "sell" ? "#C8323F" : "#15804F", qty: o.qty, ticker: o.symbol, px: px == null ? "mkt" : px.toFixed(2), via: o.tag ? `bridge ${o.tag}` : acct.name };
    }),
  ].sort((a, b) => b.ts - a.ts).slice(0, 7);

  const bridgeIt = (t: string) => { s.setQuestion(null); s.setQuery(t); router.push("/build"); };

  return (
    <main className="pb-page" style={{ maxWidth: 1400, paddingTop: 18, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pb-header">
        <div>
          <div className="pb-label" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            PORTFOLIO · {acct.name.toUpperCase()}
            <span data-testid="account-pill"><Tag tone={pill.tone} title={pill.title}>{pill.text}</Tag></span>

          </div>
          <h2 className="pb-h2">{totalValue == null ? "—" : fmtMoney(totalValue)}</h2>
          <div className="pb-lede">
            {!realHoldings ? (s.portfolio.status === "loading" ? "Reading your holdings…" : "Holdings unavailable") : totalValue == null ? "Total equity value unavailable (no quotes)" : `Total equity value${s.portfolio.data?.total_value == null ? " (priced holdings only)" : ""}`}
            {s.account.status === "ok" && s.account.data && <> · cash {fmtMoney(s.account.data.cash)}</>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {stats.map(([k, v]) => (
            <div key={k} className="pb-sub" style={{ padding: "12px 16px", minWidth: 140 }}>
              <div style={{ fontSize: 11, color: "#5A627A", display: "flex", gap: 6, alignItems: "center" }}>{k}</div>
              <div className="pb-tab" style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-.02em", marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16 }}>
        <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Label>01 · HOLDINGS{holdingsLabel === "demo holdings" ? " · DEMO" : ""}</Label>
            {holdingsLabel && <Tag tone="demo" title="These holdings are the demo seed the hedges are sized on. They are not in the broker account (05) and never add to its totals.">{holdingsLabel}</Tag>}
          </div>
          <div className="pb-table-scroll">
            <div style={{ minWidth: 640 }}>
              <div style={{ display: "grid", gridTemplateColumns: cols, gap: 14, padding: "16px 0 8px", borderBottom: "1px solid rgba(15,22,38,.14)", fontSize: 11, color: "#5A627A" }}>
                <span>Position</span><span style={{ textAlign: "right" }}>Shares</span><span style={{ textAlign: "right" }}>Price</span><span style={{ textAlign: "right" }}>Value</span><span style={{ textAlign: "right" }}>Today</span><span>Bridge</span>
              </div>
              {s.portfolio.status === "loading" && !realHoldings && <div style={{ padding: "14px 0", display: "flex", gap: 10, alignItems: "center", fontSize: 13, color: "#3C4458" }}><Orb state="working" size={20} />Reading your holdings…</div>}
              {s.portfolio.status === "error" && !realHoldings && <Unavailable what="Holdings (GET /portfolio)" error={s.portfolio.error} onRetry={s.refreshAccount} style={{ padding: "14px 0" }} />}
              {realHoldings && realHoldings.length === 0 && <div style={{ padding: "14px 0", fontSize: 13, color: "#5A627A" }}>No holdings.</div>}
              {priced.map((h) => {
                const bridged = !!h.engineBridge;
                const brokerNote = h.brokerQty !== undefined ? `broker ${h.brokerQty == null ? "n/a" : `${h.brokerQty.toLocaleString("en-US")} sh`}${h.canShort === false ? " · not shortable" : h.canShort ? " · shortable" : ""}` : "";
                const sub = h.engineBridge ? `engine bridge ${h.engineBridge}` : `${h.touching} ${h.touching === 1 ? "market touches" : "markets touch"} this`;
                const open = () => {
                  if (h.engineBridge) router.push(`/bridge/${h.engineBridge}`);
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
                    <span style={{ ...num, color: "#8A92A8" }} title="Day change is not reported by GET /portfolio">—</span>
                    <div style={{ minWidth: 0 }}>
                      <button type="button" onClick={open} style={{ display: "inline-block", padding: "4px 10px", borderRadius: 999, fontSize: 11.5, fontWeight: 600, cursor: "pointer", border: 0, background: bridged ? "rgba(34,160,107,.12)" : "#0F1626", color: bridged ? "#15804F" : "#fff" }}>{bridged ? "Bridged" : "Bridge it"}</button>
                      <div className="pb-ellipsis" style={{ fontSize: 11, color: "#5A627A", marginTop: 4 }}>{sub}</div>
                      {brokerNote && <div className="pb-ellipsis" style={{ fontSize: 10.5, color: h.canShort === false ? "#9A4A00" : "#8A92A8" }} title={h.shortReason ?? undefined}>{brokerNote}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          {realHoldings && <div style={{ marginTop: 14, fontSize: 12, color: "#5A627A" }}>The broker&rsquo;s own positions, balances and orders are in 05 below, apart from these holdings.</div>}
        </Glass>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Glass style={{ padding: "22px 26px" }}>
            <Label>02 · EXPOSURE BY EVENT</Label>
            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 16 }}>
              {(realHoldings ?? []).filter((h) => h.exposure).map((h) => (
                <div key={`x:${h.ticker}`} role="button" tabIndex={0} onClick={() => bridgeIt(h.ticker)} style={{ cursor: "pointer" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
                    <span className="pb-ellipsis" style={{ minWidth: 0 }}><span style={{ fontWeight: 600 }}>{h.ticker}</span> <span style={{ color: "#5A627A" }}>· {h.exposure!.market.question}</span></span>
                    <span className="pb-mono" style={{ fontSize: 12, flex: "none", color: "#C8323F" }}>{fmtMoney(-Math.abs(h.exposure!.remaining_usd))} at risk</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, fontSize: 11, color: "#5A627A" }}>
                    {(() => { const ml = mappingLabel(h.exposure!.source ?? "precomputed"); return ml && <Tag tone="ai" title={`${ml.title} ${h.exposure!.label}`}>{ml.text}</Tag>; })()}
                    {h.exposure!.impact_pct.toFixed(1)}% impact on {h.exposure!.direction === "up_on_yes" ? "NO" : "YES"} · {isBridged(h) ? "bridged" : "not hedged"}
                  </div>
                </div>
              ))}
              {realHoldings && !realHoldings.some((h) => h.exposure) && <div style={{ fontSize: 13, color: "#5A627A" }}>No mapped event exposure yet. Use “Bridge it” on a holding.</div>}
              {!realHoldings && s.portfolio.status === "error" && <div style={{ fontSize: 13, color: "#5A627A" }}>Needs the holdings above.</div>}
            </div>
          </Glass>
          <Glass style={{ padding: "22px 26px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
              <Label>03 · RECENT FILLS</Label>

            </div>
            <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
              {orders.error && <Unavailable what="Orders (GET /orders)" error={orders.error} onRetry={retryOrders} compact style={{ padding: "8px 0" }} />}
              {!orders.error && !orders.loading && fills.length === 0 && <div style={{ fontSize: 13, color: "#5A627A", padding: "8px 0" }}>No fills yet.</div>}
              {fills.map((f) => (
                <div key={f.key} style={{ display: "grid", gridTemplateColumns: "62px 44px minmax(0,1fr)", gap: 12, alignItems: "center", padding: "9px 0", borderBottom: "1px solid rgba(15,22,38,.07)", fontSize: 12.5 }}>
                  <span className="pb-mono" style={{ fontSize: 11.5, color: "#5A627A" }}>{f.time}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: f.color }}>{f.side}</span>
                  <span className="pb-ellipsis" style={{ minWidth: 0 }}>{f.qty} {f.ticker} @ {f.px} <span style={{ color: "#5A627A" }}>· {f.via}</span></span>
                </div>
              ))}
            </div>
          </Glass>
          <SandboxFillsPanel bridgeIds={liveIds} onOpen={(id) => router.push(`/bridge/${id}`)} />
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16 }}>
        <BrokerAccountPanel account={s.account.data} accountError={s.account.error} session={s.session.data} refreshKey="portfolio" />
        <CapitalPanel refreshKey="portfolio" />
      </div>
      <WeekendExposurePanel holdings={realHoldings} bridgeIds={hedgeIds} session={s.session.data} onOpen={(id) => router.push(`/bridge/${id}`)} />
    </main>
  );
}
