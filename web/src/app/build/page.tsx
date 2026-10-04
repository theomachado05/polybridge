"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getClosedEvidence, getEquity, getLibrary, getLiquidity, getOptionsImplied, mapEvent, searchMarkets, type FitOut, type Holding, type MapOut } from "@/lib/api";
import { sessionClosed, weekendModeCopy, type SessionView } from "@/lib/closed";
import { DEFAULT_OPP_CAPS, opportunityFit, prepareOpportunityProposal, runnableFit } from "@/lib/realBridge";
import { OVERRIDE_COPY, ackCopy, capacityFromLiquidity, capitalFitView, evidenceGate, isEvidenceError } from "@/lib/risk";
import { BadgeTag, CapacityCard, EvidenceGateBox } from "@/components/risk/RiskBits";
import { HedgeCompareCard, OptionChainCard } from "@/components/options/OptionsCards";
import { HEDGE_INSTRUMENTS, WEEKEND_REPLAY, featuredFirst, isFeaturedReplay, isListedMarket, isOpenMarket, isRecordedOnly, isWeekendReplay, questionFromMarket, topImpact, type EquityPick, type Impact, type Question } from "@/lib/markets";
import { aiLabel, aiStatus, aiTitle, mappingLabel } from "@/lib/ai";
import { fmtPct, prettyId } from "@/lib/fmt";
import { fitScoreView, IN_SAMPLE_NOTE } from "@/lib/pipeline";
import { useAsync, useRetry } from "@/lib/hooks";
import { OPP_REPLAY_NOTE, libraryIdea, optionFamilyIdea } from "@/lib/opportunity";
import { useStore } from "@/lib/store";
import { Orb, Switch, Tag, Unavailable } from "@/components/pb";

const optsBox = { marginTop: 14, padding: 6, borderRadius: 22, display: "flex", flexDirection: "column" as const };
const cardHead = { fontSize: 13, fontWeight: 600, color: "#0F1626" } as const;
const statLabel = { fontSize: 12, color: "#5A627A" } as const;
const rowStyle = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, padding: "12px 14px", borderRadius: 16, cursor: "pointer", textAlign: "left" as const, width: "100%", background: "transparent", border: 0 };

function Avatar({ state }: { state: string }) {
  return (
    <div style={{ width: 36, height: 36, borderRadius: "50%", background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.95)", boxShadow: "inset 0 1px 0 #fff,0 6px 18px rgba(40,60,120,.10)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Orb state={state} size={26} />
    </div>
  );
}

function Ai({ orb, text, children }: { orb: string; text: ReactNode; children?: ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "36px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
      <Avatar state={orb} />
      <div style={{ minWidth: 0, paddingTop: 4 }}>
        <div className="pb-serif pb-pretty" style={{ fontSize: 21, lineHeight: 1.45, letterSpacing: "-.005em" }}>{text}</div>
        {children}
      </div>
    </div>
  );
}

function User({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end" }}>
      <button type="button" title="Click to change this answer." onClick={onClick} style={{ maxWidth: "78%", padding: "12px 18px", borderRadius: "22px 22px 6px 22px", background: "#0F1626", color: "#fff", fontSize: 15, lineHeight: 1.4, cursor: "pointer", border: 0, textAlign: "left", font: "inherit" }}>{text}</button>
    </div>
  );
}

const signedImpact = (pct: number | null, direction: string) => (pct == null ? 0 : (direction === "up_on_yes" ? 1 : -1) * Math.abs(pct));

/** Real markets that touch the user's real holdings (GET /portfolio), held-first rows for step 1. Ended or
 *  effectively settled markets are left out. */
function portfolioQuestions(holdings: Holding[]): Question[] {
  const byId = new Map<string, Question>();
  for (const h of holdings) {
    const ms = [...(h.exposure ? [h.exposure.market] : []), ...h.markets];
    for (const m of ms) {
      if (!isOpenMarket(m)) continue;
      const q = byId.get(`${m.source}:${m.id}`) ?? questionFromMarket(m);
      if (!q.touches.includes(h.ticker)) q.touches = [...q.touches, h.ticker];
      byId.set(q.id, q);
    }
  }
  return [...byId.values()].sort((a, b) => b.volN - a.volN);
}

function mapImpacts(map: MapOut | null, q: Question): Impact[] {
  if (map && map.items.length) {
    return map.items.map((i) => ({ t: i.ticker.toUpperCase(), move: signedImpact(i.impact_pct, i.direction), rev: null, brand: null, why: i.rationale ?? "", direction: i.direction === "up_on_yes" ? "up_on_yes" : "down_on_yes", directionSource: "mapping", real: true }));
  }
  return q.touches.map((t) => ({ t, move: 0, rev: null, brand: null, why: "This stock is not in the precomputed mapping, thus the impact is unknown.", real: true }));
}

export default function Build() {
  const router = useRouter();
  const s = useStore();
  const { question: q, equity: e, inst, query, thinking, portfolio } = s;
  const step = !q ? 1 : !e ? 2 : 3;
  const real = !!q;
  // After the equity step: "Hedge" (the existing path) vs "Opportunity" (an options family with a real replay score).
  const [mode, setMode] = useState<{ key: string; m: "hedge" | "opportunity" } | null>(null);
  const pickKey = q && e ? `${q.id}|${e.t}` : null;
  const oppData = s.oppFit && pickKey && s.oppFit.key === pickKey && s.oppFit.status === "ok" ? s.oppFit.data : null;
  const opp = real ? opportunityFit(oppData) : null;
  const lib = useAsync(opp ? "library" : null, () => getLibrary());
  const oppIdea = opp ? optionFamilyIdea(opp.family, libraryIdea(lib.data, opp.family)) : "";
  const chosenMode = mode && mode.key === pickKey ? mode.m : null;
  const showHedge = !opp || chosenMode === "hedge";

  // Debounced live market search (step 1).
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(step === 1 ? query.trim() : ""), 350);
    return () => clearTimeout(t);
  }, [query, step]);
  const [searchTry, retrySearch] = useRetry();
  const [mapTry, retryMap] = useRetry();
  const search = useAsync(debounced ? `s:${searchTry}:${debounced}` : null, () => searchMarkets(debounced));
  const map = useAsync(q ? `m:${mapTry}:${q.id}` : null, () => mapEvent({ question: q!.q, source: q!.real.source, market_id: q!.real.id }));

  const holdings = useMemo(() => (portfolio.status === "ok" && portfolio.data ? portfolio.data.holdings : []), [portfolio]);
  const holdingOf = (t: string) => holdings.find((h) => h.ticker === t) ?? null;
  const heldOf = (_qq: Question, t: string) => holdingOf(t)?.shares ?? 0;

  useEffect(() => {
    requestAnimationFrame(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" }));
  }, [q, e, inst, thinking]);

  // ---- step 1 rows
  const ql = query.trim().toLowerCase();
  // Held-market rows, the featured TLT replay market first so it is one click away.
  const realBase = useMemo(() => featuredFirst(portfolioQuestions(holdings)), [holdings]);
  const searchRows = useMemo(() => (search.data?.markets ?? []).filter((m) => isListedMarket(m)).map((m) => {
    const known = realBase.find((x) => x.id === `${m.source}:${m.id}`);
    return known ?? questionFromMarket(m);
  }), [search.data, realBase]);
  const all = ql ? searchRows : realBase;
  const shown = ql ? all.slice(0, 10) : all.slice(0, 5);
  const more = all.length - shown.length;

  // ---- step 2 rows
  // The weekend replay's SPY pick carries its direction from the recording; keep it listed when the mapping has none.
  const impacts: Impact[] = !q ? [] : [...mapImpacts(map.data, q), ...(e && e.directionSource === "recording" && !map.data?.items.some((i) => i.ticker.toUpperCase() === e.t) ? [e] : [])];
  let elist = impacts;
  if (q && ql && step === 2) {
    const u = ql.toUpperCase();
    const universe = new Set([...holdings.map((h) => h.ticker), ...impacts.map((i) => i.t)]);
    elist = [...universe].filter((t) => t.includes(u) || (holdingOf(t)?.name ?? "").toUpperCase().includes(u))
      .map((t) => impacts.find((i) => i.t === t) ?? { t, move: 0, rev: null, brand: null, why: "This stock is not in the mapping for this market, thus the impact is unknown.", real: true });
    if (/^[A-Z]{1,5}$/.test(u) && !elist.some((i) => i.t === u)) elist.push({ t: u, move: 0, rev: null, brand: null, why: "This stock is not in the mapping for this market, thus the impact is unknown.", real: true });
  }
  elist = q ? [...elist].sort((a, b) => Number(heldOf(q, b.t) > 0) - Number(heldOf(q, a.t) > 0) || Math.abs(b.move) - Math.abs(a.move)) : [];
  const toPick = (i: Impact): EquityPick => {
    const h = holdingOf(i.t);
    return { ...i, name: h?.name ?? i.t, px: h?.spot ?? null, held: h?.shares ?? 0 };
  };

  // ---- step 3 rows
  // Only the hedge the engine actually runs, priced from a real quote or not at all.
  const instruments = !e ? [] : HEDGE_INSTRUMENTS(e.px);
  const chosen = instruments.find((i) => i.id === inst) ?? null;
  const ilist = q && e && !inst && ql && showHedge ? instruments.filter((i) => (i.name + " " + i.kind + " " + i.phrase).toLowerCase().includes(ql)) : instruments;

  // ---- actions
  const pickQuestion = (x: Question) => s.setQuestion(x);
  const pickEquity = (i: Impact) => {
    const pick = toPick(i);
    s.setEquity(pick);
    if (q) s.runFit(q, pick);
    getEquity(pick.t).then((card) => s.patchEquity(pick.t, { name: card.name ?? pick.name, px: pick.px ?? card.implied_move?.spot ?? null }), () => {});
  };
  const toConnect = () => { if (q && e && inst) router.push("/connect"); };
  const submit = () => {
    if (step === 1 && shown[0]) pickQuestion(shown[0]);
    else if (step === 2 && elist[0]) pickEquity(elist[0]);
    else if (!inst && ilist[0]) s.setInst(ilist[0].id);
    else if (inst) toConnect();
  };
  const toStep1 = () => s.setQuestion(null);
  const toStep2 = () => { if (q) s.setEquity(null); };
  const toStep3 = () => { if (e) s.setInst(null); };

  // ---- copy
  const top = q ? topImpact(impacts, (t) => heldOf(q, t) > 0) : undefined;
  const heldQ = q ? q.touches.find((t) => heldOf(q, t) > 0) ?? impacts.find((i) => heldOf(q, i.t) > 0)?.t : null;
  const ai1 = "Select a Polymarket or Kalshi market below, or type an event to find a market.";
  const weekend = isWeekendReplay(q?.real);
  const priceLine = !q ? "" : weekend
    ? `This is a replay of the recorded tariff weekend for this market, from Friday 4 April to Monday 7 April 2025 (${WEEKEND_REPLAY.recorded}). `
    : q.real.yes_price == null
      ? `${q.real.recorded ? "This market is resolved. The bridge replays its recording" : "The backend has no current price for this market"}. `
      : `The price is ${q.yes}¢ YES on ${q.venues.join(" and ")}. The 24-hour volume is ${q.vol}. `;
  const ai2 = !q ? "" : priceLine + (top && top.move
    ? `The mapping shows the largest move for ${top.t}, ${fmtPct(top.move)} if YES occurs.${heldQ ? ` You hold ${heldQ}.` : ""} Select the position to hedge.`
    : map.loading ? "Mapping the stocks for this market…"
    : weekend ? "The recording hedges SPY because a recession YES is adverse for SPY. Select the position to hedge."
    : "This market has no mapping. Type a ticker. The impact stays unknown, and you select the outcome that hurts the stock.");
  const ai3 = !e ? "" : (e.held
    ? `You hold ${e.held.toLocaleString("en-US")} shares of ${e.t}. `
    : `You do not hold ${e.t}. The hedge uses a 500-share notional. `)
    + (e.move ? `The mapping estimates ${fmtPct(e.move)} on YES${e.why ? ": " + e.why : "."} Select a hedge.`
      : e.directionSource === "recording" ? `${e.why} Select a hedge.`
      : `This market has no impact estimate for ${e.t}, thus the engine cannot use an impact to size the hedge. Select a hedge.`);
  const ai4 = !chosen ? "" : `${chosen.fit} Next, the app examines the order route and replays the applicable algo families on the history of this market. The app sends no order until you approve.`;
  const thinkingText = !q ? "Reading the order books…" : !e ? (map.data?.items.length ? `Mapping the exposure of ${map.data.items.length} stocks…` : "Mapping the stock exposure…") : !inst ? "Pricing the hedge…" : "Checking the fees and the quote…";
  const busy = thinking || (step === 2 && map.loading);

  const hdr = (n: number, filled: boolean, active: boolean) => ({ color: active ? "#2B57D6" : filled ? "#0F1626" : "#8A92A8", fg: filled ? "#0F1626" : "#8A92A8" });
  const slots = [
    { k: "1. Event", v: q ? q.ev : "Select an event", c: hdr(1, !!q, step === 1), go: toStep1 },
    { k: "2. Stock", v: e ? `${e.t}, ${e.name}` : step === 2 ? "Select a stock" : "Not selected", c: hdr(2, !!e, step === 2), go: toStep2 },
    { k: "3. Hedge", v: chosen ? chosen.short : step === 3 ? "Select a hedge" : "Not selected", c: hdr(3, !!inst, step === 3 && !inst), go: toStep3 },
  ];
  const placeholder = step === 1 ? "Type an event, for example Fed cuts in December" : step === 2 ? "Type a ticker" : !inst ? "Type the hedge that you want" : "Press Enter to continue";
  const fit = s.fit && q && e && s.fit.key === `${q.id}|${e.t}` ? s.fit : null;

  return (
    <main className="pb-page" style={{ maxWidth: 780, paddingTop: 28, paddingBottom: 40 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 24, paddingBottom: 14, borderBottom: "1px solid rgba(15,22,38,.16)" }}>
        {slots.map((x) => (
          <button type="button" key={x.k} onClick={x.go} style={{ cursor: "pointer", minWidth: 0, background: "transparent", border: 0, padding: 0, textAlign: "left", font: "inherit" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: x.c.color }}>{x.k}</div>
            <div className="pb-ellipsis" style={{ fontSize: 13, marginTop: 4, color: x.c.fg }}>{x.v}</div>
          </button>
        ))}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 24, marginTop: 32 }}>
        <Ai orb="breathing" text={ai1}>
          {step === 1 && !busy && (
            <div className="pb-glass" style={optsBox}>
              {ql && search.loading && <div style={{ padding: "10px 14px 4px", fontSize: 12.5, color: "#5A627A" }}>Searching Polymarket and Kalshi…</div>}
              {ql && search.error && <Unavailable what="Market search" error={search.error} onRetry={retrySearch} compact style={{ padding: "8px 14px 4px" }} />}
              {ql && search.data && !search.loading && shown.length === 0 && <div style={{ padding: "10px 14px", fontSize: 12.5, color: "#5A627A" }}>The search found no open market for “{query.trim()}”. Type a different event.</div>}
              {!ql && portfolio.status === "error" && <Unavailable what="The markets for your holdings (GET /portfolio)" error={portfolio.error} onRetry={s.refreshAccount} compact style={{ padding: "8px 14px 4px" }} />}
              {!ql && portfolio.status === "ok" && shown.length === 0 && <div style={{ padding: "10px 14px", fontSize: 12.5, color: "#5A627A" }}>No open market is available for your holdings. Type an event to search Polymarket and Kalshi.</div>}
              {search.data?.stale && ql && <div style={{ padding: "8px 14px 4px" }}><Tag tone="sim" title={search.data.note ?? "The live source did not answer. These results come from the cache."}>cached results</Tag></div>}
              {shown.map((x) => {
                const held = x.touches.find((t) => holdingOf(t));
                return (
                  <button key={x.id} type="button" className="pb-row" style={rowStyle} onClick={() => pickQuestion(x)}>
                    <div style={{ minWidth: 0 }}>
                      <div className="pb-pretty" style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: "-.01em", lineHeight: 1.35 }}>{x.q}</div>
                      <div style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>
                        {x.venues.join(" and ")}{x.touches.length ? ", moves " + x.touches.slice(0, 3).join(", ") : ""}{held ? ", you hold " + held : ""}{" "}
                        {isRecordedOnly(x.real)
                          ? <Tag tone="replay" title={`This market is resolved. The list shows it because the backend has its recorded history (${x.real.recorded}), and the bridge replays that history.`}>resolved, recorded replay</Tag>
                          : <Tag tone="live" title="This market comes from GET /markets/search or from the markets of your portfolio.">live market</Tag>}
                        {isFeaturedReplay(x) && <>{" "}<Tag tone="replay" title="A bridge on this market replays its recorded Polymarket history at a faster speed.">recorded replay</Tag></>}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flex: "none" }}>
                      <div className="pb-tab" style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.03em" }}>{x.real.yes_price == null ? "n/a" : x.yes + "¢"}</div>
                      <div style={{ fontSize: 11, color: "#5A627A", marginTop: 2, whiteSpace: "nowrap" }}>YES, {x.vol} volume</div>
                    </div>
                  </button>
                );
              })}
              {more > 0 && <div style={{ padding: "10px 14px 8px", fontSize: 12, color: "#5A627A" }}>{more} more markets. Type to search.</div>}
              {!ql && (
                <button type="button" className="pb-row" style={rowStyle} onClick={() => void s.openWeekendReplay()}>
                  <div style={{ minWidth: 0 }}>
                    <div className="pb-pretty" style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: "-.01em", lineHeight: 1.35 }}>{WEEKEND_REPLAY.question} (April 2025 tariff weekend)</div>
                    <div style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>Polymarket, hedges {WEEKEND_REPLAY.ticker}{" "}<Tag tone="replay" title={`The backend replays its recording (${WEEKEND_REPLAY.recorded}) from Friday 15:30 ET to Monday 10:00 ET.`}>recorded weekend</Tag></div>
                  </div>
                  <div style={{ fontSize: 11, color: "#5A627A", whiteSpace: "nowrap" }}>replay</div>
                </button>
              )}
            </div>
          )}
        </Ai>

        {q && (
          <>
            <User text={`If ${q.ev}.`} onClick={toStep1} />
            {!(busy && !e) && (
              <Ai orb="working" text={ai2}>
                {map.data && map.data.items.length > 0 && (() => {
                  const ml = mappingLabel(map.data.source);
                  return (
                    <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                      {ml && <Tag tone="ai" title={`${ml.title} ${map.data.label}`}>{ml.text}</Tag>}
                      {map.data.match_type === "fuzzy" && <span style={{ fontSize: 12, color: "#5A627A" }}>Nearest mapped question: “{map.data.matched_question}”</span>}
                    </div>
                  );
                })()}
                {map.error && <Unavailable what="Stock mapping (POST /map)" error={map.error} onRetry={retryMap} compact style={{ marginTop: 8 }} />}
                {map.data && map.data.items.length === 0 && map.data.note && <div style={{ marginTop: 8, fontSize: 12, color: "#5A627A" }}>No mapping: {map.data.note}.</div>}
                {step === 2 && !busy && elist.length > 0 && (
                  <div className="pb-glass" style={optsBox}>
                    {elist.map((i) => {
                      const held = heldOf(q, i.t), name = holdingOf(i.t)?.name ?? (e?.t === i.t ? e.name : "");
                      return (
                        <button key={i.t} type="button" className="pb-row" style={rowStyle} onClick={() => pickEquity(i)}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                              <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.02em" }}>{i.t}</span>
                              <span style={{ fontSize: 13, color: "#5A627A" }}>{name}</span>
                              {held > 0 && <span style={{ fontSize: 12, fontWeight: 500, color: "#15804F" }}>{held.toLocaleString("en-US")} shares held</span>}
                            </div>
                            {i.why && <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3, lineHeight: 1.4 }}>{i.why}</div>}
                          </div>
                          <div style={{ textAlign: "right", flex: "none" }}>
                            <div className="pb-tab" style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.03em", color: !i.move ? "#8A92A8" : i.move < 0 ? "#E0485A" : "#22A06B" }}>{i.move ? fmtPct(i.move) : "n/a"}</div>
                            <div style={{ fontSize: 11, color: "#5A627A", marginTop: 2, whiteSpace: "nowrap" }}>on YES</div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </Ai>
            )}
          </>
        )}

        {e && (
          <>
            <User text={`Hedge ${e.t}.`} onClick={toStep2} />
            {!(busy && !inst) && (
              <Ai orb="composing" text={ai3}>
                {step === 3 && !inst && !busy && opp && !chosenMode && pickKey && (
                  <div className="pb-glass" style={optsBox}>
                    <button type="button" className="pb-row" style={rowStyle} onClick={() => setMode({ key: pickKey, m: "hedge" })}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 14.5, fontWeight: 500 }}>Hedge</div>
                        <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>Hedge the {e.t} position. The engine sells shares short when the market moves against the position.</div>
                      </div>
                      <div style={{ fontSize: 11, color: "#5A627A", whiteSpace: "nowrap" }}>shares</div>
                    </button>
                    <button type="button" className="pb-row" style={rowStyle} onClick={() => setMode({ key: pickKey, m: "opportunity" })}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 14.5, fontWeight: 500 }}>Opportunity</span>
                          <Tag tone="ai" title={`${aiTitle(aiStatus(oppData))} POST /pipeline/fit (division opportunity) gives this replay score. It is the net P&L per unit of risk on the history of this market. Only presets that traded get a score. ${OPP_REPLAY_NOTE} It is a replay estimate, not a forecast.`}>{aiLabel(aiStatus(oppData))}, replay score {opp.score.toFixed(3)} (estimate)</Tag>
                        </div>
                        <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>{prettyId(opp.family)} (preset #{opp.preset_index}): {oppIdea} The replay option prices are estimates from bar closes. Option fills are simulated.{opp.score < 0 ? " This preset lost money on this replay." : ""}</div>
                      </div>
                      <div style={{ fontSize: 11, color: "#5A627A", whiteSpace: "nowrap" }}>options</div>
                    </button>
                  </div>
                )}
                {step === 3 && !inst && !busy && opp && chosenMode === "opportunity" && q && (
                  <OpportunityCard q={q} ticker={e.t} fit={oppData!} opp={opp} idea={oppIdea} onBack={() => setMode(null)}
                    onStart={async (ack) => { const id = await s.openOpportunity(q, e, { ackUnvalidated: ack }); router.push(`/bridge/${id.replace(/^live:/, "")}`); }} />
                )}
                {step === 3 && !inst && !busy && showHedge && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "#5A627A" }}>
                    The bridge runs the dynamic short hedge. The next step prices option structures (puts, collars, spreads) from real quotes for comparison.
                  </div>
                )}
                {!e.direction && real && (
                  <DirectionAsk ticker={e.t} onPick={s.chooseDirection} />
                )}
                {e.directionSource === "user" && e.direction && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "#5A627A" }}>
                    You said that {e.direction === "down_on_yes" ? "YES" : "NO"} hurts {e.t}. The hedge uses this direction.{" "}
                    <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={() => s.chooseDirection(e.direction === "down_on_yes" ? "up_on_yes" : "down_on_yes")}>Change direction</button>
                  </div>
                )}
                {step === 3 && !inst && !busy && showHedge && (
                  <div className="pb-glass" style={optsBox}>
                    {ilist.map((i) => (
                      <button key={i.id} type="button" className="pb-row" style={rowStyle} onClick={() => s.setInst(i.id)}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                            <span style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: "-.01em" }}>{i.name}</span>
                          </div>
                          <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3, lineHeight: 1.4 }}>{i.fit} {i.tax}.</div>
                        </div>
                        <div style={{ textAlign: "right", flex: "none" }}>
                          <div style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-.01em", whiteSpace: "nowrap" }}>{i.cost}</div>
                          <div style={{ fontSize: 11, color: "#5A627A", marginTop: 2, whiteSpace: "nowrap" }}>{i.cover}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </Ai>
            )}
          </>
        )}

        {chosen && (
          <>
            <User text={`Use ${chosen.phrase}.`} onClick={toStep3} />
            {!busy && (
              <Ai orb="breathing" text={ai4}>
                <FitCard fit={fit} onRetry={q && e ? () => s.retryFit(q, e) : undefined} />
                                {q && (sessionClosed(s.session.data) || s.closedPmHedge || s.actOnUnvalidated || isWeekendReplay(q.real)) && (
                  <WeekendModeCard market={q.real} ticker={e?.t ?? ""} session={s.session.data} pmHedge={s.closedPmHedge} onPmHedge={s.setClosedPmHedge}
                    override={s.actOnUnvalidated} onOverride={s.setActOnUnvalidated} />
                )}
                {e && <RiskPreview ticker={e.t} held={e.held || 500} maxHedge={s.settings.maxHedge} notional={!e.held} fitRuns={!!runnableFit(fit?.status === "ok" ? fit.data : null)} />}
                <div style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button type="button" className="pb-btn pb-btn-primary" style={{ height: 48, padding: "0 22px" }} onClick={toConnect}>Connect brokerage</button>
                  <button type="button" className="pb-btn pb-btn-secondary" style={{ height: 48, padding: "0 18px", fontSize: 14, boxShadow: "none" }} onClick={toStep1}>Start again</button>
                </div>
              </Ai>
            )}
          </>
        )}

        {busy && (
          <div style={{ display: "grid", gridTemplateColumns: "36px minmax(0,1fr)", gap: 16, alignItems: "center" }}>
            <Avatar state="working" />
            <div className="pb-serif" style={{ fontStyle: "italic", fontSize: 19, color: "#5A627A" }}>{thinkingText}</div>
          </div>
        )}
      </div>

      <div style={{ position: "sticky", bottom: 24, marginTop: 36, display: "flex", alignItems: "center", gap: 12, height: 60, padding: "0 8px 0 22px", borderRadius: 999, background: "rgba(255,255,255,.74)", backdropFilter: "blur(28px) saturate(1.6)", WebkitBackdropFilter: "blur(28px) saturate(1.6)", border: "1px solid rgba(255,255,255,.95)", boxShadow: "inset 0 1px 0 #fff,0 20px 50px rgba(40,60,120,.16)", zIndex: 3 }}>
        <input aria-label="Composer" value={query} onChange={(ev) => s.setQuery(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter") submit(); }} placeholder={placeholder} style={{ flex: 1, minWidth: 0, border: 0, outline: 0, background: "transparent", fontSize: 16, color: "#0F1626" }} />
        <span className="pb-hide-sm" style={{ fontSize: 12, color: "#5A627A", whiteSpace: "nowrap" }}>{inst ? "Press Enter to continue" : "Press Enter to select the top match"}</span>
        <button type="button" aria-label="Send" onClick={submit} style={{ width: 44, height: 44, borderRadius: "50%", background: "#0F1626", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 18, flex: "none", border: 0 }}>↑</button>
      </div>
    </main>
  );
}

const pct = (x: number | null | undefined) => (x == null || !Number.isFinite(x) ? "n/a" : `${(x * 100).toFixed(1)}%`);

/** The Opportunity step: the options fit, the PM-vs-options gap (GET /options/implied) and the risk caps the
 *  proposal is approved with. Starting it is an explicit click: propose → approve → options bridge. */
function OpportunityCard({ q, ticker, fit, opp, idea, onStart, onBack }: { q: NonNullable<ReturnType<typeof useStore>["question"]>; ticker: string; fit: FitOut; opp: NonNullable<ReturnType<typeof opportunityFit>>; idea: string; onStart: (ackUnvalidated: boolean) => Promise<void>; onBack: () => void }) {
  const m = q.real!;
  const implied = useAsync(`oi:${m.source}:${m.id}`, () => getOptionsImplied({ market_source: m.source, market_id: m.id }));
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  // The pending opportunity proposal (created, not approved): its evidence gate and capital fit before the click.
  // prepNonce: bumped after an evidence refusal so the stored evidence (rewritten by the backend before its 409) is re-read.
  const [prepNonce, setPrepNonce] = useState(0);
  const prep = useAsync(`oprep:${prepNonce}:${m.source}:${m.id}:${ticker}:${opp.family}:${opp.preset_index}`, () => prepareOpportunityProposal(q, ticker, opp));
  const gate = prep.data ? evidenceGate(prep.data.evidence) : null;
  const [ack, setAck] = useState(false);
  // Start waits for the evidence read (a click before it lands on an unvalidated market is a certain 409); a failed
  // read (prep.error) leaves it enabled and the backend's gate still applies.
  const blocked = prep.loading || (!!gate?.needsAck && !ack && prep.data?.status !== "approved");
  const capFit = prep.data ? capitalFitView(prep.data.capacity) : null;
  const d = implied.data;
  const recordedOnly = isRecordedOnly(m);
  const box = { marginTop: 14, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)" };
  const start = () => {
    if (blocked) return;
    setState({ busy: true, error: null });
    onStart(ack).catch((e) => {
      const evid = isEvidenceError(e);
      setState({ busy: false, error: `${evid ? "Evidence gate: " : ""}${e instanceof Error ? e.message : String(e)}` });
      if (evid) { setAck(false); setPrepNonce((n) => n + 1); }
    });
  };
  return (
    <div style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={cardHead}>Opportunity: {prettyId(opp.family)}, preset #{opp.preset_index}</span>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <Tag tone="ai" title={`The net P&L per unit of risk on the history of this market (in-sample). ${OPP_REPLAY_NOTE}`}>replay score {opp.score.toFixed(3)} (estimate)</Tag>
          <Tag tone="sim" title="The simulator fills option orders at the Massive quote midpoint ± half the quoted spread. For a replay of expired contracts, it uses the recorded bar close ± 2%. The Webull paper account does not accept options here.">simulated fills</Tag>
        </span>
      </div>
      {opp.instead_of && <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 6, lineHeight: 1.45 }}>The top pick of the division, {prettyId(opp.instead_of)} (score {fit.score?.toFixed(3) ?? "n/a"}), trades prediction-market legs and does not run on a bridge. This is the options family with the best score.</div>}
      <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 8 }}>{idea}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 12, marginTop: 12 }}>
        <div><div style={statLabel}>{recordedOnly ? "Final PM YES" : "Measured PM YES"}</div><div style={{ fontSize: 18, fontWeight: 600 }}>{pct(d?.pm_yes_price ?? m.yes_price)}</div></div>
        <div><div style={statLabel}>Options-implied (estimate)</div><div style={{ fontSize: 18, fontWeight: 600 }}>{implied.loading ? "…" : d?.available ? pct(d.estimate?.prob) : "n/a"}</div></div>
        <div><div style={statLabel}>Gap (PM − options)</div><div style={{ fontSize: 18, fontWeight: 600, color: d?.pm_minus_option == null ? "#8A92A8" : d.pm_minus_option > 0 ? "#22A06B" : "#E0485A" }}>{d?.pm_minus_option == null ? "n/a" : `${(d.pm_minus_option * 100).toFixed(1)} pts`}</div></div>
      </div>
      <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 8, lineHeight: 1.45 }}>
        {d?.available && d.estimate
          ? `${d.underlying_used} ${d.estimate.method?.replaceAll("_", " ")} ${d.estimate.k_lo}/${d.estimate.k_hi}, expiry ${d.estimate.expiry}. ${d.label}.`
          : recordedOnly ? `This market is resolved and its contracts expired, thus no live options estimate is available. The bridge replays its recording (${m.recorded}). The recording has the market price and the options-implied estimate for each hour, from the bar closes of the option legs.`
          : implied.error ? `The options estimate is not available (${implied.error}). Try again later.` : d && !d.available ? `No options estimate: ${d.reason ?? "unavailable"}.` : ""}
      </div>
      {fit.rationale && <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 6 }}>{fit.rationale}</div>}
      <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 6, lineHeight: 1.45 }}>{OPP_REPLAY_NOTE}</div>
      <div style={{ fontSize: 12, color: "#5A627A", marginTop: 8 }}>Risk caps on the proposal: a maximum of {DEFAULT_OPP_CAPS.max_contracts} open structures and ${DEFAULT_OPP_CAPS.max_notional.toLocaleString("en-US")} of premium or maximum loss at risk. Ticker: {ticker}.</div>
      <EvidenceGateBox gate={gate} loading={prep.loading} acknowledged={prep.data?.status === "approved" && !!prep.data.ack_unvalidated} ack={ack} onAck={setAck} copy={ackCopy(ticker, "opportunity")} testId="opp-evidence-gate" />
      {prep.error && <div style={{ fontSize: 12, color: "#8A5A00", marginTop: 6 }}>The app could not read the proposal ({prep.error}). The evidence gate of the backend still applies when you approve.</div>}
      {capFit && (
        <div style={{ fontSize: 12, color: "#3C4458", marginTop: 8, lineHeight: 1.5 }}>
          <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><span style={cardHead}>Capital</span><BadgeTag b={capFit.badge} /></span>
          {capFit.lines.map((l) => <div key={l}>{l}</div>)}
          {prep.data?.capacity?.options?.note && <div style={{ color: "#5A627A" }}>Liquidity: {prep.data.capacity.options.note}.</div>}
        </div>
      )}
      {state.error && <div role="alert" style={{ fontSize: 12.5, color: "#C8323F", marginTop: 8 }}>The options bridge did not start: {state.error}. Try again.</div>}
      <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button type="button" className={`pb-btn ${blocked ? "pb-btn-disabled" : "pb-btn-primary"}`} style={{ height: 44, padding: "0 20px" }} disabled={state.busy || blocked} onClick={start} title={blocked ? (prep.loading ? "The app reads the evidence status of this proposal first." : "Select the acknowledgement because the signal of this market is unvalidated.") : undefined}>{state.busy ? "Starting…" : prep.loading ? "Checking the evidence…" : blocked ? "Acknowledge the unvalidated market to start" : ack ? "Approve and start (unvalidated)" : "Approve and start options bridge"}</button>
        <button type="button" className="pb-btn pb-btn-secondary" style={{ height: 44, padding: "0 16px", fontSize: 14, boxShadow: "none" }} onClick={onBack}>Back</button>
      </div>
    </div>
  );
}

/** Which outcome hurts a ticker the mapping does not cover: the user says, so the hedge is never oriented by a guess. */
function DirectionAsk({ ticker, onPick }: { ticker: string; onPick: (d: "down_on_yes" | "up_on_yes") => void }) {
  return (
    <div data-testid="direction-ask" style={{ marginTop: 12, padding: "12px 14px", borderRadius: 16, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)" }}>
      <div style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.45 }}>{ticker} is not in the mapping for this market. Select the outcome that hurts {ticker}. The hedge uses your answer.</div>
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={() => onPick("down_on_yes")}>YES hurts {ticker}</button>
        <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={() => onPick("up_on_yes")}>NO hurts {ticker}</button>
      </div>
    </div>
  );
}

/** Spec §7: the fit card (event class, chosen algo, replay score, rationale, alternatives). "AI" only when an LLM answered. */
function FitCard({ fit, onRetry }: { fit: ReturnType<typeof useStore>["fit"]; onRetry?: () => void }) {
  if (!fit) return null;
  const box = { marginTop: 16, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)", fontFamily: "var(--sans)" };
  if (fit.status === "loading") return <div style={{ ...box, display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "#3C4458" }}><Orb state="working" size={20} />Replaying the applicable algo families on the history of this market…</div>;
  if (fit.noDirection) return <div style={{ ...box, fontSize: 12.5, color: "#5A627A", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><Tag tone="neutral" title={fit.error ?? undefined}>direction unknown</Tag>No hedge fit is available. Select the outcome that hurts this stock above.</div>;
  if (fit.status === "error" || !fit.data) return <div style={box}><Unavailable what="The fit (POST /pipeline/fit)" error={fit.error} onRetry={onRetry} compact /><div style={{ fontSize: 12, color: "#5A627A", marginTop: 6 }}>If no fit is available and you approve, the engine runs its default delta-bridge spec.</div></div>;
  const f = fit.data;
  const sv = fitScoreView(f);
  const ai = aiStatus(f);
  return (
    <div style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={cardHead}>{ai.live ? "AI fit" : "Fit"}: {prettyId(String(f.event_class))}</span>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <Tag tone={ai.live ? "ai" : "neutral"} title={aiTitle(ai)}>{aiLabel(ai)}</Tag>
          <Tag tone={f.ticks_source === "live_history" || f.ticks_source === "replay" ? "replay" : "neutral"} title={f.ticks_source === "none" ? undefined : IN_SAMPLE_NOTE}>{f.ticks_source === "live_history" ? `${f.n_ticks} ticks of history` : f.ticks_source === "replay" ? "replay ticks" : "no history"}</Tag>
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.015em" }}>{f.family ? prettyId(f.family) : "No applicable family"}</span>
        {f.preset_index != null && <span className="pb-mono" style={{ fontSize: 12, color: "#5A627A" }}>preset #{f.preset_index}</span>}
      </div>
            <div className="pb-mono" style={{ fontSize: 12, marginTop: 4, color: sv.tone === "positive" ? "#15804F" : "#5A627A" }} title={f.score == null ? undefined : sv.title}>{sv.headline}</div>
      {sv.secondary && <div className="pb-mono" style={{ fontSize: 11.5, marginTop: 2, color: "#5A627A" }} title={sv.title}>{sv.secondary}</div>}
      {f.rationale && <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 6 }}>{f.rationale}</div>}
      {f.alternatives?.length > 0 && <div style={{ fontSize: 12, color: "#5A627A", marginTop: 6 }}>Alternatives: {f.alternatives.slice(0, 3).map((a) => prettyId(a.family)).join(", ")}</div>}
    </div>
  );
}

/** U4: Weekend mode, shown while US equities are closed. Hedge B (an equity order staged for the first tradable moment,
 *  approved by you on the Bridge) is the default; hedge A (holding the PM contract over the closure) is an explicit
 *  opt-in, labelled an estimate and never protection, because research R1 found no evidence it reduces the loss. */
function WeekendModeCard({ market, ticker, session, pmHedge, onPmHedge, override, onOverride }: { market: { source: string; id: string; token_id?: string | null }; ticker: string; session: SessionView | null; pmHedge: boolean; onPmHedge: (on: boolean) => void; override: boolean; onOverride: (on: boolean) => void }) {
  const ev = useAsync(`ce:${market.source}:${market.id}`, () => getClosedEvidence({ market_source: market.source, market_id: market.id, token_id: market.token_id }));
  const copy = weekendModeCopy(ev.data);
  const m = ev.data?.market;
  const validated = m?.validated === true && m.status === "validated";
  const closedNow = sessionClosed(session);
  const box = { marginTop: 16, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)" };
  const opt = { display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 12, alignItems: "start", padding: "12px 0", borderTop: "1px solid rgba(15,22,38,.08)" } as const;
  return (
    <div style={box} data-testid="weekend-mode">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={cardHead}>Weekend mode: {closedNow ? session?.label ?? "market closed" : "market open, applies at the next close"}</span>
        <Tag tone={validated ? "measured" : "caution"} title={m?.evidence ?? "No out-of-sample record for this market."}>{ev.loading ? "evidence check" : validated ? "expected gap validated" : "unvalidated estimate"}</Tag>
      </div>
      <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 8 }}>
        {closedNow ? "US equities are closed, but this market continues to trade." : "US equities are open now. This mode applies from the next close, and this market continues to trade."} When equities are closed, the equity algo holds{ticker ? ` ${ticker}` : " the position"}. The bridge records the move since the close and the expected gap at the open.{validated ? "" : " For this market, the expected gap is an unvalidated estimate. The bridge shows it with its band and the closures that it comes from."}
        {m?.evidence ? ` ${m.evidence}` : ""}
      </div>
      <div style={{ ...opt, marginTop: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><span style={{ fontSize: 14, fontWeight: 600 }}>Hedge B: staged order for the first tradable time</span><Tag tone="neutral">default</Tag></div>
          <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3, lineHeight: 1.45 }}>{copy.hedgeB}</div>
        </div>
        <Tag tone="sim" title="The Bridge page stages the order. No order executes until you press Approve plan.">you approve it</Tag>
      </div>
      <div style={opt}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><span style={{ fontSize: 14, fontWeight: 600 }}>Hedge A: hold the prediction-market contract during the closure</span><Tag tone="caution">estimate, not protection</Tag></div>
          <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3, lineHeight: 1.45 }}>{copy.hedgeA}</div>
          <div style={{ fontSize: 12, color: pmHedge ? "#9A4A00" : "#5A627A", marginTop: 6 }}>{pmHedge ? "On: the bridge runs a simulated PM-leg estimate together with hedge B and closes it at the open." : "Off (default)."}</div>
        </div>
        <Switch on={pmHedge} onClick={() => onPmHedge(!pmHedge)} label="Enable hedge A (estimate, not protection)" />
      </div>
      {(!validated || override) && !ev.loading && (
        <div style={opt} data-testid="override-row">
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><span style={{ fontSize: 14, fontWeight: 600 }}>Override: stage hedge B on an unvalidated market</span><Tag tone="caution">override</Tag></div>
            <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3, lineHeight: 1.45 }}>
              If the override is off, the evidence gate stops staged orders on this market (EVIDENCE_GATE). The bridge tells you one time for each closure. {OVERRIDE_COPY} You must also select the acknowledgement when you approve.
            </div>
            <div style={{ fontSize: 12, color: override ? "#9A4A00" : "#5A627A", marginTop: 6 }}>{override ? "On: staged plans on this market show the label “override”." : "Off (default): no staged plan on an unvalidated market."}</div>
          </div>
          <Switch on={override} onClick={() => onOverride(!override)} label="Override the evidence gate for staged plans" />
        </div>
      )}
    </div>
  );
}

/** Before connecting: can the market absorb the hedge (GET /liquidity), what each hedge instrument costs
 *  (GET /options/hedge-quote), and the strike ladder on demand (GET /options/chain/{ticker}). */
function RiskPreview({ ticker, held, maxHedge, notional, fitRuns }: { ticker: string; held: number; maxHedge: string; notional: boolean; fitRuns: boolean }) {
  // Same coverage the proposal will carry (realBridge.hedgeTerms): Max hedge with a runnable fit, else at most 50%.
  const cap = Math.min(1, (parseInt(maxHedge, 10) || 100) / 100);
  const coverage = fitRuns ? cap : Math.min(0.5, cap);
  const hedge = Math.floor(coverage * held);
  const liq = useAsync(`liq:${ticker}:${coverage}:${hedge}`, () => getLiquidity(ticker, { coverage, qty: hedge }));
  const [chain, setChain] = useState(false);
  const view = liq.error ? { ...capacityFromLiquidity(null), reason: `Liquidity data is not available (${liq.error}). Orders have no cap and show the label “unknown”.`, verdict: { tone: "neutral" as const, text: "caps unknown" } } : capacityFromLiquidity(liq.data, hedge);
  return (
    <div data-testid="risk-preview">
      <CapacityCard view={view} title={`Liquidity for ${ticker}: hedge of ${hedge.toLocaleString("en-US")} shares${notional ? " (notional)" : ""}`}
        tag={<Tag tone="ai" title="Participation caps: each order is a maximum of 10% of the opening 5-minute volume, and each day is a maximum of 1% of ADV. Cost is half the spread plus square-root impact (k = 1.0).">estimate</Tag>}
        footer={<div style={{ fontSize: 11, color: "#5A627A", marginTop: 6 }}>The bridge compares each order with these caps and with the capital budget of the account. Capped orders show the label “liquidity capped”.</div>} />
      <HedgeCompareCard ticker={ticker} shares={held} />
      <div style={{ marginTop: 10 }}>
        <button type="button" className="pb-chip pb-chip-sm" data-on={chain} onClick={() => setChain(!chain)}>{chain ? "Hide the options chain" : "Show the options chain"}</button>
      </div>
      {chain && <OptionChainCard ticker={ticker} />}
    </div>
  );
}
