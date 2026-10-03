"use client";

// One client-side store for the whole flow (the prototype's single component state, split per screen by
// route). It lives in the root layout, so it survives client navigation between screens.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { getAccount, getLibrary, getPortfolio, getSession, postFit, type AccountOut, type FitOut, type PortfolioOut } from "./api";
import type { SessionView } from "./closed";
import { EQ, QUESTIONS, demoImpacts, type EquityPick, type Question } from "./demo";
import { parseLibrary, type Library } from "./library";
import { initSim, stepSim, type Sim } from "./sim";
import { fitDirection, opportunityFit, reusableBridge, runnableFit, startOpportunityBridge, startRealBridge, type AppliedFit, type Settings } from "./realBridge.ts";

export { algoRunLabel, bridgeFeeGateOff, feeGateOff, gapPerShare, runnableFit } from "./realBridge.ts";

export type { AppliedFit, Settings };
export type BridgeEntry =
  | { id: string; kind: "demo"; q: Question; eq: EquityPick; inst: string; sim: Sim }
  | {
      id: string; kind: "live"; bridgeId: string; q: Question | null; eq: EquityPick | null; inst: string;
      /** The AI fit this bridge was started with (sent with the proposal and POST /bridges, so hedgecore.Algo runs
       *  that family and preset). null: no runnable fit, the engine runs its default delta-bridge spec. */
      fit: AppliedFit | null;
      /** A fit that exists for this pick but cannot run on a bridge (e.g. an opportunity-division family). */
      unapplied?: { family: string; preset_index: number | null; why: string } | null;
      /** $/share per unit of probability sent to the engine; 0 means its fee gate is off. null: unknown (re-attached). */
      gap: number | null;
      /** "opportunity": an options bridge (Opportunity-division family, simulated option fills). Default hedge. */
      mode?: "hedge" | "opportunity";
      /** True when the proposal opted in to hedge A (closed_pm_hedge): reuse only matches the same choice. */
      pmHedge?: boolean;
    };

export interface Remote<T> { status: "loading" | "ok" | "error"; data: T | null; error: string | null }
export interface FitState extends Remote<FitOut> {
  key: string;
  /** Set when no hedge fit was requested because the adverse outcome is unknown (a ticker outside the market's
   *  mapping): the card says so instead of showing a score tuned against a guessed side. */
  noDirection?: boolean;
}

const LOADING = { status: "loading", data: null, error: null } as const;
const DEFAULT_SETTINGS: Settings = {
  broker: "webull", conns: ["webull"], account: "Taxable", rate: "32%", taxState: "CA", maxHedge: "100%",
  markets: { Polymarket: true, Kalshi: true }, guards: { edge: true, wash: true, auto: false },
};
export const TICK_MS = 900;
/** GET /session refresh (the nav pill, Build's Weekend mode and Portfolio's weekend exposure read it). */
export const SESSION_MS = 60_000;

/** The prototype's default pick (ca-str / ABNB) when a screen is opened without a wizard selection. */
export function defaultPick(): { q: Question; eq: EquityPick } {
  const q = QUESTIONS[0], imp = demoImpacts(q)[0], e = EQ[imp.t];
  return { q, eq: { ...imp, name: e.name, px: e.px, held: e.held } };
}
export function demoPick(qId: string, t: string): { q: Question; eq: EquityPick } {
  const q = QUESTIONS.find((x) => x.id === qId) ?? QUESTIONS[0];
  const imp = demoImpacts(q).find((i) => i.t === t) ?? { t, move: -1.2, rev: -0.6, brand: -1.5, why: "" };
  const e = EQ[t] ?? { name: t, px: 100, held: 0 };
  return { q, eq: { ...imp, name: e.name, px: e.px, held: e.held } };
}

function makeDemo(q: Question, eq: EquityPick, inst: string): BridgeEntry {
  return {
    id: `demo:${q.id}:${eq.t}`, kind: "demo", q, eq, inst,
    sim: initSim({ ticker: eq.t, px: eq.px ?? EQ[eq.t]?.px ?? 100, held: eq.held, yesCents: q.yes, volN: q.volN, movePct: eq.move }),
  };
}

interface Store {
  question: Question | null; equity: EquityPick | null; inst: string | null; query: string; thinking: boolean;
  setQuestion: (q: Question | null) => void;
  setEquity: (e: EquityPick | null) => void;
  patchEquity: (t: string, patch: Partial<EquityPick>) => void;
  setInst: (id: string | null) => void;
  setQuery: (q: string) => void;
  settings: Settings;
  updateSettings: (p: Partial<Settings>) => void;
  bridges: BridgeEntry[]; activeId: string | null; bridgeNote: string | null;
  setActive: (id: string) => void;
  addDemoBridge: (q: Question, eq: EquityPick, inst: string) => string;
  seedDemo: () => void;
  /** Explicit user action only (a click, or the pipeline when settings.guards.auto is on): approves a proposal. */
  openBridge: (q: Question, eq: EquityPick, inst: string) => Promise<string>;
  fit: FitState | null;
  runFit: (q: Question, eq: EquityPick) => void;
  /** The Opportunity-division fit for the same pick (POST /pipeline/fit with division "opportunity"). */
  oppFit: FitState | null;
  /** Explicit user action only: proposes, approves and starts an options bridge for the opportunity fit. */
  openOpportunity: (q: Question, eq: EquityPick) => Promise<string>;
  library: Remote<Library>;
  account: Remote<AccountOut>;
  portfolio: Remote<PortfolioOut>;
  /** The NYSE session now (GET /session, wall clock). A replay bridge's own session comes from its ticks instead. */
  session: Remote<SessionView>;
  /** Hedge A opt-in for the next hedge proposal (closed-market mode). Off by default; reset on every new pick. */
  closedPmHedge: boolean;
  setClosedPmHedge: (on: boolean) => void;
}

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside <StoreProvider>");
  return s;
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function StoreProvider({ children }: { children: ReactNode }) {
  const [question, setQuestionS] = useState<Question | null>(null);
  const [equity, setEquityS] = useState<EquityPick | null>(null);
  const [inst, setInstS] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [thinking, setThinking] = useState(false);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [bridges, setBridges] = useState<BridgeEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [bridgeNote, setBridgeNote] = useState<string | null>(null);
  const [fit, setFit] = useState<FitState | null>(null);
  const [oppFit, setOppFit] = useState<FitState | null>(null);
  const oppKey = useRef<string | null>(null);
  const [library, setLibrary] = useState<Remote<Library>>(LOADING);
  const [account, setAccount] = useState<Remote<AccountOut>>(LOADING);
  const [portfolio, setPortfolio] = useState<Remote<PortfolioOut>>(LOADING);
  const [session, setSession] = useState<Remote<SessionView>>(LOADING);
  const [closedPmHedge, setClosedPmHedge] = useState(false);
  const thinkTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const fitKey = useRef<string | null>(null);
  const opening = useRef<Map<string, Promise<string>>>(new Map());
  const pathname = usePathname();

  useEffect(() => {
    let alive = true;
    getLibrary().then(
      (raw) => { if (!alive) return; const lib = parseLibrary(raw); setLibrary(lib ? { status: "ok", data: lib, error: null } : { status: "error", data: null, error: "empty catalog" }); },
      (e) => alive && setLibrary({ status: "error", data: null, error: errMsg(e) }),
    );
    return () => { alive = false; clearTimeout(thinkTimer.current); };
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => getSession().then(
      (d) => alive && setSession({ status: "ok", data: d, error: null }),
      (e) => alive && setSession((s) => (s.data ? s : { status: "error", data: null, error: errMsg(e) })),
    );
    load();
    const t = setInterval(load, SESSION_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // GET /portfolio and GET /account change as bridges open (hedge status, cash), so they are re-read on every
  // Portfolio visit and right after a bridge starts, not only at load. A failed refresh keeps the last good data.
  const refreshAccount = useCallback(() => {
    getAccount().then((a) => setAccount({ status: "ok", data: a, error: null }), (e) => setAccount((s) => (s.data ? s : { status: "error", data: null, error: errMsg(e) })));
    getPortfolio().then((p) => setPortfolio({ status: "ok", data: p, error: null }), (e) => setPortfolio((s) => (s.data ? s : { status: "error", data: null, error: errMsg(e) })));
  }, []);
  const onPortfolio = pathname.startsWith("/portfolio");
  const firstLoad = useRef(true);
  useEffect(() => {
    if (firstLoad.current || onPortfolio) refreshAccount();
    firstLoad.current = false;
  }, [onPortfolio, refreshAccount]);

  // One interval steps every demo bridge while the Bridge or Portfolio screen is open (prototype tickLive).
  const hasDemo = bridges.some((b) => b.kind === "demo");
  const liveScreen = pathname.startsWith("/bridge") || pathname.startsWith("/portfolio");
  useEffect(() => {
    if (!hasDemo || !liveScreen) return;
    const t = setInterval(() => setBridges((bs) => bs.map((b) => (b.kind === "demo" ? { ...b, sim: stepSim(b.sim) } : b))), TICK_MS);
    return () => clearInterval(t);
  }, [hasDemo, liveScreen]);

  const think = useCallback(() => {
    clearTimeout(thinkTimer.current);
    setThinking(true);
    thinkTimer.current = setTimeout(() => setThinking(false), 900);
  }, []);

  const setQuestion = useCallback((q: Question | null) => { setQuestionS(q); setEquityS(null); setInstS(null); setQuery(""); setClosedPmHedge(false); if (q) think(); else setThinking(false); }, [think]);
  const setEquity = useCallback((e: EquityPick | null) => { setEquityS(e); setInstS(null); setQuery(""); setClosedPmHedge(false); if (e) think(); else setThinking(false); }, [think]);
  const patchEquity = useCallback((t: string, patch: Partial<EquityPick>) => setEquityS((e) => (e && e.t === t ? { ...e, ...patch } : e)), []);
  const setInst = useCallback((id: string | null) => { setInstS(id); setQuery(""); if (id) think(); else setThinking(false); }, [think]);
  const updateSettings = useCallback((p: Partial<Settings>) => setSettings((s) => ({ ...s, ...p })), []);

  const addDemoBridge = useCallback((q: Question, eq: EquityPick, instId: string) => {
    const entry = makeDemo(q, eq, instId);
    setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
    setActiveId(entry.id);
    return entry.id;
  }, []);

  const seedDemo = useCallback(() => {
    const seeds: [string, string][] = [["ca-str", "ABNB"], ["chips", "NVDA"], ["fed-dec", "JPM"]];
    const fresh = seeds.map(([qId, t]) => { const { q, eq } = demoPick(qId, t); return makeDemo(q, eq, "shares"); });
    setBridges((bs) => [...bs, ...fresh.filter((f) => !bs.some((b) => b.id === f.id))]);
    setActiveId(fresh[0].id);
    const first = demoPick("ca-str", "ABNB");
    setQuestionS(first.q); setEquityS(first.eq); setInstS("shares");
    setSettings((s) => ({ ...s, broker: s.broker ?? "webull", conns: s.conns.includes("webull") ? s.conns : [...s.conns, "webull"] }));
    setBridgeNote(null);
  }, []);

  const openBridge = useCallback((q: Question, eq: EquityPick, instId: string): Promise<string> => {
    const key = `${q.id}|${eq.t}`;
    const openKey = `${key}|${closedPmHedge ? "pmHedge" : "plain"}`;
    // Reuse a live bridge already open for this market and ticker, started under the same hedge A choice.
    const existing = reusableBridge(bridges, q.id, eq.t, closedPmHedge);
    if (existing) { setActiveId(existing.id); setBridgeNote(null); return Promise.resolve(existing.id); }
    const inflight = opening.current.get(openKey);
    if (inflight) return inflight;
    const run = (async () => {
      try {
        if (q.real && instId !== "shares") throw new Error("the engine runs only the dynamic short-shares hedge; option and contract hedges are demo-only");
        const mine = fit && fit.key === key && fit.status === "ok" ? fit.data : null;
        const want = runnableFit(mine);
        const { bridgeId, gap, applied } = await startRealBridge(q, eq, settings.maxHedge, undefined, want, { closedPmHedge });
        const unapplied = mine?.family && !applied
          ? { family: mine.family, preset_index: mine.preset_index ?? null, why: mine.division !== "hedge" ? `${mine.division} families do not run on a hedge bridge` : "no preset" }
          : null;
        const entry: BridgeEntry = { id: `live:${bridgeId}`, kind: "live", bridgeId, q, eq, inst: instId, fit: applied, unapplied, gap, pmHedge: closedPmHedge };
        setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
        setActiveId(entry.id);
        setBridgeNote(null);
        refreshAccount();
        return entry.id;
      } catch (e) {
        setBridgeNote(`No engine bridge on the backend (${errMsg(e)}). This bridge runs the prototype's simulator.`);
        return addDemoBridge(q, eq, instId);
      } finally {
        opening.current.delete(openKey);
      }
    })();
    opening.current.set(openKey, run);
    return run;
  }, [bridges, settings, fit, closedPmHedge, addDemoBridge, refreshAccount]);

  const runFit = useCallback((q: Question, eq: EquityPick) => {
    const key = `${q.id}|${eq.t}`;
    if (fitKey.current === key) return;
    fitKey.current = key;
    setFit({ key, ...LOADING });
    if (q.real && oppKey.current !== key) {  // the Opportunity division, fitted alongside (offered only when scored)
      oppKey.current = key;
      setOppFit({ key, ...LOADING });
      postFit({ market: { source: q.real.source, id: q.real.id }, question: q.q, ticker: eq.t, shares_held: 0,
        division: "opportunity", end_date: q.real.end_date ?? undefined }).then(
        (data) => { if (oppKey.current === key) setOppFit({ key, status: "ok", data, error: null }); },
        (e) => { if (oppKey.current !== key) return; oppKey.current = null; setOppFit({ key, status: "error", data: null, error: errMsg(e) }); },
      );
    }
    // A hedge fit is tuned on the series oriented to the outcome that hurts the stock. With no mapping for this
    // ticker that outcome is unknown, so no hedge fit is requested (the opportunity fit above needs no direction).
    const direction = fitDirection(q, eq);
    if (!direction) {
      setFit({ key, status: "error", data: null, noDirection: true,
        error: `${eq.t} is not in this market's mapping, so the outcome that hurts it is unknown; no hedge was fitted` });
      return;
    }
    postFit({
      market: q.real ? { source: q.real.source, id: q.real.id } : undefined,
      question: q.q, ticker: eq.t, direction, shares_held: eq.held || 500,
    }).then(
      (data) => { if (fitKey.current === key) setFit({ key, status: "ok", data, error: null }); },
      (e) => {
        if (fitKey.current !== key) return;
        fitKey.current = null; // let a later visit retry this pick
        setFit({ key, status: "error", data: null, error: errMsg(e) });
      },
    );
  }, []);

  const openOpportunity = useCallback(async (q: Question, eq: EquityPick): Promise<string> => {
    const key = `${q.id}|${eq.t}`;
    const existing = bridges.find((b) => b.kind === "live" && b.mode === "opportunity" && b.q?.id === q.id && b.eq?.t === eq.t);
    if (existing) { setActiveId(existing.id); return existing.id; }
    const want = opportunityFit(oppFit && oppFit.key === key && oppFit.status === "ok" ? oppFit.data : null);
    if (!want) throw new Error("no scored opportunity fit for this pick");
    const { bridgeId, applied } = await startOpportunityBridge(q, eq.t, want);
    const entry: BridgeEntry = { id: `live:${bridgeId}`, kind: "live", bridgeId, q, eq, inst: "options", fit: applied, gap: null, mode: "opportunity" };
    setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
    setActiveId(entry.id);
    setBridgeNote(null);
    refreshAccount();
    return entry.id;
  }, [bridges, oppFit, refreshAccount]);

  const value = useMemo<Store>(() => ({
    question, equity, inst, query, thinking, setQuestion, setEquity, patchEquity, setInst, setQuery,
    settings, updateSettings, bridges, activeId, bridgeNote, setActive: setActiveId, addDemoBridge, seedDemo, openBridge,
    fit, runFit, oppFit, openOpportunity, library, account, portfolio, session, closedPmHedge, setClosedPmHedge,
  }), [question, equity, inst, query, thinking, setQuestion, setEquity, patchEquity, setInst, settings, updateSettings, bridges, activeId, bridgeNote, addDemoBridge, seedDemo, openBridge, fit, runFit, oppFit, openOpportunity, library, account, portfolio, session, closedPmHedge]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** "sim" | "webull-paper" from GET /account, as a label. */
export function brokerLabel(a: Remote<AccountOut>): { name: string; tone: "sim" | "paper" | "demo" } {
  if (a.status !== "ok" || !a.data) return { name: "Demo account", tone: "demo" };
  const b = (a.data.broker ?? "sim").toLowerCase();
  return b.includes("webull") ? { name: "Webull paper", tone: "paper" } : { name: "Simulated account", tone: "sim" };
}
