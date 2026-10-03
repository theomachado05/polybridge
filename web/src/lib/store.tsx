"use client";

// One client-side store for the whole flow (the prototype's single component state, split per screen by
// route). It lives in the root layout, so it survives client navigation between screens.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import {
  approveProposal, createProposal, getAccount, getEquity, getLibrary, getPortfolio, postFit, startBridge,
  type AccountOut, type FitOut, type PortfolioOut,
} from "./api";
import { EQ, QUESTIONS, demoImpacts, type EquityPick, type Question } from "./demo";
import { parseLibrary, type Library } from "./library";
import { initSim, stepSim, type Sim } from "./sim";

export interface Settings {
  broker: string | null; conns: string[]; account: "Taxable" | "IRA"; rate: string; taxState: string; maxHedge: string;
  markets: Record<string, boolean>; guards: { edge: boolean; wash: boolean; auto: boolean };
}
export type BridgeEntry =
  | { id: string; kind: "demo"; q: Question; eq: EquityPick; inst: string; sim: Sim }
  | { id: string; kind: "live"; bridgeId: string; q: Question | null; eq: EquityPick | null; inst: string; family: string | null };

export interface Remote<T> { status: "loading" | "ok" | "error"; data: T | null; error: string | null }
export interface FitState extends Remote<FitOut> { key: string }

const LOADING = { status: "loading", data: null, error: null } as const;
const DEFAULT_SETTINGS: Settings = {
  broker: "webull", conns: ["webull"], account: "Taxable", rate: "32%", taxState: "CA", maxHedge: "100%",
  markets: { Polymarket: true, Kalshi: true }, guards: { edge: true, wash: true, auto: false },
};
export const TICK_MS = 900;

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
  openBridge: (q: Question, eq: EquityPick, inst: string) => Promise<string>;
  fit: FitState | null;
  runFit: (q: Question, eq: EquityPick) => void;
  library: Remote<Library>;
  account: Remote<AccountOut>;
  portfolio: Remote<PortfolioOut>;
}

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside <StoreProvider>");
  return s;
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Proposal → approval → engine bridge on the real backend (market-event path, contracts.md). */
async function startRealBridge(q: Question, eq: EquityPick, settings: Settings): Promise<string> {
  const m = q.real;
  if (!m) throw new Error("this market is from the demo set, not the live search");
  if (!eq.direction) throw new Error(`${eq.t} is not in this market's mapping, so the adverse outcome is unknown`);
  let spot = eq.px;
  if (!spot) spot = await getEquity(eq.t).then((c) => c.implied_move?.spot ?? null, () => null);
  const cap = Math.min(1, (parseInt(settings.maxHedge, 10) || 100) / 100);
  const market = { source: m.source, id: m.id, token_id: m.token_id };
  const prop = await createProposal({ ticker: eq.t, market, direction: eq.direction, shares_held: eq.held || 500, target_coverage: Math.min(0.5, cap) });
  const ok = prop.status === "approved" ? prop : await approveProposal(prop.id);
  // $/share per unit of probability; 0 (no spot or no impact estimate) turns the engine's fee gate off (contracts.md).
  const gap = spot && eq.move ? (spot * Math.abs(eq.move)) / 100 : 0;
  const sources: ("replay" | "live")[] = m.token_id ? ["replay", "live"] : ["replay"];
  let last: unknown = null;
  for (const source of sources) {
    try { return (await startBridge({ proposal_id: ok.id, source, gap_per_share: gap, direction: eq.direction, market })).bridge_id; }
    catch (e) { last = e; }
  }
  throw last instanceof Error ? last : new Error("the backend refused to start a bridge");
}

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
  const [library, setLibrary] = useState<Remote<Library>>(LOADING);
  const [account, setAccount] = useState<Remote<AccountOut>>(LOADING);
  const [portfolio, setPortfolio] = useState<Remote<PortfolioOut>>(LOADING);
  const thinkTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const fitKey = useRef<string | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    let alive = true;
    getLibrary().then(
      (raw) => { if (!alive) return; const lib = parseLibrary(raw); setLibrary(lib ? { status: "ok", data: lib, error: null } : { status: "error", data: null, error: "empty catalog" }); },
      (e) => alive && setLibrary({ status: "error", data: null, error: errMsg(e) }),
    );
    getAccount().then((a) => alive && setAccount({ status: "ok", data: a, error: null }), (e) => alive && setAccount({ status: "error", data: null, error: errMsg(e) }));
    getPortfolio().then((p) => alive && setPortfolio({ status: "ok", data: p, error: null }), (e) => alive && setPortfolio({ status: "error", data: null, error: errMsg(e) }));
    return () => { alive = false; clearTimeout(thinkTimer.current); };
  }, []);

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

  const setQuestion = useCallback((q: Question | null) => { setQuestionS(q); setEquityS(null); setInstS(null); setQuery(""); if (q) think(); else setThinking(false); }, [think]);
  const setEquity = useCallback((e: EquityPick | null) => { setEquityS(e); setInstS(null); setQuery(""); if (e) think(); else setThinking(false); }, [think]);
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

  const openBridge = useCallback(async (q: Question, eq: EquityPick, instId: string) => {
    try {
      const bridgeId = await startRealBridge(q, eq, settings);
      const entry: BridgeEntry = { id: `live:${bridgeId}`, kind: "live", bridgeId, q, eq, inst: instId, family: fit?.data?.family ?? null };
      setBridges((bs) => (bs.some((b) => b.id === entry.id) ? bs : [...bs, entry]));
      setActiveId(entry.id);
      setBridgeNote(null);
      return entry.id;
    } catch (e) {
      setBridgeNote(`No engine bridge on the backend (${errMsg(e)}). This bridge runs the prototype's simulator.`);
      return addDemoBridge(q, eq, instId);
    }
  }, [settings, fit, addDemoBridge]);

  const runFit = useCallback((q: Question, eq: EquityPick) => {
    const key = `${q.id}|${eq.t}`;
    if (fitKey.current === key) return;
    fitKey.current = key;
    setFit({ key, ...LOADING });
    postFit({
      market: q.real ? { source: q.real.source, id: q.real.id } : undefined,
      question: q.q, ticker: eq.t, direction: eq.direction ?? (eq.move < 0 ? "down_on_yes" : "up_on_yes"), shares_held: eq.held || 500,
    }).then(
      (data) => { if (fitKey.current === key) setFit({ key, status: "ok", data, error: null }); },
      (e) => { if (fitKey.current === key) setFit({ key, status: "error", data: null, error: errMsg(e) }); },
    );
  }, []);

  const value = useMemo<Store>(() => ({
    question, equity, inst, query, thinking, setQuestion, setEquity, patchEquity, setInst, setQuery,
    settings, updateSettings, bridges, activeId, bridgeNote, setActive: setActiveId, addDemoBridge, seedDemo, openBridge,
    fit, runFit, library, account, portfolio,
  }), [question, equity, inst, query, thinking, setQuestion, setEquity, patchEquity, setInst, settings, updateSettings, bridges, activeId, bridgeNote, addDemoBridge, seedDemo, openBridge, fit, runFit, library, account, portfolio]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** "sim" | "webull-paper" from GET /account, as a label. */
export function brokerLabel(a: Remote<AccountOut>): { name: string; tone: "sim" | "paper" | "demo" } {
  if (a.status !== "ok" || !a.data) return { name: "Demo account", tone: "demo" };
  const b = (a.data.broker ?? "sim").toLowerCase();
  return b.includes("webull") ? { name: "Webull paper", tone: "paper" } : { name: "Simulated account", tone: "sim" };
}
