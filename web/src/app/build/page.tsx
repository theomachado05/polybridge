"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getEquity, getLibrary, getOptionsImplied, mapEvent, searchMarkets, type FitOut, type Holding, type MapOut } from "@/lib/api";
import { DEFAULT_OPP_CAPS, opportunityFit } from "@/lib/realBridge";
import { EQ, INSTRUMENTS, QUESTIONS, REAL_INSTRUMENTS, demoFirst, demoImpacts, isDemoMarket, isOpenMarket, questionFromMarket, topImpact, type EquityPick, type Impact, type Question } from "@/lib/demo";
import { fmtPct, prettyId } from "@/lib/fmt";
import { fitScoreView, IN_SAMPLE_NOTE } from "@/lib/pipeline";
import { useAsync } from "@/lib/hooks";
import { OPP_REPLAY_NOTE, libraryIdea, optionFamilyIdea } from "@/lib/opportunity";
import { useStore } from "@/lib/store";
import { DemoTag, Orb, Tag } from "@/components/pb";

const optsBox = { marginTop: 14, padding: 6, borderRadius: 22, display: "flex", flexDirection: "column" as const };
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
    <div style={{ display: "grid", gridTemplateColumns: "36px minmax(0,1fr)", gap: 16, alignItems: "start", animation: "pb-in .35s ease-out" }}>
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
    <div style={{ display: "flex", justifyContent: "flex-end", animation: "pb-in .3s ease-out" }}>
      <div role="button" tabIndex={0} title="Edit" onClick={onClick} onKeyDown={(e) => e.key === "Enter" && onClick()} style={{ maxWidth: "78%", padding: "12px 18px", borderRadius: "22px 22px 6px 22px", background: "#0F1626", color: "#fff", fontSize: 15, lineHeight: 1.4, cursor: "pointer", boxShadow: "0 10px 26px rgba(15,22,38,.22)" }}>{text}</div>
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
    return map.items.map((i) => ({ t: i.ticker.toUpperCase(), move: signedImpact(i.impact_pct, i.direction), rev: null, brand: null, why: i.rationale ?? "", direction: i.direction === "up_on_yes" ? "up_on_yes" : "down_on_yes", real: true }));
  }
  return q.touches.map((t) => ({ t, move: 0, rev: null, brand: null, why: "Not in the precomputed mapping yet, so the impact is unknown.", real: true }));
}

export default function Build() {
  const router = useRouter();
  const s = useStore();
  const { question: q, equity: e, inst, query, thinking, settings, portfolio } = s;
  const step = !q ? 1 : !e ? 2 : 3;
  const real = !!q?.real;
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
  const search = useAsync(debounced ? `s:${debounced}` : null, () => searchMarkets(debounced));
  const map = useAsync(q?.real ? `m:${q.id}` : null, () => mapEvent({ question: q!.q, source: q!.real!.source, market_id: q!.real!.id }));

  const holdings = useMemo(() => (portfolio.status === "ok" && portfolio.data ? portfolio.data.holdings : []), [portfolio]);
  const holdingOf = (t: string) => holdings.find((h) => h.ticker === t) ?? null;
  const heldOf = (qq: Question, t: string) => (qq.real ? holdingOf(t)?.shares ?? 0 : EQ[t]?.held ?? 0);

  useEffect(() => {
    requestAnimationFrame(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" }));
  }, [q, e, inst, thinking]);

  // ---- step 1 rows
  const ql = query.trim().toLowerCase();
  // Held-market rows, the demo market (the one `make dev` replays) first so it is one click away.
  const realBase = useMemo(() => demoFirst(portfolioQuestions(holdings)), [holdings]);
  const searchRows = useMemo(() => (search.data?.markets ?? []).filter((m) => isOpenMarket(m)).map((m) => {
    const known = realBase.find((x) => x.id === `${m.source}:${m.id}`);
    return known ?? questionFromMarket(m);
  }), [search.data, realBase]);
  const demoHeld = (x: Question) => x.touches.some((t) => EQ[t]?.held);
  const demoRows = QUESTIONS.filter((x) => !ql || x.q.toLowerCase().includes(ql) || x.ev.toLowerCase().includes(ql) || x.touches.some((t) => t.toLowerCase().includes(ql)))
    .sort((a, b) => Number(demoHeld(b)) - Number(demoHeld(a)));
  const realFiltered = ql ? searchRows : realBase.slice(0, 3);
  const all = [...realFiltered, ...demoRows];
  const shown = ql ? all.slice(0, 10) : all.slice(0, 5);
  const more = all.length - shown.length;

  // ---- step 2 rows
  const impacts: Impact[] = !q ? [] : real ? mapImpacts(map.data, q) : demoImpacts(q);
  let elist = impacts;
  if (q && ql && step === 2) {
    const u = ql.toUpperCase();
    const universe = new Set([...Object.keys(EQ), ...holdings.map((h) => h.ticker), ...impacts.map((i) => i.t)]);
    elist = [...universe].filter((t) => t.includes(u) || (EQ[t]?.name ?? holdingOf(t)?.name ?? "").toUpperCase().includes(u))
      .map((t) => impacts.find((i) => i.t === t) ?? (real ? { t, move: 0, rev: null, brand: null, why: "Not in this market's mapping, so the impact is unknown.", real: true } : { t, move: -1.2, rev: -0.6, brand: -1.5, why: "" }));
    if (/^[A-Z]{1,5}$/.test(u) && !elist.some((i) => i.t === u)) elist.push({ t: u, move: 0, rev: null, brand: null, why: "Not in this market's mapping, so the impact is unknown.", real });
  }
  elist = q ? [...elist].sort((a, b) => Number(heldOf(q, b.t) > 0) - Number(heldOf(q, a.t) > 0) || Math.abs(b.move) - Math.abs(a.move)) : [];
  const toPick = (i: Impact): EquityPick => {
    const h = holdingOf(i.t), d = EQ[i.t];
    return real
      ? { ...i, name: h?.name ?? d?.name ?? i.t, px: h?.spot ?? null, held: h?.shares ?? 0 }
      : { ...i, name: d?.name ?? i.t, px: d?.px ?? 100, held: d?.held ?? 0 };
  };

  // ---- step 3 rows
  // Real markets: only the hedge the engine actually runs, priced from a real quote or not at all.
  // Sample markets: the prototype's menu (sample prices from the demo equity table), labelled as such.
  const instruments = !e ? [] : real ? REAL_INSTRUMENTS(e.px) : INSTRUMENTS(e.px ?? EQ[e.t]?.px ?? 100, settings.account);
  const chosen = instruments.find((i) => i.id === inst) ?? null;
  const ilist = q && e && !inst && ql && showHedge ? instruments.filter((i) => (i.name + " " + i.kind + " " + i.phrase).toLowerCase().includes(ql)) : instruments;

  // ---- actions
  const pickQuestion = (x: Question) => s.setQuestion(x);
  const pickEquity = (i: Impact) => {
    const pick = toPick(i);
    s.setEquity(pick);
    if (q) s.runFit(q, pick);
    if (pick.px == null || real) {
      getEquity(pick.t).then((card) => s.patchEquity(pick.t, { name: card.name ?? pick.name, px: pick.px ?? card.implied_move?.spot ?? null }), () => {});
    }
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
  const ai1 = `What are you worried about? I’m watching markets on Polymarket and Kalshi — pick one below, or describe it.`;
  const ai2 = !q ? "" : `That market is at ${q.yes}¢ YES on ${q.venues.join(" and ")}, with ${q.vol} traded in the last 24 hours. ` + (top && top.move
    ? `It moves ${top.t} most — ${fmtPct(top.move)} if YES resolves${heldQ ? ", and you hold " + heldQ : ""}. Which position should I protect?`
    : real && map.loading ? "Mapping which stocks it moves…" : "I have no precomputed mapping for it yet — type any ticker and I’ll treat its impact as unknown.");
  const ai3 = !e ? "" : (e.held
    ? (real ? `You hold ${e.held.toLocaleString("en-US")} shares of ${e.t}. ` : `You hold ${e.held.toLocaleString("en-US")} shares of ${e.t} across three lots, two of them long-term. `)
    : `You don’t hold ${e.t} yet, so I’ll size the hedge to a 500-share notional. `)
    + (e.move ? `${real ? "The mapping" : "Delta-Bridge"} expects ${fmtPct(e.move)} on YES${e.why ? ": " + e.why : "."} How should I hedge it?` : `I don’t have an impact estimate for ${e.t} on this market, so the engine can’t size from it yet. How should I hedge it?`);
  const ai4 = !chosen ? "" : real
    ? `${chosen.fit} Next I’ll check where orders go, then fit an algo family to this event on its price history. You approve before anything trades.`
    : `${chosen.fit} Next I’ll connect your brokerage, then compose the chain from the algo library and tune it to your fees and ${settings.rate} tax rate.`;
  const thinkingText = !q ? "Reading the order books…" : !e ? `Mapping exposure across ${real ? (map.data?.items.length ?? "the") : 23} equities…` : !inst ? `Pricing hedges for your ${settings.account} account…` : "Checking fees and lot ages…";
  const busy = thinking || (step === 2 && real && map.loading);

  const hdr = (n: number, filled: boolean, active: boolean) => ({ color: active ? "#2B57D6" : filled ? "#0F1626" : "#8A92A8", fg: filled ? "#0F1626" : "#8A92A8" });
  const slots = [
    { k: "01 · EVENT", v: q ? q.ev : "Choosing…", c: hdr(1, !!q, step === 1), go: toStep1 },
    { k: "02 · EQUITY", v: e ? `${e.t} · ${e.name}` : step === 2 ? "Choosing…" : "—", c: hdr(2, !!e, step === 2), go: toStep2 },
    { k: "03 · HEDGE", v: chosen ? chosen.short : step === 3 ? "Choosing…" : "—", c: hdr(3, !!inst, step === 3 && !inst), go: toStep3 },
  ];
  const placeholder = step === 1 ? "Describe an event — e.g. Fed cuts in December" : step === 2 ? "Or type any ticker" : !inst ? "Or describe the hedge you want" : "Anything to adjust before I connect?";
  const fit = s.fit && q && e && s.fit.key === `${q.id}|${e.t}` ? s.fit : null;

  return (
    <main className="pb-page" style={{ maxWidth: 780, paddingTop: 28, paddingBottom: 40 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 24, paddingBottom: 14, borderBottom: "1px solid rgba(15,22,38,.16)" }}>
        {slots.map((x) => (
          <div key={x.k} onClick={x.go} style={{ cursor: "pointer", minWidth: 0 }}>
            <div className="pb-mono" style={{ fontSize: 10.5, letterSpacing: ".1em", color: x.c.color }}>{x.k}</div>
            <div className="pb-ellipsis" style={{ fontSize: 13, marginTop: 6, color: x.c.fg }}>{x.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 24, marginTop: 32 }}>
        <Ai orb="breathing" text={ai1}>
          {step === 1 && !busy && (
            <div className="pb-glass" style={optsBox}>
              {ql && search.loading && <div className="pb-mono" style={{ padding: "10px 14px 4px", fontSize: 11, color: "#5A627A" }}>Searching Polymarket and Kalshi…</div>}
              {ql && search.error && <div style={{ padding: "8px 14px 4px", fontSize: 12, color: "#5A627A" }}>Live search unavailable ({search.error}). <DemoTag what="showing samples" /></div>}
              {search.data?.stale && ql && <div style={{ padding: "8px 14px 4px" }}><Tag tone="sim" title={search.data.note ?? "Live source failed; cached result"}>cached results</Tag></div>}
              {shown.map((x) => {
                const held = x.real ? x.touches.find((t) => holdingOf(t)) : x.touches.find((t) => EQ[t]?.held);
                return (
                  <button key={x.id} type="button" className="pb-row" style={rowStyle} onClick={() => pickQuestion(x)}>
                    <div style={{ minWidth: 0 }}>
                      <div className="pb-pretty" style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: "-.01em", lineHeight: 1.35 }}>{x.q}</div>
                      <div style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>
                        {x.venues.join(" + ")}{x.touches.length ? " · moves " + x.touches.slice(0, 3).join(", ") : ""}{held ? " · you hold " + held : ""}{" "}
                        {x.real ? <Tag tone="live" title="From GET /markets/search or your portfolio's markets">live market</Tag> : <DemoTag what="sample" />}
                        {x.real && isDemoMarket(x) && <>{" "}<Tag tone="replay" title="The demo market: make dev replays this market's own recorded Polymarket history (time-compressed) on the bridge">demo market</Tag></>}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flex: "none" }}>
                      <div className="pb-tab" style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-.03em" }}>{x.real && x.real.yes_price == null ? "—" : x.yes + "¢"}</div>
                      <div style={{ fontSize: 11, color: "#5A627A", marginTop: 2, whiteSpace: "nowrap" }}>YES · {x.vol} vol</div>
                    </div>
                  </button>
                );
              })}
              {more > 0 && <div className="pb-mono" style={{ padding: "10px 14px 8px", fontSize: 11, color: "#5A627A", letterSpacing: ".04em" }}>{more} more markets — type to search</div>}
            </div>
          )}
        </Ai>

        {q && (
          <>
            <User text={`If ${q.ev}.`} onClick={toStep1} />
            {!(busy && !e) && (
              <Ai orb="working" text={ai2}>
                {real && map.data && map.data.items.length > 0 && (
                  <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                    <Tag tone="ai" title={map.data.label}>AI estimate</Tag>
                    {map.data.match_type === "fuzzy" && <span style={{ fontSize: 12, color: "#5A627A" }}>closest mapped question: “{map.data.matched_question}”</span>}
                  </div>
                )}
                {real && map.error && <div style={{ marginTop: 8, fontSize: 12, color: "#5A627A" }}>Mapping unavailable: {map.error}</div>}
                {!real && <div style={{ marginTop: 8 }}><DemoTag what="sample impact model" /></div>}
                {step === 2 && !busy && elist.length > 0 && (
                  <div className="pb-glass" style={optsBox}>
                    {elist.map((i) => {
                      const held = heldOf(q, i.t), name = EQ[i.t]?.name ?? holdingOf(i.t)?.name ?? "";
                      return (
                        <button key={i.t} type="button" className="pb-row" style={rowStyle} onClick={() => pickEquity(i)}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                              <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.02em" }}>{i.t}</span>
                              <span style={{ fontSize: 13, color: "#5A627A" }}>{name}</span>
                              {held > 0 && <span style={{ fontSize: 12, fontWeight: 500, color: "#15804F" }}>{held.toLocaleString("en-US")} sh held</span>}
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
            <User text={`Protect ${e.t}.`} onClick={toStep2} />
            {!(busy && !inst) && (
              <Ai orb="composing" text={ai3}>
                {step === 3 && !inst && !busy && opp && !chosenMode && pickKey && (
                  <div className="pb-glass" style={optsBox}>
                    <button type="button" className="pb-row" style={rowStyle} onClick={() => setMode({ key: pickKey, m: "hedge" })}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 14.5, fontWeight: 500 }}>Hedge</div>
                        <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>Protect the {e.t} position: the engine shorts shares as the market moves against it.</div>
                      </div>
                      <div style={{ fontSize: 11, color: "#5A627A", whiteSpace: "nowrap" }}>equity</div>
                    </button>
                    <button type="button" className="pb-row" style={rowStyle} onClick={() => setMode({ key: pickKey, m: "opportunity" })}>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 14.5, fontWeight: 500 }}>Opportunity</span>
                          <Tag tone="ai" title={`Replay score from POST /pipeline/fit (division opportunity): net P&L per unit risk on this market's history, scored only when the preset traded. ${OPP_REPLAY_NOTE} A replay estimate, not a forecast.`}>AI fit · replay score {opp.score.toFixed(3)} (estimate)</Tag>
                        </div>
                        <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3 }}>{prettyId(opp.family)} (preset #{opp.preset_index}): {oppIdea} Replay option prices are estimates from bar closes; option fills are simulated.</div>
                      </div>
                      <div style={{ fontSize: 11, color: "#5A627A", whiteSpace: "nowrap" }}>options</div>
                    </button>
                  </div>
                )}
                {step === 3 && !inst && !busy && opp && chosenMode === "opportunity" && q && (
                  <OpportunityCard q={q} ticker={e.t} fit={oppData!} idea={oppIdea} onBack={() => setMode(null)}
                    onStart={async () => { const id = await s.openOpportunity(q, e); router.push(`/bridge/${id.replace(/^live:/, "")}`); }} />
                )}
                {step === 3 && !inst && !busy && showHedge && (
                  <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 12, color: "#5A627A" }}>
                    {real ? "Option and contract hedges are demo-only for now; pick a sample market to see them on the simulator." : <DemoTag what="sample hedge menu" title="Strikes, costs and tax notes are the prototype's illustrative numbers, not quotes." />}
                  </div>
                )}
                {step === 3 && !inst && !busy && showHedge && (
                  <div className="pb-glass" style={optsBox}>
                    {ilist.map((i) => (
                      <button key={i.id} type="button" className="pb-row" style={rowStyle} onClick={() => s.setInst(i.id)}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                            <span style={{ fontSize: 14.5, fontWeight: 500, letterSpacing: "-.01em" }}>{i.name}</span>
                            {i.rec && <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600, background: "rgba(59,108,246,.12)", color: "#2B57D6" }}>AI pick</span>}
                          </div>
                          <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 3, lineHeight: 1.4 }}>{i.fit} · {i.tax}</div>
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
            <User text={`With ${chosen.phrase}.`} onClick={toStep3} />
            {!busy && (
              <Ai orb="breathing" text={ai4}>
                <FitCard fit={fit} />
                <div style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button type="button" className="pb-btn pb-btn-primary" style={{ height: 48, padding: "0 22px" }} onClick={toConnect}>Connect brokerage <span className="pb-arrow">→</span></button>
                  <button type="button" className="pb-btn pb-btn-secondary" style={{ height: 48, padding: "0 18px", fontSize: 14, boxShadow: "none" }} onClick={toStep1}>Start over</button>
                </div>
              </Ai>
            )}
          </>
        )}

        {busy && (
          <div style={{ display: "grid", gridTemplateColumns: "36px minmax(0,1fr)", gap: 16, alignItems: "center", animation: "pb-in .3s ease-out" }}>
            <Avatar state="working" />
            <div className="pb-serif" style={{ fontStyle: "italic", fontSize: 19, color: "#5A627A" }}>{thinkingText}</div>
          </div>
        )}
      </div>

      <div style={{ position: "sticky", bottom: 24, marginTop: 36, display: "flex", alignItems: "center", gap: 12, height: 60, padding: "0 8px 0 22px", borderRadius: 999, background: "rgba(255,255,255,.74)", backdropFilter: "blur(28px) saturate(1.6)", WebkitBackdropFilter: "blur(28px) saturate(1.6)", border: "1px solid rgba(255,255,255,.95)", boxShadow: "inset 0 1px 0 #fff,0 20px 50px rgba(40,60,120,.16)", zIndex: 3 }}>
        <input aria-label="Composer" value={query} onChange={(ev) => s.setQuery(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter") submit(); }} placeholder={placeholder} style={{ flex: 1, minWidth: 0, border: 0, outline: 0, background: "transparent", fontSize: 16, color: "#0F1626" }} />
        <span className="pb-mono pb-hide-sm" style={{ fontSize: 11, color: "#5A627A", whiteSpace: "nowrap" }}>{inst ? "↵ continue" : "↵ picks the top match"}</span>
        <button type="button" aria-label="Send" onClick={submit} style={{ width: 44, height: 44, borderRadius: "50%", background: "#0F1626", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 18, flex: "none", border: 0 }}>↑</button>
      </div>
    </main>
  );
}

const pct = (x: number | null | undefined) => (x == null || !Number.isFinite(x) ? "n/a" : `${(x * 100).toFixed(1)}%`);

/** The Opportunity step: the options fit, the PM-vs-options gap (GET /options/implied) and the risk caps the
 *  proposal is approved with. Starting it is an explicit click: propose → approve → options bridge. */
function OpportunityCard({ q, ticker, fit, idea, onStart, onBack }: { q: NonNullable<ReturnType<typeof useStore>["question"]>; ticker: string; fit: FitOut; idea: string; onStart: () => Promise<void>; onBack: () => void }) {
  const m = q.real!;
  const implied = useAsync(`oi:${m.source}:${m.id}`, () => getOptionsImplied({ market_source: m.source, market_id: m.id }));
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const d = implied.data;
  const box = { marginTop: 14, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)" };
  const start = () => {
    setState({ busy: true, error: null });
    onStart().catch((e) => setState({ busy: false, error: e instanceof Error ? e.message : String(e) }));
  };
  return (
    <div style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-label">OPPORTUNITY · {prettyId(fit.family ?? "")} · PRESET #{fit.preset_index}</span>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <Tag tone="ai" title={`Net P&L per unit risk on this market's history. ${OPP_REPLAY_NOTE}`}>replay score {fit.score?.toFixed(3)} (estimate)</Tag>
          <Tag tone="sim" title="Option orders are filled by the simulator at the Massive quote mid ± half the quoted spread; Webull paper does not take options here.">simulated fills</Tag>
        </span>
      </div>
      <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 8 }}>{idea}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 12, marginTop: 12 }}>
        <div><div className="pb-mono" style={{ fontSize: 10.5, color: "#5A627A" }}>PM YES (MEASURED)</div><div style={{ fontSize: 18, fontWeight: 600 }}>{pct(d?.pm_yes_price ?? m.yes_price)}</div></div>
        <div><div className="pb-mono" style={{ fontSize: 10.5, color: "#5A627A" }}>OPTIONS-IMPLIED (ESTIMATE)</div><div style={{ fontSize: 18, fontWeight: 600 }}>{implied.loading ? "…" : d?.available ? pct(d.estimate?.prob) : "n/a"}</div></div>
        <div><div className="pb-mono" style={{ fontSize: 10.5, color: "#5A627A" }}>GAP (PM − OPTIONS)</div><div style={{ fontSize: 18, fontWeight: 600, color: d?.pm_minus_option == null ? "#8A92A8" : d.pm_minus_option > 0 ? "#22A06B" : "#E0485A" }}>{d?.pm_minus_option == null ? "n/a" : `${(d.pm_minus_option * 100).toFixed(1)} pts`}</div></div>
      </div>
      <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 8, lineHeight: 1.45 }}>
        {d?.available && d.estimate
          ? `${d.underlying_used} ${d.estimate.method?.replaceAll("_", " ")} ${d.estimate.k_lo}/${d.estimate.k_hi}, expiry ${d.estimate.expiry}. ${d.label}.`
          : implied.error ? `Options estimate unavailable (${implied.error}).` : d && !d.available ? `No options estimate: ${d.reason ?? "unavailable"}.` : ""}
      </div>
      {fit.rationale && <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 6 }}>{fit.rationale}</div>}
      <div className="pb-pretty" style={{ fontSize: 12, color: "#5A627A", marginTop: 6, lineHeight: 1.45 }}>{OPP_REPLAY_NOTE}</div>
      <div style={{ fontSize: 12, color: "#5A627A", marginTop: 8 }}>Risk caps on the proposal you approve: at most {DEFAULT_OPP_CAPS.max_contracts} structures open, ${DEFAULT_OPP_CAPS.max_notional.toLocaleString("en-US")} premium / max loss at risk. Ticker context: {ticker}.</div>
      {state.error && <div role="alert" style={{ fontSize: 12.5, color: "#C8323F", marginTop: 8 }}>Could not start the options bridge: {state.error}</div>}
      <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button type="button" className="pb-btn pb-btn-primary" style={{ height: 44, padding: "0 20px" }} disabled={state.busy} onClick={start}>{state.busy ? "Starting…" : "Approve & start options bridge"} <span className="pb-arrow">→</span></button>
        <button type="button" className="pb-btn pb-btn-secondary" style={{ height: 44, padding: "0 16px", fontSize: 14, boxShadow: "none" }} onClick={onBack}>Back</button>
      </div>
    </div>
  );
}

/** Spec §7: the AI fit card (event class, chosen algo, replay score, rationale, alternatives). */
function FitCard({ fit }: { fit: ReturnType<typeof useStore>["fit"] }) {
  if (!fit) return null;
  const box = { marginTop: 16, padding: "14px 16px", borderRadius: 18, background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.9)", fontFamily: "var(--sans)" };
  if (fit.status === "loading") return <div style={{ ...box, display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "#3C4458" }}><Orb state="working" size={20} />Fitting an algo to this event on its price history…</div>;
  if (fit.noDirection) return <div style={{ ...box, fontSize: 12.5, color: "#5A627A", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><Tag tone="neutral" title={fit.error ?? undefined}>direction unknown</Tag>No hedge fit: {fit.error}.</div>;
  if (fit.status === "error" || !fit.data) return <div style={{ ...box, fontSize: 12.5, color: "#5A627A" }}>AI fit unavailable ({fit.error}). The pipeline will run the prototype’s scripted steps. <DemoTag /></div>;
  const f = fit.data;
  const sv = fitScoreView(f);
  return (
    <div style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pb-label">AI FIT · {prettyId(String(f.event_class)).toUpperCase()}</span>
        <span style={{ display: "inline-flex", gap: 6 }}>
          <Tag tone="ai" title={f.llm === "gemini" ? "Classified and explained by Gemini" : "Keyword rules (no LLM key)"}>{f.llm === "gemini" ? "AI estimate" : "rules"}</Tag>
          <Tag tone={f.ticks_source === "live_history" || f.ticks_source === "replay" ? "replay" : "neutral"} title={f.ticks_source === "none" ? undefined : IN_SAMPLE_NOTE}>{f.ticks_source === "live_history" ? `${f.n_ticks} ticks history` : f.ticks_source === "replay" ? "replay ticks" : "no history"}</Tag>
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-.015em" }}>{f.family ? prettyId(f.family) : "No family fits"}</span>
        {f.preset_index != null && <span className="pb-mono" style={{ fontSize: 12, color: "#5A627A" }}>preset #{f.preset_index}</span>}
      </div>
      {/* The headline is what the PM signal adds over a static hedge of the same size: green only when it adds something. */}
      <div className="pb-mono" style={{ fontSize: 12, marginTop: 4, color: sv.tone === "positive" ? "#15804F" : "#5A627A" }} title={f.score == null ? undefined : sv.title}>{sv.headline}</div>
      {sv.secondary && <div className="pb-mono" style={{ fontSize: 11.5, marginTop: 2, color: "#5A627A" }} title={sv.title}>{sv.secondary}</div>}
      {f.rationale && <div className="pb-pretty" style={{ fontSize: 13, color: "#3C4458", lineHeight: 1.5, marginTop: 6 }}>{f.rationale}</div>}
      {f.alternatives?.length > 0 && <div style={{ fontSize: 12, color: "#5A627A", marginTop: 6 }}>Alternatives: {f.alternatives.slice(0, 3).map((a) => prettyId(a.family)).join(" · ")}</div>}
    </div>
  );
}
