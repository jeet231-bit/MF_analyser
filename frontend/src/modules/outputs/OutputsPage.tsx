import { useState } from "react";
import { runExportUrl } from "@/api/exports";
import { getGrid } from "@/api/runs";
import { getOutputs, type OutputSheet } from "@/api/views";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button, Card, EmptyState, ExportMenu, GridTable, Pill, SeriesChart, StatTile } from "@/components";
import { formatCell, formatCount, formatDelta } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { LineagePanel, type LineageTarget } from "@/modules/lineage/LineagePanel";
import { RulesPanel } from "@/modules/overview/RulesPanel";
import type { RunSession } from "@/modules/runs/useRunSession";

export interface OutputsPageProps {
  version: WorkbookVersion;
  session: RunSession;
  runId: string | null;
}

/**
 * The research result as a report page: one section per output sheet in display order, headline
 * metrics with deltas under a what-if, the ranked table, the rules that produced it, and a chart
 * only where the data is a series.
 */
export function OutputsPage({ version, session, runId }: OutputsPageProps) {
  const summary = useAsync(() => (runId ? getOutputs(version.id, runId) : Promise.reject(new Error("no run"))), [version.id, runId]);
  const [target, setTarget] = useState<LineageTarget | null>(null);

  if (!runId) {
    return <EmptyState title="No baseline run yet" description="Validate this version to produce the baseline run that outputs are read from." />;
  }
  if (summary.status === "error") {
    return (
      <EmptyState
        tone="error"
        title="Could not load outputs"
        description={summary.error}
        action={<Button onClick={summary.reload}>Retry</Button>}
      />
    );
  }
  if (summary.status === "loading" && !summary.data) {
    return (
      <div aria-busy="true" className="space-y-2">
        <div className="h-8 w-56 animate-pulse rounded-md bg-surface" />
        <div className="grid gap-2 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-md border border-hairline bg-surface" />
          ))}
        </div>
      </div>
    );
  }
  const data = summary.data!;
  const whatIf = data.baseline_run_id !== null;
  const changed = data.sheets.reduce((n, s) => n + s.changed_cells, 0);

  return (
    <div className="space-y-4 pb-16">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
        <h1 className="font-heading text-xl font-semibold text-ink">Outputs</h1>
        <p className="text-sm text-muted">
          {whatIf ? (
            <>
              What-if run with {Object.keys(session.activeRun?.overrides ?? {}).length} override(s): {formatCount(changed)} output cells changed
              against the baseline.
            </>
          ) : (
            <>Baseline results of the active version. Change an input and run the analysis to see deltas here.</>
          )}
        </p>
        </div>
        <ExportMenu
          items={[
            { label: "Excel — output sheets", hint: "Cover sheet + every output sheet, values in place", url: runExportUrl(runId, "xlsx") },
            { label: "Excel — all sheets", hint: "Every in-scope sheet; runs in the background", url: runExportUrl(runId, "xlsx", { scope: "all" }) },
            { label: "Excel — all sheets with formulas", hint: "Adds a formulas tab-set for audit", url: runExportUrl(runId, "xlsx", { scope: "all", formulas: true }) },
            { label: "PDF report", hint: "Cover, metrics, summaries, rules, changelog", url: runExportUrl(runId, "pdf") },
          ]}
        />
      </header>
      {data.sheets.length === 0 && <EmptyState title="No output sheets" description="Mark a sheet as output on the overview, or list it in dashboard.config.json." />}
      {data.sheets.map((sheet) => (
        <OutputSection key={sheet.sheet} sheet={sheet} runId={runId} whatIf={whatIf} onExplain={(s, cell) => setTarget({ sheet: s, cell })} />
      ))}
      <LineagePanel versionId={version.id} runId={runId} target={target} onClose={() => setTarget(null)} />
    </div>
  );
}

function OutputSection({
  sheet,
  runId,
  whatIf,
  onExplain,
}: {
  sheet: OutputSheet;
  runId: string;
  whatIf: boolean;
  onExplain: (sheet: string, cell: string) => void;
}) {
  const settings = useFormat();
  const [window, setWindow] = useState<{ r1: number; r2: number } | null>(null);
  const [changedOnly, setChangedOnly] = useState(false);
  const hasTable = sheet.blocks.some((b) => b.kind === "table");
  const grid = useAsync(
    () => (hasTable ? getGrid(runId, sheet.sheet, window ? { r1: window.r1, r2: window.r2 } : {}) : Promise.resolve(null)),
    [runId, sheet.sheet, hasTable, window?.r1, window?.r2],
  );

  return (
    <section aria-labelledby={`output-${sheet.sheet}`} className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-hairline pb-1">
        <h2 id={`output-${sheet.sheet}`} className="font-heading text-lg font-semibold text-ink">
          {sheet.sheet}
        </h2>
        <span className="flex items-center gap-2 text-xs text-muted">
          <Pill>{sheet.role_source === "heuristic" ? "output (inferred)" : `output (${sheet.role_source})`}</Pill>
          {whatIf && <span className="tabular">{formatCount(sheet.changed_cells, settings.grouping)} cells changed</span>}
        </span>
      </div>
      {sheet.metrics.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {sheet.metrics.map((m) => {
            const delta = whatIf && m.delta !== null ? formatDelta(m.delta, settings) : null;
            return (
              <button
                key={m.address}
                type="button"
                onClick={() => onExplain(sheet.sheet, m.address)}
                className="text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                aria-label={`Explain ${m.label ?? m.address}`}
              >
                <StatTile
                  label={m.label ?? m.address}
                  value={formatCell(m.value, m.format, settings, m.type) || "—"}
                  delta={delta && m.delta !== null ? { value: m.delta, direction: delta.direction, label: "vs baseline" } : undefined}
                  hint={whatIf && m.delta === null ? "unchanged" : m.address}
                />
              </button>
            );
          })}
        </div>
      )}
      {sheet.series && (
        <Card title="Series">
          <div className="overflow-x-auto">
            <SeriesChart series={sheet.series} />
          </div>
        </Card>
      )}
      {hasTable && (
        <Card
          title="Results"
          action={
            <span className="flex items-center gap-3">
              {whatIf && (
                <label className="flex items-center gap-1 text-xs text-muted">
                  <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
                  changed rows only
                </label>
              )}
              {grid.data && (
                <ExportMenu
                  label="Export table"
                  items={[
                    {
                      label: "CSV — this window",
                      hint: `rows ${grid.data.r1}–${grid.data.r2}, as shown`,
                      url: runExportUrl(runId, "csv", { sheet: sheet.sheet, window: windowA1(grid.data) }),
                    },
                    { label: "Excel — this sheet", hint: "Whole sheet, values in place", url: runExportUrl(runId, "xlsx", { scope: "sheet", sheet: sheet.sheet }) },
                  ]}
                />
              )}
            </span>
          }
        >
          {grid.status === "error" ? (
            <EmptyState tone="error" title="Could not load the table" description={grid.error} action={<Button onClick={grid.reload}>Retry</Button>} />
          ) : grid.data ? (
            <GridTable
              grid={grid.data}
              loading={grid.status === "loading"}
              onWindow={setWindow}
              onCellClick={(s, address) => onExplain(s, address)}
              changedOnly={changedOnly}
            />
          ) : (
            <div aria-busy="true" className="h-40 animate-pulse rounded-md bg-surface-lifted" />
          )}
        </Card>
      )}
      {sheet.rules.length > 0 && (
        <Card title="How these numbers are decided">
          <RulesPanel rules={sheet.rules} sheetOrder={[sheet.sheet]} />
        </Card>
      )}
    </section>
  );
}

function windowA1(g: { r1: number; r2: number; c1: number; c2: number; columns: { letter: string }[] }): string {
  const first = g.columns[0]?.letter ?? "A";
  const last = g.columns[g.columns.length - 1]?.letter ?? first;
  return `${first}${g.r1}:${last}${g.r2}`;
}
