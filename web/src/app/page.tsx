"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Btn } from "@/components/pb";
import { StatusTag, useRegistry } from "@/components/micro/parts";
import { mechanismById } from "@/lib/micro";
import { useStore } from "@/lib/store";

const body = { margin: 0, fontSize: 16, lineHeight: 1.5, color: "var(--text-2)" } as const;

const MECHANISM_LINES = ["ladders", "touch", "btc_15min", "generic_ai_fit", "other"] as const;

const BRIER = { poly: 0.0938, options: 0.0831, diff: 0.0108, lo: 0.0064, hi: 0.0158 };

function useWidth<T extends HTMLElement>(initial: number) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function Axis({ x, y, ticks, fmt, label, x0, x1 }: { x: (v: number) => number; y: number; ticks: number[]; fmt: (v: number) => string; label: string; x0: number; x1: number }) {
  return (
    <g>
      <line x1={x0} x2={x1} y1={y} y2={y} stroke="var(--border-strong)" />
      {ticks.map((t) => (
        <g key={t} transform={`translate(${x(t)},${y})`}>
          <line y2={5} stroke="var(--border-strong)" />
          <text y={19} textAnchor="middle" fontSize={12} fill="var(--faint)" style={{ fontVariantNumeric: "tabular-nums" }}>{fmt(t)}</text>
        </g>
      ))}
      <text x={x0} y={y + 38} fontSize={12} fill="var(--text-2)">{label}</text>
    </g>
  );
}

function BrierFigure() {
  const [ref, w] = useWidth<HTMLDivElement>(520);
  const pad = 14;
  const x0 = pad, x1 = Math.max(w - pad, x0 + 200);
  const scale = (d0: number, d1: number) => (v: number) => x0 + ((v - d0) / (d1 - d0)) * (x1 - x0);
  const xs = scale(0.075, 0.1);
  const xd = scale(-0.005, 0.02);
  const f4 = (v: number) => v.toFixed(3);
  const sgn = (v: number) => (v > 0 ? "+" : v < 0 ? "\u2212" : "") + Math.abs(v).toFixed(3);
  const narrow = w < 420;
  const scoreTicks = narrow ? [0.075, 0.085, 0.095] : [0.075, 0.08, 0.085, 0.09, 0.095, 0.1];
  const diffTicks = narrow ? [0, 0.01, 0.02] : [-0.005, 0, 0.005, 0.01, 0.015, 0.02];
  const H1 = 118, H2 = 148;
  return (
    <figure className="pb-card" style={{ margin: 0, padding: "var(--sp-5)" }}>
      <div ref={ref} style={{ width: "100%" }}>
        <div className="pb-h4" style={{ fontSize: 14 }}>Brier score by source</div>
        <svg width={w} height={H1} role="img" aria-label="Brier score: options 0.0831, Polymarket 0.0938. A lower score is better." style={{ display: "block", overflow: "visible", marginTop: 8 }}>
          {[{ k: "Options", v: BRIER.options, fill: "var(--ink)" }, { k: "Polymarket", v: BRIER.poly, fill: "var(--surface)" }].map((d) => (
            <g key={d.k} transform={`translate(${xs(d.v)},44)`}>
              <line y1={-14} y2={18} stroke="var(--border)" />
              <text y={-30} textAnchor="middle" fontSize={13} fontWeight={600} fill="var(--ink)">{d.k}</text>
              <text y={-15} textAnchor="middle" fontSize={12} fill="var(--text-2)" style={{ fontVariantNumeric: "tabular-nums" }}>{d.v.toFixed(4)}</text>
              <circle r={6} cy={2} fill={d.fill} stroke="var(--ink)" strokeWidth={1.5} />
            </g>
          ))}
          <Axis x={xs} y={66} ticks={scoreTicks} fmt={f4} label="Brier score, lower is better" x0={x0} x1={x1} />
        </svg>
        <div className="pb-h4" style={{ fontSize: 14, marginTop: 24 }}>Difference, Polymarket minus options</div>
        <svg width={w} height={H2} role="img" aria-label="Difference +0.0108, 95% confidence interval +0.0064 to +0.0158. The interval does not include 0." style={{ display: "block", overflow: "visible", marginTop: 8 }}>
          <line x1={xd(0)} x2={xd(0)} y1={10} y2={96} stroke="var(--faint)" strokeDasharray="3 3" />
          <text x={xd(0) + 6} y={22} fontSize={12} fill="var(--faint)">No difference</text>
          <rect x={xd(BRIER.lo)} y={44} width={xd(BRIER.hi) - xd(BRIER.lo)} height={12} rx={2} fill="var(--accent-tint)" stroke="var(--accent)" strokeWidth={1} />
          <line x1={xd(BRIER.diff)} x2={xd(BRIER.diff)} y1={38} y2={62} stroke="var(--ink)" strokeWidth={2} />
          <text x={xd(BRIER.diff)} y={30} textAnchor="middle" fontSize={13} fontWeight={600} fill="var(--ink)" style={{ fontVariantNumeric: "tabular-nums" }}>+{BRIER.diff.toFixed(4)}</text>
          <text x={(xd(BRIER.lo) + xd(BRIER.hi)) / 2} y={76} textAnchor="middle" fontSize={12} fill="var(--text-2)" style={{ fontVariantNumeric: "tabular-nums" }}>95% CI +{BRIER.lo.toFixed(4)} to +{BRIER.hi.toFixed(4)}</text>
          <Axis x={xd} y={96} ticks={diffTicks} fmt={sgn} label="Polymarket score minus options score" x0={x0} x1={x1} />
        </svg>
      </div>
      <figcaption className="pb-small pb-pretty" style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)", color: "var(--faint)" }}>
        n = 4,561 markets and 89 resolution dates. The bar shows the 95% confidence interval.
      </figcaption>
    </figure>
  );
}

export default function Landing() {
  const router = useRouter();
  const s = useStore();
  const reg = useRegistry();
  const [opening, setOpening] = useState(false);
  const mechs = MECHANISM_LINES.map((id) => mechanismById(reg.data, id)).filter((m) => m != null);
  const fit = mechanismById(reg.data, "generic_ai_fit");
  const watchWeekend = async () => {
    if (opening) return;
    setOpening(true);
    try { await s.openWeekendReplay(); router.push("/build"); }
    finally { setOpening(false); }
  };
  return (
    <main className="pb-page" style={{ paddingTop: 80, paddingBottom: 96 }}>
      <header style={{ maxWidth: 820 }}>
        <h1 className="pb-h1 pb-balance">Check thin prediction-market books against their own logic and the options chain.</h1>
        <p className="pb-pretty" style={{ ...body, marginTop: 24, fontSize: 20, lineHeight: 1.5, maxWidth: 640 }}>
          PolyBridge watches Polymarket date ladders and &ldquo;will it hit&rdquo; stock tickets. It compares each one with its own date logic or with listed options, and drafts proposals for your approval. Every line below carries the status of its own test.
        </p>
      </header>

      <section className="pb-split" style={{ marginTop: 96 }}>
        <h2 className="pb-h3 pb-balance" style={{ maxWidth: 400 }}>What PolyBridge acts on, and how far each was tested</h2>
        <ol data-testid="landing-mechanisms" style={{ margin: 0, padding: 0, listStyle: "none", borderTop: "1px solid var(--border-strong)" }}>
          {reg.loading && <li className="pb-small" style={{ padding: "16px 0" }}>Reading the evidence registry…</li>}
          {!reg.loading && !mechs.length && <li className="pb-small" style={{ padding: "16px 0" }}>The evidence registry (GET /evidence/mechanisms) did not answer, so no status is shown. See What we tested.</li>}
          {mechs.map((m, i) => (
            <li key={m.id} style={{ display: "grid", gridTemplateColumns: "40px minmax(0,1fr)", gap: 8, padding: "16px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="pb-serif" style={{ fontSize: 20, lineHeight: 1.2, color: "var(--faint)", fontVariantNumeric: "lining-nums" }}>{i + 1}</span>
              <span style={{ display: "grid", gap: 6, minWidth: 0 }}>
                <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <span style={{ ...body, fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>{m.name}</span>
                  <StatusTag m={m} />
                </span>
                <span className="pb-pretty" style={{ ...body, fontSize: 15 }}>{m.claim} {m.actions_allowed.text}</span>
              </span>
            </li>
          ))}
          <li style={{ display: "grid", gridTemplateColumns: "40px minmax(0,1fr)", gap: 8, padding: "16px 0", borderBottom: "1px solid var(--border)" }}>
            <span />
            <span className="pb-pretty" style={{ ...body, fontSize: 16, color: "var(--ink)" }}>No order goes to your broker until you approve it.</span>
          </li>
        </ol>
      </section>

      <section className="pb-split" style={{ marginTop: 96, alignItems: "start" }}>
        <div style={{ display: "grid", gap: 16, maxWidth: 520 }}>
          <h2 className="pb-h3">Which price is more accurate</h2>
          <p className="pb-pretty" style={body}>
            We tested 4,561 Polymarket stock markets that no earlier test used. The options-implied probability was more accurate than the Polymarket price.
          </p>
          <p className="pb-pretty" style={body}>
            The Brier score measures the error of a probability, and a lower score is better. The Polymarket score was higher than the options score.
          </p>
          <p className="pb-pretty" style={{ ...body, fontSize: 14, color: "var(--faint)" }}>
            Our lead-lag studies do not show that prediction markets move before stocks. PolyBridge uses the probability, not a time advantage.
          </p>
        </div>
        <BrierFigure />
      </section>

      <section style={{ marginTop: 96, paddingTop: 32, borderTop: "1px solid var(--border-strong)" }}>
        <h2 className="pb-h3">What you can do now</h2>
        <div className="pb-split" style={{ marginTop: 24 }}>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn href="/pipeline">Open the ladder board</Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>Polymarket date ladders in date order, with the nesting checks and any violation after fees.</p>
          </div>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn href="/bridge" kind="secondary">Open the ticket board</Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>&ldquo;Will it hit&rdquo; tickets linked to an option expiry and its two bracketing strikes, against the options reference.</p>
          </div>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn href="/tested" kind="secondary">What we tested</Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>Every mechanism, its status, and each number with its range and sample.</p>
          </div>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn href="/build" kind="secondary">Build a bridge (generic AI fit)</Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>Select a market and a stock. PolyBridge makes a hedge for your approval, behind the acknowledgement. <StatusTag m={fit} /></p>
          </div>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn kind={opening ? "disabled" : "secondary"} onClick={() => void watchWeekend()}
              title={`A recorded replay of the generic AI fit${fit ? ` (${fit.status_label})` : ""}. No order goes to the broker until you approve it.`}>
              {opening ? "Wait for the replay" : "Watch the weekend replay"}
            </Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>See a recorded bridge for the April 2025 tariff weekend. It connects the market for a US recession in 2025 to SPY.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
