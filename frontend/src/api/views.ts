import { apiGet, qs } from "./client";
import type { CellValue, ColumnFormat as CellFormat } from "./runs";
import type { BusinessRule, RoleSource, SheetRole } from "./workbooks";

export interface InputCell {
  address: string;
  label: string | null;
  value: CellValue;
  type: string;
  override: boolean;
}

export interface InputBlock {
  id: number;
  sheet: string;
  rect: string;
  r1: number;
  c1: number;
  r2: number;
  c2: number;
  cell_count: number;
  kind: "input" | "external";
  editable: boolean;
  shape: "parameters" | "labels" | "table";
  section: string | null;
  value_types: Record<string, number>;
  column_labels: (string | null)[];
  row_label_col: number | null;
  cells: InputCell[];
}

export interface InputSheet {
  sheet: string;
  role: SheetRole;
  role_source: RoleSource;
  blocks: InputBlock[];
}

export interface InputsCatalogue {
  run_id: string | null;
  sheets: InputSheet[];
}

export function getInputs(versionId: string, runId?: string | null): Promise<InputsCatalogue> {
  return apiGet<InputsCatalogue>(`/workbooks/${versionId}/inputs${qs({ run_id: runId ?? undefined })}`);
}

export interface Metric {
  address: string;
  label: string | null;
  value: CellValue;
  type: string;
  format: CellFormat;
  baseline: CellValue;
  delta: number | null;
}

export interface SeriesColumn {
  label: string;
  points: [string | number, number | null][];
}

export interface Series {
  x_label: string | null;
  x_type: "date" | "number";
  rows: number;
  columns: SeriesColumn[];
}

export interface OutputBlock {
  id: number;
  rect: string;
  cell_count: number;
  kind: "metric" | "table";
  labels: (string | null)[];
}

export interface OutputSheet {
  sheet: string;
  role: SheetRole;
  role_source: RoleSource;
  body_start: number;
  table_rect: string | null;
  blocks: OutputBlock[];
  metrics: Metric[];
  rules: BusinessRule[];
  series: Series | null;
  changed_cells: number;
}

export interface OutputsSummary {
  run_id: string;
  baseline_run_id: string | null;
  sheets: OutputSheet[];
}

export function getOutputs(versionId: string, runId?: string | null): Promise<OutputsSummary> {
  return apiGet<OutputsSummary>(`/workbooks/${versionId}/outputs${qs({ run_id: runId ?? undefined })}`);
}
