"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { shortlist } from "@/lib/library";
import { demoSteps, fitSteps, type PipeContext } from "@/lib/pipeline";
import { defaultPick, useStore } from "@/lib/store";
import { DemoTag, OrbDisc, Tag } from "@/components/pb";

const STEP_MS = 1400;
const FIT_WAIT_MS = 10000;

export default function Pipeline() {
  const router = useRouter();
  const s = useStore();
  const [{ q, eq: e }] = useState(() => (s.question && s.equity ? { q: s.question, eq: s.equity } : defaultPick()));
  const inst = s.inst ?? "shares";
  const [step, setStep] = useState(0);
  const [timedOut, setTimedOut] = useState(false);
  const [opening, setOpening] = useState(false);
  const openingRef = useRef(false);
  const { runFit } = s;

  const fit = s.fit && s.fit.key === `${q.id}|${e.t}` ? s.fit : null;
  const fitOk = fit?.status === "ok" && !!fit.data;
  const settled = fit != null && fit.status !== "loading";
  const mode: "fit" | "demo" | "pending" = fitOk ? "fit" : settled || timedOut ? "demo" : "pending";

  useEffect(() => {
    runFit(q, e);
    const t = setTimeout(() => setTimedOut(true), FIT_WAIT_MS);
    return () => clearTimeout(t);
  }, [runFit, q, e]);

  const goBridge = async () => {
    if (openingRef.current) return;
    openingRef.current = true;
    setOpening(true);
    await s.openBridge(q, e, inst);
    router.push("/bridge");
  };
  const goRef = useRef(goBridge);
  useEffect(() => { goRef.current = goBridge; });

  const done = step >= 6;
  useEffect(() => {
    if (done) {
      const t = setTimeout(() => void goRef.current(), STEP_MS);
      return () => clearTimeout(t);
    }
    if (mode === "pending") return;
    const t = setTimeout(() => setStep((n) => Math.min(6, n + 1)), STEP_MS);
    return () => clearTimeout(t);
  }, [step, done, mode]);

  const ctx: PipeContext = {
    question: q.q, venues: q.venues, yes: q.yes, vol: q.vol, ticker: e.t, held: e.held || 500,
    move: e.move, rev: e.rev, brand: e.brand, why: e.why,
    shortlisted: fitOk && s.library.data ? shortlist(s.library.data, String(fit!.data!.event_class)).map((r) => r.id) : undefined,
  };
  const steps = mode === "fit" ? fitSteps(fit!.data!, ctx) : demoSteps(ctx);
  const cur = steps[Math.min(step, steps.length - 1)];
  const orb = done ? "breathing" : cur.orb;

  return (
    <main className="pb-page" style={{ maxWidth: 820, paddingTop: 30, paddingBottom: 80, display: "flex", flexDirection: "column", alignItems: "center" }}>
      <OrbDisc state={orb} disc={220} orb={170} />
      <div className="pb-label" style={{ marginTop: 26 }}>{done ? "BRIDGE READY" : `STEP ${Math.min(step + 1, 6)} OF 6`}</div>
      <h2 className="pb-serif pb-balance" style={{ margin: "10px 0 0", fontSize: 40, letterSpacing: "-.015em", fontWeight: 400, textAlign: "center" }}>
        {done ? `${e.t} is bridged to the market` : mode === "pending" ? "Fitting an algo to the event…" : cur.name + "…"}
      </h2>
      <div style={{ marginTop: 10, minHeight: 20, display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
        {mode === "fit" && fit?.data && (
          <>
            <Tag tone="ai" title="POST /pipeline/fit">{fit.data.llm === "gemini" ? "AI estimate · Gemini" : "rules-based fit"}</Tag>
            <Tag tone={fit.data.ticks_source === "live_history" ? "measured" : fit.data.ticks_source === "replay" ? "replay" : "neutral"}>
              {fit.data.ticks_source === "live_history" ? "real price history" : fit.data.ticks_source === "replay" ? "replay ticks" : "no price history"}
            </Tag>
          </>
        )}
        {mode === "demo" && <DemoTag what="scripted demo steps" title={`POST /pipeline/fit ${fit?.error ? "failed: " + fit.error : "did not answer in time"}; showing the prototype's scripted pipeline.`} />}
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
      <button type="button" onClick={() => void goBridge()} className={`pb-btn ${done ? "pb-btn-primary" : "pb-btn-secondary"}`} style={{ height: 50, padding: "0 24px", marginTop: 22, transition: "all .3s ease", color: done ? "#fff" : "#3C4458" }}>
        {opening ? "Opening the bridge…" : done ? "Open the live bridge" : "Skip to the bridge"} <span className="pb-arrow">→</span>
      </button>
    </main>
  );
}
