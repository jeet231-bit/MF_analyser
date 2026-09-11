import { useState } from "react";
import { runExportUrl } from "@/api/exports";
import { getGrid } from "@/api/runs";
import type { LogicModel, WorkbookVersion } from "@/api/workbooks";
import { Button, Card, EmptyState, ExportMenu, GridTable, Pill, Select } from "@/components";
import { formatCount } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { LineagePanel, type LineageTarget } from "@/modules/lineage/LineagePanel";
import type { RunSession } from "@/modules/runs/useRunSession";

export interface CalculationsPageProps {
  version: WorkbookVersion;
  model: LogicModel;
  sheets: string[];
  title: string;
  session: RunSession;
  runId: string | null;
}

/** Each calculation sheet as the run computed it, mirroring the sheet's own layout. */
export function CalculationsPage({ version, model, sheets, title, session, runId }: CalculationsPageProps) {
  const [sheet, setSheet] = useState<string>(sheets[0] ?? "");
  const [window, setWindow] = useState<{ r1: number; r2: number } | null>(null);
  const [changedOnly, setChangedOnly] = useState(false);
  const [target, setTarget] = useState<LineageTarget | null>(null);
  const settings = useFormat();
  const current = sheets.includes(sheet) ? sheet : (sheets[0] ?? "");
  const info = model.sheets.find((s) => s.name === current);

  const grid = useAsync(
    () =>
      runId && current
        ? getGrid(runId, current, window ? { r1: window.r1, r2: window.r2 } : {})
        : Promise.reject(new Error("no run")),
    [runId, current, window?.r1, window?.r2],
  );

  if (sheets.length === 0) {
    return <EmptyState title={`No ${title.toLowerCase()} sheets`} description="No in-scope sheet has this role. Roles can be changed on the overview." />;
  }
  if (!runId) {
    return (
      <EmptyState
        title="No baseline run yet"
        description="Validate this version (Validation module) to produce the baseline run that these views read."
      />
    );
  }

  return (
    <div className="space-y-3 pb-16">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-heading text-xl font-semibold text-ink">{title}</h1>
          <p className="text-sm text-muted">
            {session.activeRun ? "Values from the current what-if run; changed cells show their baseline." : "Baseline values."} Click any
            computed cell to trace it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="calc-sheet" className="text-xs text-muted">
            Sheet
          </label>
          <Select
            id="calc-sheet"
            value={current}
            onChange={(e) => {
              setSheet(e.target.value);
              setWindow(null);
            }}
          >
            {sheets.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          {session.activeRun && (
            <label className="flex items-center gap-1 text-xs text-muted">
              <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
              changed rows only
            </label>
          )}
          <ExportMenu
            items={[
              ...(grid.data
                ? [
                    {
                      label: "CSV — this window",
                      hint: `${current} rows ${grid.data.r1}–${grid.data.r2}, as shown`,
                      url: runExportUrl(runId, "csv", {
                        sheet: current,
                        window: `${grid.data.columns[0]?.letter ?? "A"}${grid.data.r1}:${grid.data.columns[grid.data.columns.length - 1]?.letter ?? "A"}${grid.data.r2}`,
                      }),
                    },
                  ]
                : []),
              { label: "Excel — this sheet", hint: "Whole sheet, values in place", url: runExportUrl(runId, "xlsx", { scope: "sheet", sheet: current }) },
              { label: "Excel — all sheets", hint: "Every in-scope sheet; runs in the background", url: runExportUrl(runId, "xlsx", { scope: "all" }) },
            ]}
          />
        </div>
      </header>
      <Card
        title={current}
        action={
          info && (
            <span className="flex items-center gap-2 text-xs text-muted">
              <Pill>{info.role}</Pill>
              <span className="tabular">{formatCount(info.formula_cells, settings.grouping)} formula cells</span>
            </span>
          )
        }
      >
        {grid.status === "error" ? (
          <EmptyState tone="error" title="Could not load this sheet" description={grid.error} action={<Button onClick={grid.reload}>Retry</Button>} />
        ) : grid.data ? (
          <GridTable
            grid={grid.data}
            loading={grid.status === "loading"}
            onWindow={setWindow}
            onCellClick={(s, address) => setTarget({ sheet: s, cell: address })}
            changedOnly={changedOnly}
          />
        ) : (
          <div aria-busy="true" className="h-40 animate-pulse rounded-md bg-surface-lifted" />
        )}
      </Card>
      <LineagePanel versionId={version.id} runId={runId} target={target} onClose={() => setTarget(null)} />
    </div>
  );
}
