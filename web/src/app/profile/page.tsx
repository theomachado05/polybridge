"use client";

import { BROKERS, LOGO } from "@/lib/brokers";
import { fmtMoney } from "@/lib/fmt";
import { brokerLabel, useStore, type Settings } from "@/lib/store";
import { Btn, ChipGroup, Glass, LogoTile, Switch, Tag, Unavailable } from "@/components/pb";

const MARKETS = [
  { name: "Polymarket", sub: "CLOB websocket, read-only", logo: LOGO("polymarket.com") },
  { name: "Kalshi", sub: "REST API, read-only", logo: LOGO("kalshi.com") },
];
const GUARDS: { key: keyof Settings["guards"]; name: string; sub: string }[] = [
  { key: "edge", name: "Trade only when the edge is more than the fees", sub: "If a live bridge starts with its fee gate off (no quote or impact estimate), it waits for your approval." },
  { key: "wash", name: "Obey wash-sale windows", sub: "Preference only. Live bridges do not have a wash-sale block now." },
  { key: "auto", name: "Approve bridges automatically", sub: "When this is off, each bridge waits for your approval. After approval, the engine sends its orders and does not ask again." },
];
const row = { display: "flex", alignItems: "center", gap: "var(--sp-4)", padding: "var(--sp-3) 0", borderBottom: "1px solid var(--border)" } as const;
const card = { padding: "var(--sp-5)", minWidth: 0 } as const;
const list = { display: "flex", flexDirection: "column", marginTop: "var(--sp-3)", borderTop: "1px solid var(--border)" } as const;
const name = { fontSize: "var(--fs-14)", fontWeight: 600, color: "var(--ink)" } as const;
const sub = { fontSize: "var(--fs-13)", color: "var(--faint)", marginTop: 2, lineHeight: 1.45 } as const;
const note = { fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-4)", lineHeight: 1.5 } as const;

export default function Profile() {
  const s = useStore();
  const { settings: st, account } = s;
  const acct = brokerLabel(account);
  const toggleConn = (id: string) => {
    const on = st.conns.includes(id), conns = on ? st.conns.filter((x) => x !== id) : [...st.conns, id];
    s.updateSettings({ conns, broker: on ? conns[0] ?? null : st.broker ?? id });
  };

  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: 96, display: "flex", flexDirection: "column", gap: "var(--sp-5)" }}>
      <header className="pb-header">
        <div>
          <h1 className="pb-h2" style={{ marginTop: 0 }}>Profile</h1>
          <div className="pb-lede">Set your connections, your tax profile, and the guardrails for each bridge.</div>
        </div>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: "var(--sp-5)", alignItems: "start" }}>
        <Glass style={card}>
          <h2 className="pb-h4">Brokerages</h2>
          <div className="pb-sub" style={{ marginTop: "var(--sp-4)", padding: "var(--sp-4)", display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" }}>
              <span className="pb-label" style={{ fontSize: "var(--fs-13)" }}>Active account (it receives the orders)</span>
              <Tag tone={acct.tone} title="GET /account">{acct.name}</Tag>
            </div>
            {account.status === "ok" && account.data ? (
              <div className="pb-num" style={{ fontSize: "var(--fs-14)", color: "var(--ink)" }}>
                Cash {fmtMoney(account.data.cash)}, equity {fmtMoney(account.data.equity)}, buying power {fmtMoney(account.data.buying_power)} {account.data.currency}
              </div>
            ) : (
              <div className="pb-small" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
                {account.status === "loading" ? "The app reads the account…" : <Unavailable what="The account" error={account.error} onRetry={s.refreshAccount} compact />}
              </div>
            )}
            <div style={{ fontSize: "var(--fs-12)", color: "var(--faint)", lineHeight: 1.5 }}>Only paper and simulated accounts are available. The broker buttons below save preferences for this session. Webull paper starts on the server when its API keys are set.</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", marginTop: "var(--sp-2)" }}>
            {BROKERS.map((b) => {
              const on = st.conns.includes(b.id);
              const live = b.id === "webull" && acct.tone === "paper";
              return (
                <div key={b.id} style={row}>
                  <LogoTile logo={b.logo} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={name}>{b.name}</div>
                    <div style={sub}>{b.sub}</div>
                  </div>
                  <Btn variant={on ? "ghost" : "secondary"} size="sm" onClick={() => toggleConn(b.id)}>{live ? "Connected" : on ? "Remove preference" : "Save preference"}</Btn>
                </div>
              );
            })}
          </div>
        </Glass>

        <Glass style={card}>
          <h2 className="pb-h4">Prediction markets</h2>
          <div style={list}>
            {MARKETS.map((m) => {
              const on = !!st.markets[m.name];
              return (
                <div key={m.name} style={row}>
                  <LogoTile logo={m.logo} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={name}>{m.name}</div>
                    <div style={sub}>{m.sub}</div>
                  </div>
                  <Switch label={m.name} on={on} onClick={() => s.updateSettings({ markets: { ...st.markets, [m.name]: !on } })} />
                </div>
              );
            })}
          </div>
          <div style={note}>Read-only. PolyBridge does not trade these contracts. It reads them to trade your equities.</div>
        </Glass>

        <Glass style={card}>
          <h2 className="pb-h4">Tax and account</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-5)", marginTop: "var(--sp-4)" }}>
            <ChipGroup label="Account type" options={["Taxable", "IRA"] as const} value={st.account} onChange={(v) => s.updateSettings({ account: v })} />
            <ChipGroup label="Marginal tax rate" options={["24%", "32%", "35%", "37%"] as const} value={st.rate as "32%"} onChange={(v) => s.updateSettings({ rate: v })} />
            <ChipGroup label="State of residence" options={["CA", "NY", "TX", "Other"] as const} value={st.taxState as "CA"} onChange={(v) => s.updateSettings({ taxState: v })} />
          </div>
        </Glass>

        <Glass style={card}>
          <h2 className="pb-h4">Guardrails</h2>
          <div style={list}>
            {GUARDS.map((g) => (
              <div key={g.key} style={row}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={name}>{g.name}</div>
                  <div style={sub}>{g.sub}</div>
                </div>
                <Switch label={g.name} on={st.guards[g.key]} onClick={() => s.updateSettings({ guards: { ...st.guards, [g.key]: !st.guards[g.key] } })} />
              </div>
            ))}
          </div>
          <div style={{ marginTop: "var(--sp-5)" }}>
            <ChipGroup label="Maximum hedge ratio" options={["50%", "75%", "100%"] as const} value={st.maxHedge as "100%"} onChange={(v) => s.updateSettings({ maxHedge: v })} />
          </div>
        </Glass>
      </div>
    </main>
  );
}
