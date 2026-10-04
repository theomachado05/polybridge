"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { brokerLabel, useStore } from "@/lib/store";
import { sessionPill } from "@/lib/closed";
import { accountPill } from "@/lib/risk";

const cur = (on: boolean) => (on ? "page" as const : undefined);

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
    <header className="pb-nav">
      <div className="pb-nav-inner">
        <Link href="/" className="pb-wordmark">PolyBridge</Link>
        <nav className="pb-navtabs" aria-label="Main">
          <Link href="/build" className="pb-navtab" aria-current={cur(build)}>Build</Link>
          <button type="button" onClick={goBridge} className="pb-navtab" aria-current={cur(on("/bridge"))}>Bridge</button>
          <Link href="/library" className="pb-navtab" aria-current={cur(on("/library"))}>Library</Link>
          <Link href="/portfolio" className="pb-navtab" aria-current={cur(on("/portfolio"))}>Portfolio</Link>
        </nav>
        <div className="pb-navmeta">
          {pill && (
            <span title={pill.title} data-testid="session-pill">
              <span style={{ color: "var(--faint)" }}>NYSE </span><span style={{ color: "var(--ink)" }}>{pill.text}</span>
            </span>
          )}
          <span className="pb-navmeta-text pb-ellipsis" style={{ maxWidth: 320 }}>{label}</span>
          <Link href="/profile" title="Profile" aria-label="Profile" aria-current={cur(profile)} className="pb-iconbtn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" /></svg>
          </Link>
        </div>
      </div>
    </header>
  );
}
