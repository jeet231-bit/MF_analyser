import type { PivotQuery, PivotSummary, Scope } from "@/api/research";

/** Where the user is on the Pivots screen; kept in the history entry so Back restores it. */
export interface PivotLocation {
  id: string | null;
  /** Undefined means Excel's saved layout (with the global scope pre-filled). */
  query?: PivotQuery;
}

export const AGGREGATIONS: { value: string; label: string }[] = [
  { value: "average", label: "Average" },
  { value: "sum", label: "Sum" },
  { value: "count", label: "Count" },
  { value: "countNums", label: "Count numbers" },
  { value: "min", label: "Min" },
  { value: "max", label: "Max" },
];

export const aggLabel = (agg: string) => AGGREGATIONS.find((a) => a.value === agg)?.label ?? agg;

/** Excel's layout, with the global scope pre-filling the filter fields the config maps. */
export function defaultQuery(pivot: PivotSummary, scope: Scope | undefined, scopeFields: Record<string, string>): PivotQuery {
  const filters: Record<string, string[]> = { ...pivot.savedFilters };
  const names = new Set(pivot.fields.map((f) => f.name));
  if (scope) {
    for (const [dim, field] of Object.entries(scopeFields)) {
      const value = scope.dims[dim];
      if (value && names.has(field)) filters[field] = [value];
    }
  }
  return { filters, rows: [...pivot.layout.rows], cols: [...pivot.layout.cols], values: pivot.layout.values.map((v) => ({ ...v })) };
}
