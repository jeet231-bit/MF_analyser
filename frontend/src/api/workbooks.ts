import { apiGet, apiSend, apiUpload } from "./client";

export interface WorkbookSummary {
  filename: string;
  sheets: number;
  cells: number;
  formula_cells: number;
  named_ranges: number;
  tables: number;
  distinct_functions: number;
  functions: Record<string, number>;
  has_macros: boolean;
  warnings: string[];
  sheet_names: string[];
}

export type VersionStatus = "parsing" | "uploaded" | "interpreted" | "validated" | "active" | "pending_review" | string;

export interface WorkbookVersion {
  id: string;
  filename: string;
  uploaded_at: string;
  status: VersionStatus;
  size_bytes: number;
  parse_seconds: number | null;
  summary: WorkbookSummary | null;
}

export function listWorkbooks(): Promise<WorkbookVersion[]> {
  return apiGet<WorkbookVersion[]>("/workbooks");
}

export function getWorkbook(id: string): Promise<WorkbookVersion> {
  return apiGet<WorkbookVersion>(`/workbooks/${id}`);
}

export function uploadWorkbook(file: File): Promise<WorkbookVersion> {
  return apiUpload<WorkbookVersion>("/workbooks", file);
}

export interface InterpretResponse {
  version_id: string;
  scope: string[];
  summary: ModelSummary;
  sheets: SheetModel[];
  cycles: number[][];
  cycle_descriptions: string[];
  unresolved: string[];
}

export function interpretWorkbook(id: string, sheets?: string[]): Promise<InterpretResponse> {
  return apiSend<InterpretResponse>("POST", `/workbooks/${id}/interpret`, { sheets: sheets ?? null });
}

// ---- Logic model types (mirror backend/app/model/schema.py) ----------------------------------

export type SheetRole = "input" | "reference" | "transformation" | "calculation" | "output";
export type RoleSource = "heuristic" | "config" | "override";

export const SHEET_ROLES: SheetRole[] = ["input", "reference", "transformation", "calculation", "output"];

export interface SheetModel {
  name: string;
  index: number;
  state: string;
  in_scope: boolean;
  role: SheetRole;
  role_source: RoleSource;
  role_reason: string | null;
  used_range: string | null;
  cell_count: number;
  formula_cells: number;
  input_cells: number;
  output_cells: number;
  static_cells: number;
  formula_block_ids: number[];
  input_block_ids: number[];
  feeds: string[];
  reads: string[];
}

export interface ModelSummary {
  sheets_in_scope: number;
  templates: number;
  formula_blocks: number;
  input_blocks: number;
  external_blocks: number;
  formula_cells: number;
  input_cells: number;
  output_cells: number;
  static_cells: number;
  rules: number;
  parse_errors: number;
  cycles: number;
  self_dependent_blocks: number;
  unresolved_references: number;
  seconds: number;
  peak_mb: number;
}

export type RuleKind = "condition" | "threshold" | "lookup" | "error_fallback";

export interface BusinessRule {
  id: number;
  kind: RuleKind;
  template_id: number;
  sheet: string;
  cells: string[];
  description: string;
  detail: Record<string, unknown>;
}

export interface LogicModel {
  version_id: string;
  created_at: string;
  scope: string[];
  sheets: SheetModel[];
  summary: ModelSummary;
  cycles: number[][];
  cycle_descriptions: string[];
  unresolved: string[];
  rules: BusinessRule[];
  execution_order: number[];
}
