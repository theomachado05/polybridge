// Mirrors docs/contracts.md (HTTP API). Change both together, by PR.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Family = "hedge" | "opportunity";
export type ProposalStatus = "proposed" | "approved" | "rejected";

export interface ClassifyOut {
  family: Family | null;
  strategy: string | null;
}

export interface Proposal {
  id: string;
  ticker: string;
  family: Family;
  strategy: string;
  shares_held: number;
  target_coverage: number;
  status: ProposalStatus;
  basis?: "filing_tags" | "market_event";
  label?: string | null;
  market?: { source: string; id: string; token_id?: string | null } | null;
  direction?: Direction | null;
  algo?: AlgoChoice | null;
  /** Opportunity proposals: the approved risk caps (open option structures; premium / max loss at risk, USD). */
  max_contracts?: number | null;
  max_notional?: number | null;
  created_at: string;
  decided_at: string | null;
  bridge_started_at?: string | null;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(`Cannot reach the backend at ${API_URL}. Is it running?`, 0);
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : "";
    } catch {}
    throw new ApiError(detail || `${init?.method ?? "GET"} ${path} failed with ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export type MarketSource = "polymarket" | "kalshi";
export interface Market {
  source: MarketSource;
  id: string;
  question: string;
  yes_price: number | null;
  volume_24h: number;
  end_date: string | null;
  url: string | null;
  token_id: string | null;
}
export interface SearchOut { markets: Market[]; stale: boolean; note?: string | null }
export interface HistoryPoint { t: number; p: number }

export interface Evidence {
  strategy: string | null;
  horizon: string | null;
  difference: number | null;
  ci_lo: number | null;
  ci_hi: number | null;
  q_value: number | null;
}
export type VerdictLabel = "hedge" | "opportunity" | "no_edge";
export interface TagVerdict {
  tag: string;
  family: Family | null;
  kind: "confirmatory" | "exploratory" | "none";
  label: VerdictLabel;
  evidence: Evidence;
  note: string;
}

export interface ImpliedMove { value: number; expiry: string; spot: number; as_of: string }
export interface Filing {
  date: string;
  accession: string | null;
  url: string | null;
  tags: string[];
  verdict: TagVerdict | null;
}
export interface EquityCard {
  ticker: string;
  name: string | null;
  implied_move: ImpliedMove | null;
  filings: Filing[];
  markets: Market[];
  notes: string[];
}

export interface MapItem { ticker: string; direction: string; impact_pct: number | null; rationale: string | null }
export interface MapCandidate { source_key: string; matched_question: string; score: number; items: MapItem[] }
export interface MapOut {
  source: "precomputed" | "none";
  label: string;
  match_type: "exact" | "fuzzy" | null;
  score: number | null;
  matched_question: string | null;
  items: MapItem[];
  candidates: MapCandidate[];
  note: string | null;
}

export interface HedgeLeg { action: "buy" | "sell"; leg: string; contract: string; kind: string; strike: number; mark: number | null }
export interface HedgeOption {
  strategy: string;
  legs: HedgeLeg[];
  premium_per_share: number | null;
  premium_total: number | null;
  max_loss_per_share: number | null;
  breakeven_price: number | null;
  fees: number;
  half_spread_cost: number | null;
  covers: string;
  rank: number;
  why: string;
}
export interface HedgeMenu { ticker: string; spot: number | null; expiry: string | null; options: HedgeOption[]; notes: string[] }

export type Direction = "down_on_yes" | "up_on_yes";
export interface BridgeSummary {
  bridge_id: string;
  proposal_id: string;
  ticker: string;
  status: string;
  source: "live" | "replay";
  direction?: Direction;
  requested_source: string;
  ticks: number;
  orders: number;
  hedge: number;
  shares_held: number;
  target_coverage: number;
  coverage: number;
  basis?: "filing_tags" | "market_event";
  label?: string | null;
  reasons: Record<string, number>;
  latency_ns: { p50: number | null; p99: number | null };
  /** "algo": hedgecore.Algo runs `algo` (the fit); "legacy": the Engine default spec (no fit sent). */
  engine?: "algo" | "legacy";
  algo?: (AlgoChoice & { params?: Record<string, number> | null }) | null;
  /** Algo bridges: the approved coverage cap, sells it held, and what equity price the algo can see. */
  coverage_cap?: number | null;
  cap_holds?: number;
  equity_price?: "live_quote" | "recorded" | "none" | null;
  equity_source?: string | null;
  /** "opportunity": an options bridge (Opportunity-division family, simulated option fills). */
  division?: Family;
  option_position?: number;
  option_structure?: { kind: string; expiry?: string; strikes?: number[]; side?: string; legs?: { sign: number; ticker: string }[] } | null;
  risk_used?: number;
  max_contracts?: number | null;
  max_notional?: number | null;
  option_data?: "live_chain" | "recorded" | "none";
  pm_vs_options?: PmVsOptions | null;
  options_detail?: { supported?: boolean; available?: boolean; reason?: string | null; underlying_used?: string; strike_used?: number; expiry?: string; k_lo?: number; k_hi?: number; notes?: string[] } | null;
  fills_label?: string;
  /** "replay_sandbox": a replay bridge's orders go to an isolated in-memory sim, never the account. */
  account_scope?: "replay_sandbox" | "account";
  broker?: string | null;
  broker_hedge?: number;
  broker_filled?: number;
  /** The market the bridge was started on. */
  market?: { source: string; id: string; token_id?: string | null } | null;
  /** Replay bridges (when the backend reports them): the recorded file and the market it belongs to. */
  replay_file?: string | null;
  /** From the file's .meta.json sidecar; null when the file has no sidecar (its market is unknown). Set too when a
   *  live bridge fell back to a replay. */
  replay_market?: { source?: string | null; id?: string | null; token_id?: string | null } | null;
}

/** One tick's PM YES mid vs the options-implied P(YES) (raw orientation). The option number is an estimate. */
export interface PmVsOptions {
  pm_mid: number | null;
  opt_implied_prob: number | null;
  gap: number | null;
  opt_mid?: number | null;
  opt_iv?: number | null;
  opt_delta?: number | null;
  eightk_score?: number | null;
  label?: string;
}

/** The hedgecore algo a bridge runs (contracts.md): a catalog family plus one preset, or explicit params. */
export interface AlgoChoice {
  family: string;
  preset_index?: number | null;
  params?: Record<string, number> | null;
  source?: "ai_fit" | "user";
  /** Server-set on the stored proposal: the params that will run after the approved target_coverage capped the
   *  hedge-size params, the cap, and the params it lowered ({name: original}). */
  resolved_params?: Record<string, number> | null;
  coverage_cap?: number | null;
  capped?: Record<string, number> | null;
}

export interface HedgeStatus { status: "none" | "proposed" | "approved" | "bridging" | "rejected"; proposal_id: string | null; bridge_id: string | null }
export interface Exposure {
  market: Market;
  direction: string;
  impact_pct: number;
  rationale: string | null;
  remaining_usd: number;
  label: string;
  match_type: string | null;
  matched_question: string | null;
  score: number | null;
}
export interface Holding {
  ticker: string;
  name: string | null;
  shares: number;
  spot: number | null;
  value: number | null;
  markets: Market[];
  filings: Filing[];
  exposure: Exposure | null;
  hedge: HedgeStatus;
  notes: string[];
}
export interface PortfolioOut { holdings: Holding[]; total_value: number | null; total_exposure: number | null; total_includes_fuzzy?: boolean; stale: boolean }

export const getHealth = () => request<{ status: string }>("/health");
export const listProposals = () => request<Proposal[]>("/proposals");
export const approveProposal = (id: string) => request<Proposal>(`/proposals/${id}/approve`, { method: "POST" });
export const searchMarkets = (q: string) => request<SearchOut>(`/markets/search?q=${encodeURIComponent(q)}`);
export const getMarketHistory = (source: string, id: string) =>
  request<HistoryPoint[]>(`/markets/${source}/${encodeURIComponent(id)}/history`);
export const getEquity = (ticker: string) => request<EquityCard>(`/equities/${encodeURIComponent(ticker)}`);
export const getVerdict = (tag: string) => request<TagVerdict>(`/verdicts/${encodeURIComponent(tag)}`);
export const mapEvent = (body: { question?: string; source?: string; market_id?: string }) => post<MapOut>("/map", body);
export const getHedges = (ticker: string, shares: number, label: VerdictLabel) =>
  request<HedgeMenu>(`/hedges/${encodeURIComponent(ticker)}?shares=${shares}&label=${label}`);
export type ProposalBody =
  | { ticker: string; tags: string[]; shares_held: number; target_coverage: number; algo?: AlgoChoice }
  | { ticker: string; market: { source: string; id: string; token_id?: string | null }; direction: Direction; shares_held: number; target_coverage: number; algo?: AlgoChoice }
  | { ticker: string; market: { source: string; id: string; token_id?: string | null }; division: "opportunity"; algo: AlgoChoice; direction?: Direction; max_contracts?: number; max_notional?: number };
export const createProposal = (body: ProposalBody) => post<Proposal>("/proposals", body);
export const startBridge = (body: {
  proposal_id: string;
  source: "live" | "replay";
  market?: { source: string; id: string; token_id?: string | null };
  gap_per_share: number;
  direction?: Direction;
  /** The fitted algo (must equal the proposal's approved algo when it has one). Omitted: the Engine default spec. */
  family?: string;
  preset_index?: number;
  params?: Record<string, number>;
}) => post<{ bridge_id: string }>("/bridges", body);
export const getBridge = (id: string) => request<BridgeSummary>(`/bridges/${id}`);
export const getPortfolio = () => request<PortfolioOut>("/portfolio");
export const listVerdicts = () => request<TagVerdict[]>("/verdicts");

// ---- v4 endpoints (spec §4 fit, §5 broker, §3.4/§9 library). Shapes are parsed defensively in the UI
// because the backend streams land in parallel; every caller has a labelled demo fallback.

export type EventClass =
  | "macro_fed" | "elections" | "tariffs_trade" | "geopolitics_energy" | "housing" | "fig"
  | "tech_regulation" | "crypto" | "corporate_8k" | "company_specific" | "unsupported";

export interface FitBody {
  market?: { source: string; id: string };
  question?: string;
  ticker: string;
  direction?: Direction;
  shares_held?: number;
  /** Fit this division instead of the default (hedge when shares are held, else opportunity). */
  division?: Family;
  end_date?: string;
}
/** Replay stats the backend copies into each alternative (tune.STAT_KEYS); only finite values are present. */
export interface FitStats {
  n_ticks?: number; n_orders?: number; pnl?: number; fees?: number; max_dd?: number;
  /** Plain hedge variance reduction: any static short of a fraction h earns 1 - (1 - h)^2 of it, so never ranked. */
  hedge_var_reduction?: number;
  /** Variance cut beyond a static short of the same average size: what the PM signal adds (the hedge ranking score). */
  hedge_var_reduction_vs_static?: number;
  /** Mean short as a fraction of shares_held over the replay. */
  avg_hedge_ratio?: number;
  turnover?: number; p50_ns?: number; p99_ns?: number;
}
export interface FitAlternative { family: string; preset_index?: number; params?: Record<string, number>; score?: number | null; division?: string; stats?: FitStats }
/** What FitOut.score ranks by: the hedge score is the variance cut beyond a static hedge, never the raw cut. */
export type ScoreBasis = "hedge_var_reduction_vs_static" | "net_pnl_per_drawdown";
export interface FitOut {
  event_class: EventClass | string;
  division: Family | string;
  family: string | null;
  preset_index: number | null;
  params: Record<string, number>;
  score: number | null;
  alternatives: FitAlternative[];
  rationale: string;
  llm: "gemini" | "rules" | string;
  ticks_source: "live_history" | "replay" | "none" | string;
  n_ticks: number;
  /** What `score` measures (null or absent: unscored, or an older backend whose hedge score was the raw cut). */
  score_basis?: ScoreBasis | null;
  score_note?: string | null;
  /** Hedge fits only (null otherwise): raw variance reduction, reported but never ranked. */
  score_raw?: number | null;
  /** Hedge fits only: equals `score`, the variance cut beyond a static hedge of the same average size. */
  score_vs_static?: number | null;
  /** Hedge fits only: mean short as a fraction of shares held over the replay. */
  avg_hedge_ratio?: number | null;
}
export const postFit = (body: FitBody) => post<FitOut>("/pipeline/fit", body);

export interface CatalogParam { name: string; min?: number; max?: number; grid?: number[] }
export interface CatalogBlock { name: string; kind?: string; ui_kind?: string }
export interface CatalogFamily {
  id: string;
  division?: string;
  /** A family listed in more than one division (e.g. poly_kalshi_spread: hedge and opportunity). */
  divisions?: string[];
  event_classes?: string[];
  instruments?: string[];
  blocks?: (string | CatalogBlock)[];
  params?: CatalogParam[] | Record<string, number[] | { min?: number; max?: number; grid?: number[] }>;
  preset_count?: number;
  idea?: string;
  description?: string;
  latency?: { p50_ns?: number | null; p99_ns?: number | null } | null;
  p50_ns?: number | null;
  p99_ns?: number | null;
}
export interface LibraryOut {
  families?: CatalogFamily[];
  total_presets?: number;
  preset_total?: number;
  total?: number;
  source?: string;
}
export const getLibrary = () => request<LibraryOut | CatalogFamily[]>("/library");

// Field names checked against origin/v4/broker (backend/app/broker/models.py) and origin/v4/ai-pipeline.
export interface AccountOut {
  broker?: string;          // "sim" | "webull-paper"
  cash: number;
  equity: number;
  buying_power: number;
  currency: string;
  simulated?: boolean;
  starting_cash?: number | null;
  realized_pnl?: number | null;
  fees_paid?: number | null;
  note?: string | null;
}
export interface BrokerPosition {
  symbol: string;
  asset?: string;
  qty: number;
  avg_px?: number | null;
  avg_price?: number | null;
  market_px?: number | null;
  mark_px?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  broker?: string;
}
export interface BrokerOrder {
  id: string;
  symbol: string;
  asset?: string;
  side: "buy" | "sell";
  qty: number;
  type?: string;
  status?: string;
  fill_px?: number | null;
  filled_px?: number | null;
  avg_fill_px?: number | null;
  limit_px?: number | null;
  fee?: number | null;
  tag?: string | null;
  created_at?: string | null;
  filled_at?: string | null;
  broker?: string;
  price_source?: string | null;
  reject_reason?: string | null;
  note?: string | null;
}
export const getAccount = () => request<AccountOut>("/account");
const unwrap = <T,>(key: string) => (x: unknown): T[] =>
  Array.isArray(x) ? (x as T[]) : x && typeof x === "object" && Array.isArray((x as Record<string, unknown>)[key]) ? ((x as Record<string, T[]>)[key]) : [];
export const getPositions = () => request<unknown>("/positions").then(unwrap<BrokerPosition>("positions"));
export const getOrders = (status?: string) =>
  request<unknown>(`/orders${status ? `?status=${encodeURIComponent(status)}` : ""}`).then(unwrap<BrokerOrder>("orders"));

// ---- options data layer (backend/app/options/router.py). Every number here is labelled: options-implied values are
// risk-neutral estimates from listed prices, never measured probabilities.

export interface OptionsMatch {
  underlying: string; strike: number; expiry: string; direction: "above" | "below"; scale: number; level: number;
  label: string; fallback: [string, number] | null; approx: boolean; date_source: string; notes: string[];
}
export interface OptionsEstimate {
  prob: number | null; lo: number | null; hi: number | null; method: string | null; k_lo: number | null; k_hi: number | null;
  expiry: string | null; expiry_gap_days: number | null; expiry_gap_ok: boolean; delta: number | null; iv: number | null;
  structure_mid?: number | null; notes: string[];
}
export interface OptionsImpliedOut {
  label: string;
  market: { source: string | null; id: string | null; question: string | null; end_date: string | null; yes_price: number | null; origin: string | null };
  supported: boolean;
  available: boolean;
  reason?: string | null;
  match?: OptionsMatch;
  underlying_used?: string;
  strike_used?: number;
  approx?: boolean;
  notes?: string[];
  estimate?: OptionsEstimate;
  pm_yes_price?: number | null;
  pm_minus_option?: number | null;
  spot?: number | null;
  freshness?: Record<string, unknown>;
}
export interface OptionRow {
  ticker: string; bid: number | null; ask: number | null; mid: number | null; mark_source: string | null;
  iv: number | null; delta: number | null; open_interest: number | null; volume: number | null; updated_ns: number | null;
}
export interface OptionsChainOut {
  ticker: string;
  label: string;
  window: { expiry_from: string; expiry_to: string; strike_min: number | null; strike_max: number | null };
  available: boolean;
  reason: string | null;
  spot?: number | null;
  n_contracts?: number;
  expiries: { expiry: string; strikes: { strike: number; call: OptionRow | null; put: OptionRow | null }[] }[];
  freshness?: Record<string, unknown>;
}
export interface OptionsEightKOut {
  ticker: string;
  as_of?: string;
  score: number | null;
  coverage: "in_sample" | "live" | null;
  available: boolean;
  source: string;
  label: string;
  [k: string]: unknown;
}
const qs = (o: Record<string, string | number | undefined | null>) =>
  Object.entries(o).filter(([, v]) => v != null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
export const getOptionsImplied = (p: { market_source?: string; market_id?: string; question?: string; end_date?: string }) =>
  request<OptionsImpliedOut>(`/options/implied?${qs(p)}`);
export const getOptionsChain = (p: { ticker: string; expiry_from?: string; expiry_to?: string; strike_min?: number; strike_max?: number }) =>
  request<OptionsChainOut>(`/options/chain?${qs(p)}`);
export const getOptionsEightK = (ticker: string, as_of?: string) =>
  request<OptionsEightKOut>(`/options/eightk?${qs({ ticker, as_of })}`);
