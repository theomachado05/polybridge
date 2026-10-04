"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Btn } from "@/components/pb";
import { classifiedByGemini } from "@/lib/ai";
import { useStore } from "@/lib/store";

const h2 = { margin: 0, fontFamily: "var(--serif)", fontWeight: 400, fontSize: "clamp(26px,2.6vw,32px)", lineHeight: 1.15, letterSpacing: "-.01em" } as const;
const body = { margin: 0, fontSize: 15, lineHeight: 1.55, color: "var(--text-2)" } as const;

export default function Landing() {
  const router = useRouter();
  const s = useStore();
  const [opening, setOpening] = useState(false);
  const presets = s.library.status === "ok" && s.library.data ? s.library.data.total : null;
  const count = presets != null ? presets.toLocaleString("en-US") : null;
  const classify = classifiedByGemini(s.ai) ? "Gemini classifies the event."
    : s.ai.live ? "Gemini helps to classify the event. Keyword rules do each step that Gemini does not do."
    : "Keyword rules classify the event.";
  const steps = [
    "PolyBridge finds the stocks in your portfolio that the event can change.",
    `${classify} Then the C++ engine replays the applicable presets${count != null ? ` from a library of ${count}` : ""} on the history of that market.`,
    "It selects the preset with the best in-sample result and makes a hedge from it.",
    "A fee gate stops each order that costs more than its expected benefit. Tax-lot and wash-sale rules are in the library, but live bridges do not use them yet.",
    "No order goes to your broker until you approve it.",
  ];
  const watchWeekend = async () => {
    if (opening) return;
    setOpening(true);
    try { await s.openWeekendReplay(); router.push("/build"); }
    finally { setOpening(false); }
  };
  return (
    <main className="pb-page" style={{ maxWidth: 1080, paddingTop: 72, paddingBottom: 96 }}>
      <header style={{ maxWidth: 760 }}>
        <h1 className="pb-serif pb-balance" style={{ margin: 0, fontSize: "clamp(40px,5.2vw,68px)", lineHeight: 1.04, letterSpacing: "-.02em", fontWeight: 400 }}>Hedge your stocks before an event changes their price.</h1>
        <p className="pb-pretty" style={{ ...body, marginTop: 22, fontSize: 18, maxWidth: 640 }}>
          PolyBridge is a hedge tool for the stocks you hold. It reads the probability of an event, such as a recession, from prediction markets and options.
        </p>
      </header>

      <section style={{ marginTop: 64, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: "16px 56px", alignItems: "start" }}>
        <h2 style={h2}>What PolyBridge does with your stocks</h2>
        <ol style={{ margin: 0, paddingLeft: 20, listStyle: "decimal", display: "grid", gap: 12 }}>
          {steps.map((t) => <li key={t} className="pb-pretty" style={{ ...body, paddingLeft: 4 }}>{t}</li>)}
        </ol>
      </section>

      <section className="pb-glass" style={{ marginTop: 56, padding: "clamp(24px,3.5vw,40px)", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: "28px 56px", alignItems: "center" }}>
        <div style={{ display: "grid", gap: 14 }}>
          <h2 style={h2}>Which price is more accurate</h2>
          <p className="pb-pretty" style={body}>
            We tested 4,561 Polymarket stock markets that no earlier test used. The options-implied probability was more accurate than the Polymarket price.
          </p>
          <p className="pb-pretty" style={body}>
            The Brier score measures the error of a probability, and a lower score is better. The Polymarket score was higher than the options score.
          </p>
          <p className="pb-pretty" style={{ ...body, fontSize: 14, color: "var(--muted)" }}>
            Our lead-lag studies do not show that prediction markets move before stocks. PolyBridge uses the probability, not a time advantage.
          </p>
        </div>
        <dl style={{ margin: 0, display: "grid", gap: 6, paddingLeft: "clamp(0px,2vw,28px)", borderLeft: "1px solid var(--divider)" }}>
          <dt style={{ fontSize: 13, color: "var(--muted)" }}>Brier difference, Polymarket minus options</dt>
          <dd className="pb-serif pb-tab" style={{ margin: 0, fontSize: "clamp(44px,5vw,60px)", lineHeight: 1, letterSpacing: "-.02em" }}>+0.0108</dd>
          <dd className="pb-tab" style={{ margin: "6px 0 0", fontSize: 14, color: "var(--text-2)" }}>95% confidence interval +0.0064 to +0.0158</dd>
          <dd style={{ margin: 0, fontSize: 14, color: "var(--text-2)" }}>4,561 markets</dd>
        </dl>
      </section>

      <section style={{ marginTop: 56, paddingTop: 32, borderTop: "1px solid var(--hairline)" }}>
        <h2 style={h2}>What you can do now</h2>
        <div style={{ marginTop: 22, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 28 }}>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn href="/build">Build a bridge</Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>Select a market and a stock. PolyBridge makes a hedge for your approval.</p>
          </div>
          <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
            <Btn kind={opening ? "disabled" : "secondary"} onClick={() => void watchWeekend()}
              title="This market passed the out-of-sample test for the expected gap. No order goes to the broker until you approve it.">
              {opening ? "Wait for the replay" : "Watch the weekend replay"}
            </Btn>
            <p className="pb-pretty" style={{ ...body, fontSize: 14 }}>See a recorded bridge for the April 2025 tariff weekend. It connects the market for a US recession in 2025 to SPY.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
