"use client";

import { useState } from "react";
import { fmtNs, prettyId } from "@/lib/fmt";
import { UI_FAMILIES, type LibRow } from "@/lib/library";
import { fitScoreView, type FitScoreView } from "@/lib/pipeline";
import { aiLabel, aiStatus, aiTitle, type AiStatus } from "@/lib/ai";
import { useStore } from "@/lib/store";
import { Chip, Orb, Tag, Unavailable } from "@/components/pb";

const FAMS = ["All", ...UI_FAMILIES] as const;
const fmtGrid = (g: number[]) => (g.length ? g.map((v) => (Number.isInteger(v) ? v : +v.toFixed(4))).join(", ") : "none");
const cardHead = { fontSize: "var(--fs-13)", fontWeight: 600, color: "var(--ink)" } as const;

function UsePill({ n, label }: { n: number; label?: string }) {
  return <span className={`pb-tag ${n ? "pb-tag-up" : "pb-tag-neutral"}`}>{label ?? (n ? `In ${n} ${n === 1 ? "bridge" : "bridges"}` : "Available")}</span>;
}

function RealRow({ r, fitted, fitAi, running }: { r: LibRow; fitted: FitScoreView | null; fitAi: AiStatus; running: (number | null)[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="pb-lib-row pb-row" style={{ display: "grid", gap: "var(--sp-5)", alignItems: "center", padding: "var(--sp-4) var(--sp-5)", cursor: "pointer", width: "100%", background: open ? "var(--surface-2)" : "transparent", border: 0, textAlign: "left", font: "inherit", color: "inherit" }}>
        <span className="pb-code" style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>{r.code}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "var(--sp-2) var(--sp-3)", flexWrap: "wrap" }}>
            <span className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>{r.name}</span>
            <span style={{ fontSize: "var(--fs-12)", fontWeight: 500, color: "var(--text-2)" }}>{r.division}</span>
            {r.uiFamilies.map((f) => <span key={f} style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>{f}</span>)}
          </div>
          <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-1)" }}>{r.role}</div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div className="pb-label">Parameters</div>
          <div className="pb-small" style={{ marginTop: 2, color: "var(--ink)", lineHeight: 1.4 }}>{r.params.length ? r.params.map((p) => p.name).join(", ") : "None"}</div>
        </div>
        <div style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "var(--sp-1)" }}>
          {running.length
            ? <span title={`hedgecore.Algo runs this family on ${running.length} backend bridge${running.length === 1 ? "" : "s"}. The approved proposal sent this fit.`}><Tag tone="live">Running, preset {running.map((n) => n ?? "custom").join(", ")}</Tag></span>
            : fitted ? <span title={`POST /pipeline/fit selected this family for your last selection. It runs after you approve a bridge for it. ${aiTitle(fitAi)} ${fitted.title}`}><Tag tone={fitAi.live ? "ai" : "neutral"}>{aiLabel(fitAi)}, not running</Tag></span> : <UsePill n={0} />}
          {fitted?.scored && <span className="pb-pretty pb-num" title={fitted.title} style={{ fontSize: "var(--fs-12)", lineHeight: 1.35, color: fitted.tone === "positive" ? "var(--up)" : "var(--text-2)" }}>{fitted.short} (in-sample)</span>}
          <span className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>{r.presets.toLocaleString("en-US")} presets</span>
        </div>
      </button>
      {open && (
        <div className="pb-small" style={{ padding: "var(--sp-2) var(--sp-5) var(--sp-5)", background: "var(--surface-2)", display: "grid", gap: "var(--sp-4) var(--sp-6)", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", color: "var(--ink)" }}>
          <div>
            <div style={cardHead}>Block chain</div>
            <div style={{ marginTop: "var(--sp-1)", lineHeight: 1.6 }}>{r.blocks.length ? r.blocks.map((b, i) => <span key={b.name + i}>{i ? ", then " : ""}<b style={{ fontWeight: 600 }}>{b.name}</b>{b.ui ? <span style={{ color: "var(--text-2)" }}> ({b.ui})</span> : null}</span>) : "None"}</div>
          </div>
          <div>
            <div style={cardHead}>Parameter grid, <span className="pb-num">{r.presets.toLocaleString("en-US")}</span> presets</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: "var(--sp-1)" }}>
              {r.params.map((p) => <div key={p.name} className="pb-num">{p.name}: {fmtGrid(p.grid)}</div>)}
              {!r.params.length && <span style={{ color: "var(--text-2)" }}>This family has no parameters to tune.</span>}
            </div>
          </div>
          <div>
            <div style={cardHead}>Fit</div>
            <div style={{ marginTop: "var(--sp-1)", lineHeight: 1.6 }}>
              Events: {r.eventClasses.length ? r.eventClasses.map(prettyId).join(", ") : "none"}<br />
              Instruments: {r.instruments.length ? r.instruments.join(", ") : "none"}<br />
              Latency: {r.p50ns != null ? <><span className="pb-num">p50 {fmtNs(r.p50ns)}, p99 {fmtNs(r.p99ns)}</span> <Tag tone="measured">benchmark</Tag></> : "no benchmark"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Library() {
  const s = useStore();
  const [fam, setFam] = useState<(typeof FAMS)[number]>("All");
  const lib = s.library.status === "ok" ? s.library.data : null;
  // Bridges started with a fit run that family and preset (hedgecore.Algo); those families are marked as
  // running. The latest fit without a bridge is marked separately, as a pick that is not running yet.
  const fitData = s.fit?.status === "ok" ? s.fit.data ?? null : null;
  const fitted = fitData?.family ?? null;
  const fittedView = fitData?.family ? fitScoreView(fitData) : null;
  const fitAi = aiStatus(fitData);
  // Only backend bridges this session opened count; a family is "running" when one of them runs it.
  const running: Record<string, (number | null)[]> = {};
  for (const b of s.bridges) if (b.fit) (running[b.fit.family] ??= []).push(b.fit.preset_index);
  const rows = lib ? lib.rows.filter((r) => fam === "All" || r.uiFamilies.includes(fam)) : [];

  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: "var(--sp-8)", display: "flex", flexDirection: "column", gap: "var(--sp-5)" }}>
      <div className="pb-header">
        <div>
          <h2 className="pb-h2" style={{ marginTop: 0 }}>Algorithm library</h2>
          <div className="pb-small" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap", marginTop: "var(--sp-2)" }}>
            <span className="pb-num">{lib ? `${lib.total.toLocaleString("en-US")} presets in ${lib.rows.length} families` : "The catalog is not loaded."}</span>
            {lib && <Tag tone="measured" title="GET /library gives the compiled hedgecore catalog. The count is the value that catalog() gives.">compiled catalog</Tag>}
          </div>
          <div className="pb-lede pb-pretty">
            Each family is a fixed chain of compiled blocks with a parameter grid. A preset is one point in the grid. The fit selects only from these families, and it replays the presets on the history of the market.
          </div>
        </div>
        <div style={{ display: "flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
          {FAMS.map((f) => <Chip key={f} small on={fam === f} onClick={() => setFam(f)}>{f}</Chip>)}
        </div>
      </div>
      <div className="pb-card pb-list" style={{ overflow: "hidden" }}>
        {lib && rows.map((r) => <RealRow key={r.id} r={r} fitted={r.id === fitted ? fittedView : null} fitAi={fitAi} running={running[r.id] ?? []} />)}
        {lib && rows.length === 0 && <div className="pb-list-note">No family in the catalog uses a {fam} block. Select a different filter.</div>}
        {s.library.status === "loading" && <div className="pb-list-note" style={{ display: "flex", gap: "var(--sp-3)", alignItems: "center" }}><Orb state="working" size={20} />Reading the compiled catalog…</div>}
        {s.library.status === "error" && <Unavailable what="The algorithm library (GET /library)" error={s.library.error} onRetry={s.reloadLibrary} style={{ padding: "var(--sp-4) var(--sp-5)" }} />}
      </div>
      {lib && lib.micro.length > 0 && (
        <div className="pb-card pb-list" data-testid="library-micro" style={{ overflow: "hidden" }}>
          <div className="pb-list-note">
            <span style={{ fontWeight: 500, color: "var(--ink)" }}>Micro families · {lib.microTotal} presets</span> · their own tick types (two ladder books; a ticket and its options reference), outside the {lib.rows.length} families above. They decide the ladder and ticket boards. Status words are the catalog&apos;s.
          </div>
          {lib.micro.map((m) => (
            <div key={m.id} className="pb-list-note" style={{ borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
                <span className="pb-num" style={{ fontWeight: 500, color: "var(--ink)" }}>{m.id}</span>
                <Tag tone={m.status === "lead" ? "measured" : "caution"} title="Status word from the compiled catalog">{m.status}</Tag>
                <span className="pb-small pb-num">{m.division} · {m.presets} preset{m.presets === 1 ? "" : "s"}</span>
              </div>
              <div className="pb-small pb-pretty">{m.idea}</div>
              <div className="pb-small pb-num">{m.params.filter((p) => p.grid.length > 0).map((p) => `${p.name} ${p.grid.join("/")}`).join(" · ")}</div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
