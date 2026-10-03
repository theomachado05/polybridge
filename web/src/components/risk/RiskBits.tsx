// Risk-control pieces shared by Build, Pipeline, Bridge and Portfolio: badges, the evidence gate with its explicit
// acknowledgement, the liquidity & capacity card and budget meters. Presentational only; the numbers and verdicts come
// from src/lib/risk.ts, which mirrors what the backend enforces.
import type { CSSProperties, ReactNode } from "react";
import type { Badge, CapacityRow, CapacityView, EvidenceGateView, Meter } from "@/lib/risk";
import { Label, Tag } from "@/components/pb";

export const BadgeTag = ({ b }: { b: Badge }) => <Tag tone={b.tone} title={b.title}>{b.text}</Tag>;

export const subBox: CSSProperties = { marginTop: 14, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)" };
const k = { fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: ".04em", color: "#5A627A" } as const;

export function MetricGrid({ rows, min = 150 }: { rows: CapacityRow[]; min?: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${min}px),1fr))`, gap: "12px 16px", marginTop: 12 }}>
      {rows.map((r) => (
        <div key={r.k} style={{ minWidth: 0 }}>
          <div style={k}>{r.k}</div>
          <div className="pb-tab" style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.02em", marginTop: 2, color: r.warn ? "#9A4A00" : "#0F1626" }}>{r.v}</div>
          {r.sub && <div className="pb-pretty" style={{ fontSize: 11, color: "#5A627A", lineHeight: 1.35, marginTop: 1 }}>{r.sub}</div>}
        </div>
      ))}
    </div>
  );
}

/** Evidence badge, the backend's reason, and (when the market is not validated) the acknowledgement checkbox the
 *  Approve button waits for. */
export function EvidenceGateBox({ gate, ack, onAck, copy, loading, acknowledged, testId = "evidence-gate" }: {
  gate: EvidenceGateView | null; ack: boolean; onAck: (on: boolean) => void; copy: string; loading?: boolean;
  /** The reused proposal was already approved with the acknowledgement: no new tick is needed. */
  acknowledged?: boolean; testId?: string;
}) {
  return (
    <div style={subBox} data-testid={testId}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-label">EVIDENCE GATE</span>
        {loading || !gate ? <Tag tone="neutral">checking evidence</Tag> : <BadgeTag b={gate.badge} />}
      </div>
      {gate && <div className="pb-pretty" style={{ fontSize: 12.5, color: "#3C4458", lineHeight: 1.5, marginTop: 8 }}>{gate.reason}</div>}
      {gate?.validated && <div style={{ fontSize: 12, color: "#15804F", marginTop: 6 }}>This market passed its out-of-sample test for this ticker; decisions and fills are labelled “validated”.</div>}
      {gate?.needsAck && acknowledged && <div data-testid="evidence-acknowledged" style={{ fontSize: 12, color: "#9A4A00", marginTop: 8 }}>Already approved with your acknowledgement; decisions and fills are labelled “unvalidated (acknowledged)”.</div>}
      {gate?.needsAck && !acknowledged && (
        <label style={{ display: "grid", gridTemplateColumns: "20px minmax(0,1fr)", gap: 10, alignItems: "start", marginTop: 10, padding: "10px 12px", borderRadius: 14, background: ack ? "rgba(251,146,60,.10)" : "rgba(15,22,38,.04)", border: `1px solid ${ack ? "rgba(251,146,60,.45)" : "rgba(15,22,38,.10)"}`, cursor: "pointer" }}>
          <input type="checkbox" checked={ack} onChange={(e) => onAck(e.target.checked)} data-testid="evidence-ack" style={{ width: 16, height: 16, marginTop: 2, accentColor: "#0F1626", cursor: "pointer" }} />
          <span className="pb-pretty" style={{ fontSize: 12.5, color: "#3C4458", lineHeight: 1.5 }}>{copy}</span>
        </label>
      )}
    </div>
  );
}

export function CapacityCard({ view, title, extra, footer, tag, testId = "capacity-card" }: {
  view: CapacityView; title: string; extra?: ReactNode; footer?: ReactNode; tag?: ReactNode; testId?: string;
}) {
  return (
    <div style={subBox} data-testid={testId}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-label">{title}</span>
        <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
          <BadgeTag b={view.verdict} />
          {view.stale && <Tag tone="caution" title="The last refresh failed; these are the last good numbers.">stale</Tag>}
          {tag}
        </span>
      </div>
      {view.available ? (
        <>
          <MetricGrid rows={view.rows} />
          <div style={{ fontSize: 12, color: "#3C4458", marginTop: 10 }}>Binding limit: <span style={{ fontWeight: 600 }}>{view.binding}</span></div>
        </>
      ) : <div className="pb-pretty" style={{ fontSize: 12.5, color: "#5A627A", marginTop: 8, lineHeight: 1.45 }}>{view.reason}</div>}
      {extra}
      {view.sources.length > 0 && (
        <div className="pb-pretty" style={{ fontSize: 11, color: "#5A627A", marginTop: 8, lineHeight: 1.5 }}>
          {view.sources.map((s) => <div key={s}>{s}</div>)}
        </div>
      )}
      {footer}
    </div>
  );
}

export function MeterRow({ m }: { m: Meter }) {
  const w = m.frac == null ? 0 : Math.min(100, Math.max(m.frac > 0 ? 1.5 : 0, m.frac * 100));
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12.5 }}>
        <span className="pb-ellipsis" style={{ minWidth: 0, color: "#3C4458" }} title={m.k}>{m.k}</span>
        <span className="pb-mono pb-tab" style={{ fontSize: 11.5, flex: "none", color: m.warn ? "#9A4A00" : "#5A627A" }}>{m.text}</span>
      </div>
      <div className="pb-bar" style={{ marginTop: 6 }}><div style={{ width: `${w}%`, background: m.frac != null && m.frac > 1 ? "#E0485A" : m.warn ? "linear-gradient(90deg,#FB923C,#E0485A)" : undefined }} /></div>
    </div>
  );
}

export const PanelHead = ({ label, children }: { label: string; children?: ReactNode }) => (
  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
    <Label>{label}</Label>
    {children && <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>{children}</span>}
  </div>
);
