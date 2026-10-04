"use client";

import { forwardLine, hasRangeAndSample, numberView, type Mechanism } from "@/lib/micro";
import { Unavailable } from "@/components/pb";
import { NumberRow, PageHead, StatusTag, useForward, useRegistry } from "@/components/micro/parts";
import type { ForwardStatus } from "@/lib/micro";

/** What we tested: every mechanism in the evidence registry, with its status, claim, numbers (each with its range,
 *  sample and result file), caveats and forward test. Every label here is read from GET /evidence/mechanisms. */
export default function Tested() {
  const reg = useRegistry();
  const fw = useForward();
  const r = reg.data;
  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: "var(--sp-8)", display: "flex", flexDirection: "column", gap: "var(--sp-6)" }}>
      <PageHead kicker="03 · What we tested" title="What we tested">
        {r ? <>Each mechanism, the status its tests earned, and every number with its range and sample. Source of truth: <code className="pb-code">{r.source_of_truth}</code>. Forward tests start {r.forward_tests_start}.</> : null}
      </PageHead>
      {reg.loading && <div className="pb-small">Reading the evidence registry…</div>}
      {reg.error && <Unavailable what="The evidence registry (GET /evidence/mechanisms)" error={reg.error} onRetry={reg.retry} />}
      {fw.error && <Unavailable what="The forward tests (GET /forward/status)" error={fw.error} onRetry={fw.retry} compact />}
      {r?.mechanisms.map((m) => <MechanismCard key={m.id} m={m} fw={fw.data} />)}
      {r && r.system.length > 0 && (
        <section className="pb-card" style={{ overflow: "hidden" }} aria-label="System">
          <div style={{ padding: "var(--sp-4) var(--sp-5)", borderBottom: "1px solid var(--border)" }}><h2 className="pb-h4" style={{ margin: 0 }}>System measurements</h2></div>
          <div className="pb-list">{r.system.filter(hasRangeAndSample).map((n) => <NumberRow key={n.label} n={n} />)}</div>
        </section>
      )}
    </main>
  );
}

function MechanismCard({ m, fw }: { m: Mechanism; fw: ForwardStatus | null }) {
  const shown = m.numbers.filter((n) => numberView(n));
  const hidden = m.numbers.length - shown.length;
  const fwd = m.forward_test ? forwardLine(fw, m.id) : null;
  const fwSection = m.id === "ladders" ? fw?.ladders : m.id === "touch" ? fw?.touch : null;
  return (
    <section id={m.id} className="pb-card" style={{ overflow: "hidden", scrollMarginTop: 90 }} aria-label={m.name} data-testid={`mech-${m.id}`}>
      <div style={{ padding: "var(--sp-4) var(--sp-5)", display: "flex", flexDirection: "column", gap: "var(--sp-2)", borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", gap: "var(--sp-3)", alignItems: "center", flexWrap: "wrap" }}>
          <h2 className="pb-h3" style={{ margin: 0 }}>{m.name}</h2>
          <StatusTag m={m} />
        </div>
        <p className="pb-body pb-pretty" style={{ margin: 0 }}>{m.claim}</p>
        <div className="pb-small pb-pretty"><span className="pb-label" style={{ display: "inline" }}>Allowed · </span>{m.actions_allowed.text}</div>
      </div>
      {shown.length > 0 ? (
        <div className="pb-list">{shown.map((n) => <NumberRow key={n.label} n={n} />)}</div>
      ) : (
        <div className="pb-list-note">No number is shown for this mechanism: no result file measures it.</div>
      )}
      {hidden > 0 && <div className="pb-list-note" style={{ color: "var(--warn)" }}>{hidden} number{hidden === 1 ? "" : "s"} hidden: no range or sample in the registry.</div>}
      {m.caveats.length > 0 && (
        <div style={{ padding: "var(--sp-3) var(--sp-5)", borderTop: "1px solid var(--border)" }}>
          <div className="pb-label">Caveats</div>
          <ul className="pb-small pb-pretty" style={{ margin: "var(--sp-2) 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
            {m.caveats.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </div>
      )}
      {m.forward_test && (
        <div style={{ padding: "var(--sp-3) var(--sp-5)", borderTop: "1px solid var(--border)" }} data-testid={`forward-${m.id}`}>
          <div className="pb-label">Forward test · from {m.forward_test.starts}</div>
          <div className="pb-small" style={{ marginTop: 4 }}><code className="pb-code">{m.forward_test.file}</code></div>
          {fwSection && <div className="pb-small pb-pretty" style={{ marginTop: 4 }}>{fwSection.label}</div>}
          {fwd && <div className="pb-small pb-num pb-pretty" style={{ marginTop: 4 }}>{fwd}</div>}
          {!fw && <div className="pb-small" style={{ marginTop: 4 }}>Forward status not read yet.</div>}
        </div>
      )}
    </section>
  );
}
