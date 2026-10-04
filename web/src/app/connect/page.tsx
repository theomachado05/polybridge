"use client";

import { useRouter } from "next/navigation";
import { BROKERS, ROUTABLE_BROKER } from "@/lib/brokers";
import { fmtMoney } from "@/lib/fmt";
import { brokerLabel, useStore } from "@/lib/store";
import { REPLAY_SANDBOX_SENTENCE } from "@/lib/realBridge";
import { FIT_PATH } from "@/lib/voiceDrive";
import { Btn, ChipGroup, LogoTile, Tag, Unavailable } from "@/components/pb";

export default function Connect() {
  const router = useRouter();
  const s = useStore();
  const { settings, account } = s;
  const eq = s.equity;
  const acct = brokerLabel(account);
  const canRun = !!settings.broker && !!s.question && !!eq && !!s.inst;
  const pick = (id: string) => s.updateSettings({ broker: id, conns: settings.conns.includes(id) ? settings.conns : [...settings.conns, id] });
  const position = !eq ? "" : eq.held ? `${eq.held.toLocaleString("en-US")} sh` : "no position. The hedge uses a 500 sh notional to calculate its size.";
  const chosen = BROKERS.find((b) => b.id === settings.broker) ?? null;
  const connected = !!chosen && chosen.id === ROUTABLE_BROKER && acct.tone === "paper";
  const pos = eq ? `. ${eq.t}: ${position}` : "";
  const status = !chosen
    ? "Select the broker that holds your shares."
    : connected
      ? `Connected to Webull paper${pos}`
      : `${chosen.name} is saved as a preference only (no live connection). Orders go to ${acct.tone === "demo" ? "no account that the app can read" : "the " + acct.name.toLowerCase()}${pos}`;

  const run = () => {
    if (!canRun) return;
    router.push(FIT_PATH);
  };

  if (!s.question || !eq || !s.inst) {
    return (
      <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: 96 }}>
        <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: "var(--sp-4)", alignItems: "flex-start" }}>
          <h1 className="pb-h2 pb-pretty" style={{ marginTop: 0 }}>Select a market, a stock, and a hedge first.</h1>
          <p className="pb-body" style={{ margin: 0, fontSize: "var(--fs-16)" }}>This step uses the position that you select on Build to calculate the size of each order.</p>
          <Btn href="/build" style={{ marginTop: "var(--sp-2)" }}>Open Build</Btn>
        </div>
      </main>
    );
  }

  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: 96 }}>
      <div style={{ maxWidth: 720 }}>
        <h1 className="pb-h2 pb-balance" style={{ marginTop: 0 }}>Which broker holds {eq.t}?</h1>
        <p className="pb-lede pb-pretty">PolyBridge calculates the size of each order from your position. The account below receives the orders.</p>

        <div role="group" aria-label="Broker" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--sp-3)", marginTop: "var(--sp-6)" }}>
          {BROKERS.map((b) => {
            const sel = settings.broker === b.id;
            return (
              <button key={b.id} type="button" aria-pressed={sel} className={sel ? undefined : "pb-card-hover"} onClick={() => pick(b.id)} style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)", padding: "var(--sp-4)", borderRadius: "var(--radius)", cursor: "pointer", textAlign: "left", background: sel ? "var(--accent-tint)" : "var(--surface)", border: `1px solid ${sel ? "var(--accent)" : "var(--border)"}`, boxShadow: sel ? "inset 0 0 0 1px var(--accent)" : "none", transition: "border-color var(--dur) var(--ease), background-color var(--dur) var(--ease)" }}>
                <LogoTile logo={b.logo} />
                <div>
                  <div style={{ fontSize: "var(--fs-14)", fontWeight: 600, color: "var(--ink)" }}>{b.name}</div>
                  <div style={{ fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: 2, lineHeight: 1.45 }}>{b.sub}</div>
                </div>
              </button>
            );
          })}
        </div>

        <div className="pb-sub" style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)", marginTop: "var(--sp-4)", padding: "var(--sp-3) var(--sp-4)" }}>
          <span className="pb-body pb-pretty" style={{ color: "var(--ink)" }}>{status}</span>
          {chosen && !connected && <span style={{ marginLeft: "auto", flex: "none" }}><Tag tone="caution" title="Only the simulator and Webull paper accept orders. The account data shows which one is active.">preference only</Tag></span>}
        </div>
        <div className="pb-small" style={{ display: "flex", alignItems: "center", gap: "var(--sp-2) var(--sp-3)", marginTop: "var(--sp-3)", flexWrap: "wrap" }}>
          <span>Orders go to</span>
          <Tag tone={acct.tone} title={acct.tone === "demo" ? "The app cannot read the account." : "From the account data"}>{acct.name}</Tag>
          {account.status === "ok" && account.data && <span className="pb-num">Cash {fmtMoney(account.data.cash)}, buying power {fmtMoney(account.data.buying_power)}</span>}
          {account.status === "error" && <Unavailable what="The account" error={account.error} onRetry={s.refreshAccount} compact />}
          {acct.tone === "sim" && settings.broker === "webull" && <span>Webull paper becomes active when its API keys are set. PolyBridge does not use real money.</span>}
          <span style={{ flexBasis: "100%", color: "var(--faint)", fontSize: "var(--fs-12)" }}>{REPLAY_SANDBOX_SENTENCE.replace("its orders fill", "the engine's orders fill")}</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: "var(--sp-5)", marginTop: "var(--sp-6)", paddingTop: "var(--sp-5)", borderTop: "1px solid var(--border)" }}>
          <ChipGroup label="Account type" options={["Taxable", "IRA"] as const} value={settings.account} onChange={(v) => s.updateSettings({ account: v })} />
          <ChipGroup label="Marginal tax rate" options={["24%", "32%", "35%", "37%"] as const} value={settings.rate as "32%"} onChange={(v) => s.updateSettings({ rate: v })} />
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--sp-3)", marginTop: "var(--sp-7)", paddingTop: "var(--sp-5)", borderTop: "1px solid var(--border)", flexWrap: "wrap" }}>
          <Btn variant="ghost" onClick={() => router.push("/build")}>Return to Build</Btn>
          <Btn kind={canRun ? "primary" : "disabled"} onClick={run}>{s.ai.live ? "Start AI pipeline" : "Start fit pipeline"}</Btn>
        </div>
      </div>
    </main>
  );
}
