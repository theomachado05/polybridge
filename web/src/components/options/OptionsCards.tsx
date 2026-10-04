"use client";

import { useState } from "react";
import { getHedgeQuote, getLiveChain, getOptionMark } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { chainLabel, GREEK_LEGEND, hedgeNotes, hedgeRows, ladder, markLine, optionFillBadge, sideCells, type GreekMark } from "@/lib/optionsView";
import { useStore } from "@/lib/store";
import { Tag } from "@/components/pb";
import { BadgeTag, subBox } from "@/components/risk/RiskBits";

const th = { height: 30, padding: "0 var(--sp-2)", textAlign: "right" as const, background: "transparent", position: "static" as const };
const td = { height: 32, padding: "0 var(--sp-2)", textAlign: "right" as const, whiteSpace: "nowrap" as const };
const head = { display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" } as const;
const title = { fontSize: "var(--fs-14)" } as const;
const note = { fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-3)", lineHeight: 1.5 } as const;
const status = { marginTop: "var(--sp-3)" } as const;

export function OptionChainCard({ ticker }: { ticker: string }) {
  const [expiry, setExpiry] = useState<string | null>(null);
  const chain = useAsync(`chain:${ticker}:${expiry ?? ""}`, () => getLiveChain(ticker, { strikes: 10, ...(expiry ? { expiry } : {}) }));
  const d = chain.data;
  const rows = ladder(d);
  const label = chainLabel(d);
  const { account } = useStore();
  const fills = optionFillBadge(account.status === "ok" ? account.data : null);
  const anyComputed = rows.some((r) => [r.call, r.put].some((x) => { const m = sideCells(x).marks; return !!(m.iv || m.delta); }));
  const side = ["Bid", "Ask", "IV", "Δ", "OI", "Vol"];
  return (
    <div style={subBox} data-testid="option-chain">
      <div style={head}>
        <span className="pb-h4" style={title}>Options chain: {ticker}{d?.expiry ? `, ${d.expiry} (${d.dte ?? "?"} days)` : ""}</span>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)", flexWrap: "wrap" }}><BadgeTag b={label} /><BadgeTag b={fills} /></span>
      </div>
      {d?.expiries_listed && d.expiries_listed.length > 1 && (
        <div style={{ display: "flex", gap: "var(--sp-2)", flexWrap: "wrap", marginTop: "var(--sp-3)" }}>
          {d.expiries_listed.slice(0, 8).map((x) => (
            <button key={x} type="button" className="pb-chip pb-chip-sm" data-on={x === (expiry ?? d.expiry)} onClick={() => setExpiry(x)}>{x.slice(5)}</button>
          ))}
        </div>
      )}
      {chain.loading && <div className="pb-small" style={status}>The app reads the chain from Massive…</div>}
      {chain.error && <div className="pb-small" style={status}>The chain is not available ({chain.error}). Try again later.</div>}
      {d && !d.available && <div className="pb-small" style={status}>No chain: {d.reason ?? "unavailable"}.</div>}
      {rows.length > 0 && (
        <div className="pb-table-scroll" style={{ marginTop: "var(--sp-3)" }}>
          <table className="pb-table" style={{ minWidth: 680 }}>
            <thead>
              <tr><th colSpan={6} style={{ ...th, textAlign: "center", color: "var(--ink)", borderBottom: "1px solid var(--border)" }}>Calls</th><th style={{ ...th, textAlign: "center", color: "var(--ink)", borderBottom: "1px solid var(--border)" }}>Strike</th><th colSpan={6} style={{ ...th, textAlign: "center", color: "var(--ink)", borderBottom: "1px solid var(--border)" }}>Puts</th></tr>
              <tr>{side.map((h) => <th key={`c${h}`} style={th}>{h}</th>)}<th style={{ ...th, textAlign: "center" }} />{side.map((h) => <th key={`p${h}`} style={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const c = sideCells(r.call), p = sideCells(r.put);
                const mark = (m: GreekMark) => m ? <sup style={{ fontSize: 9, color: "var(--warn)", marginLeft: 1, fontStyle: "normal" }}>{m}</sup> : null;
                const cells = (x: typeof c, itm: boolean, key: string) => [x.bid, x.ask, x.iv, x.delta, x.oi, x.vol].map((v, i) => {
                  const m = i === 2 ? x.marks.iv : i === 3 ? x.marks.delta : "";
                  return (
                    <td key={`${key}${i}`} className="pb-num" title={x.title} style={{ ...td, background: itm ? "var(--neutral-tint)" : undefined, color: x.stale ? "var(--faint)" : m ? "var(--warn-ink)" : i < 2 ? "var(--ink)" : "var(--text-2)", fontStyle: m ? "italic" : undefined }}>{v}{mark(m)}</td>
                  );
                });
                return (
                  <tr key={r.strike} style={{ background: r.atm ? "var(--surface)" : undefined }}>
                    {cells(c, r.callItm, "c")}
                    <td className="pb-num" style={{ ...td, textAlign: "center", fontWeight: 600, color: "var(--ink)", borderLeft: "1px solid var(--border)", borderRight: "1px solid var(--border)" }}>{r.strike}{r.atm && <span style={{ fontSize: "var(--fs-12)", fontWeight: 500, color: "var(--text-2)", marginLeft: "var(--sp-1)" }}>ATM</span>}</td>
                    {cells(p, r.putItm, "p")}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {d?.available && (
        <div className="pb-pretty" style={note}>
          Underlying: {d.underlying_price?.price?.toFixed(2) ?? "n/a"} ({d.underlying_price?.source?.replaceAll("_", " ") ?? "source n/a"}). {d.snapshot_label ?? ""} Bid and ask: Massive last NBBO, 15 minutes delayed. IV and Δ: from Massive, or Black–Scholes from the mark{anyComputed ? ` (italic: ${GREEK_LEGEND})` : " (all IV and Δ values here are from Massive)"}. Put the pointer on a cell to see its source and liquidity flags.
        </div>
      )}
    </div>
  );
}

export function HedgeCompareCard({ ticker, shares, protection = 0.05, horizon = 30 }: { ticker: string; shares: number; protection?: number; horizon?: number }) {
  const [pp, setPp] = useState(protection);
  const hq = useAsync(`hq:${ticker}:${shares}:${pp}:${horizon}`, () => getHedgeQuote({ ticker, shares, horizon_days: horizon, protection_pct: pp }));
  const d = hq.data;
  const rows = hedgeRows(d);
  return (
    <div style={subBox} data-testid="hedge-compare">
      <div style={head}>
        <span className="pb-h4" style={title}>Hedge instruments: {shares.toLocaleString("en-US")} {ticker}, {horizon} days</span>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
          {d?.market_open === false ? <Tag tone="sim" title="Prices from the last session close. You cannot trade at these prices now.">last close</Tag> : d?.available ? <Tag tone="live" title="Massive last quotes (15-min delayed)">delayed quotes</Tag> : null}
          <Tag tone="ai" title={d?.label ?? "An estimate, not advice"}>estimate</Tag>
        </span>
      </div>
      <div className="pb-small" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap", marginTop: "var(--sp-3)" }}>
        Protection below spot:
        {[0.03, 0.05, 0.1].map((x) => <button key={x} type="button" className="pb-chip pb-chip-sm" data-on={x === pp} onClick={() => setPp(x)}>{(x * 100).toFixed(0)}%</button>)}
        {d?.spot?.price != null && <span className="pb-num">Spot {d.spot.price.toFixed(2)}, notional {d.notional_usd != null ? `$${Math.round(d.notional_usd).toLocaleString("en-US")}` : "n/a"}{d.expiry ? `, options expiry ${d.expiry}` : ""}</span>}
      </div>
      {hq.loading && <div className="pb-small" style={status}>Pricing the four hedges from the last quotes…</div>}
      {hq.error && <div className="pb-small" style={status}>The hedge quote is not available ({hq.error}). Try again later.</div>}
      {d && !d.available && <div className="pb-small" style={status}>No hedge quote: {d.reason ?? "unavailable"}.</div>}
      {rows.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", marginTop: "var(--sp-3)", borderTop: "1px solid var(--border)" }}>
          {rows.map((r) => (
            <div key={r.id} style={{ padding: "var(--sp-3) 0", borderBottom: "1px solid var(--border)", opacity: r.available ? 1 : 0.65 }} data-testid={`hedge-${r.id}`}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", flexWrap: "wrap", alignItems: "baseline" }}>
                <span style={{ display: "inline-flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontSize: "var(--fs-14)", fontWeight: 600 }}>{r.name}</span>
                  {r.rank != null && <span className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--faint)" }}>Rank {r.rank} by friction</span>}
                  {r.cheapest && <Tag tone="measured" title="Lowest expected trading friction (spread + fees, borrow for short stock)">lowest friction</Tag>}
                  {r.id === "short_stock" && <Tag tone="neutral" title="The engine uses this hedge. The bridge sells shares short.">the bridge uses this</Tag>}
                  {r.available && <BadgeTag b={r.liquidity} />}
                </span>
                {r.available
                  ? <span className="pb-num" style={{ fontSize: "var(--fs-13)", color: "var(--ink)" }}>{r.upfront} upfront ({r.upfrontBp}), expected {r.expected} ({r.expectedBp})</span>
                  : <span className="pb-small">not available: {r.reason}</span>}
              </div>
              {r.available && (
                <>
                  <div className="pb-small pb-num" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--sp-1) var(--sp-4)", marginTop: "var(--sp-2)" }}>
                    <span>Protection: {r.protection}</span><span>Upside: {r.upside}</span><span>Capital: {r.capital}</span><span>{r.ratio}</span>
                  </div>
                  {r.flags.length > 0 && <div className="pb-small" style={{ color: "var(--warn)", marginTop: "var(--sp-1)" }}>Liquidity flags: {r.flags.join(", ")}</div>}
                  {r.legs.length > 0 && <div className="pb-code" style={{ fontSize: "var(--fs-12)", color: "var(--text-2)", marginTop: "var(--sp-2)", lineHeight: 1.6 }}>{r.legs.map((l) => <div key={l}>{l}</div>)}</div>}
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {d?.available && <div className="pb-pretty" style={note}>{hedgeNotes(d).map((n) => <div key={n}>{n}</div>)}</div>}
    </div>
  );
}

export function LegMark({ contract, sign, qty }: { contract: string; sign?: number; qty?: number }) {
  const m = useAsync(`mark:${contract}`, () => getOptionMark(contract));
  const v = m.error ? { text: `no mark (${m.error})`, tone: "neutral" as const, title: "" } : markLine(m.data);
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-3)", flexWrap: "wrap", alignItems: "center", fontSize: "var(--fs-13)" }} data-testid="leg-mark">
      <span className="pb-code" style={{ color: "var(--ink)" }}>{sign != null ? (sign > 0 ? "+" : "−") : ""}{qty != null ? `${Math.abs(qty)} ` : ""}{contract}</span>
      <Tag tone={v.tone} title={v.title}>{v.text}</Tag>
    </div>
  );
}
