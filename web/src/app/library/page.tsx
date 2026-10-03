"use client";

import { useState } from "react";
import { ALGOS, IN_CHAIN } from "@/lib/demo";
import { fmtNs, prettyId } from "@/lib/fmt";
import { UI_FAMILIES, type LibRow } from "@/lib/library";
import { fitScoreView, type FitScoreView } from "@/lib/pipeline";
import { useStore } from "@/lib/store";
import { Chip, DemoTag, Glass, Tag } from "@/components/pb";

const FAMS = ["All", ...UI_FAMILIES] as const;
const fmtGrid = (g: number[]) => (g.length ? g.map((v) => (Number.isInteger(v) ? v : +v.toFixed(4))).join(" · ") : "—");

function UsePill({ n, label }: { n: number; label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", borderRadius: 999, fontSize: 11.5, fontWeight: 600, background: n ? "rgba(34,160,107,.12)" : "rgba(15,22,38,.06)", color: n ? "#15804F" : "#5A627A", whiteSpace: "nowrap" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: n ? "#22A06B" : "rgba(15,22,38,.3)" }} />
      {label ?? (n ? `In ${n} ${n === 1 ? "bridge" : "bridges"}` : "Available")}
    </span>
  );
}

function RealRow({ r, fitted, running }: { r: LibRow; fitted: FitScoreView | null; running: (number | null)[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pb-row-soft" style={{ borderRadius: 20, transition: "background .2s ease" }}>
      <div role="button" tabIndex={0} aria-expanded={open} onClick={() => setOpen((o) => !o)} onKeyDown={(e) => e.key === "Enter" && setOpen((o) => !o)} className="pb-lib-row" style={{ display: "grid", gap: 18, alignItems: "center", padding: "16px 18px", cursor: "pointer" }}>
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
          <div style={{ fontSize: 11, color: "#5A627A" }}>Tunes</div>
          <div className="pb-mono" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.4 }}>{r.params.length ? r.params.map((p) => p.name).join(" · ") : "—"}</div>
        </div>
        <div style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          {running.length
            ? <span title={`hedgecore.Algo runs this family on ${running.length} live bridge${running.length === 1 ? "" : "s"} (the AI fit sent with the approved proposal)`}><Tag tone="ai">Running · preset {running.map((n) => n ?? "custom").join(", ")}</Tag></span>
            : fitted ? <span title={`Picked by POST /pipeline/fit for your last pick; it runs once you approve a bridge for it. ${fitted.title}`}><Tag tone="ai">AI fit · not running yet</Tag></span> : <UsePill n={0} />}
          {/* What the signal adds over a static hedge (neutral, never green, when it adds nothing). */}
          {fitted?.scored && <span className="pb-pretty" title={fitted.title} style={{ fontSize: 11, lineHeight: 1.35, color: fitted.tone === "positive" ? "#2B57D6" : "#5A627A" }}>{fitted.short} (in-sample)</span>}
          <span className="pb-mono" style={{ fontSize: 11, color: "#5A627A" }}>{r.presets.toLocaleString("en-US")} presets</span>
        </div>
      </div>
      {open && (
        <div style={{ padding: "0 18px 18px", display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", animation: "pb-in .3s ease-out" }}>
          <div className="pb-sub" style={{ padding: "12px 14px" }}>
            <div className="pb-label">BLOCK CHAIN</div>
            <div style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6 }}>{r.blocks.length ? r.blocks.map((b, i) => <span key={b.name + i}>{i ? " → " : ""}<b style={{ fontWeight: 600 }}>{b.name}</b>{b.ui ? <span style={{ color: "#5A627A" }}> ({b.ui})</span> : null}</span>) : "—"}</div>
          </div>
          <div className="pb-sub" style={{ padding: "12px 14px" }}>
            <div className="pb-label">PARAMETER GRID · {r.presets.toLocaleString("en-US")} PRESETS</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
              {r.params.map((p) => <div key={p.name} className="pb-mono" style={{ fontSize: 11.5 }}>{p.name}: {fmtGrid(p.grid)}</div>)}
              {!r.params.length && <span style={{ fontSize: 12, color: "#5A627A" }}>No tunable parameters.</span>}
            </div>
          </div>
          <div className="pb-sub" style={{ padding: "12px 14px" }}>
            <div className="pb-label">FIT</div>
            <div style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.5 }}>
              Events: {r.eventClasses.length ? r.eventClasses.map(prettyId).join(", ") : "—"}<br />
              Instruments: {r.instruments.length ? r.instruments.join(", ") : "—"}<br />
              Latency: {r.p50ns != null ? <>p50 {fmtNs(r.p50ns)} · p99 {fmtNs(r.p99ns)} <Tag tone="measured">benchmark</Tag></> : "not benchmarked"}
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
  // Live bridges started with an AI fit run that family and preset (hedgecore.Algo); those families are marked as
  // running. The latest AI fit without a bridge is marked separately, as a pick that is not running yet.
  const fitData = s.fit?.status === "ok" ? s.fit.data ?? null : null;
  const fitted = fitData?.family ?? null;
  const fittedView = fitData?.family ? fitScoreView(fitData) : null;
  const running: Record<string, (number | null)[]> = {};
  for (const b of s.bridges) if (b.kind === "live" && b.fit) (running[b.fit.family] ??= []).push(b.fit.preset_index);
  const demoBridges = s.bridges.filter((b) => b.kind === "demo").length;
  const rows = lib ? lib.rows.filter((r) => fam === "All" || r.uiFamilies.includes(fam)) : [];
  const demoRows = ALGOS.filter((a) => fam === "All" || a.fam === fam);

  return (
    <main className="pb-page" style={{ maxWidth: 1180, paddingTop: 18, paddingBottom: 60, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pb-header">
        <div>
          <div className="pb-label" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {lib ? `LIBRARY · ${lib.total.toLocaleString("en-US")} PRESETS · ${lib.rows.length} FAMILIES` : "LIBRARY · SAMPLE ALGORITHMS"}
            {lib ? <Tag tone="measured" title="GET /library — the compiled hedgecore catalog; the count is what catalog() reports">compiled catalog</Tag> : <DemoTag what="sample list" title={`GET /library failed (${s.library.error ?? "loading"}); showing the prototype's 15 sample algorithms.`} />}
          </div>
          <h2 className="pb-h2">Composed per event, tuned per tick.</h2>
          <div className="pb-lede">
            {lib
              ? "Every family is a fixed chain of compiled blocks with a parameter grid; a preset is one grid point. The AI only picks from what is compiled here."
              : "Every bridge chains a handful of these. We show what each one does and which parameters it tunes — the logic stays ours."}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {FAMS.map((f) => <Chip key={f} small on={fam === f} onClick={() => setFam(f)}>{f}</Chip>)}
        </div>
      </div>
      <Glass style={{ padding: 8 }}>
        {lib && rows.map((r) => <RealRow key={r.id} r={r} fitted={r.id === fitted ? fittedView : null} running={running[r.id] ?? []} />)}
        {lib && rows.length === 0 && <div style={{ padding: "18px", fontSize: 13, color: "#5A627A" }}>No family in the catalog uses a {fam} block yet.</div>}
        {!lib && demoRows.map((a) => {
          const n = IN_CHAIN.has(a.name) ? demoBridges : 0;
          return (
            <div key={a.id} className="pb-row-soft pb-lib-row" style={{ display: "grid", gap: 18, alignItems: "center", padding: "16px 18px", borderRadius: 20 }}>
              <span className="pb-mono" style={{ fontSize: 11.5, color: "#5A627A" }}>{a.id}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.015em" }}>{a.name}</span>
                  <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 500, background: "rgba(15,22,38,.06)", color: "#3C4458" }}>{a.fam}</span>
                </div>
                <div className="pb-pretty" style={{ fontSize: 12.5, color: "#3C4458", lineHeight: 1.45, marginTop: 4 }}>{a.role}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "#5A627A" }}>Tunes</div>
                <div className="pb-mono" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.4 }}>{a.tunes}</div>
              </div>
              <div style={{ textAlign: "right" }}><UsePill n={n} /></div>
            </div>
          );
        })}
      </Glass>
    </main>
  );
}
