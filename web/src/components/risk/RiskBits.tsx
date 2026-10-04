// Risk-control pieces shared by Build, Pipeline, Bridge and Portfolio: badges, the evidence gate with its explicit
// acknowledgement, the liquidity & capacity card and budget meters. Presentational only; the numbers and verdicts come
// from src/lib/risk.ts, which mirrors what the backend enforces.
import type { CSSProperties, ReactNode } from "react";
import type { Badge, CapacityRow, CapacityView, EvidenceGateView, Meter } from "@/lib/risk";
import { Tag } from "@/components/pb";

export const BadgeTag = ({ b }: { b: Badge }) => <Tag tone={b.tone} title={b.title}>{b.text}</Tag>;

export const subBox: CSSProperties = { marginTop: "var(--sp-4)", padding: "var(--sp-4)", borderRadius: "var(--radius-sm)", background: "var(--surface-2)", border: "1px solid var(--border)" };

const KEY_LABEL: Record<string, string> = {
  CASH: "Cash", EQUITY: "Equity", "BUYING POWER": "Buying power", "DAY BUYING POWER": "Day buying power",
  "OPTION BUYING POWER": "Option buying power", "MARKET VALUE": "Market value", "UNREALIZED P&L": "Unrealized P&L",
  "MAINTENANCE MARGIN": "Maintenance margin", "DAY TRADES LEFT": "Day trades left", "GROSS HEDGE NOTIONAL": "Gross hedge notional",
  "MARGIN USED (INITIAL)": "Initial margin used", "HEDGE AT APPROVED SIZE": "Hedge at approved size", "MAX ORDER": "Maximum order",
  "MAX POSITION / DAY": "Maximum position per day", "EST. COST": "Estimated cost", "BOOK-SIZE CAPACITY": "Book-size capacity",
  "SESSIONS NEEDED": "Sessions necessary", ADV: "ADV", "DAILY σ": "Daily σ",
};
const keyLabel = (key: string) => KEY_LABEL[key] ?? key;

export function MetricGrid({ rows, min = 150 }: { rows: CapacityRow[]; min?: number }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${min}px),1fr))`, gap: "var(--sp-4) var(--sp-5)", margin: "var(--sp-4) 0 0" }}>
      {rows.map((r) => (
        <div key={r.k} style={{ minWidth: 0 }}>
          <dt className="pb-label">{keyLabel(r.k)}</dt>
          <dd className="pb-num" style={{ margin: "var(--sp-1) 0 0", fontSize: "var(--fs-16)", fontWeight: 600, color: r.warn ? "var(--warn)" : "var(--ink)" }}>{r.v}</dd>
          {r.sub && <dd className="pb-pretty" style={{ margin: "2px 0 0", fontSize: "var(--fs-12)", color: "var(--faint)", lineHeight: 1.4 }}>{r.sub}</dd>}
        </div>
      ))}
    </dl>
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
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>Evidence gate</span>
        {loading || !gate ? <Tag tone="neutral">evidence not read yet</Tag> : <BadgeTag b={gate.badge} />}
      </div>
      {gate && <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{gate.reason}</div>}
      {gate?.validated && <div className="pb-small" style={{ color: "var(--up)", marginTop: "var(--sp-2)" }}>This market passed its out-of-sample test for this ticker. The app labels decisions and fills “validated”.</div>}
      {gate?.needsAck && acknowledged && <div data-testid="evidence-acknowledged" className="pb-small" style={{ color: "var(--warn)", marginTop: "var(--sp-2)" }}>You approved this with your acknowledgement. The app labels decisions and fills “unvalidated (acknowledged)”.</div>}
      {gate?.needsAck && !acknowledged && (
        <label style={{ display: "grid", gridTemplateColumns: "20px minmax(0,1fr)", gap: "var(--sp-3)", alignItems: "start", marginTop: "var(--sp-3)", padding: "var(--sp-3)", borderRadius: "var(--radius-sm)", background: ack ? "var(--warn-tint)" : "var(--surface)", border: `1px solid ${ack ? "var(--warn)" : "var(--border-strong)"}`, cursor: "pointer" }}>
          <input type="checkbox" checked={ack} onChange={(e) => onAck(e.target.checked)} data-testid="evidence-ack" style={{ width: 16, height: 16, marginTop: 2, accentColor: "var(--accent)", cursor: "pointer" }} />
          <span className="pb-small pb-pretty" style={{ color: "var(--ink)" }}>{copy}</span>
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
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-h4" style={{ fontSize: "var(--fs-14)" }}>{title}</span>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
          <BadgeTag b={view.verdict} />
          {view.stale && <Tag tone="caution" title="The last refresh did not complete. These are the last good values.">stale</Tag>}
          {tag}
        </span>
      </div>
      {view.available ? (
        <>
          <MetricGrid rows={view.rows} />
          <div className="pb-small" style={{ marginTop: "var(--sp-3)" }}>Binding limit: <span style={{ fontWeight: 600, color: "var(--ink)" }}>{view.binding}</span></div>
        </>
      ) : <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{view.reason}</div>}
      {extra}
      {view.sources.length > 0 && (
        <div className="pb-pretty" style={{ fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-3)", lineHeight: 1.5 }}>
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
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", fontSize: "var(--fs-13)" }}>
        <span className="pb-ellipsis" style={{ minWidth: 0, color: "var(--ink)" }} title={m.k}>{m.k}</span>
        <span className="pb-num" style={{ flex: "none", color: m.warn ? "var(--warn)" : "var(--text-2)" }}>{m.text}</span>
      </div>
      <div className="pb-bar" style={{ marginTop: "var(--sp-2)" }}><div style={{ width: `${w}%`, background: m.frac != null && m.frac > 1 ? "var(--down)" : m.warn ? "var(--warn)" : undefined }} /></div>
    </div>
  );
}

export const PanelHead = ({ label, children }: { label: string; children?: ReactNode }) => (
  <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2) var(--sp-3)", flexWrap: "wrap", alignItems: "center" }}>
    <h2 className="pb-h4">{label}</h2>
    {children && <span style={{ display: "inline-flex", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>{children}</span>}
  </div>
);
