import { useState, type ReactNode } from "react";
import type { CellValue, GridCell, GridWindow } from "@/api/runs";
import { cn } from "@/lib/cn";
import { formatCell, formatCount, formatDelta } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { Button } from "./Button";

export interface GridTableProps {
  grid: GridWindow;
  /** Called with a window request when the user pages or jumps. */
  onWindow?: (window: { r1: number; r2: number }) => void;
  /** Computed cell clicked: open lineage. */
  onCellClick?: (sheet: string, address: string, cell: GridCell) => void;
  /** Input cell edited (editable grids only). */
  onCellEdit?: (sheet: string, address: string, cell: GridCell, value: CellValue | null) => void;
  /** "Sheet!A1" -> draft value, so edited-but-not-run cells show as pending. */
  draft?: Map<string, { value: CellValue }>;
  /** Show only rows with at least one cell whose value differs from the baseline. */
  changedOnly?: boolean;
  loading?: boolean;
  maxHeight?: string;
  caption?: ReactNode;
}

/**
 * Dense windowed grid that mirrors a sheet: column labels over column letters, row labels, tabular
 * numerics, and markers for formulas, overrides and baseline deltas. Paging is explicit.
 */
export function GridTable({
  grid,
  onWindow,
  onCellClick,
  onCellEdit,
  draft,
  changedOnly = false,
  loading = false,
  maxHeight = "34rem",
  caption,
}: GridTableProps) {
  const settings = useFormat();
  const [jump, setJump] = useState("");
  const pageSize = Math.max(1, grid.r2 - grid.r1 + 1);
  const bodyRows = Math.max(0, grid.total_rows - grid.body_start + 1);
  const rows = changedOnly ? grid.rows.filter((r) => r.cells.some((c) => c && "b" in c)) : grid.rows;

  const page = (dir: -1 | 1) => {
    const r1 = Math.max(grid.body_start, grid.r1 + dir * pageSize);
    onWindow?.({ r1, r2: r1 + pageSize - 1 });
  };
  const jumpTo = () => {
    const n = Number(jump);
    if (!Number.isFinite(n) || n < 1) return;
    const r1 = Math.min(Math.max(grid.body_start, Math.floor(n)), Math.max(grid.body_start, grid.total_rows));
    onWindow?.({ r1, r2: r1 + pageSize - 1 });
  };

  return (
    <div className="space-y-2">
      {onWindow && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="tabular">
            rows {formatCount(grid.r1, settings.grouping)}–{formatCount(grid.r2, settings.grouping)} of{" "}
            {formatCount(grid.total_rows, settings.grouping)}
            {bodyRows > 0 && grid.body_start > 1 ? ` (body from row ${grid.body_start})` : ""}
          </span>
          <Button size="sm" onClick={() => page(-1)} disabled={loading || grid.r1 <= grid.body_start}>
            Previous
          </Button>
          <Button size="sm" onClick={() => page(1)} disabled={loading || grid.r2 >= grid.total_rows}>
            Next
          </Button>
          <label className="flex items-center gap-1">
            <span>Go to row</span>
            <input
              type="number"
              min={1}
              value={jump}
              onChange={(e) => setJump(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && jumpTo()}
              aria-label="Go to row"
              className="tabular w-20 rounded-sm border border-hairline bg-surface px-1 py-0.5 text-xs text-ink"
            />
          </label>
          {caption}
        </div>
      )}
      <div
        className={cn("overflow-auto rounded-md border border-hairline", loading && "opacity-60")}
        style={{ maxHeight }}
        aria-busy={loading || undefined}
      >
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-surface-lifted">
            <tr>
              <th scope="col" className="border-b border-hairline px-2 py-1 text-left font-heading font-medium text-muted">
                {grid.row_label_col ? "" : "Row"}
              </th>
              {grid.columns.map((col) => (
                <th
                  key={col.col}
                  scope="col"
                  className={cn(
                    "border-b border-hairline px-2 py-1 text-left align-bottom font-heading font-medium text-muted",
                    isNumericFormat(col.format) && "text-right",
                  )}
                  title={`${col.letter} · ${col.kind}`}
                >
                  <div className="max-w-[12rem] truncate">{col.label ?? col.letter}</div>
                  <div className="text-[10px] font-normal text-muted/80">{col.letter}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={grid.columns.length + 1} className="px-2 py-4 text-center text-muted">
                  {changedOnly ? "No changed cells in this window." : "Nothing in this window."}
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.row} className="border-b border-hairline last:border-b-0 hover:bg-surface-lifted">
                <th scope="row" className="tabular whitespace-nowrap px-2 py-0.5 text-left font-normal text-muted">
                  {row.label ? <span className="text-ink">{row.label}</span> : row.row}
                  {row.label && <span className="ml-1 text-[10px]">{row.row}</span>}
                </th>
                {row.cells.map((cell, i) => {
                  const col = grid.columns[i];
                  const address = `${col.letter}${row.row}`;
                  const ref = `${grid.sheet}!${address}`;
                  const pending = draft?.get(ref);
                  return (
                    <td
                      key={col.col}
                      className={cn(
                        "px-2 py-0.5 align-top",
                        isNumericFormat(col.format) && "tabular text-right",
                        cell?.f && onCellClick && "cursor-pointer hover:text-accent",
                        cell?.o && "bg-accent-soft",
                        pending && "bg-accent-soft outline outline-1 outline-accent/40",
                      )}
                      onClick={cell?.f && onCellClick ? () => onCellClick(grid.sheet, address, cell) : undefined}
                      title={cell?.f ? `${address} · formula` : cell?.o ? `${address} · override` : address}
                    >
                      {cell === null ? (
                        ""
                      ) : onCellEdit && !cell.f && col.kind === "input" ? (
                        <input
                          type="text"
                          aria-label={`${grid.sheet}!${address}`}
                          defaultValue={String(pending ? (pending.value ?? "") : (cell.v ?? ""))}
                          onBlur={(e) => {
                            const parsed = parseLike(e.target.value, cell);
                            if (parsed !== undefined) onCellEdit(grid.sheet, address, cell, parsed);
                          }}
                          className="w-full min-w-[4rem] bg-transparent text-inherit focus:outline-none"
                        />
                      ) : (
                        <CellText cell={cell} format={col.format} />
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CellText({ cell, format }: { cell: GridCell; format: GridWindow["columns"][number]["format"] }) {
  const settings = useFormat();
  const text = formatCell(cell.v, format, settings, cell.t);
  if (!("b" in cell) || typeof cell.v !== "number" || typeof cell.b !== "number") {
    return (
      <span className={cn(cell.t === "error" && "text-negative")}>
        {text}
        {"b" in cell && <span className="ml-1 text-[10px] text-muted">was {formatCell(cell.b ?? null, format, settings)}</span>}
      </span>
    );
  }
  const delta = formatDelta(cell.v - cell.b, settings);
  return (
    <span>
      {text}
      <span className={cn("ml-1 text-[10px]", delta.direction === "up" ? "text-positive" : delta.direction === "down" ? "text-negative" : "text-muted")}>
        {delta.text}
      </span>
    </span>
  );
}

function isNumericFormat(format: string): boolean {
  return format === "number" || format === "integer" || format === "percent" || format === "general";
}

function parseLike(raw: string, cell: GridCell): CellValue | undefined {
  const s = raw.trim();
  if (s === "") return null;
  if (cell.t === "number" || cell.t === "date") {
    const n = Number(s.replace(/,/g, ""));
    return Number.isFinite(n) ? n : undefined;
  }
  if (cell.t === "bool") return s.toUpperCase() === "TRUE";
  return s;
}
