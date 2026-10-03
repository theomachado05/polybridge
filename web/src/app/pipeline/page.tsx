"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { shortlist } from "@/lib/library";
import { demoSteps, fitScoreView, fitSteps, type PipeContext } from "@/lib/pipeline";
import { algoRunLabel, brokerLabel, defaultPick, feeGateOff, runnableFit, useStore } from "@/lib/store";
import { sessionClosed } from "@/lib/closed";
import { hedgeTerms, prepareHedgeProposal, REPLAY_SANDBOX_SENTENCE } from "@/lib/realBridge";
import { useAsync } from "@/lib/hooks";
import { ackCopy, capacityFromProposal, capitalFitView, evidenceGate, isEvidenceError, OVERRIDE_ON_LINE, pmDepthLine } from "@/lib/risk";
import { DemoTag, OrbDisc, Tag } from "@/components/pb";
import { BadgeTag, CapacityCard, EvidenceGateBox } from "@/components/risk/RiskBits";

const STEP_MS = 1400;
const FIT_WAIT_MS = 10000;

export default function Pipeline() {
  const router = useRouter();
  const s = useStore();
  const [{ q, eq: e }] = useState(() => (s.question && s.equity ? { q: s.question, eq: s.equity } : defaultPick()));
  const inst = s.inst ?? "shares";
  const [step, setStep] = useState(0);
  // Set when the fit misses its deadline. A demo market then stays on the scripted steps; on a live market a fit that
  // lands later still replaces them (see `mode`).
  const [forcedDemo, setForcedDemo] = useState(false);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  // The evidence acknowledgement, per proposal id (a new proposal needs a new tick).
  const [ack, setAck] = useState<{ id: string; on: boolean } | null>(null);
  // Bumped after an evidence refusal so the approval step re-reads the proposal (the backend rewrites its evidence
  // before a 409 at approval; a refused bridge start drops it from reuse, so the re-read proposes again).
  const [prepNonce, setPrepNonce] = useState(0);
  const openingRef = useRef(false);
  const { runFit } = s;

  const fit = s.fit && s.fit.key === `${q.id}|${e.t}` ? s.fit : null;
  const fitOk = fit?.status === "ok" && !!fit.data;
  const settled = fit != null && fit.status !== "loading";
  // On a live market a fit that lands after the deadline still takes over: approval sends it, so the steps must say so.
  const mode: "fit" | "demo" | "pending" = fitOk && (!forcedDemo || !!q.real) ? "fit" : forcedDemo || settled ? "demo" : "pending";
  const fitOkRef = useRef(fitOk);
  useEffect(() => { fitOkRef.current = fitOk; });

  useEffect(() => {
    runFit(q, e);
    const t = setTimeout(() => { if (!fitOkRef.current) setForcedDemo(true); }, FIT_WAIT_MS);
    return () => clearTimeout(t);
  }, [runFit, q, e]);

  // Approving starts the engine, which sends orders to the account. That needs a click, unless the user turned
  // on auto-approve in Profile; a bridge that would run with its fee gate off always waits when the edge guard is on.
  const real = !!q.real;
  // What approving starts: openBridge sends the runnable AI fit (hedge family + preset) when the fit answered, else
  // the engine runs its default delta-bridge spec. Same rule as the store, so the copy matches what runs.
  const applied = runnableFit(fitOk ? fit!.data : null);
  const runs = algoRunLabel(applied);
  // Only the default spec (legacy Engine) reads gap_per_share; an AI-fit algo is fee-gated on the tick's under_px.
  const gateOff = feeGateOff(q, e, applied);
  const { guards } = s.settings;
  const acct = brokerLabel(s.account);
  // A ticker outside the market's mapping: no hedge fit, and startRealBridge refuses (adverse outcome unknown).
  const noDir = real && !e.direction;

  // The approval step reads the pending proposal first: its evidence status (the gate) and its capacity block
  // (liquidity caps, estimated cost, capital budget). Creating a proposal approves nothing.
  const done0 = step >= 6;
  const terms = (() => {
    if (!real || noDir || !done0) return null;
    try { return hedgeTerms(q, e, s.settings.maxHedge, applied, { closedPmHedge: s.closedPmHedge, actOnUnvalidated: s.actOnUnvalidated }); } catch { return null; }
  })();
  const prep = useAsync(terms ? `prep:${prepNonce}:${JSON.stringify(terms)}` : null, () => prepareHedgeProposal(terms!));
  const proposal = prep.data;
  const gate = proposal ? evidenceGate(proposal.evidence) : null;
  const acked = !!proposal && ack?.id === proposal.id && ack.on;
  // Approve waits for the evidence read: on an unvalidated market a click before it lands is a certain 409. If the
  // read fails (prep.error) Approve is allowed and the backend's gate still applies.
  const evidencePending = !!terms && prep.loading;
  const ackBlocked = evidencePending || (!!gate?.needsAck && !acked && proposal?.status !== "approved");
  // The Weekend-mode override travels on the proposal (act_on_unvalidated); approving with the acknowledgement confirms it.
  const overrideOn = !!terms?.actOnUnvalidated;
  const capView = proposal ? capacityFromProposal(proposal.capacity) : null;
  const capFit = proposal ? capitalFitView(proposal.capacity) : null;
  // Auto-approve never covers an unvalidated market: that needs the explicit acknowledgement below.
  const evidenceReady = !terms || (!!proposal && !gate?.needsAck) || proposal?.status === "approved";
  const autoOpen = !real || (guards.auto && !(gateOff && guards.edge) && evidenceReady);

  const goBridge = async () => {
    if (openingRef.current || ackBlocked) return;
    openingRef.current = true;
    setOpening(true);
    setOpenError(null);
    try {
      await s.openBridge(q, e, inst, { ackUnvalidated: acked });
      router.push("/bridge");
    } catch (err) {
      openingRef.current = false;
      setOpening(false);
      const evid = isEvidenceError(err);
      setOpenError(`${evid ? "The evidence gate refused the approval" : "Could not open the bridge"}: ${err instanceof Error ? err.message : String(err)}`);
      if (evid) { setAck(null); setPrepNonce((n) => n + 1); }  // re-read the proposal's evidence
    }
  };
  const goRef = useRef(goBridge);
  useEffect(() => { goRef.current = goBridge; });

  const done = step >= 6;
  useEffect(() => {
    if (done) {
      if (!autoOpen) return;
      const t = setTimeout(() => void goRef.current(), STEP_MS);
      return () => clearTimeout(t);
    }
    if (mode === "pending") return;
    const t = setTimeout(() => setStep((n) => Math.min(6, n + 1)), STEP_MS);
    return () => clearTimeout(t);
  }, [step, done, mode, autoOpen]);

  const ctx: PipeContext = {
    question: q.q, venues: q.venues, yes: q.yes, vol: q.vol, ticker: e.t, held: e.held || 500,
    move: e.move, rev: e.rev, brand: e.brand, why: e.why, real: !!q.real, heldReal: e.held,
    libraryTotal: s.library.status === "ok" && s.library.data ? s.library.data.total : undefined,
    shortlisted: fitOk && s.library.data ? shortlist(s.library.data, String(fit!.data!.event_class), fit!.data!.division ? String(fit!.data!.division) : null).map((r) => r.id) : undefined,
    noDirection: !!fit?.noDirection,
  };
  const steps = mode === "fit" ? fitSteps(fit!.data!, ctx) : demoSteps(ctx);
  const cur = steps[Math.min(step, steps.length - 1)];
  const orb = done ? "breathing" : cur.orb;

  return (
    <main className="pb-page" style={{ maxWidth: 820, paddingTop: 30, paddingBottom: 80, display: "flex", flexDirection: "column", alignItems: "center" }}>
      <OrbDisc state={orb} disc={220} orb={170} />
      <div className="pb-label" style={{ marginTop: 26 }}>{done ? (real && !autoOpen ? "WAITING FOR YOUR APPROVAL" : "BRIDGE READY") : `STEP ${Math.min(step + 1, 6)} OF 6`}</div>
      <h2 className="pb-serif pb-balance" style={{ margin: "10px 0 0", fontSize: 40, letterSpacing: "-.015em", fontWeight: 400, textAlign: "center" }}>
        {done ? (real && !autoOpen ? `Approve the ${e.t} bridge?` : real ? `Opening the ${e.t} bridge` : `${e.t} is bridged to the market`) : mode === "pending" ? "Fitting an algo to the event…" : cur.name + "…"}
      </h2>
      <div style={{ marginTop: 10, minHeight: 20, display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
        {mode === "fit" && fit?.data && (
          <>
            <Tag tone="ai" title="POST /pipeline/fit">{fit.data.llm === "gemini" ? "AI estimate · Gemini" : "rules-based fit"}</Tag>
            <Tag tone={fit.data.ticks_source === "live_history" ? "measured" : fit.data.ticks_source === "replay" ? "replay" : "neutral"}>
              {fit.data.ticks_source === "live_history" ? "real price history" : fit.data.ticks_source === "replay" ? "replay ticks" : "no price history"}
            </Tag>
            {fit.data.family && fit.data.score != null && (() => {
              const sv = fitScoreView(fit.data);
              // Neutral (never green) when the signal adds nothing over a static hedge of the same size.
              return <Tag tone={sv.tone === "positive" ? "ai" : "neutral"} title={sv.title}>{sv.short}</Tag>;
            })()}
          </>
        )}
        {mode === "demo" && fit?.noDirection && <Tag tone="neutral" title={fit.error ?? undefined}>no hedge fit · direction unknown</Tag>}
        {mode === "demo" && !fit?.noDirection && <DemoTag what="scripted demo steps" title={`POST /pipeline/fit ${fit?.error ? "failed: " + fit.error : "did not answer in time"}; showing the prototype's scripted pipeline.`} />}
      </div>
      <div className="pb-glass" style={{ width: "100%", marginTop: 22, padding: "10px 12px", display: "flex", flexDirection: "column", gap: 4 }}>
        {steps.map((st, i) => {
          const d = i < step, a = i === step && !done;
          const text = d || a ? (mode === "pending" && a ? "Waiting on the fit…" : st.text) : "";
          return (
            <div key={st.key} style={{ display: "grid", gridTemplateColumns: "28px minmax(110px,190px) minmax(0,1fr)", gap: 14, alignItems: "start", padding: "12px 14px", borderRadius: 18, background: a ? "rgba(255,255,255,.75)" : "transparent", transition: "all .3s ease" }}>
              <span style={{ width: 22, height: 22, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 600, background: d ? "#22A06B" : a ? "#0F1626" : "rgba(15,22,38,.08)", color: d || a ? "#fff" : "#8A92A8", marginTop: 1 }}>{d ? "✓" : i + 1}</span>
              <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.01em", color: d || a ? "#0F1626" : "#8A92A8", paddingTop: 2 }}>{st.name}</span>
              <span className="pb-pretty" style={{ fontSize: 13, lineHeight: 1.5, color: "#3C4458", paddingTop: 2, minWidth: 0, overflowWrap: "anywhere" }}>{text}{a && <span className="pb-caret" />}</span>
            </div>
          );
        })}
      </div>
      {done && real && (
        <div className="pb-glass" style={{ width: "100%", marginTop: 16, padding: "16px 18px", fontSize: 13.5, lineHeight: 1.55, color: "#3C4458", display: "flex", flexDirection: "column", gap: 8 }}>
          {noDir ? (
            <div style={{ color: "#8A5A00" }}>
              {e.t} is not in this market&rsquo;s mapping, so the outcome that hurts it is unknown. The engine will not start a bridge it cannot orient; opening it shows the prototype&rsquo;s simulator, with no orders sent anywhere.
            </div>
          ) : (
          <div>
            Approving creates a hedge proposal for {(e.held || 500).toLocaleString("en-US")} {e.t} shares{e.held ? "" : " (notional)"} on this market and starts a bridge that runs {runs.sentence}.
            {acct.tone === "demo"
              ? <> Once it runs, the engine places its orders without asking again; this backend has no account endpoint, so they are simulated fills inside the engine <Tag tone="sim" title="GET /account is unavailable">no broker</Tag>.</>
              : <> Once it runs, the engine places its orders with <Tag tone={acct.tone} title="GET /account">{acct.name}</Tag> without asking again.</>}
            {" "}{REPLAY_SANDBOX_SENTENCE}
          </div>
          )}
          {!noDir && sessionClosed(s.session.data) && (
            <div data-testid="pipeline-weekend">
              US equities are closed: the equity algo holds until the regular session, and a staged order (hedge B) is planned for the first tradable moment; it executes only when you press Approve plan on the Bridge.
              {s.closedPmHedge
                ? <> Hedge A is on: a simulated prediction-market leg runs over the closure <Tag tone="caution" title="Research R1 found no evidence it reduces the open-gap loss">estimate — not protection</Tag>.</>
                : " Hedge A (the PM-leg estimate) is off."}
            </div>
          )}
          {!noDir && !sessionClosed(s.session.data) && s.closedPmHedge && (
            <div data-testid="pipeline-weekend">
              Hedge A is on: US equities are open now, and from the next close a simulated prediction-market leg runs over the closure <Tag tone="caution" title="Research R1 found no evidence it reduces the open-gap loss">estimate — not protection</Tag>. Turn it off in Weekend mode on Build before approving if you do not want it.
            </div>
          )}
          {terms && (
            <div data-testid="approval-risk">
              {prep.error && <div style={{ fontSize: 12.5, color: "#8A5A00" }}>Could not read the proposal before approval ({prep.error}); approving will still go through the backend’s evidence gate.</div>}
              {overrideOn && (
                <div data-testid="approval-override" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 12.5, color: "#9A4A00", marginBottom: 10 }}>
                  <Tag tone="caution" title="Weekend mode on Build: stage hedge B on a market whose expected gap is not validated">override on</Tag>
                  <span className="pb-pretty">{OVERRIDE_ON_LINE} Nothing staged executes until you press Approve plan.</span>
                </div>
              )}
              <EvidenceGateBox gate={gate} loading={prep.loading} acknowledged={proposal?.status === "approved" && !!proposal.ack_unvalidated} ack={acked} onAck={(on) => proposal && setAck({ id: proposal.id, on })} copy={ackCopy(e.t, "hedge", { override: overrideOn })} />
              {prep.loading && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Checking liquidity and the capital budget…</div>}
              {capView && (
                <CapacityCard view={capView} title={`LIQUIDITY & CAPACITY · ${e.t}`}
                  tag={<Tag tone={proposal?.capacity?.source === "live" ? "live" : "sim"} title={proposal?.capacity?.label}>{proposal?.capacity?.source === "live" ? "live numbers" : "cached numbers"}</Tag>}
                  extra={pmDepthLine(proposal?.capacity) && <div className="pb-pretty" style={{ fontSize: 12, color: "#3C4458", marginTop: 8 }}>{pmDepthLine(proposal?.capacity)}</div>}
                  footer={capFit && (
                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(15,22,38,.08)" }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><span className="pb-label">CAPITAL BUDGET</span><BadgeTag b={capFit.badge} /></div>
                      <div style={{ fontSize: 12, color: "#3C4458", marginTop: 6, lineHeight: 1.5 }}>{capFit.lines.map((l) => <div key={l}>{l}</div>)}</div>
                      {capFit.badge.tone === "caution" && <div style={{ fontSize: 12, color: "#9A4A00", marginTop: 4 }}>Orders that would breach a budget are refused before they are sent (capital_budget).</div>}
                    </div>
                  )} />
              )}
            </div>
          )}
          {gateOff && !noDir && (
            <div style={{ color: "#8A5A00" }}>
              Fee gate off: there is no {e.px ? "impact estimate" : "quote"} for {e.t}, so the engine cannot price an order against its fees and will trade on probability alone.
              {guards.edge && " Your “act only when edge beats fees” guardrail is on, so this needs your explicit approval."}
            </div>
          )}
          {guards.auto && !autoOpen && <div style={{ fontSize: 12, color: "#5A627A" }}>Auto-approve is on, but it does not apply {gate?.needsAck ? "to an unvalidated market (tick the acknowledgement)" : gateOff ? "while the fee gate is off" : "until the evidence check answers"}.</div>}
          {openError && <div role="alert" style={{ fontSize: 12.5, color: "#C8323F" }}>{openError}</div>}
          {autoOpen && <div style={{ fontSize: 12, color: "#5A627A" }}>Auto-approve is on (Profile), so the bridge opens by itself.</div>}
        </div>
      )}
      <button type="button" onClick={() => (done ? void goBridge() : setStep(6))} disabled={done && ackBlocked} title={done && ackBlocked ? (evidencePending ? "Reading this proposal's evidence status first" : "Tick the acknowledgement above: this market's signal is unvalidated") : undefined} className={`pb-btn ${done ? (ackBlocked ? "pb-btn-disabled" : "pb-btn-primary") : "pb-btn-secondary"}`} style={{ height: 50, padding: "0 24px", marginTop: 22, transition: "all .3s ease", color: done ? (ackBlocked ? undefined : "#fff") : "#3C4458" }}>
        {opening ? "Opening the bridge…" : !done ? (real ? "Skip to approval" : "Skip to the bridge") : real ? (noDir ? "Open the simulator bridge" : evidencePending ? "Checking the evidence…" : ackBlocked ? "Acknowledge the unvalidated market to approve" : gateOff ? `Approve without the fee gate${acked ? " (unvalidated)" : ""}` : acked ? "Approve on an unvalidated market" : "Approve and open the bridge") : "Open the demo bridge"} <span className="pb-arrow">→</span>
      </button>
    </main>
  );
}
