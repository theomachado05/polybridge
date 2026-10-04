// Mirrors docs/contracts.md (HTTP API). Change both together, by PR.
import type { ClosedLabels, ClosedModeSummary, ClosureView, GapView, HedgeASummary, SessionView, StagedOrder } from "./closed.ts";
import type { ForwardStatus, LaddersOut, Registry, TicketsOut } from "./micro.ts";
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
  /** Hedge A opt-in (closed-market mode): a simulated PM-leg estimate while equities are closed. Off by default. */
  closed_pm_hedge?: boolean;
  /** Closed-market override: stage hedge B on a market whose signal is NOT validated (labelled "override"). */
  act_on_unvalidated?: boolean;
  /** The evidence gate for this (market, ticker), computed by the backend; approval needs ack_unvalidated when not validated. */
  evidence?: EvidenceStatus | null;
  /** True when the approval acknowledged an unvalidated market (decisions and fills are labelled so). */
  ack_unvalidated?: boolean;
  /** Liquidity and capital before approval (POST /proposals; cached numbers on the sync path). */
  capacity?: Capacity | null;
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
    throw new ApiError(`Cannot reach the backend at ${API_URL}. Start the backend and try again.`, 0);
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : "";
    } catch {}
    throw new ApiError(detail || `${init?.method ?? "GET"} ${path} did not complete (error ${res.status})`, res.status);
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
  /** The backend's recording of this market (replay file name), when it has one. A resolved market with a recording
   *  is still listed in Build: its replay runs offline (and, with option columns, the Opportunity division). */
  recorded?: string | null;
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
  /** "ai_precomputed" (an LLM ahead of time, ai_map.json), "ai_live:<openai|gemini>:<model>" (that LLM, now), or "none". */
  source: "ai_precomputed" | "none" | string;
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
  /** Closed-market mode (backend app/closed/bridge_mode.py): the session at the bridge's latest tick (recorded time on
   *  a replay), the PM move since the last close, the expected open gap (evidence-gated), staged hedge B, hedge A. */
  session?: SessionView | null;
  closure?: ClosureView | null;
  expected_gap?: GapView | null;
  closed_mode?: ClosedModeSummary | null;
  hedge_a?: HedgeASummary | null;
  /** Evidence gate at bridge start: the backend's status and the label every decision/fill carries. */
  evidence?: EvidenceStatus | null;
  evidence_label?: string | null;
  act_on_unvalidated?: boolean;
  /** Orders capped by the participation caps / refused by the capital budget on this bridge. */
  liquidity_capped?: number;
  capital_refused?: number;
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
  /** Where the mapping came from (POST /map's `source`); absent on backends that only serve precomputed mappings. */
  source?: string | null;
  match_type: string | null;
  matched_question: string | null;
  score: number | null;
}
export interface Holding {
  /** Shares of this ticker in the broker book (not the demo shares); null when the broker could not be read. */
  broker_qty?: number | null;
  /** Can the active broker short it now (true / false / unknown), and why. */
  can_short?: boolean | null;
  short_reason?: string | null;
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
/** The active broker's real book (GET /portfolio broker_account): the Webull paper account, or the simulator. */
export interface BrokerBook {
  broker?: string | null; label?: string; available?: boolean; error?: string | null;
  account?: AccountOut | null; positions?: BrokerPosition[]; options_supported?: boolean | null; note?: string | null;
}
export interface PortfolioOut {
  holdings: Holding[]; total_value: number | null; total_exposure: number | null; total_includes_fuzzy?: boolean; stale: boolean;
  /** "demo holdings": the holdings above are the demo seed, never the broker's book. */
  holdings_label?: string;
  broker_account?: BrokerBook | null;
}

// ---- evidence gate, liquidity and capital (backend app/closed/evidence.py, app/liquidity, app/capital)

/** The backend's evidence gate for one (market, ticker). The UI never upgrades it. */
export interface EvidenceStatus {
  validated: boolean;
  status: string;
  evidence?: string | null;
  market?: string | null;
  rate_source?: string | null;
  basis_ticker?: string | null;
  reasons?: string[] | null;
  oos?: unknown;
}
export interface Freshness { age_s?: number | null; cache_stale?: boolean; staleness?: string; fetched_at?: number }
export interface CostBreakdown { qty?: number; half_spread_bp?: number | null; impact_bp?: number | null; total_bp?: number | null }
/** The equity part of a proposal's capacity block: the hedge at its approved size against the participation caps. */
export interface CapacityEquity {
  ticker?: string; available?: boolean; reason?: string | null; hedge_shares?: number; price?: number | null;
  hedge_notional_usd?: number | null; max_order_shares?: number | null; per_day_shares?: number | null;
  inside_caps?: boolean | null; binding?: string | null; est_cost_bp?: number | null; cost?: CostBreakdown | null;
  orders_at_open_needed?: number | null; sessions_needed?: number | null; book_usd_capacity?: number | null;
  book_usd_within_one_session?: number | null; adv_shares?: number | null; open5_median_shares?: number | null;
  spread_bp?: number | null; spread_source?: string | null; freshness?: Freshness | null; note?: string | null;
}
export interface DepthBand { contracts?: number; usd?: number }
export interface PmDepth { mid?: number | null; best_bid?: number | null; best_ask?: number | null; spread?: number | null; buy?: Record<string, DepthBand>; sell?: Record<string, DepthBand> }
export interface CapacityPm {
  available?: boolean; reason?: string | null; source?: string; depth?: PmDepth | null;
  max_order_contracts?: { buy?: number | null; sell?: number | null } | null;
  est_cost_at_cap?: Record<string, { qty?: number; avg_px?: number; cost_cents?: number; cost_bp?: number } | null> | null;
  freshness?: Freshness | null;
  twin?: { available?: boolean; reason?: string | null; source?: string; id?: string; max_order_contracts?: { buy?: number | null; sell?: number | null } | null } | null;
}
export interface CapitalFit {
  fits?: boolean | null; checked?: boolean; breaches?: { kind: string; detail?: string; after_usd?: number; limit_usd?: number }[] | null; note?: string | null;
  add_notional?: number | null;
  gross?: { now?: number; after?: number; limit_usd?: number | null } | null;
  event?: { key?: string; now?: number; after?: number; limit_usd?: number | null } | null;
  buying_power?: { basis?: string; required?: number; available?: number | null } | null;
  limits?: CapitalLimits | null;
}
export interface Capacity {
  label?: string; source?: "live" | "cache"; error?: string;
  caps?: Record<string, Record<string, string>>;
  equity?: CapacityEquity | null;
  options?: { max_notional?: number | null; max_contracts?: number | null; note?: string } | null;
  pm?: CapacityPm | null;
  capital?: CapitalFit | null;
}
/** GET /liquidity/{ticker}: participation caps, cost model and book-size capacity for one equity. */
export interface LiquidityEquity {
  kind?: "equity"; ticker: string; available: boolean; reason?: string | null;
  caps?: { per_order?: string; per_day?: string }; cost_model?: { formula?: string; k?: number; k_source?: string; sigma_source?: string; spread_source?: string };
  freshness?: Freshness | null; price?: number | null; adv_shares?: number | null; adv_usd?: number | null; sigma_daily?: number | null;
  open5_median_shares?: number | null; spread_bp?: number | null; spread_source?: string | null;
  max_order_shares?: number | null; max_position_shares?: number | null; per_day_shares?: number | null; binding?: string | null;
  est_cost_bp?: number | null; cost?: CostBreakdown | null;
  capacity?: { coverage?: number; book_usd?: number | null; book_usd_within_one_session?: number | null; note?: string } | null;
  sources?: Record<string, { source?: string | null; as_of?: string | null; at?: string | null; phase?: string | null; sessions?: number | null; note?: string | null; timeframe?: string | null }>;
}
export interface CapitalLimits { max_gross_hedge_pct: number; max_event_pct: number; reg_t_initial: number; reg_t_maintenance: number; short_put_mode: string }
export interface CapitalEvent { event: string; equity_hedge_usd?: number; equity_hedge_shares?: number; staged_pending_usd?: number; option_risk_usd?: number; total_usd: number; limit_usd?: number | null; use_pct?: number | null; proposals?: string[] }
export interface CapitalBreach { kind: string; event?: string; after_usd?: number; limit_usd?: number; detail?: string | null }
/** GET /capital: the account budget in force, hedge exposure per event, margin and breaches. */
export interface CapitalOut {
  broker?: string | null; account_read?: boolean; account_error?: string | null; account_type?: string | null; account_label?: string | null;
  /** False: the broker has no account read, so the budget is not enforced. */ account_checked?: boolean;
  /** True: the live read failed and this is the last good read (`account_age_s` old). */ account_stale?: boolean; account_age_s?: number | null;
  equity?: number | null; cash?: number | null; buying_power?: number | null; buying_power_basis?: string | null;
  limits?: CapitalLimits; gross_hedge_notional?: number; gross_limit_usd?: number | null; gross_use_pct?: number | null;
  equity_hedge_usd?: number; broker_short_notional?: number | null; staged_pending_usd?: number; option_risk_usd?: number;
  margin?: { initial_required?: number; maintenance_required?: number; excess_over_maintenance?: number | null; rule?: string };
  events?: CapitalEvent[]; breaches?: CapitalBreach[]; unpriced?: string[]; note?: string;
}
export const getLiquidity = (ticker: string, p: { coverage?: number; qty?: number } = {}) =>
  request<LiquidityEquity>(`/liquidity/${encodeURIComponent(ticker)}${Object.keys(p).length ? `?${qs(p)}` : ""}`);
export const getCapital = () => request<CapitalOut>("/capital");

/** GET /health; `ai` (when the backend reports it) says whether an LLM is configured and answering. */
export interface HealthOut { status: string; ai?: { live?: boolean | null; model?: string | null; provider?: string | null } | null }
export const getHealth = () => request<HealthOut>("/health");
export const listProposals = () => request<Proposal[]>("/proposals");
/** Explicit user action only. `ackUnvalidated` is the user's acknowledgement that the market's signal has not passed
 *  its out-of-sample test (the backend answers 409 EVIDENCE_UNVALIDATED without it on such a market). */
export const approveProposal = (id: string, ackUnvalidated = false) =>
  ackUnvalidated
    ? post<Proposal>(`/proposals/${id}/approve`, { ack_unvalidated: true })
    : request<Proposal>(`/proposals/${id}/approve`, { method: "POST" });
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
  | { ticker: string; market: { source: string; id: string; token_id?: string | null }; direction: Direction; shares_held: number; target_coverage: number; algo?: AlgoChoice; closed_pm_hedge?: boolean; act_on_unvalidated?: boolean }
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
  /** Closed-market override on this bridge (accepted only for a proposal approved with the acknowledgement). */
  act_on_unvalidated?: boolean;
}) => post<{ bridge_id: string }>("/bridges", body);
export const getBridge = (id: string) => request<BridgeSummary>(`/bridges/${id}`);
export const getPortfolio = () => request<PortfolioOut>("/portfolio");
export const listVerdicts = () => request<TagVerdict[]>("/verdicts");

// ---- v4 endpoints (spec §4 fit, §5 broker, §3.4/§9 library). Shapes are parsed defensively in the UI
// because the backend streams land in parallel; a caller whose endpoint fails shows the error with a retry.

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
  /** Which classifier answered this fit: "openai:<model>", "gemini:<model>" (or a legacy Gemini id) or "rules". The only basis for an "AI" label. */
  llm: "rules" | string;
  /** The LLM model (OpenAI or Gemini), when the backend reports it. */
  model?: string | null;
  /** LLM provenance block (docs/contracts.md "AI provenance"): `steps` says what produced each step
   *  (classify "openai" | "gemini" | "rules", explain "openai" | "gemini" | "template"); `live` alone does not mean an LLM classified. */
  ai?: { live?: boolean | null; model?: string | null; provider?: string | null; cached?: boolean | null;
    steps?: { classify?: string | null; explain?: string | null } | null; fell_back_reason?: string | null } | null;
  ticks_source: "live_history" | "replay" | "none" | string;
  n_ticks: number;
  /** What `score` measures (null or absent: unscored, or an older backend whose hedge score was the raw cut). */
  no_static_benchmark?: boolean;
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
  /** Webull margin fields (null when the broker does not report them). */
  account_type?: string | null;
  account_class?: string | null;
  account_label?: string | null;
  extended_hours?: boolean;
  market_open?: boolean;
  session?: string | null;
  next_open?: string | null;
  day_buying_power?: number | null;
  overnight_buying_power?: number | null;
  option_buying_power?: number | null;
  settled_cash?: number | null;
  unsettled_cash?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  maintenance_margin?: number | null;
  init_margin?: number | null;
  used_margin?: number | null;
  margin_excess?: number | null;
  margin_ratio?: number | null;
  open_margin_calls?: unknown[] | null;
  day_trades_left?: string | number | null;
  options_supported?: boolean;
  options_route?: string | null;
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
  multiplier?: number;
  /** "Webull paper account" | "Simulated account" | "demo holdings". */
  account?: string;
  strategy?: string | null;
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
  client_order_id?: string;
  /** "polybridge" (placed here) | "webull_open" | "webull_history" (read back from Webull). */
  origin?: string | null;
  /** The broker's own status word (e.g. Webull FILLED / CANCELLED), kept next to the mapped status. */
  broker_status?: string | null;
}
export const getAccount = () => request<AccountOut>("/account");
const unwrap = <T,>(key: string) => (x: unknown): T[] =>
  Array.isArray(x) ? (x as T[]) : x && typeof x === "object" && Array.isArray((x as Record<string, unknown>)[key]) ? ((x as Record<string, T[]>)[key]) : [];
export const getPositions = (includeDemo = false) =>
  request<unknown>(`/positions${includeDemo ? "?include_demo=true" : ""}`).then(unwrap<BrokerPosition>("positions"));
export const getOrders = (status?: string, days?: number) => {
  const q = qs({ status, days });
  return request<unknown>(`/orders${q ? `?${q}` : ""}`).then(unwrap<BrokerOrder>("orders"));
};
/** GET /broker/reconcile: the Webull order reconciler (runs every 15 s in the regular session, idles when closed). */
export interface ReconcileStatus {
  running?: boolean; state?: string; idle_reason?: string | null; interval_s?: number; market_open?: boolean; broker?: string | null;
  supported?: boolean; passes?: number; errors?: number; last_run_at?: string | null; last_error?: string | null;
  last_result?: { checked?: number; open_at_webull?: number; updated?: number; transitions?: unknown[]; external_open?: number; deferred?: number } | null;
  next_run_in_s?: number | null; recent_transitions?: { order_id?: string; symbol?: string; from?: string; to?: string; at?: string }[];
  status_map?: Record<string, string>;
}
export const getReconcile = () => request<ReconcileStatus>("/broker/reconcile");
export interface ShortInfo { symbol: string; can_short: boolean | null; reason?: string | null; shortable?: boolean | null; easy_to_borrow?: boolean | null; status?: string | null }
export interface BrokerCapabilities { broker?: string; options_supported?: boolean; options_route?: string | null; extended_hours?: boolean; reconcile?: boolean; can_short?: Record<string, ShortInfo>; note?: string | null }
export const getBrokerCapabilities = (symbols: string[]) =>
  request<BrokerCapabilities>(`/broker/capabilities${symbols.length ? `?symbols=${encodeURIComponent(symbols.join(","))}` : ""}`);

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

// ---- closed-market mode (backend app/closed/router.py, staged.py, opportunity_routes.py). The evidence gate is the
// backend's: a gap is "validated" only for a market whose own out-of-sample record passes; the UI never upgrades it.

export const getSession = (at?: string) => request<SessionView>(`/session${at ? `?at=${encodeURIComponent(at)}` : ""}`);
export interface ExpectedGapOut {
  market_source: string; market_id: string; ticker: string;
  session: SessionView; closure: ClosureView & Record<string, unknown>;
  /** The gap service's names (expected_gap_bp, band_bp, n_closures, label) plus validated / status / evidence. */
  expected_gap: Record<string, unknown>;
  evidence: { validated: boolean; status: string; market: string | null; evidence: string };
  move_source: "what_if" | "history_seed" | "tracker";
}
export const getExpectedGap = (p: { market_source: string; market_id: string; ticker?: string; direction?: Direction; token_id?: string | null }) =>
  request<ExpectedGapOut>(`/closed/expected-gap?${qs({ ...p, token_id: p.token_id ?? undefined })}`);
export interface ClosedEvidenceOut extends ClosedLabels {
  rule?: string; validated_markets: string[];
  market?: { validated: boolean; status: string; market: string | null; evidence: string };
}
export const getClosedEvidence = (p: { market_source?: string; market_id?: string; token_id?: string | null } = {}) =>
  request<ClosedEvidenceOut>(`/closed/evidence${Object.keys(p).length ? `?${qs({ ...p, token_id: p.token_id ?? undefined })}` : ""}`);
export interface StagedListOut { orders: StagedOrder[]; broker: { name: string | null; extended_hours: boolean }; note: string }
export const listStaged = (p: { bridge_id?: string; proposal_id?: string } = {}) =>
  request<StagedListOut>(`/staged${Object.keys(p).length ? `?${qs(p)}` : ""}`);
/** Explicit user action only: approves one staged plan (hedge B) at the quantity the user saw. An unapproved plan
 *  resizes with the gap; if it changed since it was rendered the backend refuses (409 PLAN_CHANGED). */
export const approveStaged = (id: string, qtySeen: number) =>
  post<StagedOrder>(`/staged/${encodeURIComponent(id)}/approve`, { qty: qtySeen });
export const cancelStaged = (id: string) => request<StagedOrder>(`/staged/${encodeURIComponent(id)}`, { method: "DELETE" });
export interface ClosedOpportunityOut {
  label: string;
  research: { id: string; status: string; verdict?: string | null; supports_claim: boolean };
  supported: boolean;
  display: "research_supported" | "estimate" | "hidden";
  snapshots: unknown[];
}
export const getClosedOpportunity = () => request<ClosedOpportunityOut>("/closed/opportunity");

// ---- options: live chain, hedge-instrument comparison, marks (backend app/options/live.py, hedge.py, mark.py).
// Bid/ask are Massive's last NBBO (15-min delayed); when the market is closed every row is the last session's close.

export interface ChainContract {
  ticker: string; strike: number; right: "call" | "put"; expiry: string;
  bid: number | null; ask: number | null; mid: number | null; mark_source?: string | null; quote_source?: string | null;
  last?: number | null; volume: number | null; open_interest: number | null;
  iv: number | null; delta: number | null; gamma?: number | null; theta?: number | null; vega?: number | null;
  iv_source?: string | null; greeks_source?: string | null; age_s?: number | null; stale?: boolean; stale_reason?: string | null;
  liquidity?: string | null; liquidity_flags?: string[]; exercise_style?: string | null;
}
export interface MarketClock { market_open?: boolean; phase?: string; label?: string; last_close?: string | null; next_open?: string | null }
export interface LiveChainOut {
  underlying: string; label?: string; market?: MarketClock; market_open?: boolean; available: boolean; reason?: string | null;
  expiry?: string | null; dte?: number | null; expiries_listed?: string[];
  underlying_price?: { price?: number | null; source?: string | null } | null; snapshot_label?: string | null;
  contracts: ChainContract[]; n_contracts?: number;
  freshness?: Freshness & { n_quoted?: number; n_stale?: number; staleness?: string; timeframe?: string; data_age_s?: number } | null;
  notes?: string[];
}
export const getLiveChain = (underlying: string, p: { expiry?: string; strikes?: number; window?: number } = {}) => {
  const q = qs(p);
  return request<LiveChainOut>(`/options/chain/${encodeURIComponent(underlying)}${q ? `?${q}` : ""}`);
};

export interface QuoteLeg {
  ticker: string; right: "call" | "put"; strike: number; expiry: string; side: "buy" | "sell"; contracts: number;
  bid: number | null; ask: number | null; mid: number | null; half_spread?: number | null; exec_px?: number | null;
  spread_source?: string | null; iv?: number | null; delta?: number | null; open_interest?: number | null; volume?: number | null;
  stale?: boolean; liquidity?: string | null; liquidity_flags?: string[];
}
export interface HedgeStrategy {
  available: boolean; reason?: string | null; legs?: QuoteLeg[]; contracts?: number; covered_shares?: number;
  upfront_usd?: number | null; upfront_bp?: number | null; expected_cost_usd?: number | null; expected_cost_bp?: number | null;
  delta_equivalent_shares?: number | null; hedge_ratio?: number | null;
  protection?: { floor_price?: number | null; floor_pct?: number | null; note?: string } | null;
  upside?: { cap_price?: number | null; cap_pct?: number | null; note?: string } | null;
  capital?: { cash_upfront_usd?: number | null; margin_initial_usd?: number | null; note?: string } | null;
  execution?: { order?: string; suggested_limit?: number | null; when?: string } | null;
  liquidity?: string | null; liquidity_flags?: string[];
  cost_breakdown?: { borrow_usd?: number; borrow_rate_annual?: number; spread_round_trip_usd?: number; fees_usd?: number } | null;
  breakeven_price?: number | null;
}
export type HedgeStrategyId = "short_stock" | "protective_put" | "collar" | "put_spread";
export interface HedgeQuoteOut {
  ticker: string; shares: number; horizon_days: number; protection_pct: number; label?: string; market?: MarketClock;
  market_open?: boolean; available: boolean; reason?: string | null; spot?: { price?: number | null; source?: string | null } | null;
  notional_usd?: number | null; expiry?: string | null; dte?: number | null; expiry_covers_horizon?: boolean;
  strategies?: Partial<Record<HedgeStrategyId, HedgeStrategy>>;
  ranking?: { by?: string; order?: HedgeStrategyId[]; cheapest?: HedgeStrategyId | null } | null;
  assumptions?: { borrow_rate_annual?: number; borrow_rate_assumed?: boolean } & Record<string, unknown>;
  caveats?: string[]; notes?: string[]; freshness?: Freshness & { staleness?: string } | null; options_reason?: string | null;
}
export const getHedgeQuote = (p: { ticker: string; shares: number; horizon_days?: number; protection_pct?: number }) =>
  request<HedgeQuoteOut>(`/options/hedge-quote?${qs(p)}`);

export interface OptionMark {
  contract: string; available: boolean; reason?: string | null; mark?: number | null; bid?: number | null; ask?: number | null;
  half_spread?: number | null; spread_source?: "nbbo" | "estimated" | "settlement" | string | null; mark_source?: string | null;
  exit_long?: number | null; exit_short?: number | null; mark_per_contract?: number | null; iv?: number | null; delta?: number | null;
  stale?: boolean; stale_reason?: string | null; market_open?: boolean; as_of_label?: string | null; expired?: boolean; cache_stale?: boolean;
}
export const getOptionMark = (contract: string) => request<OptionMark>(`/options/mark/${encodeURIComponent(contract)}`);

// Micro-market mechanisms (docs: backend/app/contracts, app/closed/evidence.py, app/forward). Labels come from the registry.
export const getMechanisms = () => request<Registry>("/evidence/mechanisms");
export const getLadders = () => request<LaddersOut>("/ladders");
export const getTickets = () => request<TicketsOut>("/tickets");
export const getForwardStatus = () => request<ForwardStatus>("/forward/status");
