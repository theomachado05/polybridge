"use client";

import { useRouter } from "next/navigation";
import { BROKERS, ROUTABLE_BROKER } from "@/lib/brokers";
import { fmtMoney } from "@/lib/fmt";
import { brokerLabel, useStore } from "@/lib/store";
import { REPLAY_SANDBOX_SENTENCE } from "@/lib/realBridge";
import { Btn, ChipGroup, Glass, Label, LogoTile, Orb, Tag, Unavailable } from "@/components/pb";

export default function Connect() {
  const router = useRouter();
  const s = useStore();
  const { settings, account } = s;
  const eq = s.equity;
  const acct = brokerLabel(account);
  const canRun = !!settings.broker && !!s.question && !!eq && !!s.inst;
  const pick = (id: string) => s.updateSettings({ broker: id, conns: settings.conns.includes(id) ? settings.conns : [...settings.conns, id] });
  const position = !eq ? "" : eq.held ? `${eq.held.toLocaleString("en-US")} sh` : "no position — hedge will size to a 500 sh notional";
  // Only the broker GET /account reports is "connected"; every other card is a saved preference.
  const chosen = BROKERS.find((b) => b.id === settings.broker) ?? null;
  const connected = !!chosen && chosen.id === ROUTABLE_BROKER && acct.tone === "paper";
  const pos = eq ? ` · ${eq.t}: ${position}` : "";
  const status = !chosen
    ? "Choose where your shares live."
    : connected
      ? `Connected · Webull paper${pos}`
      : `${chosen.name} saved as a preference only (no live connection) · orders route to ${acct.tone === "demo" ? "no readable account" : "the " + acct.name.toLowerCase()}${pos}`;

  const run = () => {
    if (!canRun) return;
    router.push("/pipeline");
  };

  if (!s.question || !eq || !s.inst) {
    return (
      <main className="pb-page" style={{ maxWidth: 760, paddingTop: 30, paddingBottom: 80 }}>
        <Glass style={{ padding: "28px 30px", borderRadius: 30, display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-start" }}>
          <Label rule>NOTHING TO CONNECT YET</Label>
          <h2 className="pb-serif" style={{ margin: 0, fontSize: 32, letterSpacing: "-.015em", fontWeight: 400 }}>Pick a market, a stock and a hedge first.</h2>
          <p style={{ margin: 0, fontSize: 14, color: "#3C4458" }}>The brokerage step sizes orders to the position you choose on Build.</p>
          <Btn href="/build" arrow>Go to Build</Btn>
        </Glass>
      </main>
    );
  }

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
          {chosen && !connected && <span style={{ marginLeft: "auto", flex: "none" }}><Tag tone="caution" title="Only the simulator and Webull paper take orders; GET /account names the one that does.">preference only</Tag></span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, padding: "0 4px", fontSize: 12, color: "#5A627A", flexWrap: "wrap" }}>
          <span>Orders route to</span>
          <Tag tone={acct.tone} title={acct.tone === "demo" ? "GET /account could not be read" : "From GET /account"}>{acct.name}</Tag>
          {account.status === "ok" && account.data && <span className="pb-mono">cash {fmtMoney(account.data.cash)} · buying power {fmtMoney(account.data.buying_power)}</span>}
          {account.status === "error" && <Unavailable what="The account" error={account.error} onRetry={s.refreshAccount} compact />}
          {acct.tone === "sim" && settings.broker === "webull" && <span>Webull paper takes over when its API keys are set; real money is out of scope.</span>}
          <span style={{ flexBasis: "100%" }}>{REPLAY_SANDBOX_SENTENCE.replace("its orders fill", "the engine's orders fill")}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: 16, marginTop: 22 }}>
          <ChipGroup label="Account type" options={["Taxable", "IRA"] as const} value={settings.account} onChange={(v) => s.updateSettings({ account: v })} />
          <ChipGroup label="Marginal tax rate" options={["24%", "32%", "35%", "37%"] as const} value={settings.rate as "32%"} onChange={(v) => s.updateSettings({ rate: v })} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 26, flexWrap: "wrap" }}>
          <span role="link" tabIndex={0} onClick={() => router.push("/build")} onKeyDown={(e) => e.key === "Enter" && router.push("/build")} style={{ fontSize: 13, color: "#5A627A", cursor: "pointer" }}>← Back to the bridge</span>
          <button type="button" onClick={run} className={`pb-btn ${canRun ? "pb-btn-primary" : "pb-btn-disabled"}`} style={{ height: 50, padding: "0 24px" }} disabled={!canRun}>{s.ai.live ? "Run the AI pipeline" : "Run the fit pipeline"} <span className="pb-arrow">→</span></button>
        </div>
      </Glass>
    </main>
  );
}
