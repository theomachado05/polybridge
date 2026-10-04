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

const optsBox = { marginTop: "var(--sp-4)", overflow: "hidden" } as const;
const cardHead = { fontSize: "var(--fs-14)", fontWeight: 600, color: "var(--ink)" } as const;
const statLabel = { fontSize: "var(--fs-12)", color: "var(--faint)" } as const;
const statValue = { fontSize: "var(--fs-20)", fontWeight: 600, marginTop: 2 } as const;
const cardBox = { marginTop: "var(--sp-4)", padding: "var(--sp-4) var(--sp-5)" } as const;
const rowTitle = { fontSize: "var(--fs-14)", fontWeight: 500, lineHeight: 1.35, color: "var(--ink)" } as const;
const rowSub = { fontSize: "var(--fs-12)", color: "var(--text-2)", marginTop: 2, lineHeight: 1.4 } as const;
const rowSide = { fontSize: "var(--fs-12)", color: "var(--faint)", whiteSpace: "nowrap" } as const;
const rowFigure = { fontSize: "var(--fs-16)", fontWeight: 600, color: "var(--ink)" } as const;
const note = { marginTop: "var(--sp-2)", fontSize: "var(--fs-12)", color: "var(--text-2)" } as const;

function Avatar({ state }: { state: string }) {
  return (
    <div style={{ width: 36, height: 36, borderRadius: "50%", background: "var(--surface)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Orb state={state} size={26} />
    </div>
  );
}

function Ai({ orb, text, children }: { orb: string; text: ReactNode; children?: ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "36px minmax(0,1fr)", gap: "var(--sp-4)", alignItems: "start" }}>
      <Avatar state={orb} />
      <div style={{ minWidth: 0, paddingTop: "var(--sp-1)" }}>
        <div className="pb-serif pb-pretty" style={{ fontSize: "var(--fs-20)", lineHeight: 1.45, color: "var(--ink)" }}>{text}</div>
        {children}
      </div>
    </div>
  );
}

function User({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end" }}>
      <button type="button" title="Click to change this answer." onClick={onClick} className="pb-chip" data-on={false} style={{ maxWidth: "78%", padding: "var(--sp-2) var(--sp-4)", borderRadius: "var(--radius)", fontSize: "var(--fs-14)", lineHeight: 1.4, color: "var(--ink)", textAlign: "left" }}>{text}</button>
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

  const hdr = (filled: boolean, active: boolean) => ({ active, color: active ? "var(--ink)" : "var(--faint)", fg: active ? "var(--text-2)" : filled ? "var(--text-2)" : "var(--faint)" });
  const slots = [
    { k: "1. Event", v: q ? q.ev : "Select an event", c: hdr(!!q, step === 1), go: toStep1 },
    { k: "2. Stock", v: e ? `${e.t}, ${e.name}` : step === 2 ? "Select a stock" : "Not selected", c: hdr(!!e, step === 2), go: toStep2 },
    { k: "3. Hedge", v: chosen ? chosen.short : step === 3 ? "Select a hedge" : "Not selected", c: hdr(!!inst, step === 3 && !inst), go: toStep3 },
  ];
  const placeholder = step === 1 ? "Type an event, for example Fed cuts in December" : step === 2 ? "Type a ticker" : !inst ? "Type the hedge that you want" : "Press Enter to continue";
  const fit = s.fit && q && e && s.fit.key === `${q.id}|${e.t}` ? s.fit : null;

  return (
    <main className="pb-page" style={{ paddingTop: "var(--sp-6)", paddingBottom: "var(--sp-6)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: "var(--sp-5)", borderBottom: "1px solid var(--border)" }}>
        {slots.map((x) => (
          <button type="button" key={x.k} onClick={x.go} aria-current={x.c.active ? "step" : undefined} style={{ cursor: "pointer", minWidth: 0, background: "transparent", border: 0, borderBottom: `2px solid ${x.c.active ? "var(--accent)" : "transparent"}`, marginBottom: -1, padding: "0 0 var(--sp-3)", textAlign: "left", font: "inherit", transition: "border-color var(--dur) var(--ease)" }}>
            <div style={{ fontSize: "var(--fs-13)", fontWeight: x.c.active ? 600 : 500, color: x.c.color }}>{x.k}</div>
            <div className="pb-ellipsis" style={{ fontSize: "var(--fs-13)", marginTop: 2, color: x.c.fg }}>{x.v}</div>
          </button>
        ))}
      </div>

      <div style={{ maxWidth: 820, display: "flex", flexDirection: "column", gap: "var(--sp-5)", marginTop: "var(--sp-6)" }}>
        <Ai orb="breathing" text={ai1}>
          {step === 1 && !busy && (
            <div className="pb-card pb-list" style={optsBox}>
              {ql && search.loading && <div className="pb-list-note">Searching Polymarket and Kalshi…</div>}
              {ql && search.error && <Unavailable what="Market search" error={search.error} onRetry={retrySearch} compact style={{ padding: "var(--sp-3) var(--sp-5)" }} />}
              {ql && search.data && !search.loading && shown.length === 0 && <div className="pb-list-note">The search found no open market for “{query.trim()}”. Type a different event.</div>}
              {!ql && portfolio.status === "error" && <Unavailable what="The markets for your holdings (GET /portfolio)" error={portfolio.error} onRetry={s.refreshAccount} compact style={{ padding: "var(--sp-3) var(--sp-5)" }} />}
              {!ql && portfolio.status === "ok" && shown.length === 0 && <div className="pb-list-note">No open market is available for your holdings. Type an event to search Polymarket and Kalshi.</div>}
              {search.data?.stale && ql && <div className="pb-list-note"><Tag tone="sim" title={search.data.note ?? "The live source did not answer. These results come from the cache."}>cached results</Tag></div>}
              {shown.map((x) => {
                const held = x.touches.find((t) => holdingOf(t));
                return (
                  <button key={x.id} type="button" className="pb-list-row" onClick={() => pickQuestion(x)}>
                    <div style={{ minWidth: 0 }}>
                      <div className="pb-pretty" style={rowTitle}>{x.q}</div>
                      <div style={{ ...rowSub, display: "flex", alignItems: "center", gap: "var(--sp-1) var(--sp-2)", flexWrap: "wrap" }}>
                        <span>
                        {x.venues.join(" and ")}{x.touches.length ? ", moves " + x.touches.slice(0, 3).join(", ") : ""}{held ? ", you hold " + held : ""}</span>
                        {isRecordedOnly(x.real)
                          ? <Tag tone="replay" title={`This market is resolved. The list shows it because the backend has its recorded history (${x.real.recorded}), and the bridge replays that history.`}>resolved, recorded replay</Tag>
                          : <Tag tone="live" title="This market comes from GET /markets/search or from the markets of your portfolio.">live market</Tag>}
                        {isFeaturedReplay(x) && <><Tag tone="replay" title="A bridge on this market replays its recorded Polymarket history at a faster speed.">recorded replay</Tag></>}
                      </div>
                    </div>
                    <div className="pb-num" style={{ textAlign: "right", flex: "none", minWidth: 120 }}>
                      <div style={rowFigure}>{x.real.yes_price == null ? "n/a" : x.yes + "¢"}</div>
                      <div style={{ ...rowSide, marginTop: 2 }}>YES, {x.vol} volume</div>
                    </div>
                  </button>
                );
              })}
              {more > 0 && <div className="pb-list-note" style={{ fontSize: "var(--fs-12)" }}>{more} more markets. Type to search.</div>}
              {!ql && (
                <button type="button" className="pb-list-row" onClick={() => void s.openWeekendReplay()}>
                  <div style={{ minWidth: 0 }}>
                    <div className="pb-pretty" style={rowTitle}>{WEEKEND_REPLAY.question} (April 2025 tariff weekend)</div>
                    <div style={{ ...rowSub, display: "flex", alignItems: "center", gap: "var(--sp-1) var(--sp-2)", flexWrap: "wrap" }}><span>Polymarket, hedges {WEEKEND_REPLAY.ticker}</span><Tag tone="replay" title={`The backend replays its recording (${WEEKEND_REPLAY.recorded}) from Friday 15:30 ET to Monday 10:00 ET.`}>recorded weekend</Tag></div>
                  </div>
                  <div style={rowSide}>replay</div>
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
                    <div style={{ marginTop: "var(--sp-2)", display: "flex", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
                      {ml && <Tag tone="ai" title={`${ml.title} ${map.data.label}`}>{ml.text}</Tag>}
                      {map.data.match_type === "fuzzy" && <span style={{ fontSize: "var(--fs-12)", color: "var(--text-2)" }}>Nearest mapped question: “{map.data.matched_question}”</span>}
                    </div>
                  );
                })()}
                {map.error && <Unavailable what="Stock mapping (POST /map)" error={map.error} onRetry={retryMap} compact style={{ marginTop: "var(--sp-2)" }} />}
                {map.data && map.data.items.length === 0 && map.data.note && <div style={note}>No mapping: {map.data.note}.</div>}
                {step === 2 && !busy && elist.length > 0 && (
                  <div className="pb-card pb-list" style={optsBox}>
                    {elist.map((i) => {
                      const held = heldOf(q, i.t), name = holdingOf(i.t)?.name ?? (e?.t === i.t ? e.name : "");
                      return (
                        <button key={i.t} type="button" className="pb-list-row" onClick={() => pickEquity(i)}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: "var(--sp-1) var(--sp-3)", flexWrap: "wrap" }}>
                              <span className="pb-ticker" style={{ fontSize: "var(--fs-14)" }}>{i.t}</span>
                              <span style={{ fontSize: "var(--fs-13)", color: "var(--text-2)" }}>{name}</span>
                              {held > 0 && <span className="pb-num" style={{ fontSize: "var(--fs-12)", fontWeight: 500, color: "var(--up)" }}>{held.toLocaleString("en-US")} shares held</span>}
                            </div>
                            {i.why && <div className="pb-pretty" style={rowSub}>{i.why}</div>}
                          </div>
                          <div className="pb-num" style={{ textAlign: "right", flex: "none", minWidth: 80 }}>
                            <div style={{ ...rowFigure, color: !i.move ? "var(--faint)" : i.move < 0 ? "var(--down)" : "var(--up)" }}>{i.move ? fmtPct(i.move) : "n/a"}</div>
                            <div style={{ ...rowSide, marginTop: 2 }}>on YES</div>
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
                  <div className="pb-card pb-list" style={optsBox}>
                    <button type="button" className="pb-list-row" onClick={() => setMode({ key: pickKey, m: "hedge" })}>
                      <div style={{ minWidth: 0 }}>
                        <div style={rowTitle}>Hedge</div>
                        <div className="pb-pretty" style={rowSub}>Hedge the {e.t} position. The engine sells shares short when the market moves against the position.</div>
                      </div>
                      <div style={rowSide}>shares</div>
                    </button>
                    <button type="button" className="pb-list-row" onClick={() => setMode({ key: pickKey, m: "opportunity" })}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" }}>
                          <span style={rowTitle}>Opportunity</span>
                          <Tag tone="ai" title={`${aiTitle(aiStatus(oppData))} POST /pipeline/fit (division opportunity) gives this replay score. It is the net P&L per unit of risk on the history of this market. Only presets that traded get a score. ${OPP_REPLAY_NOTE} It is a replay estimate, not a forecast.`}>{aiLabel(aiStatus(oppData))}, replay score {opp.score.toFixed(3)} (estimate)</Tag>
                        </div>
                        <div className="pb-pretty" style={rowSub}>{prettyId(opp.family)} (preset #{opp.preset_index}): {oppIdea} The replay option prices are estimates from bar closes. Option fills are simulated.{opp.score < 0 ? " This preset lost money on this replay." : ""}</div>
                      </div>
                      <div style={rowSide}>options</div>
                    </button>
                  </div>
                )}
                {step === 3 && !inst && !busy && opp && chosenMode === "opportunity" && q && (
                  <OpportunityCard q={q} ticker={e.t} fit={oppData!} opp={opp} idea={oppIdea} onBack={() => setMode(null)}
                    onStart={async (ack) => { const id = await s.openOpportunity(q, e, { ackUnvalidated: ack }); router.push(`/bridge/${id.replace(/^live:/, "")}`); }} />
                )}
                {step === 3 && !inst && !busy && showHedge && (
                  <div style={note}>
                    The bridge runs the dynamic short hedge. The next step prices option structures (puts, collars, spreads) from real quotes for comparison.
                  </div>
                )}
                {!e.direction && real && (
                  <DirectionAsk ticker={e.t} onPick={s.chooseDirection} />
                )}
                {e.directionSource === "user" && e.direction && (
                  <div style={note}>
                    You said that {e.direction === "down_on_yes" ? "YES" : "NO"} hurts {e.t}. The hedge uses this direction.{" "}
                    <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={() => s.chooseDirection(e.direction === "down_on_yes" ? "up_on_yes" : "down_on_yes")}>Change direction</button>
                  </div>
                )}
                {step === 3 && !inst && !busy && showHedge && (
                  <div className="pb-card pb-list" style={optsBox}>
                    {ilist.map((i) => (
                      <button key={i.id} type="button" className="pb-list-row" onClick={() => s.setInst(i.id)}>
                        <div style={{ minWidth: 0 }}>
                          <div style={rowTitle}>{i.name}</div>
                          <div className="pb-pretty" style={rowSub}>{i.fit} {i.tax}.</div>
                        </div>
                        <div className="pb-num" style={{ textAlign: "right", flex: "none" }}>
                          <div style={{ fontSize: "var(--fs-14)", fontWeight: 600, whiteSpace: "nowrap", color: "var(--ink)" }}>{i.cost}</div>
                          <div style={{ ...rowSide, marginTop: 2 }}>{i.cover}</div>
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
                <div style={{ marginTop: "var(--sp-5)", display: "flex", gap: "var(--sp-3)", flexWrap: "wrap" }}>
                  <button type="button" className="pb-btn pb-btn-primary" onClick={toConnect}>Connect brokerage</button>
                  <button type="button" className="pb-btn pb-btn-secondary" onClick={toStep1}>Start again</button>
                </div>
              </Ai>
            )}
          </>
        )}

        {busy && (
          <div style={{ display: "grid", gridTemplateColumns: "36px minmax(0,1fr)", gap: "var(--sp-4)", alignItems: "center" }}>
            <Avatar state="working" />
            <div className="pb-serif" style={{ fontStyle: "italic", fontSize: "var(--fs-20)", color: "var(--faint)" }}>{thinkingText}</div>
          </div>
        )}
      </div>

      <div style={{ position: "sticky", bottom: "var(--sp-5)", maxWidth: 820, boxSizing: "border-box", marginTop: "var(--sp-6)", display: "flex", alignItems: "center", gap: "var(--sp-3)", height: 56, padding: "0 var(--sp-2) 0 var(--sp-5)", borderRadius: "var(--radius)", background: "var(--surface)", border: "1px solid var(--border-strong)", boxShadow: "var(--shadow-overlay)", zIndex: 3 }}>
        <input aria-label="Composer" value={query} onChange={(ev) => s.setQuery(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter") submit(); }} placeholder={placeholder} style={{ flex: 1, minWidth: 0, border: 0, outline: 0, background: "transparent", fontSize: "var(--fs-16)", color: "var(--ink)" }} />
        <span className="pb-hide-sm" style={{ fontSize: "var(--fs-12)", color: "var(--faint)", whiteSpace: "nowrap" }}>{inst ? "Press Enter to continue" : "Press Enter to select the top match"}</span>
        <button type="button" aria-label="Send" onClick={submit} style={{ width: 40, height: 40, borderRadius: 8, background: "var(--ink)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: "var(--fs-16)", flex: "none", border: 0 }}>↑</button>
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
    <div className="pb-card" style={cardBox}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
        <span style={cardHead}>Opportunity: {prettyId(opp.family)}, preset #{opp.preset_index}</span>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)" }}>
          <Tag tone="ai" title={`The net P&L per unit of risk on the history of this market (in-sample). ${OPP_REPLAY_NOTE}`}>replay score {opp.score.toFixed(3)} (estimate)</Tag>
          <Tag tone="sim" title="The simulator fills option orders at the Massive quote midpoint ± half the quoted spread. For a replay of expired contracts, it uses the recorded bar close ± 2%. The Webull paper account does not accept options here.">simulated fills</Tag>
        </span>
      </div>
      {opp.instead_of && <div className="pb-pretty" style={{ ...note, lineHeight: 1.45 }}>The top pick of the division, {prettyId(opp.instead_of)} (score {fit.score?.toFixed(3) ?? "n/a"}), trades prediction-market legs and does not run on a bridge. This is the options family with the best score.</div>}
      <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{idea}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: "var(--sp-3)", marginTop: "var(--sp-4)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)" }}>
        <div><div style={statLabel}>{recordedOnly ? "Final PM YES" : "Measured PM YES"}</div><div className="pb-num" style={statValue}>{pct(d?.pm_yes_price ?? m.yes_price)}</div></div>
        <div><div style={statLabel}>Options-implied (estimate)</div><div className="pb-num" style={statValue}>{implied.loading ? "…" : d?.available ? pct(d.estimate?.prob) : "n/a"}</div></div>
        <div><div style={statLabel}>Gap (PM − options)</div><div className="pb-num" style={{ ...statValue, color: d?.pm_minus_option == null ? "var(--faint)" : d.pm_minus_option > 0 ? "var(--up)" : "var(--down)" }}>{d?.pm_minus_option == null ? "n/a" : `${(d.pm_minus_option * 100).toFixed(1)} pts`}</div></div>
      </div>
      <div className="pb-pretty" style={{ ...note, lineHeight: 1.45 }}>
        {d?.available && d.estimate
          ? `${d.underlying_used} ${d.estimate.method?.replaceAll("_", " ")} ${d.estimate.k_lo}/${d.estimate.k_hi}, expiry ${d.estimate.expiry}. ${d.label}.`
          : recordedOnly ? `This market is resolved and its contracts expired, thus no live options estimate is available. The bridge replays its recording (${m.recorded}). The recording has the market price and the options-implied estimate for each hour, from the bar closes of the option legs.`
          : implied.error ? `The options estimate is not available (${implied.error}). Try again later.` : d && !d.available ? `No options estimate: ${d.reason ?? "unavailable"}.` : ""}
      </div>
      {fit.rationale && <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{fit.rationale}</div>}
      <div className="pb-pretty" style={{ ...note, lineHeight: 1.45 }}>{OPP_REPLAY_NOTE}</div>
      <div className="pb-num" style={note}>Risk caps on the proposal: a maximum of {DEFAULT_OPP_CAPS.max_contracts} open structures and ${DEFAULT_OPP_CAPS.max_notional.toLocaleString("en-US")} of premium or maximum loss at risk. Ticker: {ticker}.</div>
      <EvidenceGateBox gate={gate} loading={prep.loading} acknowledged={prep.data?.status === "approved" && !!prep.data.ack_unvalidated} ack={ack} onAck={setAck} copy={ackCopy(ticker, "opportunity")} testId="opp-evidence-gate" />
      {prep.error && <div style={{ ...note, color: "var(--warn)" }}>The app could not read the proposal ({prep.error}). The evidence gate of the backend still applies when you approve.</div>}
      {capFit && (
        <div className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--text-2)", marginTop: "var(--sp-3)", paddingTop: "var(--sp-3)", borderTop: "1px solid var(--border)", lineHeight: 1.5 }}>
          <span style={{ display: "inline-flex", gap: "var(--sp-2)", alignItems: "center", marginBottom: "var(--sp-1)" }}><span style={cardHead}>Capital</span><BadgeTag b={capFit.badge} /></span>
          {capFit.lines.map((l) => <div key={l}>{l}</div>)}
          {prep.data?.capacity?.options?.note && <div style={{ color: "var(--faint)" }}>Liquidity: {prep.data.capacity.options.note}.</div>}
        </div>
      )}
      {state.error && <div role="alert" className="pb-small" style={{ color: "var(--down)", marginTop: "var(--sp-2)" }}>The options bridge did not start: {state.error}. Try again.</div>}
      <div style={{ marginTop: "var(--sp-4)", display: "flex", gap: "var(--sp-3)", flexWrap: "wrap" }}>
        <button type="button" className={`pb-btn ${blocked ? "pb-btn-disabled" : "pb-btn-primary"}`} disabled={state.busy || blocked} onClick={start} title={blocked ? (prep.loading ? "The app reads the evidence status of this proposal first." : "Select the acknowledgement because the signal of this market is unvalidated.") : undefined}>{state.busy ? "Starting…" : prep.loading ? "Checking the evidence…" : blocked ? "Acknowledge the unvalidated market to start" : ack ? "Approve and start (unvalidated)" : "Approve and start options bridge"}</button>
        <button type="button" className="pb-btn pb-btn-secondary" onClick={onBack}>Back</button>
      </div>
    </div>
  );
}

/** Which outcome hurts a ticker the mapping does not cover: the user says, so the hedge is never oriented by a guess. */
function DirectionAsk({ ticker, onPick }: { ticker: string; onPick: (d: "down_on_yes" | "up_on_yes") => void }) {
  return (
    <div data-testid="direction-ask" className="pb-card" style={cardBox}>
      <div className="pb-small">{ticker} is not in the mapping for this market. Select the outcome that hurts {ticker}. The hedge uses your answer.</div>
      <div style={{ display: "flex", gap: "var(--sp-2)", marginTop: "var(--sp-3)", flexWrap: "wrap" }}>
        <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={() => onPick("down_on_yes")}>YES hurts {ticker}</button>
        <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={() => onPick("up_on_yes")}>NO hurts {ticker}</button>
      </div>
    </div>
  );
}

/** Spec §7: the fit card (event class, chosen algo, replay score, rationale, alternatives). "AI" only when an LLM answered. */
function FitCard({ fit, onRetry }: { fit: ReturnType<typeof useStore>["fit"]; onRetry?: () => void }) {
  if (!fit) return null;
  const box = cardBox;
  if (fit.status === "loading") return <div className="pb-card pb-small" style={{ ...box, display: "flex", alignItems: "center", gap: "var(--sp-3)" }}><Orb state="working" size={20} />Replaying the applicable algo families on the history of this market…</div>;
  if (fit.noDirection) return <div className="pb-card pb-small" style={{ ...box, display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}><Tag tone="neutral" title={fit.error ?? undefined}>direction unknown</Tag>No hedge fit is available. Select the outcome that hurts this stock above.</div>;
  if (fit.status === "error" || !fit.data) return <div className="pb-card" style={box}><Unavailable what="The fit (POST /pipeline/fit)" error={fit.error} onRetry={onRetry} compact /><div style={note}>If no fit is available and you approve, the engine runs its default delta-bridge spec.</div></div>;
  const f = fit.data;
  const sv = fitScoreView(f);
  const ai = aiStatus(f);
  return (
    <div className="pb-card" style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
        <span style={cardHead}>{ai.live ? "AI fit" : "Fit"}: {prettyId(String(f.event_class))}</span>
        <span style={{ display: "inline-flex", gap: "var(--sp-2)" }}>
          <Tag tone={ai.live ? "ai" : "neutral"} title={aiTitle(ai)}>{aiLabel(ai)}</Tag>
          <Tag tone={f.ticks_source === "live_history" || f.ticks_source === "replay" ? "replay" : "neutral"} title={f.ticks_source === "none" ? undefined : IN_SAMPLE_NOTE}>{f.ticks_source === "live_history" ? `${f.n_ticks} ticks of history` : f.ticks_source === "replay" ? "replay ticks" : "no history"}</Tag>
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--sp-3)", marginTop: "var(--sp-3)", flexWrap: "wrap" }}>
        <span style={{ fontSize: "var(--fs-16)", fontWeight: 600, color: "var(--ink)" }}>{f.family ? prettyId(f.family) : "No applicable family"}</span>
        {f.preset_index != null && <span className="pb-num" style={{ fontSize: "var(--fs-12)", color: "var(--text-2)" }}>preset #{f.preset_index}</span>}
      </div>
      <div className="pb-num" style={{ fontSize: "var(--fs-12)", marginTop: "var(--sp-1)", color: sv.tone === "positive" ? "var(--up)" : "var(--text-2)" }} title={f.score == null ? undefined : sv.title}>{sv.headline}</div>
      {sv.secondary && <div className="pb-num" style={{ fontSize: "var(--fs-12)", marginTop: 2, color: "var(--text-2)" }} title={sv.title}>{sv.secondary}</div>}
      {f.rationale && <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>{f.rationale}</div>}
      {f.alternatives?.length > 0 && <div style={note}>Alternatives: {f.alternatives.slice(0, 3).map((a) => prettyId(a.family)).join(", ")}</div>}
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
  const opt = { display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: "var(--sp-3)", alignItems: "start", padding: "var(--sp-3) 0", borderTop: "1px solid var(--border)" } as const;
  const optTitle = { fontSize: "var(--fs-14)", fontWeight: 600, color: "var(--ink)" } as const;
  const optBody = { fontSize: "var(--fs-12)", color: "var(--text-2)", marginTop: 2, lineHeight: 1.45 } as const;
  return (
    <div className="pb-card" style={{ ...cardBox, paddingBottom: "var(--sp-1)" }} data-testid="weekend-mode">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", flexWrap: "wrap", alignItems: "center" }}>
        <span style={cardHead}>Weekend mode: {closedNow ? session?.label ?? "market closed" : "market open, applies at the next close"}</span>
        <Tag tone={validated ? "measured" : "caution"} title={m?.evidence ?? "No out-of-sample record for this market."}>{ev.loading ? "evidence check" : validated ? "expected gap validated" : "unvalidated estimate"}</Tag>
      </div>
      <div className="pb-small pb-pretty" style={{ marginTop: "var(--sp-2)" }}>
        {closedNow ? "US equities are closed, but this market continues to trade." : "US equities are open now. This mode applies from the next close, and this market continues to trade."} When equities are closed, the equity algo holds{ticker ? ` ${ticker}` : " the position"}. The bridge records the move since the close and the expected gap at the open.{validated ? "" : " For this market, the expected gap is an unvalidated estimate. The bridge shows it with its band and the closures that it comes from."}
        {m?.evidence ? ` ${m.evidence}` : ""}
      </div>
      <div style={{ ...opt, marginTop: "var(--sp-3)" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}><span style={optTitle}>Hedge B: staged order for the first tradable time</span><Tag tone="neutral">default</Tag></div>
          <div className="pb-pretty" style={optBody}>{copy.hedgeB}</div>
        </div>
        <Tag tone="sim" title="The Bridge page stages the order. No order executes until you press Approve plan.">you approve it</Tag>
      </div>
      <div style={opt}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}><span style={optTitle}>Hedge A: hold the prediction-market contract during the closure</span><Tag tone="caution">estimate, not protection</Tag></div>
          <div className="pb-pretty" style={optBody}>{copy.hedgeA}</div>
          <div style={{ fontSize: "var(--fs-12)", color: pmHedge ? "var(--warn)" : "var(--faint)", marginTop: "var(--sp-1)" }}>{pmHedge ? "On: the bridge runs a simulated PM-leg estimate together with hedge B and closes it at the open." : "Off (default)."}</div>
        </div>
        <Switch on={pmHedge} onClick={() => onPmHedge(!pmHedge)} label="Enable hedge A (estimate, not protection)" />
      </div>
      {(!validated || override) && !ev.loading && (
        <div style={opt} data-testid="override-row">
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center", flexWrap: "wrap" }}><span style={optTitle}>Override: stage hedge B on an unvalidated market</span><Tag tone="caution">override</Tag></div>
            <div className="pb-pretty" style={optBody}>
              If the override is off, the evidence gate stops staged orders on this market (EVIDENCE_GATE). The bridge tells you one time for each closure. {OVERRIDE_COPY} You must also select the acknowledgement when you approve.
            </div>
            <div style={{ fontSize: "var(--fs-12)", color: override ? "var(--warn)" : "var(--faint)", marginTop: "var(--sp-1)" }}>{override ? "On: staged plans on this market show the label “override”." : "Off (default): no staged plan on an unvalidated market."}</div>
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
        footer={<div style={{ fontSize: "var(--fs-12)", color: "var(--faint)", marginTop: "var(--sp-2)" }}>The bridge compares each order with these caps and with the capital budget of the account. Capped orders show the label “liquidity capped”.</div>} />
      <HedgeCompareCard ticker={ticker} shares={held} />
      <div style={{ marginTop: "var(--sp-3)" }}>
        <button type="button" className="pb-chip pb-chip-sm" data-on={chain} onClick={() => setChain(!chain)}>{chain ? "Hide the options chain" : "Show the options chain"}</button>
      </div>
      {chain && <OptionChainCard ticker={ticker} />}
    </div>
  );
}
