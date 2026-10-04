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
  max_contracts?: number | null;
  max_notional?: number | null;
  closed_pm_hedge?: boolean;
  act_on_unvalidated?: boolean;
  evidence?: EvidenceStatus | null;
  ack_unvalidated?: boolean;
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
  engine?: "algo" | "legacy";
  algo?: (AlgoChoice & { params?: Record<string, number> | null }) | null;
  coverage_cap?: number | null;
  cap_holds?: number;
  equity_price?: "live_quote" | "recorded" | "none" | null;
  equity_source?: string | null;
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
  account_scope?: "replay_sandbox" | "account";
  broker?: string | null;
  broker_hedge?: number;
  broker_filled?: number;
  market?: { source: string; id: string; token_id?: string | null } | null;
  replay_file?: string | null;
  replay_market?: { source?: string | null; id?: string | null; token_id?: string | null } | null;
  session?: SessionView | null;
  closure?: ClosureView | null;
  expected_gap?: GapView | null;
  closed_mode?: ClosedModeSummary | null;
  hedge_a?: HedgeASummary | null;
  evidence?: EvidenceStatus | null;
  evidence_label?: string | null;
  act_on_unvalidated?: boolean;
  liquidity_capped?: number;
  capital_refused?: number;
}

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

export interface AlgoChoice {
  family: string;
  preset_index?: number | null;
  params?: Record<string, number> | null;
  source?: "ai_fit" | "user";
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
  source?: string | null;
  match_type: string | null;
  matched_question: string | null;
  score: number | null;
}
export interface Holding {
  broker_qty?: number | null;
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
export interface BrokerBook {
  broker?: string | null; label?: string; available?: boolean; error?: string | null;
  account?: AccountOut | null; positions?: BrokerPosition[]; options_supported?: boolean | null; note?: string | null;
}
export interface PortfolioOut {
  holdings: Holding[]; total_value: number | null; total_exposure: number | null; total_includes_fuzzy?: boolean; stale: boolean;
  holdings_label?: string;
  broker_account?: BrokerBook | null;
}

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
export interface CapitalOut {
  broker?: string | null; account_read?: boolean; account_error?: string | null; account_type?: string | null; account_label?: string | null;
  account_checked?: boolean;
  account_stale?: boolean; account_age_s?: number | null;
  equity?: number | null; cash?: number | null; buying_power?: number | null; buying_power_basis?: string | null;
  limits?: CapitalLimits; gross_hedge_notional?: number; gross_limit_usd?: number | null; gross_use_pct?: number | null;
  equity_hedge_usd?: number; broker_short_notional?: number | null; staged_pending_usd?: number; option_risk_usd?: number;
  margin?: { initial_required?: number; maintenance_required?: number; excess_over_maintenance?: number | null; rule?: string };
  events?: CapitalEvent[]; breaches?: CapitalBreach[]; unpriced?: string[]; note?: string;
}
export const getLiquidity = (ticker: string, p: { coverage?: number; qty?: number } = {}) =>
  request<LiquidityEquity>(`/liquidity/${encodeURIComponent(ticker)}${Object.keys(p).length ? `?${qs(p)}` : ""}`);
export const getCapital = () => request<CapitalOut>("/capital");

export interface HealthOut { status: string; ai?: { live?: boolean | null; model?: string | null; provider?: string | null } | null }
export const getHealth = () => request<HealthOut>("/health");
export const listProposals = () => request<Proposal[]>("/proposals");
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
  family?: string;
  preset_index?: number;
  params?: Record<string, number>;
  act_on_unvalidated?: boolean;
}) => post<{ bridge_id: string }>("/bridges", body);
export const getBridge = (id: string) => request<BridgeSummary>(`/bridges/${id}`);
export const getPortfolio = () => request<PortfolioOut>("/portfolio");
export const listVerdicts = () => request<TagVerdict[]>("/verdicts");

export type EventClass =
  | "macro_fed" | "elections" | "tariffs_trade" | "geopolitics_energy" | "housing" | "fig"
  | "tech_regulation" | "crypto" | "corporate_8k" | "company_specific" | "unsupported";

export interface FitBody {
  market?: { source: string; id: string };
  question?: string;
  ticker: string;
  direction?: Direction;
  shares_held?: number;
  division?: Family;
  end_date?: string;
}
export interface FitStats {
  n_ticks?: number; n_orders?: number; pnl?: number; fees?: number; max_dd?: number;
  hedge_var_reduction?: number;
  hedge_var_reduction_vs_static?: number;
  avg_hedge_ratio?: number;
  turnover?: number; p50_ns?: number; p99_ns?: number;
}
export interface FitAlternative { family: string; preset_index?: number; params?: Record<string, number>; score?: number | null; division?: string; stats?: FitStats }
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
  model?: string | null;
  ai?: { live?: boolean | null; model?: string | null; provider?: string | null; cached?: boolean | null;
    steps?: { classify?: string | null; explain?: string | null } | null; fell_back_reason?: string | null } | null;
  ticks_source: "live_history" | "replay" | "none" | string;
  n_ticks: number;
  no_static_benchmark?: boolean;
  score_basis?: ScoreBasis | null;
  score_note?: string | null;
  score_raw?: number | null;
  score_vs_static?: number | null;
  avg_hedge_ratio?: number | null;
}
export const postFit = (body: FitBody) => post<FitOut>("/pipeline/fit", body);

export interface CatalogParam { name: string; min?: number; max?: number; grid?: number[] }
export interface CatalogBlock { name: string; kind?: string; ui_kind?: string }
export interface CatalogFamily {
  id: string;
  division?: string;
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

export interface AccountOut {
  broker?: string;
  cash: number;
  equity: number;
  buying_power: number;
  currency: string;
  simulated?: boolean;
  starting_cash?: number | null;
  realized_pnl?: number | null;
  fees_paid?: number | null;
  note?: string | null;
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
  origin?: string | null;
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

export const getSession = (at?: string) => request<SessionView>(`/session${at ? `?at=${encodeURIComponent(at)}` : ""}`);
export interface ExpectedGapOut {
  market_source: string; market_id: string; ticker: string;
  session: SessionView; closure: ClosureView & Record<string, unknown>;
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

export const getMechanisms = () => request<Registry>("/evidence/mechanisms");
export const getLadders = () => request<LaddersOut>("/ladders");
export const getTickets = () => request<TicketsOut>("/tickets");
export const getForwardStatus = () => request<ForwardStatus>("/forward/status");
