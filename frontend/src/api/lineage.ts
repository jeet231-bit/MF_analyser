import { apiGet, qs } from "./client";
import type { CellValue } from "./runs";

export interface LineageCell {
  address: string;
  value?: CellValue;
  type?: string;
}

export interface LineageRange {
  sheet: string;
  range: string;
  count: number;
  cells?: LineageCell[];
  truncated?: boolean;
  node?: LineageNode;
}

export interface LineageNode {
  sheet: string;
  cell: string;
  kind: "formula" | "input" | "external" | "static";
  formula?: string;
  template_id?: number;
  value?: CellValue;
  type?: string;
  reads?: LineageRange[];
  /** Which IF / IFERROR branches the formula took, in words; absent when nothing to narrate. */
  explanation?: string[];
  /** The business rule this formula's template encodes. */
  rule?: string;
}

export function getLineage(
  versionId: string,
  sheet: string,
  cell: string,
  options: { runId?: string | null; depth?: number } = {},
): Promise<LineageNode> {
  const ref = encodeURIComponent(`${sheet}!${cell}`);
  return apiGet<LineageNode>(
    `/workbooks/${versionId}/lineage/${ref}${qs({ run_id: options.runId ?? undefined, depth: options.depth })}`,
  );
}
