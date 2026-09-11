import { apiGet } from "./client";

export type LogicKind =
  | "template_added"
  | "template_removed"
  | "template_changed"
  | "rule_added"
  | "rule_removed"
  | "name_added"
  | "name_removed"
  | "name_changed";
export type DataKind = "rows_added" | "rows_removed" | "values_changed" | "inputs_resized";
export type StructuralKind =
  | "sheet_added"
  | "sheet_removed"
  | "sheet_renamed"
  | "role_changed"
  | "blocks_merged"
  | "blocks_split"
  | "anomaly_new"
  | "anomaly_resolved";

export interface AffectedOutput {
  block_id: number;
  sheet: string;
  range: string;
  label: string | null;
  cells: number;
}

export interface LogicChange {
  id: number;
  kind: LogicKind;
  sheet: string;
  location: string;
  cells: number;
  title: string;
  description: string;
  detail: Record<string, unknown>;
  affected_outputs: AffectedOutput[];
  affected_output_count: number;
}

export interface DataChange {
  id: number;
  kind: DataKind;
  sheet: string;
  count: number;
  description: string;
  detail: Record<string, unknown>;
}

export interface StructuralChange {
  id: number;
  kind: StructuralKind;
  sheet: string;
  description: string;
  detail: Record<string, unknown>;
}

export interface DiffSummary {
  logic_changes: number;
  data_changes: number;
  structural_changes: number;
  outputs_total: number;
  outputs_affected_by_logic: number;
  outputs_affected_by_data: number;
  logic_cells: number;
}

export interface DiffReport {
  base_version_id: string;
  target_version_id: string;
  created_at: string;
  headline: string;
  summary: DiffSummary;
  logic: LogicChange[];
  data: DataChange[];
  structural: StructuralChange[];
  sheet_map: Record<string, string>;
}

export function getDiff(baseId: string, targetId: string): Promise<DiffReport> {
  return apiGet<DiffReport>(`/workbooks/${baseId}/diff/${targetId}`);
}

export const LOGIC_LABELS: Record<LogicKind, string> = {
  template_added: "New formula",
  template_removed: "Formula removed",
  template_changed: "Formula changed",
  rule_added: "Rule added",
  rule_removed: "Rule removed",
  name_added: "Name added",
  name_removed: "Name removed",
  name_changed: "Name changed",
};

export const STRUCTURAL_LABELS: Record<StructuralKind, string> = {
  sheet_added: "Sheet added",
  sheet_removed: "Sheet removed",
  sheet_renamed: "Sheet renamed",
  role_changed: "Role changed",
  blocks_merged: "Blocks merged",
  blocks_split: "Blocks split",
  anomaly_new: "New anomaly",
  anomaly_resolved: "Anomaly resolved",
};
