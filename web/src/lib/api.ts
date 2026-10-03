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
  | { ticker: string; tags: string[]; shares_held: number; target_coverage: number }
  | { ticker: string; market: { source: string; id: string; token_id?: string | null }; direction: Direction; shares_held: number; target_coverage: number };
export const createProposal = (body: ProposalBody) => post<Proposal>("/proposals", body);
export const startBridge = (body: {
  proposal_id: string;
  source: "live" | "replay";
  market?: { source: string; id: string; token_id?: string | null };
  gap_per_share: number;
  direction?: Direction;
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
}
export interface FitAlternative { family: string; preset_index?: number; params?: Record<string, number>; score?: number | null; division?: string }
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
}
export const postFit = (body: FitBody) => post<FitOut>("/pipeline/fit", body);

export interface CatalogParam { name: string; min?: number; max?: number; grid?: number[] }
export interface CatalogBlock { name: string; kind?: string }
export interface CatalogFamily {
  id: string;
  division?: string;
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
}
export interface BrokerPosition {
  symbol: string;
  asset?: string;
  qty: number;
  avg_px?: number | null;
  avg_price?: number | null;
  market_px?: number | null;
  market_value?: number | null;
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
}
export const getAccount = () => request<AccountOut>("/account");
const unwrap = <T,>(key: string) => (x: unknown): T[] =>
  Array.isArray(x) ? (x as T[]) : x && typeof x === "object" && Array.isArray((x as Record<string, unknown>)[key]) ? ((x as Record<string, T[]>)[key]) : [];
export const getPositions = () => request<unknown>("/positions").then(unwrap<BrokerPosition>("positions"));
export const getOrders = (status?: string) =>
  request<unknown>(`/orders${status ? `?status=${encodeURIComponent(status)}` : ""}`).then(unwrap<BrokerOrder>("orders"));
