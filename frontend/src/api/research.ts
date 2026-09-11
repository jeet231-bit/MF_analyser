import { apiGet, qs } from "./client";

// ---- shapes (mirror backend/app/api/research.py) ---------------------------------------------

export type MeasureRole = "score" | "rank" | "quartile" | "return" | "factor";

export interface MeasureMeta {
  key: string;
  label: string;
  role: MeasureRole;
  format: string; // number | integer | percent | general | inr_crore
  unit: string | null;
  higherIsBetter: boolean;
  primary: boolean;
  decimals?: number | null;
}

export interface VersionRef {
  id: string;
  filename: string;
  uploaded_at?: string | null;
  as_of?: string | null;
  /** "31 Aug" (or "31 Aug 2025" across years): what narratives call the version. */
  date?: string | null;
}

interface Envelope {
  configured: boolean;
  problems: string[];
  version_id?: string | null;
  run_id?: string | null;
  version?: { id: string; filename: string; uploaded_at: string; status: string };
  run?: { id: string; kind: string; created_at: string };
}

export interface ResearchConfig extends Envelope {
  entity?: { sheet: string; rows: number[] | null; key: string; label: string | null; universe: string | null };
  dimensions?: { key: string; label: string; ref: string; resolved: boolean; split: string | null }[];
  measures?: { key: string; label: string; role: MeasureRole; ref: string; format: string; unit: string | null; higherIsBetter: boolean; primary: boolean; resolved: boolean }[];
  phases?: { key: string; label: string; columns: { col: string; label: string | null }[] }[];
  periods?: { col: string; label: string | null }[];
  categoryStats?: { col: string; label: string | null }[];
  insights?: { key: string; section: string; eyebrow: string; title: string; mode: string }[];
  narratives?: Record<string, unknown>;
  footer?: string | null;
  findings?: Finding[];
  quartileRule?: { unrankedBelow: number; unrankedValue: string };
  minGroupCount?: number;
}

export interface Finding {
  title: string;
  detail: string;
  status: "fixed" | "open";
}

export interface Universe {
  total: number;
  rated: number;
  complete: number;
  quartiles: Record<string, number>;
  categories: number;
  unranked_categories: number;
  unrated_small_categories: number;
  unrated_missing_data: number;
  outside_universe?: number;
  stats_only_categories?: number;
}

export interface Mover {
  key: string;
  label: string;
  sub: string | null;
  category: string | null;
  rankFrom: number;
  rankTo: number;
  delta: number;
  quartileFrom: number | null;
  quartileTo: number | null;
  cause: "market" | "repair";
  note: string | null;
}

export interface HeldQ1 {
  available: boolean;
  count?: number;
  current_q1?: number;
  versions?: number;
  from?: string | null;
  note?: string;
}

export interface ResearchSummary extends Envelope {
  as_of?: unknown;
  universe?: Universe;
  quartiles?: Record<string, number>;
  category_averages?: { measure: string; label: string; rows: { key: string; value: number; label: string; count: number }[]; total: number } | null;
  measures?: MeasureMeta[];
  validation?: { status: string; checked: number; matched: number; anomalies: number } | null;
  findings?: { open: number; fixed: number };
  movement?: {
    previous: VersionRef;
    same_month: boolean;
    moved: number;
    up: number;
    down: number;
    repairs: number;
    entries: number;
    exits: number;
    top: Mover[];
  } | null;
  held_q1?: HeldQ1;
  history?: { id: string; date: string | null; as_of: string }[];
  universe_narrative?: string | null;
  narrative?: string | null;
  footer?: string | null;
}

export interface EntityRow {
  key: string;
  label: string;
  sub: string | null;
  dims: Record<string, string | null>;
  measures: Record<string, number | null>;
  raw: Record<string, unknown>;
  rated: boolean;
  delta?: { rank: number | null; quartileFrom?: number | null; new: boolean } | null;
  group?: string | null;
}

export interface EntitiesPage extends Envelope {
  total: number;
  page: number;
  size: number;
  sort: string | null;
  dir: "asc" | "desc";
  measures: MeasureMeta[];
  dimensions: { key: string; label: string }[];
  facets: Record<string, string[]>;
  previous: VersionRef | null;
  groups: { key: string; label: string; count: number; subtotals: Record<string, number | null> }[] | null;
  rows: EntityRow[];
}

export interface EntityMeasure {
  key: string;
  label: string;
  role: MeasureRole;
  value: number | null;
  display: string;
  unit: string | null;
  format: string;
  decimals?: number | null;
  primary?: boolean;
  categoryRank: number | null;
  categoryCount: number;
  cell: string | null;
}

export interface EntityDetail extends Envelope {
  entity: EntityRow;
  row: number;
  measures: EntityMeasure[];
  phases: { group: string; groupLabel: string; label: string; value: number | null; categoryMean: number | null; unit: string | null }[];
  periods: { label: string; value: number | null; unit: string | null }[];
  category: { key: string | null; count: number; rated: number; quartiles: Record<string, number>; means: Record<string, number | null> };
  peers: { key: string; label: string; rank: number | null; quartile: number | null; score: number | null; scoreLabel: string; me: boolean }[];
  history: { version_id: string; filename: string; uploaded_at: string; date: string | null; as_of: string; rank: number | null; quartile: number | null; score: number | null }[];
  delta: number | null;
  deltaLabel: string | null;
  previous: VersionRef | null;
  quartileExplanation: string[] | null;
  narrative: string | null;
  cells: Record<string, string>;
}

export interface CategoryRow {
  key: string;
  count: number;
  rated: number;
  quartiles: Record<string, number>;
  means: Record<string, number | null>;
  spreads: Record<string, number | null>;
  stats: Record<string, number | null>;
  statLabels: Record<string, string>;
  unranked: boolean;
  value: number | null;
  valueLabel: string;
}

export interface CategoriesResponse extends Envelope {
  measure: string | null;
  measures: { key: string; label: string }[];
  unrankedBelow: number;
  minGroupCount: number;
  statsOnly: number;
  rows: CategoryRow[];
  narrative: string | null;
}

export interface MovementResponse extends Envelope {
  available: boolean;
  reason?: string;
  from?: VersionRef;
  to?: VersionRef;
  same_month?: boolean;
  rated?: number;
  moved?: number;
  up?: number;
  down?: number;
  avg_up?: number | null;
  avg_down?: number | null;
  quartileChanges?: { total: number; into_q1: number; out_of_q1: number };
  risers?: Mover[];
  fallers?: Mover[];
  entries?: { key: string; label: string; category: string | null }[];
  exits?: { key: string; label: string; category: string | null }[];
  repairs?: { key: string; label: string; note: string | null }[];
  versions?: (VersionRef & { status: string; activated_at: string | null })[];
  narrative?: string | null;
}

export interface InsightRow {
  key: string | null;
  label: string;
  sub: string | null;
  value: number | null;
  valueLabel: string;
  extra: Record<string, unknown>;
}

export interface Insight {
  key: string;
  section: string;
  eyebrow: string;
  title: string;
  sentence: string;
  count: number;
  total: number;
  measure: string | null;
  drill: { sort?: string; dir?: "asc" | "desc"; keys?: string[] };
  problems: string[];
  status: "ok" | "empty" | "unavailable" | "problem";
  note: string | null;
  rows: InsightRow[];
}

export interface InsightsResponse extends Envelope {
  sections: string[];
  insights: Insight[];
  footer: string | null;
}

// ---- calls ----------------------------------------------------------------------------------

export interface EntityQuery {
  q?: string;
  category?: string;
  amc?: string;
  plan?: string;
  quartile?: number[];
  keys?: string[];
  sort?: string;
  dir?: "asc" | "desc";
  page?: number;
  size?: number;
  groupBy?: string;
}

function entityQs(query: EntityQuery): string {
  const params = new URLSearchParams();
  const set = (k: string, v: string | number | undefined) => v !== undefined && v !== "" && params.set(k, String(v));
  set("q", query.q);
  set("category", query.category);
  set("amc", query.amc);
  set("plan", query.plan);
  set("sort", query.sort);
  set("dir", query.dir);
  set("page", query.page);
  set("size", query.size);
  set("groupBy", query.groupBy);
  for (const q of query.quartile ?? []) params.append("quartile", String(q));
  for (const k of query.keys ?? []) params.append("keys", k);
  const s = params.toString();
  return s ? `?${s}` : "";
}

export function getResearchConfig(): Promise<ResearchConfig> {
  return apiGet<ResearchConfig>("/research/config");
}

export function getResearchSummary(measure?: string): Promise<ResearchSummary> {
  return apiGet<ResearchSummary>(`/research/summary${qs({ measure })}`);
}

export function getResearchEntities(query: EntityQuery = {}): Promise<EntitiesPage> {
  return apiGet<EntitiesPage>(`/research/entities${entityQs(query)}`);
}

export function getResearchEntity(key: string): Promise<EntityDetail> {
  return apiGet<EntityDetail>(`/research/entities/${encodeURIComponent(key)}`);
}

export function getResearchCategories(measure?: string): Promise<CategoriesResponse> {
  return apiGet<CategoriesResponse>(`/research/categories${qs({ measure })}`);
}

export function getResearchMovement(from?: string, to?: string): Promise<MovementResponse> {
  return apiGet<MovementResponse>(`/research/movement${qs({ from, to })}`);
}

export function getResearchInsights(section?: string): Promise<InsightsResponse> {
  return apiGet<InsightsResponse>(`/research/insights${qs({ section })}`);
}

export type ResearchExportKind = "entities" | "categories" | "movement" | "insights";

export function researchExportUrl(kind: ResearchExportKind, format: "csv" | "xlsx", query: EntityQuery & { from?: string; to?: string; measure?: string } = {}): string {
  const base = `/api/research/${kind}/export`;
  if (kind === "entities") {
    const q = entityQs(query);
    return `${base}${q ? `${q}&` : "?"}format=${format}`;
  }
  return `${base}${qs({ format, from: query.from, to: query.to, measure: query.measure })}`;
}
