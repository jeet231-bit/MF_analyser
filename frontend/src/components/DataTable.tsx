import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { formatNumber, type Grouping } from "@/lib/format";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Right-aligned, tabular figures; numbers are formatted with the table's grouping. */
  numeric?: boolean;
  decimals?: number;
  width?: string;
  render?: (row: T) => ReactNode;
  value?: (row: T) => unknown;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  grouping?: Grouping;
  maxHeight?: string;
  emptyMessage?: string;
  dense?: boolean;
  className?: string;
}

/** Sticky header, hairline rows, right-aligned tabular numerics. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  grouping = "indian",
  maxHeight = "32rem",
  emptyMessage = "Nothing to show.",
  dense = false,
  className,
}: DataTableProps<T>) {
  const cell = (col: Column<T>, row: T): ReactNode => {
    if (col.render) return col.render(row);
    const raw = col.value ? col.value(row) : (row as Record<string, unknown>)[col.key];
    if (col.numeric && typeof raw === "number") return formatNumber(raw, { grouping, decimals: col.decimals ?? 0 });
    if (raw === null || raw === undefined) return <span className="text-muted">—</span>;
    return String(raw);
  };

  return (
    <div className={cn("overflow-auto rounded-lg glass", className)} style={{ maxHeight }}>
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-surface-lifted">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                style={col.width ? { width: col.width } : undefined}
                className={cn(
                  "border-b border-hairline px-2 py-1.5 text-left font-heading text-xs font-medium text-muted",
                  col.numeric && "text-right",
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-2 py-4 text-center text-sm text-muted">
                {emptyMessage}
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-hairline last:border-b-0 hover:bg-surface-lifted">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "px-2 align-top text-ink",
                    dense ? "py-1" : "py-1.5",
                    col.numeric && "tabular text-right",
                  )}
                >
                  {cell(col, row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
