"use client";

// Options views: the strike ladder (GET /options/chain/{underlying}), the hedge-instrument comparison
// (GET /options/hedge-quote) and option legs marked to market (GET /options/mark/{contract}).
import { useState } from "react";
import { getHedgeQuote, getLiveChain, getOptionMark } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { chainLabel, GREEK_LEGEND, hedgeNotes, hedgeRows, ladder, markLine, optionFillBadge, sideCells, type GreekMark } from "@/lib/optionsView";
import { useStore } from "@/lib/store";
import { Tag } from "@/components/pb";
import { BadgeTag, subBox } from "@/components/risk/RiskBits";

const th = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".06em", color: "#5A627A", fontWeight: 500, padding: "6px 6px", textAlign: "right" as const, whiteSpace: "nowrap" as const };
const td = { fontFamily: "var(--mono)", fontSize: 11.5, padding: "6px 6px", textAlign: "right" as const, whiteSpace: "nowrap" as const, fontVariantNumeric: "tabular-nums" as const };

/** Strike ladder: calls left, puts right, one expiry; in-the-money cells tinted, the strike nearest spot marked. */
export function OptionChainCard({ ticker }: { ticker: string }) {
  const [expiry, setExpiry] = useState<string | null>(null);
  const chain = useAsync(`chain:${ticker}:${expiry ?? ""}`, () => getLiveChain(ticker, { strikes: 10, ...(expiry ? { expiry } : {}) }));
  const d = chain.data;
  const rows = ladder(d);
  const label = chainLabel(d);
  const { account } = useStore();
  const fills = optionFillBadge(account.status === "ok" ? account.data : null);
  const anyComputed = rows.some((r) => [r.call, r.put].some((x) => { const m = sideCells(x).marks; return !!(m.iv || m.delta); }));
  const side = ["BID", "ASK", "IV", "Δ", "OI", "VOL"];
  return (
    <div style={subBox} data-testid="option-chain">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-label">OPTIONS CHAIN · {ticker}{d?.expiry ? ` · ${d.expiry} (${d.dte ?? "?"}d)` : ""}</span>
        <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}><BadgeTag b={label} /><BadgeTag b={fills} /></span>
      </div>
      {d?.expiries_listed && d.expiries_listed.length > 1 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          {d.expiries_listed.slice(0, 8).map((x) => (
            <button key={x} type="button" className="pb-chip pb-chip-sm" data-on={x === (expiry ?? d.expiry)} onClick={() => setExpiry(x)}>{x.slice(5)}</button>
          ))}
        </div>
      )}
      {chain.loading && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Loading the chain from Massive…</div>}
      {chain.error && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Chain unavailable ({chain.error}).</div>}
      {d && !d.available && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>No chain: {d.reason ?? "unavailable"}.</div>}
      {rows.length > 0 && (
        <div className="pb-table-scroll" style={{ marginTop: 10 }}>
          <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 680 }}>
            <thead>
              <tr><th colSpan={6} style={{ ...th, textAlign: "center", color: "#15804F" }}>CALLS</th><th style={{ ...th, textAlign: "center" }}>STRIKE</th><th colSpan={6} style={{ ...th, textAlign: "center", color: "#C8323F" }}>PUTS</th></tr>
              <tr style={{ borderBottom: "1px solid rgba(15,22,38,.14)" }}>{side.map((h) => <th key={`c${h}`} style={th}>{h}</th>)}<th style={{ ...th, textAlign: "center" }} />{side.map((h) => <th key={`p${h}`} style={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const c = sideCells(r.call), p = sideCells(r.put);
                const mark = (m: GreekMark) => m ? <sup style={{ fontSize: 8.5, color: "#9A4A00", marginLeft: 1, fontStyle: "normal" }}>{m}</sup> : null;
                const cells = (x: typeof c, itm: boolean, key: string) => [x.bid, x.ask, x.iv, x.delta, x.oi, x.vol].map((v, i) => {
                  const m = i === 2 ? x.marks.iv : i === 3 ? x.marks.delta : "";
                  return (
                    <td key={`${key}${i}`} title={x.title} style={{ ...td, background: itm ? "rgba(59,108,246,.06)" : undefined, color: x.stale ? "#8A92A8" : m ? "#7A6A55" : i < 2 ? "#0F1626" : "#3C4458", fontStyle: m ? "italic" : undefined }}>{v}{mark(m)}</td>
                  );
                });
                return (
                  <tr key={r.strike} style={{ borderBottom: "1px solid rgba(15,22,38,.06)", background: r.atm ? "rgba(255,255,255,.9)" : undefined }}>
                    {cells(c, r.callItm, "c")}
                    <td style={{ ...td, textAlign: "center", fontWeight: 600, color: "#0F1626" }}>{r.strike}{r.atm && <span style={{ fontSize: 9, color: "#2B57D6", marginLeft: 4 }}>ATM</span>}</td>
                    {cells(p, r.putItm, "p")}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {d?.available && (
        <div className="pb-pretty" style={{ fontSize: 11, color: "#5A627A", marginTop: 8, lineHeight: 1.5 }}>
          Underlying {d.underlying_price?.price?.toFixed(2) ?? "n/a"} ({d.underlying_price?.source?.replaceAll("_", " ") ?? "source n/a"}). {d.snapshot_label ?? ""} Bid/ask: Massive last NBBO, 15 minutes delayed; IV and Δ from Massive, else Black–Scholes from the mark{anyComputed ? ` (italic; ${GREEK_LEGEND})` : " (every IV and Δ shown here is Massive's)"}. Hover a cell for its source and liquidity flags.
        </div>
      )}
    </div>
  );
}

/** Short stock vs protective put vs collar vs put spread for this position, at executable prices. */
export function HedgeCompareCard({ ticker, shares, protection = 0.05, horizon = 30 }: { ticker: string; shares: number; protection?: number; horizon?: number }) {
  const [pp, setPp] = useState(protection);
  const hq = useAsync(`hq:${ticker}:${shares}:${pp}:${horizon}`, () => getHedgeQuote({ ticker, shares, horizon_days: horizon, protection_pct: pp }));
  const d = hq.data;
  const rows = hedgeRows(d);
  return (
    <div style={subBox} data-testid="hedge-compare">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-label">HEDGE INSTRUMENTS · {shares.toLocaleString("en-US")} {ticker} · {horizon} DAYS</span>
        <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
          {d?.market_open === false ? <Tag tone="sim" title="Last session's close; not tradable now">last close</Tag> : d?.available ? <Tag tone="live" title="Massive last quotes (15-min delayed)">delayed quotes</Tag> : null}
          <Tag tone="ai" title={d?.label ?? "An estimate, not advice"}>estimate</Tag>
        </span>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginTop: 10, fontSize: 12, color: "#5A627A" }}>
        Protection below spot:
        {[0.03, 0.05, 0.1].map((x) => <button key={x} type="button" className="pb-chip pb-chip-sm" data-on={x === pp} onClick={() => setPp(x)}>{(x * 100).toFixed(0)}%</button>)}
        {d?.spot?.price != null && <span>· spot {d.spot.price.toFixed(2)} · notional {d.notional_usd != null ? `$${Math.round(d.notional_usd).toLocaleString("en-US")}` : "n/a"}{d.expiry ? ` · options expiry ${d.expiry}` : ""}</span>}
      </div>
      {hq.loading && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Pricing the four hedges from the last quotes…</div>}
      {hq.error && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>Hedge quote unavailable ({hq.error}).</div>}
      {d && !d.available && <div style={{ fontSize: 12.5, color: "#5A627A", marginTop: 10 }}>No hedge quote: {d.reason ?? "unavailable"}.</div>}
      {rows.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
          {rows.map((r) => (
            <div key={r.id} className="pb-sub" style={{ padding: "12px 14px", opacity: r.available ? 1 : 0.65 }} data-testid={`hedge-${r.id}`}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "baseline" }}>
                <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-.01em" }}>{r.name}</span>
                  {r.rank != null && <span className="pb-mono" style={{ fontSize: 11, color: "#5A627A" }}>#{r.rank} by friction</span>}
                  {r.cheapest && <Tag tone="measured" title="Lowest expected trading friction (spread + fees, borrow for short stock)">lowest friction</Tag>}
                  {r.id === "short_stock" && <Tag tone="neutral" title="The engine's hedge: the bridge shorts shares">what the bridge runs</Tag>}
                  {r.available && <BadgeTag b={r.liquidity} />}
                </span>
                {r.available
                  ? <span className="pb-mono pb-tab" style={{ fontSize: 12.5 }}>{r.upfront} upfront ({r.upfrontBp}) · expected {r.expected} ({r.expectedBp})</span>
                  : <span style={{ fontSize: 12, color: "#5A627A" }}>unavailable: {r.reason}</span>}
              </div>
              {r.available && (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "4px 14px", marginTop: 6, fontSize: 12, color: "#3C4458" }}>
                    <span>Protection: {r.protection}</span><span>Upside: {r.upside}</span><span>Capital: {r.capital}</span><span>{r.ratio}</span>
                  </div>
                  {r.flags.length > 0 && <div style={{ fontSize: 11.5, color: "#9A4A00", marginTop: 4 }}>Liquidity flags: {r.flags.join(" · ")}</div>}
                  {r.legs.length > 0 && <div className="pb-mono" style={{ fontSize: 11, color: "#5A627A", marginTop: 6, lineHeight: 1.6 }}>{r.legs.map((l) => <div key={l}>{l}</div>)}</div>}
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {d?.available && <div className="pb-pretty" style={{ fontSize: 11, color: "#5A627A", marginTop: 8, lineHeight: 1.5 }}>{hedgeNotes(d).map((n) => <div key={n}>{n}</div>)}</div>}
    </div>
  );
}

/** One option leg with its live mark (GET /options/mark), for open structures and broker option positions. */
export function LegMark({ contract, sign, qty }: { contract: string; sign?: number; qty?: number }) {
  const m = useAsync(`mark:${contract}`, () => getOptionMark(contract));
  const v = m.error ? { text: `no mark (${m.error})`, tone: "neutral" as const, title: "" } : markLine(m.data);
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "center", fontSize: 11.5 }} data-testid="leg-mark">
      <span className="pb-mono" style={{ color: "#3C4458" }}>{sign != null ? (sign > 0 ? "+" : "−") : ""}{qty != null ? `${Math.abs(qty)} ` : ""}{contract}</span>
      <Tag tone={v.tone} title={v.title}>{v.text}</Tag>
    </div>
  );
}
