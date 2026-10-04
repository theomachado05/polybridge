"use client";

import { getCapital, getOrders, getPositions, getReconcile, type AccountOut } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { accountPill, accountRows, capitalView, orderRows, reconcileView, splitPositions } from "@/lib/risk";
import type { SessionView } from "@/lib/closed";
import { Glass, Tag } from "@/components/pb";
import { LegMark } from "@/components/options/OptionsCards";
import { BadgeTag, MeterRow, MetricGrid, PanelHead } from "./RiskBits";
import { VOICE_ANCHOR } from "@/lib/voiceDrive";

const card = { padding: "var(--sp-5)", minWidth: 0 } as const;
const msg = { marginTop: "var(--sp-3)" } as const;
const sub = { fontSize: "var(--fs-14)", marginTop: "var(--sp-6)" } as const;
const fine = { fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-3)", lineHeight: 1.5 } as const;

export function CapitalPanel({ refreshKey }: { refreshKey: string }) {
  const cap = useAsync(`capital:${refreshKey}`, getCapital);
  const v = capitalView(cap.data);
  const lim = cap.data?.limits;
  return (
    <Glass style={card}>
      <div data-testid="capital-panel">
        <PanelHead label="Capital use">
          {cap.data?.account_label && <Tag tone={(cap.data.broker ?? "").includes("webull") ? "paper" : "sim"}>{cap.data.broker?.includes("webull") ? "Webull paper" : "Simulated account"}, {cap.data.account_label}</Tag>}
          {v.stale && <BadgeTag b={v.stale} />}
          {cap.data && <BadgeTag b={v.status} />}
        </PanelHead>
        {cap.loading && <div className="pb-small" style={msg}>Reading the account and the budget…</div>}
        {cap.error && <div className="pb-small" style={msg}>The capital budget is not available ({cap.error}). Try again later.</div>}
        {cap.data && (
          <>
            {v.error && <div role="alert" className="pb-small" style={{ ...msg, color: "var(--warn)" }}>{v.error}</div>}
            <MetricGrid rows={v.tiles} min={170} />
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)", marginTop: "var(--sp-5)" }}>
              {v.meters.map((m) => <MeterRow key={m.k} m={m} />)}
            </div>
            <h3 className="pb-h4" style={sub}>Budget per event (maximum {lim ? `${Math.round(lim.max_event_pct * 100)}%` : "n/a"} of equity each)</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)", marginTop: "var(--sp-3)" }}>
              {v.events.length === 0 && <div className="pb-small">The account has no hedge exposure. The budget does not count replay bridges, because they trade in a sandbox.</div>}
              {v.events.map((m) => <MeterRow key={m.k} m={m} />)}
            </div>
            {v.breaches.length > 0 && (
              <div className="pb-small" style={{ marginTop: "var(--sp-3)", color: "var(--warn)" }}>
                {v.breaches.map((b) => <div key={b}>Over the limit: {b}</div>)}
              </div>
            )}
            <div className="pb-pretty" style={{ ...fine, marginTop: "var(--sp-5)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)" }}>
              {cap.data.margin?.rule ?? "Reg T margin"}. Gross hedge limit: {lim ? `${Math.round(lim.max_gross_hedge_pct * 100)}%` : "n/a"} of equity. {v.enforcement} {cap.data.unpriced?.length ? `No price, not counted: ${cap.data.unpriced.join(", ")}.` : ""}
            </div>
          </>
        )}
      </div>
    </Glass>
  );
}

export function BrokerAccountPanel({ account, accountError, session, refreshKey }: { account: AccountOut | null; accountError: string | null; session: SessionView | null; refreshKey: string }) {
  const positions = useAsync(`bpos:${refreshKey}`, () => getPositions(true));
  const orders = useAsync(`bord:${refreshKey}`, () => getOrders(undefined, 7));
  const rec = useAsync(`brec:${refreshKey}`, getReconcile);
  const pill = accountPill(account, session);
  const split = splitPositions(positions.data ?? []);
  const rows = orderRows(orders.data ?? []).slice(0, 10);
  const r = reconcileView(rec.error ? null : rec.data);
  const webull = (account?.broker ?? "").includes("webull");
  return (
    <Glass style={card}>
      <div data-testid="broker-account">
        <PanelHead label={webull ? "Webull paper account" : "Broker account"}>
          <Tag tone={pill.tone} title={pill.title}>{pill.text}</Tag>
        </PanelHead>
        {!account && <div className="pb-small" style={msg}>{accountError ? `The account data is not available (${accountError}). Try again later.` : "The app reads the account…"}</div>}
        {account && (
          <>
            <MetricGrid rows={accountRows(account)} min={150} />
            {account.note && <div className="pb-pretty" style={fine}>{account.note}</div>}
          </>
        )}

        <h3 id={VOICE_ANCHOR.positions} className="pb-h4" style={{ ...sub, scrollMarginTop: 90 }}>Positions at the broker</h3>
        <div style={{ marginTop: "var(--sp-2)" }}>
          {positions.error && <div className="pb-small">The positions are not available ({positions.error}). Try again later.</div>}
          {positions.data && split.broker.length === 0 && <div className="pb-small">The {webull ? "Webull paper" : "simulated"} account has no open positions.</div>}
          {split.broker.length > 0 && (
            <table className="pb-table">
              <tbody>
                {split.broker.map((p) => p.asset === "option" ? (
                  <tr key={p.symbol}><td colSpan={4}><LegMark contract={p.symbol} qty={p.qty} sign={p.qty} /></td></tr>
                ) : (
                  <tr key={p.symbol}>
                    <td><span className="pb-ticker">{p.symbol}</span> <span style={{ color: "var(--faint)", fontSize: "var(--fs-12)" }}>{p.asset ?? "equity"}{p.strategy ? `, ${p.strategy}` : ""}</span></td>
                    <td className="pb-num" style={{ color: p.qty < 0 ? "var(--down)" : "var(--ink)" }}>{p.qty > 0 ? "+" : "−"}{Math.abs(p.qty).toLocaleString("en-US")}</td>
                    <td className="pb-num">{(p.avg_px ?? p.avg_price) ? `avg ${(p.avg_px ?? p.avg_price)!.toFixed(2)}` : "n/a"}</td>
                    <td className="pb-num">{p.market_value != null ? `$${Math.round(p.market_value).toLocaleString("en-US")}` : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {split.demo.length > 0 && <div style={fine}>The demo holdings ({split.demo.map((p) => p.symbol).join(", ")}) are in the Holdings section. They are not in the broker account.</div>}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap", marginTop: "var(--sp-6)" }}>
          <h3 className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>Orders in the last 7 days</h3>
          <BadgeTag b={r.badge} />
        </div>
        <div className="pb-pretty" style={{ ...fine, marginTop: "var(--sp-1)" }} data-testid="reconcile-status">{r.line}</div>
        <div style={{ marginTop: "var(--sp-3)" }}>
          {orders.error && <div className="pb-small">The orders are not available ({orders.error}). Try again later.</div>}
          {orders.data && rows.length === 0 && <div className="pb-small">There are no orders in the last 7 days.</div>}
          {rows.length > 0 && (
            <div className="pb-table-scroll">
              <table className="pb-table" style={{ minWidth: 520 }}>
                <thead>
                  <tr><th>Time (UTC)</th><th>Side</th><th>Order</th><th style={{ textAlign: "right" }}>Price</th><th>Status</th><th>Origin</th></tr>
                </thead>
                <tbody>
                  {rows.map((o) => (
                    <tr key={o.key} title={o.title || undefined}>
                      <td className="pb-num" style={{ color: "var(--faint)", whiteSpace: "nowrap" }}>{o.when}</td>
                      <td style={{ fontWeight: 600, color: o.side === "SELL" ? "var(--down)" : "var(--up)" }}>{o.side}</td>
                      <td style={{ fontVariantNumeric: "tabular-nums" }}>{o.qty.toLocaleString("en-US")} {o.symbol}</td>
                      <td className="pb-num">{o.px}</td>
                      <td style={{ color: "var(--text-2)" }}>{o.status}</td>
                      <td style={{ color: "var(--faint)" }}>{o.origin}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Glass>
  );
}
