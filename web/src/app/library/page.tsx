"use client";

import { useState } from "react";
import { fmtNs, prettyId } from "@/lib/fmt";
import { UI_FAMILIES, type LibRow } from "@/lib/library";
import { fitScoreView, type FitScoreView } from "@/lib/pipeline";
import { aiLabel, aiStatus, aiTitle, type AiStatus } from "@/lib/ai";
import { useStore } from "@/lib/store";
import { Chip, Glass, Orb, Tag, Unavailable } from "@/components/pb";

const FAMS = ["All", ...UI_FAMILIES] as const;
const fmtGrid = (g: number[]) => (g.length ? g.map((v) => (Number.isInteger(v) ? v : +v.toFixed(4))).join(", ") : "none");
const cardHead = { fontSize: 13, fontWeight: 600, color: "#0F1626" } as const;

function UsePill({ n, label }: { n: number; label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", padding: "4px 10px", borderRadius: 999, fontSize: 11.5, fontWeight: 600, background: n ? "rgba(34,160,107,.12)" : "rgba(15,22,38,.06)", color: n ? "#15804F" : "#5A627A", whiteSpace: "nowrap" }}>
      {label ?? (n ? `In ${n} ${n === 1 ? "bridge" : "bridges"}` : "Available")}
    </span>
  );
}

function RealRow({ r, fitted, fitAi, running }: { r: LibRow; fitted: FitScoreView | null; fitAi: AiStatus; running: (number | null)[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pb-row-soft" style={{ borderRadius: 20 }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="pb-lib-row" style={{ display: "grid", gap: 18, alignItems: "center", padding: "16px 18px", cursor: "pointer", width: "100%", background: "transparent", border: 0, textAlign: "left", font: "inherit", color: "inherit" }}>
        <span className="pb-mono" style={{ fontSize: 11.5, color: "#5A627A" }}>{r.code}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.015em" }}>{r.name}</span>
            <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 500, background: "rgba(15,22,38,.06)", color: "#3C4458" }}>{r.division}</span>
            {r.uiFamilies.map((f) => <span key={f} style={{ fontSize: 11, color: "#5A627A" }}>{f}</span>)}
          </div>
          <div className="pb-pretty" style={{ fontSize: 12.5, color: "#3C4458", lineHeight: 1.45, marginTop: 4 }}>{r.role}</div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "#5A627A" }}>Parameters</div>
          <div className="pb-mono" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.4 }}>{r.params.length ? r.params.map((p) => p.name).join(", ") : "None"}</div>
        </div>
        <div style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          {running.length
            ? <span title={`hedgecore.Algo runs this family on ${running.length} backend bridge${running.length === 1 ? "" : "s"}. The approved proposal sent this fit.`}><Tag tone="live">Running, preset {running.map((n) => n ?? "custom").join(", ")}</Tag></span>
            : fitted ? <span title={`POST /pipeline/fit selected this family for your last selection. It runs after you approve a bridge for it. ${aiTitle(fitAi)} ${fitted.title}`}><Tag tone={fitAi.live ? "ai" : "neutral"}>{aiLabel(fitAi)}, not running</Tag></span> : <UsePill n={0} />}
              {fitted?.scored && <span className="pb-pretty" title={fitted.title} style={{ fontSize: 11, lineHeight: 1.35, color: fitted.tone === "positive" ? "#2B57D6" : "#5A627A" }}>{fitted.short} (in-sample)</span>}
          <span className="pb-mono" style={{ fontSize: 11, color: "#5A627A" }}>{r.presets.toLocaleString("en-US")} presets</span>
        </div>
      </button>
      {open && (
        <div style={{ padding: "0 18px 18px", display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))" }}>
          <div className="pb-sub" style={{ padding: "12px 14px" }}>
            <div style={cardHead}>Block chain</div>
            <div style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6 }}>{r.blocks.length ? r.blocks.map((b, i) => <span key={b.name + i}>{i ? ", then " : ""}<b style={{ fontWeight: 600 }}>{b.name}</b>{b.ui ? <span style={{ color: "#5A627A" }}> ({b.ui})</span> : null}</span>) : "None"}</div>
          </div>
          <div className="pb-sub" style={{ padding: "12px 14px" }}>
            <div style={cardHead}>Parameter grid, {r.presets.toLocaleString("en-US")} presets</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
              {r.params.map((p) => <div key={p.name} className="pb-mono" style={{ fontSize: 11.5 }}>{p.name}: {fmtGrid(p.grid)}</div>)}
              {!r.params.length && <span style={{ fontSize: 12, color: "#5A627A" }}>This family has no parameters to tune.</span>}
            </div>
          </div>
          <div className="pb-sub" style={{ padding: "12px 14px" }}>
            <div style={cardHead}>Fit</div>
            <div style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.5 }}>
              Events: {r.eventClasses.length ? r.eventClasses.map(prettyId).join(", ") : "none"}<br />
              Instruments: {r.instruments.length ? r.instruments.join(", ") : "none"}<br />
              Latency: {r.p50ns != null ? <>p50 {fmtNs(r.p50ns)}, p99 {fmtNs(r.p99ns)} <Tag tone="measured">benchmark</Tag></> : "no benchmark"}
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
    <main className="pb-page" style={{ maxWidth: 1180, paddingTop: 18, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pb-header">
        <div>
          <h2 className="pb-h2">Algorithm library</h2>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13, color: "#5A627A", marginTop: 6 }}>
            {lib ? `${lib.total.toLocaleString("en-US")} presets in ${lib.rows.length} families` : "The catalog is not loaded."}
            {lib && <Tag tone="measured" title="GET /library gives the compiled hedgecore catalog. The count is the value that catalog() gives.">compiled catalog</Tag>}
          </div>
          <div className="pb-lede">
            Each family is a fixed chain of compiled blocks with a parameter grid. A preset is one point in the grid. The fit selects only from these families, and it replays the presets on the history of the market.
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {FAMS.map((f) => <Chip key={f} small on={fam === f} onClick={() => setFam(f)}>{f}</Chip>)}
        </div>
      </div>
      <Glass style={{ padding: 8 }}>
        {lib && rows.map((r) => <RealRow key={r.id} r={r} fitted={r.id === fitted ? fittedView : null} fitAi={fitAi} running={running[r.id] ?? []} />)}
        {lib && rows.length === 0 && <div style={{ padding: "18px", fontSize: 13, color: "#5A627A" }}>No family in the catalog uses a {fam} block. Select a different filter.</div>}
        {s.library.status === "loading" && <div style={{ padding: 18, display: "flex", gap: 10, alignItems: "center", fontSize: 13, color: "#3C4458" }}><Orb state="working" size={20} />Reading the compiled catalog…</div>}
        {s.library.status === "error" && <Unavailable what="The algorithm library (GET /library)" error={s.library.error} onRetry={s.reloadLibrary} style={{ padding: 18 }} />}
      </Glass>
    </main>
  );
}
