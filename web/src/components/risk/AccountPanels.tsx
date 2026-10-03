"use client";

// Portfolio: the capital budget in force (GET /capital) and the active broker's real book (the Webull paper account:
// balances, positions, order history, reconciliation), kept apart from the demo holdings.
import { getCapital, getOrders, getPositions, getReconcile, type AccountOut } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { accountPill, accountRows, capitalView, orderRows, reconcileView, splitPositions } from "@/lib/risk";
import type { SessionView } from "@/lib/closed";
import { Glass, Tag } from "@/components/pb";
import { LegMark } from "@/components/options/OptionsCards";
import { BadgeTag, MeterRow, MetricGrid, PanelHead } from "./RiskBits";

const num = { fontFamily: "var(--mono)", fontSize: 12, textAlign: "right" as const, fontVariantNumeric: "tabular-nums" as const };
const head = { fontSize: 11, color: "#5A627A" };

export function CapitalPanel({ refreshKey }: { refreshKey: string }) {
  const cap = useAsync(`capital:${refreshKey}`, getCapital);
  const v = capitalView(cap.data);
  const lim = cap.data?.limits;
  return (
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <div data-testid="capital-panel">
        <PanelHead label="06 · CAPITAL USAGE">
          {cap.data?.account_label && <Tag tone={(cap.data.broker ?? "").includes("webull") ? "paper" : "sim"}>{cap.data.broker?.includes("webull") ? "Webull paper" : "simulated"} · {cap.data.account_label}</Tag>}
          {v.stale && <BadgeTag b={v.stale} />}
          {cap.data && <BadgeTag b={v.status} />}
        </PanelHead>
        {cap.loading && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 12 }}>Reading the account and the budget…</div>}
        {cap.error && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 12 }}>GET /capital unavailable ({cap.error}).</div>}
        {cap.data && (
          <>
            {v.error && <div role="alert" style={{ fontSize: 12.5, color: "#9A4A00", marginTop: 10 }}>{v.error}</div>}
            <MetricGrid rows={v.tiles} min={170} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
              {v.meters.map((m) => <MeterRow key={m.k} m={m} />)}
            </div>
            <div className="pb-label" style={{ marginTop: 18 }}>PER-EVENT BUDGET (≤ {lim ? `${Math.round(lim.max_event_pct * 100)}%` : "n/a"} OF EQUITY EACH)</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 10 }}>
              {v.events.length === 0 && <div style={{ fontSize: 12.5, color: "#5A627A" }}>No hedge exposure at the account yet. Replay bridges trade a sandbox and are not counted.</div>}
              {v.events.map((m) => <MeterRow key={m.k} m={m} />)}
            </div>
            {v.breaches.length > 0 && (
              <div style={{ marginTop: 14, fontSize: 12.5, color: "#9A4A00", lineHeight: 1.5 }}>
                {v.breaches.map((b) => <div key={b}>Breach: {b}</div>)}
              </div>
            )}
            <div className="pb-pretty" style={{ fontSize: 11.5, color: "#5A627A", marginTop: 14, lineHeight: 1.5 }}>
              {cap.data.margin?.rule ?? "Reg T margin"}. Gross hedge ≤ {lim ? `${Math.round(lim.max_gross_hedge_pct * 100)}%` : "n/a"} of equity. {v.enforcement} {cap.data.unpriced?.length ? `Unpriced (not counted): ${cap.data.unpriced.join(", ")}.` : ""}
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
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <div data-testid="broker-account">
        <PanelHead label={`05 · ${webull ? "WEBULL PAPER ACCOUNT" : "BROKER ACCOUNT"}`}>
          <Tag tone={pill.tone} title={pill.title}>{pill.text}</Tag>
        </PanelHead>
        {!account && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 12 }}>{accountError ? `GET /account unavailable (${accountError}).` : "Reading the account…"}</div>}
        {account && (
          <>
            <MetricGrid rows={accountRows(account)} min={150} />
            {account.note && <div className="pb-pretty" style={{ fontSize: 11.5, color: "#5A627A", marginTop: 10, lineHeight: 1.5 }}>{account.note}</div>}
          </>
        )}

        <div className="pb-label" style={{ marginTop: 18 }}>POSITIONS AT THE BROKER</div>
        <div style={{ marginTop: 8 }}>
          {positions.error && <div style={{ fontSize: 12.5, color: "#5A627A" }}>GET /positions unavailable ({positions.error}).</div>}
          {positions.data && split.broker.length === 0 && <div style={{ fontSize: 12.5, color: "#5A627A" }}>No open positions in the {webull ? "Webull paper" : "simulated"} account.</div>}
          {split.broker.map((p) => p.asset === "option" ? (
            <div key={p.symbol} style={{ padding: "6px 0", borderBottom: "1px solid rgba(15,22,38,.07)" }}><LegMark contract={p.symbol} qty={p.qty} sign={p.qty} /></div>
          ) : (
            <div key={p.symbol} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 90px 90px 100px", gap: 10, padding: "7px 0", borderBottom: "1px solid rgba(15,22,38,.07)", fontSize: 12.5 }}>
              <span style={{ fontWeight: 600 }}>{p.symbol} <span style={{ fontWeight: 400, color: "#5A627A", fontSize: 11 }}>{p.asset ?? "equity"}{p.strategy ? ` · ${p.strategy}` : ""}</span></span>
              <span style={{ ...num, color: p.qty < 0 ? "#C8323F" : "#0F1626" }}>{p.qty > 0 ? "+" : "−"}{Math.abs(p.qty).toLocaleString("en-US")}</span>
              <span style={num}>{(p.avg_px ?? p.avg_price) ? `avg ${(p.avg_px ?? p.avg_price)!.toFixed(2)}` : "—"}</span>
              <span style={num}>{p.market_value != null ? `$${Math.round(p.market_value).toLocaleString("en-US")}` : "—"}</span>
            </div>
          ))}
          {split.demo.length > 0 && <div style={{ fontSize: 11.5, color: "#8A92A8", marginTop: 6 }}>Demo holdings ({split.demo.map((p) => p.symbol).join(", ")}) are listed under Holdings, not here: they are not in the broker account.</div>}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 18 }}>
          <span className="pb-label">ORDER HISTORY · LAST 7 DAYS</span>
          <BadgeTag b={r.badge} />
        </div>
        <div className="pb-pretty" style={{ fontSize: 11.5, color: "#5A627A", marginTop: 4, lineHeight: 1.45 }} data-testid="reconcile-status">{r.line}</div>
        <div style={{ marginTop: 8 }}>
          {orders.error && <div style={{ fontSize: 12.5, color: "#5A627A" }}>GET /orders unavailable ({orders.error}).</div>}
          {orders.data && rows.length === 0 && <div style={{ fontSize: 12.5, color: "#5A627A" }}>No orders in the last 7 days.</div>}
          {rows.length > 0 && (
            <div className="pb-table-scroll">
              <div style={{ minWidth: 520 }}>
                <div style={{ display: "grid", gridTemplateColumns: "120px 44px minmax(0,1fr) 70px minmax(90px,.8fr) 100px", gap: 10, padding: "4px 0", borderBottom: "1px solid rgba(15,22,38,.14)", ...head }}>
                  <span>Time (UTC)</span><span>Side</span><span>Order</span><span style={{ textAlign: "right" }}>Price</span><span>Status</span><span>Origin</span>
                </div>
                {rows.map((o) => (
                  <div key={o.key} title={o.title || undefined} style={{ display: "grid", gridTemplateColumns: "120px 44px minmax(0,1fr) 70px minmax(90px,.8fr) 100px", gap: 10, padding: "7px 0", borderBottom: "1px solid rgba(15,22,38,.07)", fontSize: 12 }}>
                    <span className="pb-mono" style={{ fontSize: 11, color: "#5A627A" }}>{o.when}</span>
                    <span style={{ fontSize: 11, fontWeight: 600, color: o.side === "SELL" ? "#C8323F" : "#15804F" }}>{o.side}</span>
                    <span className="pb-ellipsis">{o.qty.toLocaleString("en-US")} {o.symbol}</span>
                    <span style={num}>{o.px}</span>
                    <span className="pb-ellipsis" style={{ color: "#3C4458" }}>{o.status}</span>
                    <span className="pb-ellipsis" style={{ color: "#5A627A" }}>{o.origin}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Glass>
  );
}
