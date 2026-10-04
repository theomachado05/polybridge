"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { brokerLabel, useStore } from "@/lib/store";
import { sessionPill } from "@/lib/closed";
import { accountPill } from "@/lib/risk";

const tabStyle = (on: boolean) => ({
  padding: "7px 14px", borderRadius: 6, cursor: "pointer", border: 0, font: "inherit",
  background: on ? "var(--ink)" : "transparent", color: on ? "#fff" : "var(--muted)",
});

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const s = useStore();
  const on = (p: string) => path === p || path.startsWith(p + "/");
  const build = on("/build") || on("/connect") || on("/pipeline");
  const step = !s.question ? 1 : !s.equity ? 2 : 3;
  const routeBridge = path.startsWith("/bridge/") && !s.bridges.some((b) => path.endsWith("/" + b.bridgeId)) ? 1 : 0;
  const n = s.bridges.length + routeBridge;
  const live = on("/bridge") || (on("/portfolio") && n > 0);
  const lib = s.library.status === "ok" && s.library.data ? `${s.library.data.total.toLocaleString("en-US")} presets` : "Preset library";
  const label = live ? (n ? `${n} active ${n === 1 ? "bridge" : "bridges"}` : "No active bridges")
    : on("/library") ? lib
    : on("/profile") ? `${s.settings.conns.length} connection${s.settings.conns.length === 1 ? "" : "s"}`
    : on("/pipeline") ? "Bridge setup"
    : on("/build") ? `Step ${step} of 3`
    : on("/connect") ? "Brokerage connection"
    : s.account.status === "ok" ? accountPill(s.account.data, s.session.data).text : brokerLabel(s.account).name;

  const goBridge = () => router.push("/bridge");
  const profile = on("/profile");
  const pill = sessionPill(s.session.data);

  return (
    <div style={{ position: "relative", zIndex: 2, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "18px clamp(16px,4vw,40px)", flexWrap: "wrap", borderBottom: "1px solid var(--divider)" }}>
      <Link href="/" style={{ display: "flex", alignItems: "center", height: 40, color: "var(--ink)" }}>
        <span className="pb-serif" style={{ fontWeight: 500, fontSize: 22, letterSpacing: "-.01em" }}>PolyBridge</span>
      </Link>
      <nav className="pb-navpill" style={{ display: "flex", alignItems: "center", gap: 2, height: 40, padding: "0 4px", borderRadius: 8, fontSize: 13, fontWeight: 500 }}>
        <Link href="/build" style={tabStyle(build)}>Build</Link>
        <button type="button" onClick={goBridge} style={tabStyle(on("/bridge"))}>Bridge</button>
        <Link href="/library" style={tabStyle(on("/library"))}>Library</Link>
        <Link href="/portfolio" style={tabStyle(on("/portfolio"))}>Portfolio</Link>
      </nav>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {pill && (
          <div title={pill.title} data-testid="session-pill" style={{ display: "flex", alignItems: "center", gap: 6, height: 40, padding: "0 4px", color: "var(--ink)", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap" }}>
            <span style={{ color: "var(--muted)" }}>NYSE</span>{pill.text}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", height: 40, padding: "0 14px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--ink)", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap" }}>
          {label}
        </div>
        <Link href="/profile" title="Profile" aria-label="Profile" aria-current={profile ? "page" : undefined} style={{ width: 40, height: 40, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", background: profile ? "var(--ink)" : "var(--surface)", color: profile ? "#fff" : "var(--ink)", border: "1px solid var(--border)" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" /></svg>
        </Link>
      </div>
    </div>
  );
}
