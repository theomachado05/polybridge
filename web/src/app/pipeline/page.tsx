"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { shortlist } from "@/lib/library";
import { fitScoreView, fitSteps, noFitSteps, type PipeContext } from "@/lib/pipeline";
import { algoRunLabel, brokerLabel, feeGateOff, pickKey, proposalForPick, runnableFit, useStore } from "@/lib/store";
import { VOICE_ANCHOR } from "@/lib/voiceDrive";
import { aiLabel, aiStatus, aiTitle } from "@/lib/ai";
import type { EquityPick, Question } from "@/lib/markets";
import { sessionClosed } from "@/lib/closed";
import { hedgeTerms, prepareHedgeProposal, REPLAY_SANDBOX_SENTENCE } from "@/lib/realBridge";
import { useAsync } from "@/lib/hooks";
import { ackCopy, capacityFromProposal, capitalFitView, evidenceGate, isEvidenceError, OVERRIDE_ON_LINE, pmDepthLine } from "@/lib/risk";
import { Btn, Glass, OrbDisc, Tag, Unavailable } from "@/components/pb";
import { BadgeTag, CapacityCard, EvidenceGateBox } from "@/components/risk/RiskBits";

const STEP_MS = 1400;
const FIT_WAIT_MS = 10000;

export default function Pipeline() {
  const s = useStore();
  // The pick is read once: the pipeline runs on what Build chose when this screen opened. A different pick made
  // while this screen is open (the voice agent fitted or proposed another market or ticker) restarts it on that pick.
  const [pick, setPick] = useState(() => (s.question && s.equity ? { q: s.question, eq: s.equity } : null));
  const liveKey = pickKey(s.question, s.equity);
  const key = pick ? pickKey(pick.q, pick.eq) : null;
  if (liveKey && liveKey !== key) setPick({ q: s.question!, eq: s.equity! });
  if (!pick) {
    return (
      <main className="pb-page" style={{ maxWidth: 760, paddingTop: 30, paddingBottom: 80 }}>
        <Glass style={{ padding: "28px 30px", borderRadius: 30, display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-start" }}>
          <h2 className="pb-serif" style={{ margin: 0, fontSize: 32, letterSpacing: "-.015em", fontWeight: 400 }}>No market or stock is selected.</h2>
          <p style={{ margin: 0, fontSize: 14, color: "#3C4458" }}>Select a market and a stock on the Build page. The pipeline then fits an algo to them on the history of that market.</p>
          <Btn href="/build">Open Build</Btn>
        </Glass>
      </main>
    );
  }
  return <PipelineRun key={key} q={pick.q} e={pick.eq} />;
}

function PipelineRun({ q, e }: { q: Question; e: EquityPick }) {
  const router = useRouter();
  const s = useStore();
  const inst = s.inst ?? "shares";
  const [stepN, setStep] = useState(0);
  // A proposal the voice agent drafted for this pick: the screen goes straight to its approval panel.
  const voiceProp = proposalForPick(s.voiceProposal, q, e) ? s.voiceProposal : null;
  const step = voiceProp ? 6 : stepN;
  // Set when the fit misses its deadline: the steps then go on with the facts of the pick (no fit); a fit that lands
  // later still replaces them (see `mode`), since approval sends it.
  const [timedOut, setTimedOut] = useState(false);
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
  // A fit that lands after the deadline still takes over: approval sends it, so the steps must say so.
  const mode: "fit" | "nofit" | "pending" = fitOk ? "fit" : timedOut || settled ? "nofit" : "pending";
  const fitOkRef = useRef(fitOk);
  useEffect(() => { fitOkRef.current = fitOk; });

  useEffect(() => {
    runFit(q, e);
    const t = setTimeout(() => { if (!fitOkRef.current) setTimedOut(true); }, FIT_WAIT_MS);
    return () => clearTimeout(t);
  }, [runFit, q, e]);

  // Approving starts the engine, which sends orders to the account. That needs a click, unless the user turned
  // on auto-approve in Profile; a bridge that would run with its fee gate off always waits when the edge guard is on.
  // What approving starts: openBridge sends the runnable fit (hedge family + preset) when the fit answered, else
  // the engine runs its default delta-bridge spec. Same rule as the store, so the copy matches what runs.
  const applied = runnableFit(fitOk ? fit!.data : null);
  const runs = algoRunLabel(applied);
  // Only the default spec (legacy Engine) reads gap_per_share; a fitted algo is fee-gated on the tick's under_px.
  const gateOff = feeGateOff(q, e, applied);
  const { guards } = s.settings;
  const acct = brokerLabel(s.account);
  // A ticker outside the market's mapping: no hedge fit, and startRealBridge refuses (adverse outcome unknown).
  const noDir = !e.direction;

  // The approval step reads the pending proposal first: its evidence status (the gate) and its capacity block
  // (liquidity caps, estimated cost, capital budget). Creating a proposal approves nothing.
  const done0 = step >= 6;
  const terms = (() => {
    if (noDir || !done0) return null;
    try { return hedgeTerms(q, e, s.settings.maxHedge, applied, { closedPmHedge: s.closedPmHedge, actOnUnvalidated: s.actOnUnvalidated }); } catch { return null; }
  })();
  const prep = useAsync(terms && !voiceProp ? `prep:${prepNonce}:${JSON.stringify(terms)}` : null, () => prepareHedgeProposal(terms!));
  const proposal = voiceProp ?? prep.data;
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
  const autoOpen = !noDir && guards.auto && !(gateOff && guards.edge) && evidenceReady;

  const goBridge = async () => {
    if (openingRef.current || ackBlocked) return;
    openingRef.current = true;
    setOpening(true);
    setOpenError(null);
    try {
      await s.openBridge(q, e, inst, { ackUnvalidated: acked || (proposal?.status === "approved" && !!proposal.ack_unvalidated), proposal: voiceProp });
      router.push("/bridge");
    } catch (err) {
      openingRef.current = false;
      setOpening(false);
      const evid = isEvidenceError(err);
      setOpenError(`${evid ? "The evidence gate stopped the approval" : "The bridge did not open"}: ${err instanceof Error ? err.message : String(err)}. ${evid ? "Read the evidence status and try again." : "Try again."}`);
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
    move: e.move, rev: e.rev, brand: e.brand, why: e.why, heldReal: e.held,
    libraryTotal: s.library.status === "ok" && s.library.data ? s.library.data.total : undefined,
    shortlisted: fitOk && s.library.data ? shortlist(s.library.data, String(fit!.data!.event_class), fit!.data!.division ? String(fit!.data!.division) : null).map((r) => r.id) : undefined,
    noDirection: !!fit?.noDirection,
  };
  const steps = mode === "fit" ? fitSteps(fit!.data!, ctx) : noFitSteps(ctx);
  const cur = steps[Math.min(step, steps.length - 1)];
  const orb = done ? "breathing" : cur.orb;

  return (
    <main className="pb-page" style={{ maxWidth: 820, paddingTop: 30, paddingBottom: 80, display: "flex", flexDirection: "column", alignItems: "center" }}>
      <OrbDisc state={orb} disc={220} orb={170} />
      <div style={{ marginTop: 26, fontSize: 13, fontWeight: 600, color: "#5A627A" }}>{done ? (!autoOpen ? "Approval necessary" : "Bridge ready") : `Step ${Math.min(step + 1, 6)} of 6`}</div>
      <h2 className="pb-serif pb-balance" style={{ margin: "10px 0 0", fontSize: 40, letterSpacing: "-.015em", fontWeight: 400, textAlign: "center" }}>
        {done ? (noDir ? `Select the outcome that hurts ${e.t}` : !autoOpen ? `Approve the ${e.t} bridge` : `Opening the ${e.t} bridge`) : mode === "pending" ? "Fitting an algo to the event…" : cur.name + "…"}
      </h2>
      <div style={{ marginTop: 10, minHeight: 20, display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
        {mode === "fit" && fit?.data && (
          <>
            <Tag tone={aiStatus(fit.data).live ? "ai" : "neutral"} title={aiTitle(aiStatus(fit.data))}>{aiLabel(aiStatus(fit.data))}</Tag>
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
        {mode === "nofit" && fit?.noDirection && <Tag tone="neutral" title={fit.error ?? undefined}>no hedge fit, direction unknown</Tag>}
        {mode === "nofit" && !fit?.noDirection && <Tag tone="caution" title={`POST /pipeline/fit ${fit?.error ? "did not complete: " + fit.error : "did not answer in time"}.`}>no fit, engine default spec</Tag>}
      </div>
      {mode !== "fit" && fit?.status === "error" && !fit.noDirection && (
        <Unavailable what="The fit (POST /pipeline/fit)" error={fit.error} onRetry={() => s.retryFit(q, e)} style={{ marginTop: 14, justifyContent: "center" }} />
      )}
      {mode === "nofit" && fit?.status === "loading" && <div style={{ marginTop: 14, fontSize: 12.5, color: "#5A627A" }}>The fit continues to run. When it answers, it replaces these steps.</div>}
      <div id={VOICE_ANCHOR.steps} className="pb-glass" style={{ width: "100%", marginTop: 22, padding: "10px 12px", display: "flex", flexDirection: "column", gap: 4, scrollMarginTop: 90 }}>
        {steps.map((st, i) => {
          const d = i < step, a = i === step && !done;
          const text = d || a ? (mode === "pending" && a ? "Waiting for the fit…" : st.text) : "";
          return (
            <div key={st.key} style={{ display: "grid", gridTemplateColumns: "28px minmax(110px,190px) minmax(0,1fr)", gap: 14, alignItems: "start", padding: "12px 14px", borderRadius: 18, background: a ? "rgba(255,255,255,.75)" : "transparent" }}>
              <span style={{ width: 22, height: 22, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 600, background: d ? "#22A06B" : a ? "#0F1626" : "rgba(15,22,38,.08)", color: d || a ? "#fff" : "#8A92A8", marginTop: 1 }}>{d ? "✓" : i + 1}</span>
              <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-.01em", color: d || a ? "#0F1626" : "#8A92A8", paddingTop: 2 }}>{st.name}</span>
              <span className="pb-pretty" style={{ fontSize: 13, lineHeight: 1.5, color: "#3C4458", paddingTop: 2, minWidth: 0, overflowWrap: "anywhere" }}>{text}{a && <span className="pb-caret" />}</span>
            </div>
          );
        })}
      </div>
      {done && (
        <div id={VOICE_ANCHOR.approval} className="pb-glass" style={{ scrollMarginTop: 90, width: "100%", marginTop: 16, padding: "16px 18px", fontSize: 13.5, lineHeight: 1.55, color: "#3C4458", display: "flex", flexDirection: "column", gap: 8 }}>
          {noDir ? (
            <div style={{ color: "#8A5A00" }}>
              {e.t} is not in the mapping for this market, and you did not select the outcome that hurts it. Thus the engine cannot orient a hedge. Go to Build and select the outcome. The app makes no proposal until you do.
            </div>
          ) : (
          <div>
            When you approve, the app makes a hedge proposal for {(e.held || 500).toLocaleString("en-US")} {e.t} shares{e.held ? "" : " (notional)"} on this market. It then starts a bridge that runs {runs.sentence}.
            {acct.tone === "demo"
              ? <> After it starts, the engine sends orders to the active broker of the backend and does not ask again. The app cannot read the account now <Tag tone="caution" title={s.account.error ?? "The app cannot read GET /account."}>account not available</Tag>.</>
              : <> After it starts, the engine sends orders to <Tag tone={acct.tone} title="GET /account">{acct.name}</Tag> and does not ask again.</>}
            {" "}{REPLAY_SANDBOX_SENTENCE}
          </div>
          )}
          {!noDir && sessionClosed(s.session.data) && (
            <div data-testid="pipeline-weekend">
              US equities are closed. The equity algo holds until the regular session. The app stages an order (hedge B) for the first tradable time. The order executes only when you press Approve plan on the Bridge page.
              {s.closedPmHedge
                ? <> Hedge A is on. A simulated prediction-market leg runs during the closure <Tag tone="caution" title="Research R1 found no evidence that it decreases the loss from the open gap.">estimate, not protection</Tag>.</>
                : " Hedge A (the PM-leg estimate) is off."}
            </div>
          )}
          {!noDir && !sessionClosed(s.session.data) && s.closedPmHedge && (
            <div data-testid="pipeline-weekend">
              Hedge A is on. US equities are open now. From the next close, a simulated prediction-market leg runs during the closure <Tag tone="caution" title="Research R1 found no evidence that it decreases the loss from the open gap.">estimate, not protection</Tag>. If you do not want hedge A, disable it in Weekend mode on Build before you approve.
            </div>
          )}
          {terms && (
            <div data-testid="approval-risk">
              {prep.error && <div style={{ fontSize: 12.5, color: "#8A5A00" }}>The app could not read the proposal ({prep.error}). The evidence gate of the backend still applies when you approve.</div>}
              {overrideOn && (
                <div data-testid="approval-override" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 12.5, color: "#9A4A00", marginBottom: 10 }}>
                  <Tag tone="caution" title="Weekend mode on Build stages hedge B on a market that has no validated expected gap.">override on</Tag>
                  <span className="pb-pretty">{OVERRIDE_ON_LINE} No staged order executes until you press Approve plan.</span>
                </div>
              )}
              <EvidenceGateBox gate={gate} loading={prep.loading} acknowledged={proposal?.status === "approved" && !!proposal.ack_unvalidated} ack={acked} onAck={(on) => proposal && setAck({ id: proposal.id, on })} copy={ackCopy(e.t, "hedge", { override: overrideOn })} />
              {prep.loading && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Checking the liquidity and the capital budget…</div>}
              {capView && (
                <CapacityCard view={capView} title={`Liquidity and capacity for ${e.t}`}
                  tag={<Tag tone={proposal?.capacity?.source === "live" ? "live" : "sim"} title={proposal?.capacity?.label}>{proposal?.capacity?.source === "live" ? "live numbers" : "cached numbers"}</Tag>}
                  extra={pmDepthLine(proposal?.capacity) && <div className="pb-pretty" style={{ fontSize: 12, color: "#3C4458", marginTop: 8 }}>{pmDepthLine(proposal?.capacity)}</div>}
                  footer={capFit && (
                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(15,22,38,.08)" }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><span style={{ fontSize: 13, fontWeight: 600, color: "#0F1626" }}>Capital budget</span><BadgeTag b={capFit.badge} /></div>
                      <div style={{ fontSize: 12, color: "#3C4458", marginTop: 6, lineHeight: 1.5 }}>{capFit.lines.map((l) => <div key={l}>{l}</div>)}</div>
                      {capFit.badge.tone === "caution" && <div style={{ fontSize: 12, color: "#9A4A00", marginTop: 4 }}>The app stops each order that goes above a budget before it sends the order (capital_budget).</div>}
                    </div>
                  )} />
              )}
            </div>
          )}
          {gateOff && !noDir && (
            <div style={{ color: "#8A5A00" }}>
              Fee gate off: {e.t} has no {e.px ? "impact estimate" : "quote"}. Thus the engine cannot compare an order with its fees and trades on probability only.
              {guards.edge && " Your “act only when edge beats fees” guardrail is on, thus you must approve this bridge."}
            </div>
          )}
          {guards.auto && !autoOpen && <div style={{ fontSize: 12, color: "#5A627A" }}>Auto-approve is on, but it does not apply {gate?.needsAck ? "to an unvalidated market. Select the acknowledgement" : gateOff ? "when the fee gate is off" : "until the evidence check answers"}.</div>}
          {openError && <div role="alert" style={{ fontSize: 12.5, color: "#C8323F" }}>{openError}</div>}
          {autoOpen && <div style={{ fontSize: 12, color: "#5A627A" }}>Auto-approve is on (Profile), thus the bridge opens automatically.</div>}
        </div>
      )}
      {done && noDir ? (
        <Btn href="/build" kind="secondary" style={{ height: 50, padding: "0 24px", marginTop: 22 }}>Select the outcome on Build</Btn>
      ) : (
      <button type="button" onClick={() => (done ? void goBridge() : setStep(6))} disabled={done && ackBlocked} title={done && ackBlocked ? (evidencePending ? "The app reads the evidence status of this proposal first." : "Select the acknowledgement above because the signal of this market is unvalidated.") : undefined} className={`pb-btn ${done ? (ackBlocked ? "pb-btn-disabled" : "pb-btn-primary") : "pb-btn-secondary"}`} style={{ height: 50, padding: "0 24px", marginTop: 22, color: done ? (ackBlocked ? undefined : "#fff") : "#3C4458" }}>
        {opening ? "Opening the bridge…" : !done ? "Go to approval" : evidencePending ? "Checking the evidence…" : proposal?.status === "approved" ? "Open approved bridge" : ackBlocked ? "Acknowledge the unvalidated market to approve" : gateOff ? `Approve without the fee gate${acked ? " (unvalidated)" : ""}` : acked ? "Approve on an unvalidated market" : "Approve and open the bridge"}
      </button>
      )}
    </main>
  );
}
