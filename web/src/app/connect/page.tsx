"use client";

import { useRouter } from "next/navigation";
import { BROKERS } from "@/lib/demo";
import { fmtMoney } from "@/lib/fmt";
import { brokerLabel, defaultPick, useStore } from "@/lib/store";
import { ChipGroup, DemoTag, Glass, Label, LogoTile, Orb, Tag } from "@/components/pb";

export default function Connect() {
  const router = useRouter();
  const s = useStore();
  const { settings, account } = s;
  const eq = s.equity ?? defaultPick().eq;
  const acct = brokerLabel(account);
  const canRun = !!settings.broker;
  const pick = (id: string) => s.updateSettings({ broker: id, conns: settings.conns.includes(id) ? settings.conns : [...settings.conns, id] });
  const position = eq.held ? `${eq.held.toLocaleString("en-US")} sh${s.question?.real ? "" : " in 3 lots (2 long-term)"}` : "no position — hedge will size to a 500 sh notional";
  // Only the broker GET /account reports is "connected"; every other card is a saved preference.
  const chosen = BROKERS.find((b) => b.id === settings.broker) ?? null;
  const connected = !!chosen && chosen.id === "webull" && acct.tone === "paper";
  const status = !chosen
    ? "Choose where your shares live."
    : connected
      ? `Connected · Webull paper · ${eq.t}: ${position}`
      : `${chosen.name} saved as a preference only (no live connection) · orders route to ${acct.tone === "demo" ? "no account yet" : "the " + acct.name.toLowerCase()} · ${eq.t}: ${position}`;

  const run = () => {
    if (!canRun) return;
    if (!s.question || !s.equity) {
      const d = defaultPick();
      s.setQuestion(d.q);
      s.setEquity(d.eq);
      s.setInst("shares");
    }
    router.push("/pipeline");
  };

  return (
    <main className="pb-page" style={{ maxWidth: 760, paddingTop: 30, paddingBottom: 80 }}>
      <Glass style={{ padding: "28px 30px", borderRadius: 30, background: "rgba(255,255,255,.58)" }}>
        <Label rule>ONE LAST THING</Label>
        <h2 className="pb-serif" style={{ margin: "10px 0 0", fontSize: 38, letterSpacing: "-.015em", fontWeight: 400, lineHeight: 1.1 }}>Where does {eq.t} live?</h2>
        <p style={{ margin: "8px 0 0", fontSize: 14, color: "#3C4458", lineHeight: 1.5 }}>PolyBridge sizes every order to your position; the account named below is the one that receives them.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, marginTop: 22 }}>
          {BROKERS.map((b) => {
            const sel = settings.broker === b.id;
            return (
              <button key={b.id} type="button" className="pb-card-hover" onClick={() => pick(b.id)} style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16, borderRadius: 20, cursor: "pointer", textAlign: "left", background: sel ? "#fff" : "rgba(255,255,255,.5)", border: `1px solid ${sel ? "rgba(59,108,246,.6)" : "rgba(255,255,255,.9)"}`, transition: "all .2s ease" }}>
                <LogoTile logo={b.logo} />
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.01em" }}>{b.name}</div>
                  <div style={{ fontSize: 11.5, color: "#5A627A", marginTop: 2 }}>{b.sub}</div>
                </div>
              </button>
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)", fontSize: 13 }}>
          <Orb state={settings.broker ? "breathing" : "searching"} size={24} />
          <span style={{ color: "#3C4458" }}>{status}</span>
          {chosen && !connected && <span style={{ marginLeft: "auto", flex: "none" }}><DemoTag what="preference only" title="Only the simulator and Webull paper exist; GET /account names the one that takes orders." /></span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, padding: "0 4px", fontSize: 12, color: "#5A627A", flexWrap: "wrap" }}>
          <span>Orders route to</span>
          <Tag tone={acct.tone} title={acct.tone === "demo" ? "GET /account is unavailable" : "From GET /account"}>{acct.name}</Tag>
          {account.status === "ok" && account.data && <span className="pb-mono">cash {fmtMoney(account.data.cash)} · buying power {fmtMoney(account.data.buying_power)}</span>}
          {account.status === "error" && <DemoTag what="no account endpoint" />}
          {acct.tone === "sim" && settings.broker === "webull" && <span>Webull paper takes over when its API keys are set; real money is out of scope.</span>}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: 16, marginTop: 22 }}>
          <ChipGroup label="Account type" options={["Taxable", "IRA"] as const} value={settings.account} onChange={(v) => s.updateSettings({ account: v })} />
          <ChipGroup label="Marginal tax rate" options={["24%", "32%", "35%", "37%"] as const} value={settings.rate as "32%"} onChange={(v) => s.updateSettings({ rate: v })} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 26, flexWrap: "wrap" }}>
          <span role="link" tabIndex={0} onClick={() => router.push("/build")} onKeyDown={(e) => e.key === "Enter" && router.push("/build")} style={{ fontSize: 13, color: "#5A627A", cursor: "pointer" }}>← Back to the bridge</span>
          <button type="button" onClick={run} className={`pb-btn ${canRun ? "pb-btn-primary" : "pb-btn-disabled"}`} style={{ height: 50, padding: "0 24px" }} disabled={!canRun}>Run the AI pipeline <span className="pb-arrow">→</span></button>
        </div>
      </Glass>
    </main>
  );
}
