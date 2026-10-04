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
import { capacityFromProposal, capitalFitView, evidenceGate, fitAckCopy, fitEvidenceGate, isEvidenceError, OVERRIDE_ON_LINE, pmDepthLine } from "@/lib/risk";
import { Btn, OrbDisc, Tag, Unavailable } from "@/components/pb";
import { BadgeTag, CapacityCard, EvidenceGateBox } from "@/components/risk/RiskBits";
import { StatusTag, useRegistry } from "@/components/micro/parts";
import { mechanismById } from "@/lib/micro";

const STEP_MS = 1400;
const FIT_WAIT_MS = 10000;
const FIT_ID = "generic_ai_fit";
const NO_PROPOSAL = "no-proposal";

function FitEvidence() {
  const reg = useRegistry();
  const m = mechanismById(reg.data, FIT_ID);
  if (!m) return null;
  return (
    <div data-testid="fit-evidence" className="pb-small pb-pretty" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap", marginBottom: "var(--sp-4)", color: "var(--text-2)" }}>
      <StatusTag m={m} prefix={m.name} />
      <span>{m.claim} {m.actions_allowed.text}</span>
    </div>
  );
}

export default function GenericFit() {
  const s = useStore();
  const [pick, setPick] = useState(() => (s.question && s.equity ? { q: s.question, eq: s.equity } : null));
  const liveKey = pickKey(s.question, s.equity);
  const key = pick ? pickKey(pick.q, pick.eq) : null;
  if (liveKey && liveKey !== key) setPick({ q: s.question!, eq: s.equity! });
  if (!pick) {
    return (
      <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: "var(--sp-8)" }}>
        <div className="pb-card" style={{ maxWidth: 720, padding: "var(--sp-6)", display: "flex", flexDirection: "column", gap: "var(--sp-3)", alignItems: "flex-start" }}>
          <FitEvidence />
          <h2 className="pb-h3">No market or stock is selected.</h2>
          <p className="pb-body" style={{ margin: 0 }}>Select a market and a stock on the Build page. The pipeline then fits an algo to them on the history of that market.</p>
          <Btn href="/build" style={{ marginTop: "var(--sp-2)" }}>Open Build</Btn>
        </div>
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
  const voiceProp = proposalForPick(s.voiceProposal, q, e) ? s.voiceProposal : null;
  const step = voiceProp ? 6 : stepN;
  const [timedOut, setTimedOut] = useState(false);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const [ack, setAck] = useState<{ id: string; on: boolean } | null>(null);
  const [prepNonce, setPrepNonce] = useState(0);
  const openingRef = useRef(false);
  const { runFit } = s;
  const reg = useRegistry();
  const fitMech = mechanismById(reg.data, FIT_ID);

  const fit = s.fit && s.fit.key === `${q.id}|${e.t}` ? s.fit : null;
  const fitOk = fit?.status === "ok" && !!fit.data;
  const settled = fit != null && fit.status !== "loading";
  const mode: "fit" | "nofit" | "pending" = fitOk ? "fit" : timedOut || settled ? "nofit" : "pending";
  const fitOkRef = useRef(fitOk);
  useEffect(() => { fitOkRef.current = fitOk; });

  useEffect(() => {
    runFit(q, e);
    const t = setTimeout(() => { if (!fitOkRef.current) setTimedOut(true); }, FIT_WAIT_MS);
    return () => clearTimeout(t);
  }, [runFit, q, e]);

  const applied = runnableFit(fitOk ? fit!.data : null);
  const runs = algoRunLabel(applied);
  const gateOff = feeGateOff(q, e, applied);
  const { guards } = s.settings;
  const acct = brokerLabel(s.account);
  const noDir = !e.direction;

  const done0 = step >= 6;
  const terms = (() => {
    if (noDir || !done0) return null;
    try { return hedgeTerms(q, e, s.settings.maxHedge, applied, { closedPmHedge: s.closedPmHedge, actOnUnvalidated: s.actOnUnvalidated }); } catch { return null; }
  })();
  const prep = useAsync(terms && !voiceProp ? `prep:${prepNonce}:${JSON.stringify(terms)}` : null, () => prepareHedgeProposal(terms!));
  const proposal = voiceProp ?? prep.data;
  const marketGate = proposal ? evidenceGate(proposal.evidence) : null;
  const gate = proposal || prep.error ? fitEvidenceGate(marketGate, fitMech) : null;
  const ackId = proposal?.id ?? NO_PROPOSAL;
  const acked = ack?.id === ackId && ack.on;
  const approvedAcked = proposal?.status === "approved" && !!proposal.ack_unvalidated;
  const evidencePending = !!terms && prep.loading;
  const ackBlocked = evidencePending || (!!gate?.needsAck && !acked && !approvedAcked);
  const overrideOn = !!terms?.actOnUnvalidated;
  const capView = proposal ? capacityFromProposal(proposal.capacity) : null;
  const capFit = proposal ? capitalFitView(proposal.capacity) : null;

  const goBridge = async () => {
    if (openingRef.current || ackBlocked) return;
    openingRef.current = true;
    setOpening(true);
    setOpenError(null);
    try {
      await s.openBridge(q, e, inst, { ackUnvalidated: acked || approvedAcked, proposal: voiceProp });
      router.push("/bridge");
    } catch (err) {
      openingRef.current = false;
      setOpening(false);
      const evid = isEvidenceError(err);
      setOpenError(`${evid ? "The evidence gate stopped the approval" : "The bridge did not open"}: ${err instanceof Error ? err.message : String(err)}. ${evid ? "Read the evidence status and try again." : "Try again."}`);
      if (evid) { setAck(null); setPrepNonce((n) => n + 1); }
    }
  };

  const done = step >= 6;
  useEffect(() => {
    if (done || mode === "pending") return;
    const t = setTimeout(() => setStep((n) => Math.min(6, n + 1)), STEP_MS);
    return () => clearTimeout(t);
  }, [step, done, mode]);

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
    <main className="pb-page" style={{ paddingTop: "var(--sp-7)", paddingBottom: "var(--sp-8)" }}>
      <div style={{ maxWidth: 880, display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
      <FitEvidence />
      <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-5)", width: "100%" }}>
        <OrbDisc state={orb} disc={96} orb={72} />
        <div style={{ minWidth: 0 }}>
          <div className="pb-num" style={{ fontSize: "var(--fs-13)", fontWeight: 500, color: "var(--faint)" }}>{done ? "Approval necessary" : `Step ${Math.min(step + 1, 6)} of 6`}</div>
          <h2 className="pb-h2 pb-balance" style={{ marginTop: "var(--sp-1)" }}>
            {done ? (noDir ? `Select the outcome that hurts ${e.t}` : `Approve the ${e.t} bridge`) : mode === "pending" ? "Fitting an algo to the event…" : cur.name + "…"}
          </h2>
        </div>
      </div>
      <div style={{ marginTop: "var(--sp-4)", minHeight: 20, display: "flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
        {mode === "fit" && fit?.data && (
          <>
            <Tag tone={aiStatus(fit.data).live ? "ai" : "neutral"} title={aiTitle(aiStatus(fit.data))}>{aiLabel(aiStatus(fit.data))}</Tag>
            <Tag tone={fit.data.ticks_source === "live_history" ? "measured" : fit.data.ticks_source === "replay" ? "replay" : "neutral"}>
              {fit.data.ticks_source === "live_history" ? "real price history" : fit.data.ticks_source === "replay" ? "replay ticks" : "no price history"}
            </Tag>
            {fit.data.family && fit.data.score != null && (() => {
              const sv = fitScoreView(fit.data);
              return <Tag tone={sv.tone === "positive" ? "ai" : "neutral"} title={sv.title}>{sv.short}</Tag>;
            })()}
          </>
        )}
        {mode === "nofit" && fit?.noDirection && <Tag tone="neutral" title={fit.error ?? undefined}>no hedge fit, direction unknown</Tag>}
        {mode === "nofit" && !fit?.noDirection && <Tag tone="caution" title={`POST /pipeline/fit ${fit?.error ? "did not complete: " + fit.error : "did not answer in time"}.`}>no fit, engine default spec</Tag>}
      </div>
      {mode !== "fit" && fit?.status === "error" && !fit.noDirection && (
        <Unavailable what="The fit (POST /pipeline/fit)" error={fit.error} onRetry={() => s.retryFit(q, e)} style={{ marginTop: "var(--sp-3)" }} />
      )}
      {mode === "nofit" && fit?.status === "loading" && <div className="pb-small" style={{ marginTop: "var(--sp-3)" }}>The fit continues to run. When it answers, it replaces these steps.</div>}
      <div id={VOICE_ANCHOR.steps} className="pb-card pb-list" style={{ width: "100%", marginTop: "var(--sp-5)", overflow: "hidden", scrollMarginTop: 90 }}>
        {steps.map((st, i) => {
          const d = i < step, a = i === step && !done;
          const text = d || a ? (mode === "pending" && a ? "Waiting for the fit…" : st.text) : "";
          return (
            <div key={st.key} style={{ display: "grid", gridTemplateColumns: "24px minmax(110px,190px) minmax(0,1fr)", gap: "var(--sp-4)", alignItems: "start", minHeight: 46, boxSizing: "border-box", padding: "var(--sp-3) var(--sp-5)", background: a ? "var(--surface-2)" : "transparent" }}>
              <span className="pb-num" style={{ width: 22, height: 22, boxSizing: "border-box", borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "var(--fs-12)", fontWeight: 600, background: a ? "var(--ink)" : d ? "var(--up-tint)" : "var(--track)", color: a ? "#fff" : d ? "var(--up-ink)" : "var(--faint)" }}>{d ? "✓" : i + 1}</span>
              <span style={{ fontSize: "var(--fs-14)", fontWeight: 600, color: d || a ? "var(--ink)" : "var(--faint)", lineHeight: "22px" }}>{st.name}</span>
              <span className="pb-pretty" style={{ fontSize: "var(--fs-13)", lineHeight: 1.5, color: "var(--text-2)", paddingTop: 2, minWidth: 0, overflowWrap: "anywhere" }}>{text}{a && <span className="pb-caret" />}</span>
            </div>
          );
        })}
      </div>
      {done && (
        <div id={VOICE_ANCHOR.approval} className="pb-body" style={{ scrollMarginTop: 90, width: "100%", boxSizing: "border-box", marginTop: "var(--sp-6)", paddingTop: "var(--sp-5)", borderTop: "1px solid var(--border-strong)", display: "flex", flexDirection: "column", gap: "var(--sp-3)" }}>
          {noDir ? (
            <div style={{ color: "var(--warn)" }}>
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
              {prep.error && <div className="pb-small" style={{ color: "var(--warn)" }}>The app could not read the proposal ({prep.error}). The evidence gate of the backend still applies when you approve.</div>}
              {overrideOn && (
                <div data-testid="approval-override" className="pb-small" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap", color: "var(--warn)", marginBottom: "var(--sp-3)" }}>
                  <Tag tone="caution" title="Weekend mode on Build stages hedge B on a market that has no validated expected gap.">override on</Tag>
                  <span className="pb-pretty">{OVERRIDE_ON_LINE} No staged order executes until you press Approve plan.</span>
                </div>
              )}
              <EvidenceGateBox gate={gate} loading={prep.loading} acknowledged={approvedAcked} ack={acked} onAck={(on) => setAck({ id: ackId, on })} copy={fitAckCopy(e.t, fitMech, marketGate, { override: overrideOn })} />
              {prep.loading && <div className="pb-small" style={{ marginTop: "var(--sp-3)" }}>Checking the liquidity and the capital budget…</div>}
              {capView && (
                <CapacityCard view={capView} title={`Liquidity and capacity for ${e.t}`}
                  tag={<Tag tone={proposal?.capacity?.source === "live" ? "live" : "sim"} title={proposal?.capacity?.label}>{proposal?.capacity?.source === "live" ? "live numbers" : "cached numbers"}</Tag>}
                  extra={pmDepthLine(proposal?.capacity) && <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{pmDepthLine(proposal?.capacity)}</div>}
                  footer={capFit && (
                    <div style={{ marginTop: "var(--sp-3)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)" }}>
                      <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}><span className="pb-h4" style={{ fontSize: "var(--fs-13)" }}>Capital budget</span><BadgeTag b={capFit.badge} /></div>
                      <div className="pb-small pb-num" style={{ marginTop: "var(--sp-1)" }}>{capFit.lines.map((l) => <div key={l}>{l}</div>)}</div>
                      {capFit.badge.tone === "caution" && <div className="pb-small" style={{ color: "var(--warn)", marginTop: "var(--sp-1)" }}>The app stops each order that goes above a budget before it sends the order (capital_budget).</div>}
                    </div>
                  )} />
              )}
            </div>
          )}
          {gateOff && !noDir && (
            <div style={{ color: "var(--warn)" }}>
              Fee gate off: {e.t} has no {e.px ? "impact estimate" : "quote"}. Thus the engine cannot compare an order with its fees and trades on probability only.
              {guards.edge && " Your “act only when edge beats fees” guardrail is on, thus you must approve this bridge."}
            </div>
          )}
          {guards.auto && <div className="pb-small" data-testid="fit-no-auto">Auto-approve is on, but it never applies to the generic AI fit{fitMech ? ` (${fitMech.status_label})` : ""}. Select the acknowledgement and approve.</div>}
          {openError && <div role="alert" className="pb-small" style={{ color: "var(--down)" }}>{openError}</div>}
        </div>
      )}
      {done && noDir ? (
        <Btn href="/build" kind="secondary" style={{ marginTop: "var(--sp-5)" }}>Select the outcome on Build</Btn>
      ) : (
      <button type="button" onClick={() => (done ? void goBridge() : setStep(6))} disabled={done && ackBlocked} title={done && ackBlocked ? (evidencePending ? "The app reads the evidence status of this proposal first." : "Select the acknowledgement above: the generic AI fit is unvalidated.") : undefined} className={`pb-btn ${done ? (ackBlocked ? "pb-btn-disabled" : "pb-btn-primary") : "pb-btn-secondary"}`} style={{ marginTop: "var(--sp-5)" }}>
        {opening ? "Opening the bridge…" : !done ? "Go to approval" : evidencePending ? "Checking the evidence…" : proposal?.status === "approved" ? "Open approved bridge" : ackBlocked ? "Acknowledge the unvalidated fit to approve" : gateOff ? `Approve without the fee gate${acked ? " (unvalidated)" : ""}` : "Approve the unvalidated fit"}
      </button>
      )}
      </div>
    </main>
  );
}
