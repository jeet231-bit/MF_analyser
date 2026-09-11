import { apiGet, apiSend } from "./client";
import type { WorkbookVersion } from "./workbooks";

export type ValidationStatus = "passed" | "passed_with_warnings" | "failed";
export type MismatchClass = "precision" | "semantics" | "data";
export type AnomalyKind = "fragmentation" | "own_row" | "duplicate_keys" | "stale";

export interface Totals {
  checked: number;
  matched: number;
  mismatched: number;
  skipped_unsupported: number;
  skipped_stale: number;
}

export interface SheetCoverage {
  sheet: string;
  formula_cells: number;
  checked: number;
  matched: number;
  mismatched: number;
  skipped_unsupported: number;
  skipped_stale: number;
}

export interface Mismatch {
  sheet: string;
  cell: string;
  template_id: number | null;
  formula: string | null;
  excel: unknown;
  engine: unknown;
  delta: number | null;
  classification: MismatchClass;
}

export interface UnsupportedTemplate {
  function: string;
  sheet: string;
  cell: string;
  cells: number;
}

export interface Anomaly {
  id: number;
  kind: AnomalyKind;
  sheet: string;
  location: string;
  title: string;
  explanation: string;
  detail: Record<string, unknown>;
}

export interface ValidationReport {
  id: string;
  version_id: string;
  run_id: string | null;
  created_at: string;
  status: ValidationStatus;
  policy: { significant_digits: number; max_mismatch_ratio: number; max_precision_ratio: number };
  totals: Totals;
  by_sheet: SheetCoverage[];
  mismatches: Mismatch[];
  mismatches_truncated: boolean;
  unsupported: UnsupportedTemplate[];
  anomalies: Anomaly[];
  anomaly_counts: Partial<Record<AnomalyKind, number>>;
  reasons: string[];
  seconds: number;
}

export function getValidation(versionId: string): Promise<ValidationReport> {
  return apiGet<ValidationReport>(`/workbooks/${versionId}/validation`);
}

export function runValidation(versionId: string): Promise<ValidationReport> {
  return apiSend<ValidationReport>("POST", `/workbooks/${versionId}/validate`);
}

export function activateVersion(versionId: string, overrideReason?: string): Promise<WorkbookVersion> {
  return apiSend<WorkbookVersion>("POST", `/workbooks/${versionId}/activate`, {
    override_reason: overrideReason ?? null,
  });
}

export const ANOMALY_LABELS: Record<AnomalyKind, string> = {
  fragmentation: "Pattern breaks",
  own_row: "Rows reading other rows",
  duplicate_keys: "Duplicate lookup keys",
  stale: "Missing cached values",
};

export function anomalyTotal(counts: Partial<Record<AnomalyKind, number>> | undefined): number {
  if (!counts) return 0;
  return Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
}
