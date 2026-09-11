import { apiGet, apiSend, qs } from "./client";

export type CellValue = number | string | boolean | null;

export interface HotTemplate {
  template_id: number;
  sheet: string;
  example_cell: string;
  cells: number;
  seconds: number;
}

export interface RunSummary {
  kind: string;
  blocks_evaluated: number;
  cells_evaluated: number;
  seconds: number;
  peak_mb: number;
  error_cells: number;
  hot_templates: HotTemplate[];
  evaluated_block_ids: number[];
  skipped_blocks: number;
  skipped_template_ids: number[];
  notes: string[];
}

export type RunStatus = "running" | "ok" | "failed";

export interface RunOut {
  id: string;
  version_id: string;
  kind: "full" | "incremental";
  parent_run_id: string | null;
  overrides: Record<string, CellValue>;
  status: RunStatus;
  error: string | null;
  created_at: string;
  summary: RunSummary;
}

export function createRun(
  versionId: string,
  overrides: Record<string, CellValue>,
  options: { mode?: "auto" | "full"; background?: boolean } = {},
): Promise<RunOut> {
  return apiSend<RunOut>("POST", `/workbooks/${versionId}/runs`, {
    overrides,
    mode: options.mode ?? "auto",
    background: options.background ?? false,
  });
}

export function getRun(runId: string): Promise<RunOut> {
  return apiGet<RunOut>(`/runs/${runId}`);
}

export function listRuns(versionId: string): Promise<RunOut[]> {
  return apiGet<RunOut[]>(`/workbooks/${versionId}/runs`);
}

/** One cell of a grid window: value, type, and markers (f formula, o override, b baseline value). */
export interface GridCell {
  v: CellValue;
  t: string;
  f?: boolean;
  o?: boolean;
  b?: CellValue;
  stale?: boolean;
}

export type ColumnKind = "output" | "formula" | "input" | "static";
export type ColumnFormat = "general" | "number" | "integer" | "percent" | "date" | "text";

export interface GridColumn {
  col: number;
  letter: string;
  label: string | null;
  kind: ColumnKind;
  format: ColumnFormat;
}

export interface GridRow {
  row: number;
  label: string | null;
  cells: (GridCell | null)[];
}

export interface GridWindow {
  run_id: string;
  sheet: string;
  r1: number;
  r2: number;
  c1: number;
  c2: number;
  used_range: string | null;
  body_start: number;
  total_rows: number;
  total_cols: number;
  row_label_col: number | null;
  baseline_run_id: string | null;
  columns: GridColumn[];
  rows: GridRow[];
}

export function getGrid(
  runId: string,
  sheet: string,
  window: { r1?: number; r2?: number; c1?: number; c2?: number } = {},
): Promise<GridWindow> {
  return apiGet<GridWindow>(`/runs/${runId}/grid${qs({ sheet, ...window })}`);
}
