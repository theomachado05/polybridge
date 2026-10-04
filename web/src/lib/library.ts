// GET /library (the hedgecore catalog manifest) → Library screen rows.
// The UI families come from block kinds (spec §9): signals→Reader, sizers→Impact, gates→Gate,
// execution→Execution, tax→Tax, routing→Routing; risk blocks sit with Gate.
import type { CatalogFamily, CatalogParam, LibraryOut } from "./api";
import { prettyId } from "./fmt.ts";

export const UI_FAMILIES = ["Gate", "Reader", "Impact", "Execution", "Tax", "Routing"] as const;
export type UiFamily = (typeof UI_FAMILIES)[number];

const KIND_TO_UI: Record<string, UiFamily> = {
  signal: "Reader", signals: "Reader", reader: "Reader",
  sizer: "Impact", sizers: "Impact", impact: "Impact",
  gate: "Gate", gates: "Gate", risk: "Gate",
  execution: "Execution", exec: "Execution",
  tax: "Tax",
  routing: "Routing", router: "Routing",
};

// Block names from spec §3.1 and §9, for manifests that list blocks by name only.
const BLOCK_KIND: Record<string, UiFamily> = {};
const add = (ui: UiFamily, names: string) => names.split(" ").forEach((n) => (BLOCK_KIND[n.toLowerCase()] = ui));
add("Reader", "PMid ImpliedProb BookImbalance Microprice CrossVenueGap DeltaDp EwmaVol Momentum MeanRevertZ OptionImpliedProb PMvsOptionGap EightKScore");
add("Gate", "Staleness Sigma Spread Depth Session Cooldown EventWindow PositionCap NotionalCap DrawdownKill GapFlipKill DailyLossCap");
add("Impact", "DeltaBridge LinearExposure ConvexExposure KellyCapped VolTarget FixedNotional");
add("Execution", "NoTradeBand FeeGate Slicer PassiveAggressive IcebergCap");
add("Tax", "TaxLotSelector WashSaleGuard");
add("Routing", "VenueRouter");

export function blockUi(b: string | { name: string; kind?: string; ui_kind?: string }): UiFamily | null {
  const name = typeof b === "string" ? b : b.name;
  const kind = typeof b === "string" ? undefined : b.kind;
  const ui = typeof b === "string" ? undefined : b.ui_kind;  // the compiled manifest names the UI family itself
  if (ui && (UI_FAMILIES as readonly string[]).includes(ui)) return ui as UiFamily;
  if (kind && KIND_TO_UI[kind.toLowerCase()]) return KIND_TO_UI[kind.toLowerCase()];
  const key = name.replace(/Gate$|Block$/, "").toLowerCase();
  return BLOCK_KIND[name.toLowerCase()] ?? BLOCK_KIND[key] ?? null;
}

export interface LibParam { name: string; grid: number[]; min?: number; max?: number }
export interface LibRow {
  code: string;          // PB-0001…
  id: string;            // family id
  name: string;
  division: string;
  /** Every division the family runs in (the catalog's `divisions`, else its single `division`). */
  divisions: string[];
  role: string;
  eventClasses: string[];
  instruments: string[];
  blocks: { name: string; ui: UiFamily | null }[];
  uiFamilies: UiFamily[];
  params: LibParam[];
  presets: number;
  p50ns: number | null;
  p99ns: number | null;
}
/** A micro family (hedgecore ladder_pair, touch_ticket_reference): its own tick type, outside the 17 families. The
 *  status word is the catalog's (`lead`, `unvalidated`). */
export interface MicroFam { id: string; name: string; status: string; idea: string; division: string; presets: number; params: LibParam[] }
export interface Library { rows: LibRow[]; total: number; source: string | null; micro: MicroFam[]; microTotal: number }

type RawMicro = { id?: unknown; status?: unknown; idea?: unknown; division?: unknown; preset_count?: unknown; params?: CatalogFamily["params"] };

/** The catalog's `micro_families` (empty when the catalog has none). */
export function parseMicro(raw: unknown): { micro: MicroFam[]; microTotal: number } {
  const r = (raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {}) as { micro_families?: RawMicro[]; micro_total?: unknown };
  const micro = (Array.isArray(r.micro_families) ? r.micro_families : []).filter((f) => f && typeof f.id === "string").map((f) => ({
    id: f.id as string, name: prettyId(f.id as string), status: typeof f.status === "string" ? f.status : "",
    idea: typeof f.idea === "string" ? f.idea : "", division: typeof f.division === "string" ? f.division : "micro",
    presets: typeof f.preset_count === "number" ? f.preset_count : 0, params: params(f.params),
  }));
  const microTotal = typeof r.micro_total === "number" ? r.micro_total : micro.reduce((a, m) => a + m.presets, 0);
  return { micro, microTotal };
}

function params(p: CatalogFamily["params"]): LibParam[] {
  if (!p) return [];
  if (Array.isArray(p)) return p.map((x: CatalogParam) => ({ name: x.name, grid: x.grid ?? [], min: x.min, max: x.max }));
  return Object.entries(p).map(([name, v]) => (Array.isArray(v) ? { name, grid: v } : { name, grid: v.grid ?? [], min: v.min, max: v.max }));
}

export function parseLibrary(raw: LibraryOut | CatalogFamily[] | null | undefined): Library | null {
  if (!raw) return null;
  const fams = Array.isArray(raw) ? raw : raw.families ?? [];
  if (!Array.isArray(fams) || fams.length === 0) return null;
  const rows: LibRow[] = fams.filter((f) => f && typeof f.id === "string").map((f, i) => {
    const ps = params(f.params);
    const presets = f.preset_count ?? (ps.length ? ps.reduce((acc, x) => acc * Math.max(1, x.grid.length), 1) : 0);
    const blocks = (f.blocks ?? []).map((b) => ({ name: typeof b === "string" ? b : b.name, ui: blockUi(b) }));
    const uiFamilies = UI_FAMILIES.filter((u) => blocks.some((b) => b.ui === u));
    return {
      code: "PB-" + String(i + 1).padStart(4, "0"),
      id: f.id,
      name: prettyId(f.id),
      division: f.division ?? f.divisions?.[0] ?? "hedge",
      divisions: f.divisions?.length ? f.divisions : [f.division ?? "hedge"],
      role: f.idea ?? f.description ?? (f.event_classes?.length ? `Event classes: ${f.event_classes.map(prettyId).join(", ")}.` : ""),
      eventClasses: f.event_classes ?? [],
      instruments: f.instruments ?? [],
      blocks, uiFamilies, params: ps, presets,
      p50ns: f.latency?.p50_ns ?? f.p50_ns ?? null,
      p99ns: f.latency?.p99_ns ?? f.p99_ns ?? null,
    };
  });
  const reported = Array.isArray(raw) ? undefined : raw.total_presets ?? raw.preset_total ?? raw.total;
  const total = typeof reported === "number" ? reported : rows.reduce((a, r) => a + r.presets, 0);
  return { rows, total, source: Array.isArray(raw) ? null : raw.source ?? null, ...parseMicro(raw) };
}

/** Families whose event classes include `cls` (the pipeline's shortlist step, recomputed client-side). With
 *  `division`, only families in that division: the backend shortlists within the chosen division, so the step must
 *  count the same set its rationale does. */
export const shortlist = (lib: Library | null, cls: string, division?: string | null) => (lib
  ? lib.rows.filter((r) => (r.eventClasses.includes(cls) || r.eventClasses.includes("all")) && (!division || r.divisions.includes(division)))
  : []);

