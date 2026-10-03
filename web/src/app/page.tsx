"use client";

import { useRouter } from "next/navigation";
import { Btn, Glass, Label, Orb } from "@/components/pb";
import { LOGO } from "@/lib/demo";
import { useStore } from "@/lib/store";

const CARDS = [
  { k: "01 · REVERSE THE BRIDGE", t: "The contract is the signal, not the trade", p: "Polymarket and Kalshi put a live probability on the event itself. We read that probability and its σ — and act in the stock you hold. (Our lead-lag case studies do not show the markets moving first; the signal is the probability, not a head start.)" },
  { k: "02 · AI-COMPOSED ALGOS", t: "1,284 algorithms, chained per event", p: "An impact model sizes the move; the AI picks a compiled family of gates, readers and sizers for the event and tunes its preset on replayed history." },
  { k: "03 · YOUR FEES, YOUR TAXES", t: "Acts only when it beats the cost", p: "A fee gate holds any order whose expected benefit does not cover its cost, and every decision is explained in plain words. Tax-lot and wash-sale blocks are in the library, not yet on live bridges." },
];

export default function Landing() {
  const router = useRouter();
  const { seedDemo, library } = useStore();
  const presets = library.status === "ok" && library.data ? library.data.total : null;
  const count = presets != null ? presets.toLocaleString("en-US") : "1,284";
  return (
    <main className="pb-page" style={{ maxWidth: 1180, paddingTop: 60, paddingBottom: 80, animationDuration: ".5s" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 22 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "6px 14px 6px 8px", borderRadius: 999, background: "rgba(255,255,255,.55)", border: "1px solid rgba(255,255,255,.85)", backdropFilter: "blur(20px)", fontSize: 12.5, fontWeight: 500, color: "#2B57D6" }}>
          <Orb state="connecting" size={20} ink="#2B57D6" />
          <span style={{ display: "inline-flex", gap: 4 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={LOGO("polymarket.com").replace("128", "64")} alt="" style={{ width: 12, height: 12, borderRadius: 3 }} />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={LOGO("kalshi.com").replace("128", "64")} alt="" style={{ width: 12, height: 12, borderRadius: 3 }} />
          </span>
          Prediction markets → your portfolio
        </div>
        <h1 className="pb-serif pb-balance" style={{ margin: 0, fontSize: "clamp(44px,6vw,80px)", lineHeight: 1.02, letterSpacing: "-.02em", fontWeight: 400, maxWidth: 920 }}>Hedge the headline before it hits your stock.</h1>
        <p className="pb-pretty" style={{ margin: 0, maxWidth: 640, fontSize: 18, lineHeight: 1.5, color: "#3C4458" }}>
          Prediction markets already price the event. PolyBridge reads that signal, estimates what it does to the equities you hold, and composes a hedge from {count} {presets != null ? "compiled algorithm presets" : "proprietary algorithms"} — fee-aware, acting only when it must.
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center", marginTop: 6 }}>
          <Btn href="/build" arrow>Build a bridge</Btn>
          <Btn kind="secondary" onClick={() => { seedDemo(); router.push("/bridge"); }}>Watch a demo bridge</Btn>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,280px),1fr))", gap: 16, marginTop: 70 }}>
        {CARDS.map((c, i) => (
          <Glass key={c.k} style={{ padding: 26 }}>
            <Label rule color="#2B57D6">{c.k}</Label>
            <div className="pb-serif" style={{ fontSize: 25, fontWeight: 400, letterSpacing: "-.01em", lineHeight: 1.2, marginTop: 14 }}>{i === 1 && presets != null ? `${count} presets, chained per event` : c.t}</div>
            <p style={{ margin: "10px 0 0", fontSize: 14, lineHeight: 1.5, color: "#3C4458" }}>{c.p}</p>
          </Glass>
        ))}
      </div>
    </main>
  );
}
