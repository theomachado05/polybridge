"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { brokerLabel, defaultPick, useStore } from "@/lib/store";
import { sessionPill } from "@/lib/closed";

const tabStyle = (on: boolean) => ({
  padding: "8px 16px", borderRadius: 999, cursor: "pointer",
  background: on ? "#fff" : "transparent", color: on ? "#0F1626" : "#5A627A", boxShadow: on ? "0 2px 8px rgba(20,30,60,.12)" : "none",
});

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const s = useStore();
  const on = (p: string) => path === p || path.startsWith(p + "/");
  const build = on("/build") || on("/connect") || on("/pipeline");
  const step = !s.question ? 1 : !s.equity ? 2 : 3;
  // A backend bridge opened by URL (/bridge/<id>) counts even before it is in the store.
  const routeBridge = path.startsWith("/bridge/") && !s.bridges.some((b) => b.kind === "live" && path.endsWith("/" + b.bridgeId)) ? 1 : 0;
  const n = s.bridges.length + routeBridge, anyLive = routeBridge > 0 || s.bridges.some((b) => b.kind === "live");
  const live = on("/bridge") || (on("/portfolio") && n > 0);
  const lib = s.library.status === "ok" && s.library.data ? `${s.library.data.total.toLocaleString("en-US")} presets` : "Algo library";
  const dot = live ? "#4ADE80" : on("/pipeline") ? "#FBBF24" : "#9A7BFF";
  const label = live ? `${anyLive ? "Running" : "Demo"} · ${n} ${n === 1 ? "bridge" : "bridges"}`
    : on("/library") ? lib
    : on("/profile") ? `${s.settings.conns.length} connection${s.settings.conns.length === 1 ? "" : "s"}`
    : on("/pipeline") ? "Composing bridge"
    : on("/build") ? `Step ${step} of 3`
    : on("/connect") ? "Connect brokerage"
    : brokerLabel(s.account).name;

  const goBridge = () => {
    if (!s.bridges.length) {
      const d = defaultPick();
      s.addDemoBridge(s.question ?? d.q, s.equity ?? d.eq, s.inst ?? "shares");
    }
    router.push("/bridge");
  };
  const profile = on("/profile");
  const pill = sessionPill(s.session.data);

  return (
    <div style={{ position: "relative", zIndex: 2, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "22px clamp(16px,4vw,40px)", flexWrap: "wrap" }}>
      <Link href="/" className="pb-navpill" style={{ display: "flex", alignItems: "center", gap: 10, height: 44, padding: "0 18px 0 14px", borderRadius: 999, background: "rgba(255,255,255,.55)", color: "#0F1626" }}>
        <span style={{ width: 18, height: 18, borderRadius: "50%", background: "linear-gradient(135deg,#3B6CF6,#9A7BFF)" }} />
        <span className="pb-serif" style={{ fontWeight: 500, fontSize: 19, letterSpacing: "-.01em" }}>PolyBridge</span>
      </Link>
      <nav className="pb-navpill" style={{ display: "flex", alignItems: "center", gap: 4, height: 44, padding: "0 5px", borderRadius: 999, background: "rgba(255,255,255,.5)", fontSize: 13, fontWeight: 500 }}>
        <Link href="/build" style={tabStyle(build)}>Build</Link>
        <span role="link" tabIndex={0} onClick={goBridge} onKeyDown={(e) => e.key === "Enter" && goBridge()} style={tabStyle(on("/bridge"))}>Bridge</span>
        <Link href="/library" style={tabStyle(on("/library"))}>Library</Link>
        <Link href="/portfolio" style={tabStyle(on("/portfolio"))}>Portfolio</Link>
      </nav>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {pill && (
          <div className="pb-navpill" title={pill.title} data-testid="session-pill" style={{ display: "flex", alignItems: "center", gap: 8, height: 44, padding: "0 14px", borderRadius: 999, background: "rgba(255,255,255,.55)", color: "#0F1626", fontSize: 12.5, fontWeight: 500, whiteSpace: "nowrap" }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: pill.dot }} />
            <span className="pb-mono" style={{ fontSize: 10.5, letterSpacing: ".08em", color: "#5A627A" }}>NYSE</span>{pill.text}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 10, height: 44, padding: "0 18px", borderRadius: 999, background: "rgba(15,22,38,.9)", color: "#fff", boxShadow: "0 8px 30px rgba(15,22,38,.25)", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, animation: "pb-pulse 1.6s ease-in-out infinite" }} />{label}
        </div>
        <Link href="/profile" title="Profile" className="pb-navpill" style={{ width: 44, height: 44, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 600, letterSpacing: ".02em", background: profile ? "#0F1626" : "rgba(255,255,255,.55)", color: profile ? "#fff" : "#0F1626", border: "1px solid rgba(255,255,255,.85)" }}>JD</Link>
      </div>
    </div>
  );
}
