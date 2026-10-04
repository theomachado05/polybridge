"use client";

import { BROKERS, LOGO } from "@/lib/brokers";
import { fmtMoney } from "@/lib/fmt";
import { brokerLabel, useStore, type Settings } from "@/lib/store";
import { ChipGroup, Glass, Label, LogoTile, Switch, Tag, Unavailable } from "@/components/pb";

const MARKETS = [
  { name: "Polymarket", sub: "CLOB websocket, read-only", logo: LOGO("polymarket.com") },
  { name: "Kalshi", sub: "REST API, read-only", logo: LOGO("kalshi.com") },
];
const GUARDS: { key: keyof Settings["guards"]; name: string; sub: string }[] = [
  { key: "edge", name: "Trade only when the edge is more than the fees", sub: "If a live bridge starts with its fee gate off (no quote or impact estimate), it waits for your approval." },
  { key: "wash", name: "Obey wash-sale windows", sub: "Preference only. Live bridges do not have a wash-sale block now." },
  { key: "auto", name: "Approve bridges automatically", sub: "When this is off, each bridge waits for your approval. After approval, the engine sends its orders and does not ask again." },
];
const row = { display: "flex", alignItems: "center", gap: 14, padding: "12px 0", borderBottom: "1px solid rgba(15,22,38,.07)" } as const;

export default function Profile() {
  const s = useStore();
  const { settings: st, account } = s;
  const acct = brokerLabel(account);
  const toggleConn = (id: string) => {
    const on = st.conns.includes(id), conns = on ? st.conns.filter((x) => x !== id) : [...st.conns, id];
    s.updateSettings({ conns, broker: on ? conns[0] ?? null : st.broker ?? id });
  };

  return (
    <main className="pb-page" style={{ maxWidth: 1040, paddingTop: 18, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pb-header">
        <div>
          <h2 className="pb-h2">Profile</h2>
          <div className="pb-lede">Set your connections, your tax profile, and the guardrails for each bridge.</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 16 }}>
        <Glass style={{ padding: "22px 26px" }}>
          <Label>Brokerages</Label>
          <div className="pb-sub" style={{ marginTop: 14, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: "#5A627A", fontWeight: 500 }}>Active account (it receives the orders)</span>
              <Tag tone={acct.tone} title="GET /account">{acct.name}</Tag>
            </div>
            {account.status === "ok" && account.data ? (
              <div className="pb-mono" style={{ fontSize: 12, color: "#0F1626" }}>
                Cash {fmtMoney(account.data.cash)}, equity {fmtMoney(account.data.equity)}, buying power {fmtMoney(account.data.buying_power)} {account.data.currency}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "#5A627A", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                {account.status === "loading" ? "The app reads the account…" : <Unavailable what="The account" error={account.error} onRetry={s.refreshAccount} compact />}
              </div>
            )}
            <div style={{ fontSize: 11.5, color: "#5A627A", lineHeight: 1.45 }}>Only paper and simulated accounts are available. The broker buttons below save preferences for this session. Webull paper starts on the server when its API keys are set.</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 6 }}>
            {BROKERS.map((b) => {
              const on = st.conns.includes(b.id);
              const live = b.id === "webull" && acct.tone === "paper";
              return (
                <div key={b.id} style={row}>
                  <LogoTile logo={b.logo} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.01em" }}>{b.name}</div>
                    <div style={{ fontSize: 11.5, color: "#5A627A", marginTop: 1 }}>{b.sub}</div>
                  </div>
                  <button type="button" onClick={() => toggleConn(b.id)} style={{ padding: "7px 14px", borderRadius: 999, fontSize: 12.5, fontWeight: 600, cursor: "pointer", background: on ? "rgba(34,160,107,.12)" : "#0F1626", color: on ? "#15804F" : "#fff", border: `1px solid ${on ? "rgba(34,160,107,.25)" : "#0F1626"}` }}>{live ? "Connected" : on ? "Remove preference" : "Save preference"}</button>
                </div>
              );
            })}
          </div>
        </Glass>

        <Glass style={{ padding: "22px 26px" }}>
          <Label>Prediction markets</Label>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
            {MARKETS.map((m) => {
              const on = !!st.markets[m.name];
              return (
                <div key={m.name} style={row}>
                  <LogoTile logo={m.logo} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.01em" }}>{m.name}</div>
                    <div style={{ fontSize: 11.5, color: "#5A627A", marginTop: 1 }}>{m.sub}</div>
                  </div>
                  <Switch label={m.name} on={on} onClick={() => s.updateSettings({ markets: { ...st.markets, [m.name]: !on } })} />
                </div>
              );
            })}
          </div>
          <div style={{ fontSize: 12, color: "#5A627A", marginTop: 14, lineHeight: 1.5 }}>Read-only. PolyBridge does not trade these contracts. It reads them to trade your equities.</div>
        </Glass>

        <Glass style={{ padding: "22px 26px" }}>
          <Label>Tax and account</Label>
          <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 16 }}>
            <ChipGroup label="Account type" options={["Taxable", "IRA"] as const} value={st.account} onChange={(v) => s.updateSettings({ account: v })} />
            <ChipGroup label="Marginal tax rate" options={["24%", "32%", "35%", "37%"] as const} value={st.rate as "32%"} onChange={(v) => s.updateSettings({ rate: v })} />
            <ChipGroup label="State of residence" options={["CA", "NY", "TX", "Other"] as const} value={st.taxState as "CA"} onChange={(v) => s.updateSettings({ taxState: v })} />
          </div>
        </Glass>

        <Glass style={{ padding: "22px 26px" }}>
          <Label>Guardrails</Label>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
            {GUARDS.map((g) => (
              <div key={g.key} style={row}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.01em" }}>{g.name}</div>
                  <div style={{ fontSize: 11.5, color: "#5A627A", marginTop: 1 }}>{g.sub}</div>
                </div>
                <Switch label={g.name} on={st.guards[g.key]} onClick={() => s.updateSettings({ guards: { ...st.guards, [g.key]: !st.guards[g.key] } })} />
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <ChipGroup label="Maximum hedge ratio" options={["50%", "75%", "100%"] as const} value={st.maxHedge as "100%"} onChange={(v) => s.updateSettings({ maxHedge: v })} />
          </div>
        </Glass>
      </div>
    </main>
  );
}
