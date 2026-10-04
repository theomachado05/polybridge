import type { CSSProperties, ReactNode } from "react";
import { LOGO } from "@/lib/brokers";
import { OrbDisc, Spark, Tag, type TagTone } from "@/components/pb";

const cell: CSSProperties = { minWidth: 0, padding: "var(--sp-5)", display: "flex", flexDirection: "column" };
const footer: CSSProperties = { display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", marginTop: "auto", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)", fontSize: "var(--fs-13)", color: "var(--text-2)" };
const colHead: CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" };

export function SectionHead({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--sp-3)", flexWrap: "wrap", marginBottom: "var(--sp-3)" }}>
      <h2 className="pb-h4">{title}</h2>
      {children && <span style={{ display: "inline-flex", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center", justifyContent: "flex-end" }}>{children}</span>}
    </div>
  );
}

function Venue({ name, on }: { name: "Polymarket" | "Kalshi"; on: boolean }) {
  return (
    <span className="pb-tag" style={on ? { background: "var(--surface)", color: "var(--ink)", border: "1px solid var(--border-strong)", gap: "var(--sp-1)" } : { gap: "var(--sp-1)", color: "var(--faint)" }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={LOGO(name === "Polymarket" ? "polymarket.com" : "kalshi.com").replace("128", "64")} alt="" style={{ width: 12, height: 12, borderRadius: 3, opacity: on ? 1 : 0.5 }} />{name}
    </span>
  );
}

export function TopRow(p: {
  question: string; venues: string[]; pBig: string; pSub: ReactNode; pSpark: number[]; volLabel: string; volValue: ReactNode; marketTag?: ReactNode;
  orb: string; nodeLabel: string; nodeLines: ReactNode;
  instShort: string; exchange: string; ticker: string; name: string; px: string; pxDelta: ReactNode; pxColor: string; pxSpark: number[]; driftLabel: string; drift: ReactNode; equityTag?: ReactNode;
}) {
  return (
    <section>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "var(--sp-5)", flexWrap: "wrap", paddingBottom: "var(--sp-5)" }}>
        <h1 className="pb-h3 pb-balance" style={{ minWidth: 0, maxWidth: 760 }}>{p.question}</h1>
        {p.marketTag && <div>{p.marketTag}</div>}
      </div>
      <div className="pb-card pb-bridge-top" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(180px,230px) minmax(0,1fr)", alignItems: "stretch" }}>
        <div style={cell}>
          <div style={colHead}>
            <span className="pb-label">Prediction market</span>
            <span style={{ display: "inline-flex", gap: "var(--sp-1)" }}>
              <Venue name="Polymarket" on={p.venues[0] !== "Kalshi"} />
              <Venue name="Kalshi" on={p.venues[0] === "Kalshi"} />
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "var(--sp-4)", marginTop: "var(--sp-5)" }}>
            <div className="pb-figure">{p.pBig}</div>
            <Spark data={p.pSpark} color="var(--ink)" w={180} h={48} />
          </div>
          <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)", marginBottom: "var(--sp-4)" }}>{p.pSub}</div>
          <div style={footer}><span>{p.volLabel}</span><span className="pb-num" style={{ color: "var(--ink)", fontWeight: 500 }}>{p.volValue}</span></div>
        </div>
        <div style={{ ...cell, alignItems: "center", justifyContent: "center", textAlign: "center", gap: "var(--sp-2)", borderLeft: "1px solid var(--border)", borderRight: "1px solid var(--border)", background: "var(--surface-2)" }}>
          <OrbDisc state={p.orb} disc={104} orb={80} />
          <div className="pb-label" style={{ color: "var(--ink)", marginTop: "var(--sp-2)" }}>{p.nodeLabel}</div>
          <div className="pb-small pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>{p.nodeLines}</div>
        </div>
        <div style={cell}>
          <div style={colHead}>
            <span className="pb-label">Equity ({p.exchange})</span>
            <Tag tone="neutral">{p.instShort}</Tag>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "var(--sp-2)", marginTop: "var(--sp-3)", flexWrap: "wrap" }}>
            <span className="pb-ticker" style={{ fontSize: "var(--fs-16)" }}>{p.ticker}</span>
            {p.name && <span className="pb-small">{p.name}</span>}
            {p.equityTag}
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "var(--sp-4)", marginTop: "var(--sp-3)" }}>
            <div className="pb-figure">{p.px}</div>
            {p.pxSpark.length > 1 && <Spark data={p.pxSpark} color="var(--ink)" w={180} h={48} />}
          </div>
          <div className="pb-small" style={{ marginTop: "var(--sp-2)", marginBottom: "var(--sp-4)", color: p.pxColor }}>{p.pxDelta}</div>
          <div style={footer}><span>{p.driftLabel}</span><span className="pb-num" style={{ color: "var(--ink)", fontWeight: 500 }}>{p.drift}</span></div>
        </div>
      </div>
    </section>
  );
}

export interface DockAlgo { name: string; status: string; line: string; active: boolean }
export function AlgoDock({ label, algos, tag }: { label: string; algos: DockAlgo[]; tag?: ReactNode }) {
  return (
    <section>
      <SectionHead title={label}>{tag}</SectionHead>
      <div className="pb-card" style={{ padding: "0 var(--sp-5)" }}>
        <div className="pb-table-scroll">
          <table className="pb-table">
            <thead><tr><th style={{ width: "30%" }}>Gate</th><th style={{ width: "22%" }}>Status</th><th>Activity</th></tr></thead>
            <tbody>
              {algos.map((a) => (
                <tr key={a.name} aria-current={a.active ? "true" : undefined}>
                  <td style={{ fontWeight: a.active ? 600 : 500, color: "var(--ink)" }}>{a.name}</td>
                  <td>
                    {a.active
                      ? <span className="pb-tag" style={{ background: "var(--accent-tint)", color: "var(--accent)" }}>{a.status}</span>
                      : a.status === "Triggered" ? <span className="pb-tag pb-tag-neutral">{a.status}</span>
                      : <span style={{ color: "var(--faint)", whiteSpace: "nowrap" }}>{a.status}</span>}
                  </td>
                  <td style={{ color: "var(--text-2)" }}>{a.line}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

export function PortfolioPanel(p: {
  big: string; bigColor: string; bigNote: string; left: [string, string, string]; right: [string, string, string]; ratio: number; ratioLabel?: string; footL: ReactNode; footR: ReactNode; tag?: ReactNode;
}) {
  return (
    <section>
      <SectionHead title="Portfolio">{p.tag}</SectionHead>
      <div className="pb-card" style={{ padding: "var(--sp-5)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,180px),1fr))", gap: "var(--sp-5)", alignItems: "end" }}>
          <div>
            <div className="pb-figure" style={{ color: p.bigColor }}>{p.big}</div>
            <div className="pb-small" style={{ marginTop: "var(--sp-2)" }}>{p.bigNote}</div>
          </div>
          {[p.left, p.right].map(([a, b, c]) => (
            <div key={a}>
              <div className="pb-label">{a}</div>
              <div className="pb-num" style={{ fontSize: "var(--fs-20)", fontWeight: 600, marginTop: "var(--sp-1)" }}>{b}</div>
              <div className="pb-small pb-num" style={{ color: "var(--faint)" }}>{c}</div>
            </div>
          ))}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)" }}>
              <span className="pb-label">{p.ratioLabel ?? "Event exposure covered"}</span>
              <span className="pb-num" style={{ fontWeight: 600 }}>{p.ratio}%</span>
            </div>
            <div className="pb-bar" style={{ marginTop: "var(--sp-2)" }}><div style={{ width: `${p.ratio}%` }} /></div>
          </div>
        </div>
        <div className="pb-small pb-num" style={{ marginTop: "var(--sp-5)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", flexWrap: "wrap", color: "var(--faint)" }}>
          <span>{p.footL}</span><span>{p.footR}</span>
        </div>
      </div>
    </section>
  );
}

export interface TradeCard {
  id: string | number; side: "SELL" | "BUY" | "HOLD"; time: string; head: ReactNode; algo: string; reason: string;
  qty?: number; what?: string; px?: string;
  tags?: { tone: TagTone; text: string; title?: string }[];
}
const SIDE_TEXT: Record<TradeCard["side"], string> = { SELL: "Sell", BUY: "Buy", HOLD: "Hold" };
const SIDE_TAG: Record<TradeCard["side"], string> = { SELL: "pb-tag-down", BUY: "pb-tag-up", HOLD: "pb-tag-neutral" };
export function TradesPanel({ trades, empty, tag }: { trades: TradeCard[]; empty?: string; tag?: ReactNode }) {
  const nums = trades.some((t) => t.qty != null);
  return (
    <section>
      <SectionHead title="Trades and reasons">{tag}<span className="pb-small" style={{ color: "var(--faint)" }}>Reason for each order</span></SectionHead>
      <div className="pb-card" style={{ padding: trades.length ? "0 var(--sp-5)" : "var(--sp-5)" }}>
        {trades.length === 0 && empty && <div className="pb-body">{empty}</div>}
        {trades.length > 0 && (
          <div className="pb-table-scroll">
            <table className="pb-table" style={{ minWidth: 640 }}>
              <thead>
                <tr>
                  <th style={{ width: 64 }}>Decision</th><th style={{ width: 64 }}>Side</th><th>Order and reason</th>
                  {nums && <><th className="pb-num" style={{ width: 72 }}>Shares</th><th className="pb-num" style={{ width: 88 }}>Price</th></>}
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td style={{ verticalAlign: "top", paddingTop: "var(--sp-3)", color: "var(--faint)" }}>{t.time}</td>
                    <td style={{ verticalAlign: "top", paddingTop: "var(--sp-3)" }}><span className={`pb-tag ${SIDE_TAG[t.side]}`}>{SIDE_TEXT[t.side]}</span></td>
                    <td style={{ padding: "var(--sp-3)", height: "auto" }}>
                      <div style={{ fontWeight: 600, color: "var(--ink)" }}>
                        {t.qty != null ? t.what : t.head} <span style={{ color: "var(--text-2)", fontWeight: 400, marginLeft: "var(--sp-1)" }}>{t.algo}</span>
                      </div>
                      {t.tags && t.tags.length > 0 && <div style={{ display: "flex", gap: "var(--sp-1)", flexWrap: "wrap", marginTop: "var(--sp-1)" }} data-testid="trade-tags">{t.tags.map((g) => <Tag key={g.text} tone={g.tone} title={g.title}>{g.text}</Tag>)}</div>}
                      <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-1)", maxWidth: 720 }}>{t.reason}</div>
                    </td>
                    {nums && <>
                      <td className="pb-num" style={{ verticalAlign: "top", paddingTop: "var(--sp-3)", fontWeight: 600 }}>{t.qty != null ? t.qty.toLocaleString("en-US") : ""}</td>
                      <td className="pb-num" style={{ verticalAlign: "top", paddingTop: "var(--sp-3)" }}>{t.px ?? ""}</td>
                    </>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
