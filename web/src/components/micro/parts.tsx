"use client";

import { useState, type ReactNode } from "react";
import { getForwardStatus, getMechanisms } from "@/lib/api";
import { useAsync, useRetry } from "@/lib/hooks";
import { approveEnabled, numberView, statusTag, type ActionPlan, type EvNumber, type Mechanism } from "@/lib/micro";

export function useRegistry() {
  const [n, retry] = useRetry();
  const r = useAsync(`registry:${n}`, getMechanisms);
  return { ...r, retry };
}

export function useForward() {
  const [n, retry] = useRetry();
  const r = useAsync(`forward:${n}`, getForwardStatus);
  return { ...r, retry };
}

export function StatusTag({ m, prefix }: { m: Mechanism | null | undefined; prefix?: string }) {
  const t = statusTag(m);
  if (!t) return null;
  return <span className={`pb-tag pb-tag-${t.tone}`} title={t.title} data-testid="status-tag">{prefix ? `${prefix} · ` : ""}{t.text}</span>;
}

export function NumberRow({ n }: { n: EvNumber }) {
  const v = numberView(n);
  if (!v) return null;
  return (
    <div className="pb-mm-row pb-mm-num">
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: "var(--fs-14)", fontWeight: 500, color: "var(--ink)", lineHeight: 1.4 }} className="pb-pretty">{v.label}</div>
        {v.note && <div className="pb-small pb-pretty" style={{ marginTop: 2 }}>{v.note}</div>}
        <div className="pb-small" style={{ marginTop: 4, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span className={`pb-tag pb-tag-${v.confirmatory ? "up" : "neutral"}`}>{v.confirmatory ? "confirmatory" : "exploratory / post hoc"}</span>
          <code className="pb-code" style={{ fontSize: "var(--fs-12)", overflowWrap: "anywhere" }}>{v.source}</code>
          {v.sourceNote && <span style={{ color: "var(--warn)" }}>{v.sourceNote}</span>}
        </div>
      </div>
      <div style={{ minWidth: 0, textAlign: "right" }}>
        <div className="pb-num" style={{ fontSize: "var(--fs-16)", fontWeight: 600, color: "var(--ink)" }}>{v.value}</div>
        <div className="pb-num pb-small">{v.range}</div>
        <div className="pb-small pb-pretty">{v.rangeKind}</div>
        <div className="pb-num pb-small">{v.sample}</div>
      </div>
    </div>
  );
}

export function ProposalPanel({ plan, mechanism, title, lines, onClose }: {
  plan: ActionPlan; mechanism: Mechanism | null; title: string; lines: ReactNode[]; onClose: () => void;
}) {
  const [acked, setAcked] = useState(false);
  const [approved, setApproved] = useState(false);
  const can = approveEnabled(plan, acked);
  return (
    <div className="pb-card" role="region" aria-label="Proposal" data-testid="proposal-panel" style={{ padding: "var(--sp-5)", marginTop: "var(--sp-3)", display: "flex", flexDirection: "column", gap: "var(--sp-3)" }}>
      <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
        <span className="pb-h4">{title}</span>
        <StatusTag m={mechanism} />
      </div>
      <div className="pb-small pb-num" style={{ display: "flex", flexDirection: "column", gap: 2 }}>{lines.map((l, i) => <div key={i}>{l}</div>)}</div>
      <div className="pb-small pb-pretty">{plan.text}</div>
      {plan.acknowledge && (
        <label className="pb-small" style={{ display: "flex", gap: 8, alignItems: "flex-start", color: "var(--warn)" }}>
          <input type="checkbox" checked={acked} onChange={(e) => setAcked(e.target.checked)} data-testid="ack" />
          <span className="pb-pretty">I understand this mechanism is {mechanism?.status_label.toLowerCase() ?? "unvalidated"}: its fresh test did not confirm it.</span>
        </label>
      )}
      {approved ? (
        <div className="pb-small" style={{ color: "var(--up-ink)" }} role="status">Approved in this browser. No order was sent: the backend has no order route for this mechanism yet.</div>
      ) : (
        <div style={{ display: "flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
          <button type="button" className={`pb-btn pb-btn-sm ${can ? "pb-btn-primary" : "pb-btn-disabled"}`} disabled={!can} onClick={() => setApproved(true)}
            title={!can && plan.acknowledge ? "Select the acknowledgement first." : undefined}>
            {plan.acknowledge && !acked ? "Acknowledge to approve" : "Approve proposal"}
          </button>
          <button type="button" className="pb-btn pb-btn-sm pb-btn-ghost" onClick={onClose}>Discard</button>
        </div>
      )}
    </div>
  );
}

export function PageHead({ kicker, title, children, tag }: { kicker: string; title: string; children?: ReactNode; tag?: ReactNode }) {
  return (
    <header style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)", maxWidth: 880 }}>
      <div className="pb-label">{kicker}</div>
      <div style={{ display: "flex", gap: "var(--sp-3)", alignItems: "center", flexWrap: "wrap" }}>
        <h1 className="pb-h2 pb-balance" style={{ margin: 0 }}>{title}</h1>
        {tag}
      </div>
      {children && <div className="pb-body pb-pretty" style={{ margin: 0 }}>{children}</div>}
    </header>
  );
}
