// Presentational pieces of the Bridge screen, shared by the demo simulator and the live SSE view.
import type { ReactNode } from "react";
import { LOGO } from "@/lib/demo";
import { Glass, Label, OrbDisc, Spark } from "@/components/pb";

const panelPad = { minWidth: 0, padding: "24px 26px 22px" };
const big = { fontSize: "clamp(38px,4vw,56px)", fontWeight: 400, letterSpacing: "-.02em", lineHeight: 1 } as const;
const footer = { display: "flex", justifyContent: "space-between", gap: 10, marginTop: 18, paddingTop: 14, borderTop: "1px solid rgba(15,22,38,.08)", fontSize: 12, color: "#5A627A" } as const;

function Venue({ name, on }: { name: "Polymarket" | "Kalshi"; on: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 9px 3px 7px", borderRadius: 999, background: on ? "rgba(59,108,246,.12)" : "rgba(15,22,38,.07)", color: on ? "#2B57D6" : undefined }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={LOGO(name === "Polymarket" ? "polymarket.com" : "kalshi.com").replace("128", "64")} alt="" style={{ width: 12, height: 12, borderRadius: 3 }} />{name}
    </span>
  );
}

export function TopRow(p: {
  question: string; venues: string[]; pBig: string; pSub: ReactNode; pSpark: number[]; volLabel: string; volValue: ReactNode; marketTag?: ReactNode;
  orb: string; nodeLabel: string; nodeLines: ReactNode;
  instShort: string; exchange: string; ticker: string; name: string; px: string; pxDelta: ReactNode; pxColor: string; pxSpark: number[]; driftLabel: string; drift: ReactNode; equityTag?: ReactNode;
}) {
  return (
    <div className="pb-bridge-top" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) clamp(20px,5vw,72px) minmax(170px,240px) clamp(20px,5vw,72px) minmax(0,1fr)", alignItems: "center" }}>
      <Glass style={panelPad}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, color: "#5A627A", fontWeight: 500, gap: 8, flexWrap: "wrap" }}>
          <span className="pb-mono" style={{ letterSpacing: ".08em" }}>01 · PREDICTION MARKET</span>
          <span style={{ display: "inline-flex", gap: 6 }}>
            <Venue name="Polymarket" on={p.venues[0] !== "Kalshi"} />
            <Venue name="Kalshi" on={p.venues[0] === "Kalshi"} />
          </span>
        </div>
        <div className="pb-serif pb-pretty" style={{ fontSize: 25, fontWeight: 400, letterSpacing: "-.01em", lineHeight: 1.2, marginTop: 14 }}>{p.question}</div>
        {p.marketTag && <div style={{ marginTop: 8 }}>{p.marketTag}</div>}
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 22, gap: 12 }}>
          <div>
            <div className="pb-serif pb-tab" style={big}>{p.pBig}</div>
            <div style={{ fontSize: 12, color: "#5A627A", marginTop: 8 }}>{p.pSub}</div>
          </div>
          <Spark data={p.pSpark} color="#3B6CF6" />
        </div>
        <div style={footer}><span>{p.volLabel}</span><span style={{ color: "#0F1626", fontWeight: 500 }}>{p.volValue}</span></div>
      </Glass>
      <div className="pb-connector" style={{ position: "relative", height: 2, background: "rgba(59,108,246,.18)" }}>
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg,rgba(59,108,246,0),#3B6CF6,rgba(59,108,246,0))", backgroundSize: "200% 100%", animation: "pb-shimmer 2.2s linear infinite" }} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, textAlign: "center", padding: "10px 0" }}>
        <OrbDisc state={p.orb} disc={170} orb={130} />
        <Label style={{ marginTop: 6 }}>{p.nodeLabel}</Label>
        <div style={{ fontSize: 12, color: "#5A627A", lineHeight: 1.45 }}>{p.nodeLines}</div>
      </div>
      <div className="pb-connector" style={{ position: "relative", height: 2, background: "rgba(224,72,90,.18)" }}>
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg,rgba(224,72,90,0),#E0485A,rgba(224,72,90,0))", backgroundSize: "200% 100%", animation: "pb-shimmer 2.2s linear infinite .6s" }} />
      </div>
      <Glass style={panelPad}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, color: "#5A627A", fontWeight: 500, gap: 8, flexWrap: "wrap" }}>
          <span className="pb-mono" style={{ letterSpacing: ".08em" }}>03 · EQUITY · {p.exchange}</span>
          <span style={{ padding: "3px 9px", borderRadius: 999, background: "rgba(15,22,38,.07)" }}>{p.instShort}</span>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          <span style={{ fontSize: 21, fontWeight: 600, letterSpacing: "-.025em" }}>{p.ticker}</span>
          <span style={{ fontSize: 13, color: "#5A627A" }}>{p.name}</span>
          {p.equityTag}
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 22, gap: 12 }}>
          <div>
            <div className="pb-serif pb-tab" style={big}>{p.px}</div>
            <div style={{ fontSize: 12, marginTop: 8, fontWeight: 500, color: p.pxColor }}>{p.pxDelta}</div>
          </div>
          <Spark data={p.pxSpark} color="#0F1626" />
        </div>
        <div style={footer}><span>{p.driftLabel}</span><span style={{ color: "#0F1626", fontWeight: 500 }}>{p.drift}</span></div>
      </Glass>
    </div>
  );
}

export interface DockAlgo { name: string; status: string; line: string; active: boolean }
export function AlgoDock({ label, algos, tag }: { label: string; algos: DockAlgo[]; tag?: ReactNode }) {
  // The data tags sit on their own line above the pill, so the label stays short and the six capsules keep to one
  // row like the prototype's dock instead of wrapping around a wide tag cluster.
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
    {tag && <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, flexWrap: "wrap", padding: "0 8px" }}>{tag}</div>}
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 8, borderRadius: 999, background: "rgba(255,255,255,.5)", backdropFilter: "blur(28px) saturate(1.6)", WebkitBackdropFilter: "blur(28px) saturate(1.6)", border: "1px solid rgba(255,255,255,.85)", boxShadow: "inset 0 1px 0 rgba(255,255,255,.95),0 16px 40px rgba(40,60,120,.10)", flexWrap: "wrap" }}>
      <span className="pb-mono" style={{ padding: "0 10px 0 14px", fontSize: 11, letterSpacing: ".08em", color: "#5A627A", whiteSpace: "nowrap" }}>{label}</span>
      {algos.map((a) => (
        <div key={a.name} style={{ flex: 1, minWidth: 170, display: "flex", flexDirection: "column", gap: 2, padding: "9px 14px", borderRadius: 999, background: a.active ? "rgba(255,255,255,.85)" : "rgba(255,255,255,.35)", border: `1px solid ${a.active ? "rgba(59,108,246,.35)" : "rgba(255,255,255,.7)"}`, transition: "all .3s ease" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12.5, fontWeight: 600, letterSpacing: "-.01em", whiteSpace: "nowrap", minWidth: 0 }}>
            <span className="pb-ellipsis" style={{ minWidth: 0 }}>{a.name}</span>
            <span style={{ color: a.active ? "#22A06B" : "#5A627A", fontWeight: 500, flex: "none" }}>{a.status}</span>
          </div>
          <div className="pb-ellipsis" style={{ fontSize: 11, color: "#5A627A" }}>{a.line}</div>
        </div>
      ))}
    </div>
    </div>
  );
}

export function PortfolioPanel(p: {
  big: string; bigColor: string; bigNote: string; left: [string, string, string]; right: [string, string, string]; ratio: number; ratioLabel?: string; footL: ReactNode; footR: ReactNode; tag?: ReactNode;
}) {
  return (
    <Glass style={{ padding: "22px 26px", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}><Label>05 · PORTFOLIO</Label>{p.tag}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 10 }}>
        <span className="pb-serif" style={{ fontSize: 46, fontWeight: 400, letterSpacing: "-.02em", lineHeight: 1, color: p.bigColor }}>{p.big}</span>
        <span style={{ fontSize: 12, color: "#5A627A" }}>{p.bigNote}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 20 }}>
        {[p.left, p.right].map(([a, b, c]) => (
          <div key={a} className="pb-sub" style={{ padding: "12px 14px" }}>
            <div style={{ fontSize: 11, color: "#5A627A" }}>{a}</div>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 2, letterSpacing: "-.02em" }}>{b}</div>
            <div style={{ fontSize: 11, color: "#5A627A" }}>{c}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#5A627A" }}><span>{p.ratioLabel ?? "Event exposure covered"}</span><span style={{ color: "#0F1626", fontWeight: 600 }}>{p.ratio}%</span></div>
        <div className="pb-bar" style={{ height: 8, marginTop: 8 }}><div style={{ width: `${p.ratio}%` }} /></div>
      </div>
      <div style={{ marginTop: "auto", paddingTop: 18, display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12, color: "#5A627A", flexWrap: "wrap" }}><span>{p.footL}</span><span>{p.footR}</span></div>
    </Glass>
  );
}

export interface TradeCard { id: string | number; side: "SELL" | "BUY" | "HOLD"; time: string; head: ReactNode; algo: string; reason: string }
export function TradesPanel({ trades, empty, tag }: { trades: TradeCard[]; empty?: string; tag?: ReactNode }) {
  return (
    <Glass style={{ padding: "22px 26px", minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#5A627A", fontWeight: 500, gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-mono" style={{ letterSpacing: ".08em" }}>06 · TRADES &amp; REASONING</span>
        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>{tag}Why each fill happened</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
        {trades.length === 0 && empty && <div style={{ fontSize: 13, color: "#5A627A", padding: "12px 4px" }}>{empty}</div>}
        {trades.map((t) => (
          <div key={t.id} className="pb-sub" style={{ display: "grid", gridTemplateColumns: "64px minmax(0,1fr)", gap: 14, padding: "12px 14px", animation: "pb-in .4s ease-out" }}>
            <div>
              <div style={{ display: "inline-block", padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 600, color: "#fff", background: t.side === "SELL" ? "#E0485A" : t.side === "BUY" ? "#22A06B" : "#8A92A8" }}>{t.side}</div>
              <div style={{ fontSize: 11, color: "#5A627A", marginTop: 6 }}>{t.time}</div>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-.01em" }}>{t.head} <span style={{ color: "#5A627A", fontWeight: 400 }}>· {t.algo}</span></div>
              <div className="pb-pretty" style={{ fontSize: 12, color: "#3C4458", lineHeight: 1.45, marginTop: 3 }}>{t.reason}</div>
            </div>
          </div>
        ))}
      </div>
    </Glass>
  );
}
