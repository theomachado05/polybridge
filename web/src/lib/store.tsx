"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { getAccount, getEquity, getHealth, getLibrary, getPortfolio, getSession, mapEvent, postFit, searchMarkets, type AccountOut, type Direction, type FitOut, type Market, type PortfolioOut, type Proposal } from "./api";
import { aiStatus, NO_AI, type AiStatus } from "./ai.ts";
import type { SessionView } from "./closed";
import { questionFromMarket, WEEKEND_REPLAY, weekendPick, weekendQuestion, type EquityPick, type Question } from "./markets.ts";
import type { StoreUpdate } from "./voiceDrive.ts";
import { parseLibrary, type Library } from "./library";
import { fitDirection, opportunityFit, reusableBridge, runnableFit, startOpportunityBridge, startRealBridge, type AppliedFit, type Settings } from "./realBridge.ts";

export { algoRunLabel, bridgeFeeGateOff, feeGateOff, gapPerShare, runnableFit } from "./realBridge.ts";

export type { AppliedFit, Settings };
export interface BridgeEntry {
  id: string; kind: "live"; bridgeId: string; q: Question | null; eq: EquityPick | null; inst: string;
  fit: AppliedFit | null;
  unapplied?: { family: string; preset_index: number | null; why: string } | null;
  gap: number | null;
  mode?: "hedge" | "opportunity";
  pmHedge?: boolean;
  override?: boolean;
}

export interface Remote<T> { status: "loading" | "ok" | "error"; data: T | null; error: string | null }
export interface FitState extends Remote<FitOut> {
  key: string;
  noDirection?: boolean;
}

const LOADING = { status: "loading", data: null, error: null } as const;
const DEFAULT_SETTINGS: Settings = {
  broker: "webull", conns: ["webull"], account: "Taxable", rate: "32%", taxState: "CA", maxHedge: "100%",
  markets: { Polymarket: true, Kalshi: true }, guards: { edge: true, wash: true, auto: false },
};
export const SESSION_MS = 60_000;
const WEEKEND_SEARCH_MS = 4000;

export interface Store {
  question: Question | null; equity: EquityPick | null; inst: string | null; query: string; thinking: boolean;
  setQuestion: (q: Question | null) => void;
  setEquity: (e: EquityPick | null) => void;
  patchEquity: (t: string, patch: Partial<EquityPick>) => void;
  setInst: (id: string | null) => void;
  setQuery: (q: string) => void;
  chooseDirection: (direction: Direction) => void;
  openWeekendReplay: () => Promise<void>;
  settings: Settings;
  updateSettings: (p: Partial<Settings>) => void;
  bridges: BridgeEntry[]; activeId: string | null;
  setActive: (id: string) => void;
  openBridge: (q: Question, eq: EquityPick, inst: string, opts?: { ackUnvalidated?: boolean; proposal?: Proposal | null }) => Promise<string>;
  fit: FitState | null;
  runFit: (q: Question, eq: EquityPick) => void;
  retryFit: (q: Question, eq: EquityPick) => void;
  oppFit: FitState | null;
  openOpportunity: (q: Question, eq: EquityPick, opts?: { ackUnvalidated?: boolean }) => Promise<string>;
  library: Remote<Library>;
  reloadLibrary: () => void;
  account: Remote<AccountOut>;
  portfolio: Remote<PortfolioOut>;
  refreshAccount: () => void;
  ai: AiStatus;
  session: Remote<SessionView>;
  closedPmHedge: boolean;
  setClosedPmHedge: (on: boolean) => void;
  actOnUnvalidated: boolean;
  setActOnUnvalidated: (on: boolean) => void;
  voiceProposal: Proposal | null;
  applyVoice: (u: StoreUpdate) => Promise<void>;
}

export const pickKey = (q: Pick<Question, "id"> | null | undefined, eq: Pick<EquityPick, "t"> | null | undefined) => (q && eq ? `${q.id}|${eq.t}` : null);
export const proposalForPick = (p: Proposal | null | undefined, q: Question | null | undefined, eq: EquityPick | null | undefined): p is Proposal =>
  !!p && !!q && !!eq && p.ticker.toUpperCase() === eq.t && !!p.market && `${p.market.source}:${p.market.id}` === q.id;

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside <StoreProvider>");
  return s;
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));
const withTimeout = <T,>(p: Promise<T>, ms: number): Promise<T | null> =>
  Promise.race([p.catch(() => null), new Promise<null>((r) => setTimeout(() => r(null), ms))]);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [question, setQuestionS] = useState<Question | null>(null);
  const [equity, setEquityS] = useState<EquityPick | null>(null);
  const [inst, setInstS] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [thinking, setThinking] = useState(false);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [bridges, setBridges] = useState<BridgeEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [fit, setFit] = useState<FitState | null>(null);
  const [oppFit, setOppFit] = useState<FitState | null>(null);
  const oppKey = useRef<string | null>(null);
  const [library, setLibrary] = useState<Remote<Library>>(LOADING);
  const [account, setAccount] = useState<Remote<AccountOut>>(LOADING);
  const [portfolio, setPortfolio] = useState<Remote<PortfolioOut>>(LOADING);
  const [session, setSession] = useState<Remote<SessionView>>(LOADING);
  const [ai, setAi] = useState<AiStatus>(NO_AI);
  const [closedPmHedge, setClosedPmHedge] = useState(false);
  const [actOnUnvalidated, setActOnUnvalidated] = useState(false);
  const [voiceProposal, setVoiceProposal] = useState<Proposal | null>(null);
  const thinkTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const fitKey = useRef<string | null>(null);
  const opening = useRef<Map<string, Promise<string>>>(new Map());
  const pathname = usePathname();

  const loadLibrary = useCallback(() => getLibrary().then(
    (raw) => { const lib = parseLibrary(raw); setLibrary(lib ? { status: "ok", data: lib, error: null } : { status: "error", data: null, error: "the catalog is empty" }); },
    (e) => setLibrary({ status: "error", data: null, error: errMsg(e) }),
  ), []);
  const reloadLibrary = useCallback(() => { setLibrary(LOADING); void loadLibrary(); }, [loadLibrary]);

  useEffect(() => {
    void loadLibrary();
    getHealth().then((h) => { if (h && typeof h === "object" && "ai" in h) setAi(aiStatus(h)); }, () => {});
    return () => clearTimeout(thinkTimer.current);
  }, [loadLibrary]);

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

  const think = useCallback(() => {
    clearTimeout(thinkTimer.current);
    setThinking(true);
    thinkTimer.current = setTimeout(() => setThinking(false), 900);
  }, []);

  const resetToggles = useCallback(() => { setClosedPmHedge(false); setActOnUnvalidated(false); }, []);
  const setQuestion = useCallback((q: Question | null) => { setQuestionS(q); setEquityS(null); setInstS(null); setQuery(""); resetToggles(); if (q) think(); else setThinking(false); }, [think, resetToggles]);
  const setEquity = useCallback((e: EquityPick | null) => { setEquityS(e); setInstS(null); setQuery(""); resetToggles(); if (e) think(); else setThinking(false); }, [think, resetToggles]);
  const patchEquity = useCallback((t: string, patch: Partial<EquityPick>) => setEquityS((e) => (e && e.t === t ? { ...e, ...patch } : e)), []);
  const setInst = useCallback((id: string | null) => { setInstS(id); setQuery(""); if (id) think(); else setThinking(false); }, [think]);
  const updateSettings = useCallback((p: Partial<Settings>) => setSettings((s) => ({ ...s, ...p })), []);

  const openBridge = useCallback((q: Question, eq: EquityPick, instId: string, opts: { ackUnvalidated?: boolean; proposal?: Proposal | null } = {}): Promise<string> => {
    const key = `${q.id}|${eq.t}`;
    const openKey = `${key}|${closedPmHedge ? "pmHedge" : "plain"}|${actOnUnvalidated ? "override" : ""}`;
    const existing = reusableBridge(bridges, q.id, eq.t, closedPmHedge, actOnUnvalidated);
    if (existing) { setActiveId(existing.id); return Promise.resolve(existing.id); }
    const inflight = opening.current.get(openKey);
    if (inflight) return inflight;
    const run = (async () => {
      try {
        if (instId !== "shares") throw new Error("the engine uses only the dynamic short-shares hedge");
        const mine = fit && fit.key === key && fit.status === "ok" ? fit.data : null;
        const want = runnableFit(mine);
        const { bridgeId, gap, applied } = await startRealBridge(q, eq, settings.maxHedge, undefined, want, { closedPmHedge, actOnUnvalidated, ackUnvalidated: opts.ackUnvalidated, proposal: opts.proposal ?? null });
        const unapplied = mine?.family && !applied
          ? { family: mine.family, preset_index: mine.preset_index ?? null, why: mine.division !== "hedge" ? `${mine.division} families do not operate on a hedge bridge` : "no preset" }
          : null;
        const entry: BridgeEntry = { id: `live:${bridgeId}`, kind: "live", bridgeId, q, eq, inst: instId, fit: applied, unapplied, gap, pmHedge: closedPmHedge, override: actOnUnvalidated };
        setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
        setActiveId(entry.id);
        refreshAccount();
        return entry.id;
      } finally {
        opening.current.delete(openKey);
      }
    })();
    opening.current.set(openKey, run);
    return run;
  }, [bridges, settings, fit, closedPmHedge, actOnUnvalidated, refreshAccount]);

  const runOppFit = useCallback((q: Question, eq: EquityPick) => {
    const key = `${q.id}|${eq.t}`;
    if (oppKey.current === key) return;
    oppKey.current = key;
    setOppFit({ key, ...LOADING });
    postFit({ market: { source: q.real.source, id: q.real.id }, question: q.q, ticker: eq.t, shares_held: 0,
      division: "opportunity", end_date: q.real.end_date ?? undefined }).then(
      (data) => { if (oppKey.current === key) setOppFit({ key, status: "ok", data, error: null }); },
      (e) => { if (oppKey.current !== key) return; oppKey.current = null; setOppFit({ key, status: "error", data: null, error: errMsg(e) }); },
    );
  }, []);

  const runFit = useCallback((q: Question, eq: EquityPick) => {
    const key = `${q.id}|${eq.t}`;
    if (fitKey.current === key) return;
    fitKey.current = key;
    setFit({ key, ...LOADING });
    runOppFit(q, eq);
    const direction = fitDirection(q, eq);
    if (!direction) {
      fitKey.current = null;
      setFit({ key, status: "error", data: null, noDirection: true,
        error: `${eq.t} is not in this market's mapping, so the outcome that hurts it is unknown; say which one does to fit a hedge` });
      return;
    }
    postFit({
      market: { source: q.real.source, id: q.real.id },
      question: q.q, ticker: eq.t, direction, shares_held: eq.held || 500,
    }).then(
      (data) => { if (fitKey.current === key) { setFit({ key, status: "ok", data, error: null }); setAi(aiStatus(data)); } },
      (e) => {
        if (fitKey.current !== key) return;
        fitKey.current = null;
        setFit({ key, status: "error", data: null, error: errMsg(e) });
      },
    );
  }, [runOppFit]);

  const retryFit = useCallback((q: Question, eq: EquityPick) => {
    fitKey.current = null;
    runFit(q, eq);
  }, [runFit]);

  const chooseDirection = useCallback((direction: Direction) => {
    if (!question || !equity) return;
    const next: EquityPick = { ...equity, direction, directionSource: "user" };
    setEquityS(next);
    fitKey.current = null;
    runFit(question, next);
  }, [question, equity, runFit]);

  const openWeekendReplay = useCallback(async () => {
    const rows = await withTimeout(searchMarkets(WEEKEND_REPLAY.query).then((r) => r.markets), WEEKEND_SEARCH_MS);
    const q = weekendQuestion(rows);
    const holding = (portfolio.data?.holdings ?? []).find((h) => h.ticker === WEEKEND_REPLAY.ticker) ?? null;
    const eq = weekendPick(holding);
    setQuestionS(q); setEquityS(eq); setInstS("shares"); setQuery(""); resetToggles();
    fitKey.current = null;
    runFit(q, eq);
    if (eq.px == null) getEquity(eq.t).then((card) => setEquityS((e) => (e && e.t === eq.t ? { ...e, name: card.name ?? e.name, px: card.implied_move?.spot ?? null } : e)), () => {});
  }, [portfolio.data, runFit, resetToggles]);

  const openOpportunity = useCallback(async (q: Question, eq: EquityPick, opts: { ackUnvalidated?: boolean } = {}): Promise<string> => {
    const key = `${q.id}|${eq.t}`;
    const existing = bridges.find((b) => b.mode === "opportunity" && b.q?.id === q.id && b.eq?.t === eq.t);
    if (existing) { setActiveId(existing.id); return existing.id; }
    const want = opportunityFit(oppFit && oppFit.key === key && oppFit.status === "ok" ? oppFit.data : null);
    if (!want) throw new Error("there is no scored opportunity fit for this selection");
    const { bridgeId, applied } = await startOpportunityBridge(q, eq.t, want, undefined, undefined, opts);
    const entry: BridgeEntry = { id: `live:${bridgeId}`, kind: "live", bridgeId, q, eq, inst: "options", fit: applied, gap: null, mode: "opportunity" };
    setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
    setActiveId(entry.id);
    refreshAccount();
    return entry.id;
  }, [bridges, oppFit, refreshAccount]);

  const voicePick = useCallback(async (market: Market, ticker: string, direction: Direction | null, held: number | null): Promise<{ q: Question; eq: EquityPick; same: boolean }> => {
    const t = ticker.toUpperCase();
    const qid = `${market.source}:${market.id}`;
    if (question?.id === qid && equity?.t === t) {
      const eq = direction && direction !== equity.direction ? { ...equity, direction, directionSource: "user" as const } : equity;
      return { q: question, eq, same: eq === equity };
    }
    const base = question?.id === qid ? question : questionFromMarket(market);
    const q = base.touches.includes(t) ? base : { ...base, touches: [...base.touches, t] };
    const h = (portfolio.data?.holdings ?? []).find((x) => x.ticker === t) ?? null;
    const eq: EquityPick = { t, move: 0, rev: null, brand: null, why: "", real: true, name: h?.name ?? t, px: h?.spot ?? null,
      held: held ?? h?.shares ?? 0, ...(direction ? { direction, directionSource: "user" as const } : {}) };
    if (!direction) {
      const map = await withTimeout(mapEvent({ question: q.q, source: market.source, market_id: market.id }), 4000);
      const item = map?.items.find((i) => i.ticker.toUpperCase() === t);
      if (item) {
        const d: Direction = item.direction === "up_on_yes" ? "up_on_yes" : "down_on_yes";
        Object.assign(eq, { direction: d, directionSource: "mapping", why: item.rationale ?? "",
          move: item.impact_pct == null ? 0 : (d === "up_on_yes" ? 1 : -1) * Math.abs(item.impact_pct) });
      }
    }
    return { q, eq, same: false };
  }, [question, equity, portfolio.data]);

  const setPick = useCallback((q: Question, eq: EquityPick, same: boolean) => {
    if (same) return;
    setQuestionS(q); setEquityS(eq); setInstS("shares"); setQuery("");
    if (question?.id !== q.id || equity?.t !== eq.t) resetToggles();
  }, [question, equity, resetToggles]);

  const applyVoice = useCallback(async (u: StoreUpdate): Promise<void> => {
    switch (u.kind) {
      case "search":
        setQuestion(null);
        setQuery(u.query);
        return;
      case "fit": {
        const { q, eq, same } = await voicePick(u.market, u.ticker, u.direction, u.sharesHeld);
        setPick(q, eq, same);
        const key = `${q.id}|${eq.t}`;
        fitKey.current = key;
        setFit({ key, status: "ok", data: u.fit, error: null });
        setAi(aiStatus(u.fit));
        runOppFit(q, eq);
        setVoiceProposal((p) => (proposalForPick(p, q, eq) ? p : null));
        return;
      }
      case "proposal": {
        const p = u.proposal;
        const { q, eq, same } = await voicePick(u.market, p.ticker, p.direction ?? null, p.shares_held ?? null);
        setPick(q, eq, same);
        setVoiceProposal(p);
        return;
      }
      case "bridge": {
        const mine = !!voiceProposal && voiceProposal.id === u.proposalId && proposalForPick(voiceProposal, question, equity);
        const key = pickKey(question, equity);
        const entry: BridgeEntry = {
          id: `live:${u.bridgeId}`, kind: "live", bridgeId: u.bridgeId, q: mine ? question : null, eq: mine ? equity : null, inst: "shares",
          fit: mine && fit && fit.key === key && fit.status === "ok" ? runnableFit(fit.data) : null, gap: null,
          pmHedge: mine ? voiceProposal!.closed_pm_hedge === true : undefined, override: mine ? voiceProposal!.act_on_unvalidated === true : undefined,
        };
        setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
        setActiveId(entry.id);
        refreshAccount();
        return;
      }
      case "account":
        refreshAccount();
        return;
    }
  }, [voicePick, setPick, setQuestion, runOppFit, voiceProposal, question, equity, fit, refreshAccount]);

  const value = useMemo<Store>(() => ({
    question, equity, inst, query, thinking, setQuestion, setEquity, patchEquity, setInst, setQuery, chooseDirection, openWeekendReplay,
    settings, updateSettings, bridges, activeId, setActive: setActiveId, openBridge,
    fit, runFit, retryFit, oppFit, openOpportunity, library, reloadLibrary, account, portfolio, refreshAccount, ai, session,
    closedPmHedge, setClosedPmHedge, actOnUnvalidated, setActOnUnvalidated, voiceProposal, applyVoice,
  }), [question, equity, inst, query, thinking, setQuestion, setEquity, patchEquity, setInst, chooseDirection, openWeekendReplay, settings, updateSettings, bridges, activeId, openBridge, fit, runFit, retryFit, oppFit, openOpportunity, library, reloadLibrary, account, portfolio, refreshAccount, ai, session, closedPmHedge, actOnUnvalidated, voiceProposal, applyVoice]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function brokerLabel(a: Remote<AccountOut>): { name: string; tone: "sim" | "paper" | "demo" } {
  if (a.status !== "ok" || !a.data) return { name: a.status === "loading" ? "Account not read yet" : "Account not available", tone: "demo" };
  const b = (a.data.broker ?? "sim").toLowerCase();
  return b.includes("webull") ? { name: "Webull paper", tone: "paper" } : { name: "Simulated account", tone: "sim" };
}
