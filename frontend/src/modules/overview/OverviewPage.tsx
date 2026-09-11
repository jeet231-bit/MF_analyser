import { useState } from "react";
import { getRules, getSheetGraph } from "@/api/model";
import { interpretWorkbook, type LogicModel, type WorkbookVersion } from "@/api/workbooks";
import { Button, Card, EmptyState, Pill, StatTile } from "@/components";
import { formatBytes, formatCount, formatSeconds, formatTimestamp } from "@/lib/format";
import { describeError, useAsync, type AsyncState } from "@/lib/useAsync";
import { CycleChip } from "./CycleChip";
import { RulesPanel } from "./RulesPanel";
import { SheetFlow } from "./SheetFlow";
import { SheetRolesPanel } from "./SheetRolesPanel";

export interface OverviewPageProps {
  displayName: string | null;
  version: WorkbookVersion;
  model: AsyncState<LogicModel> & { reload: () => void };
  onBusy: (busy: boolean, label?: string) => void;
  onVersionChanged: () => void;
}

export function OverviewPage({ displayName, version, model, onBusy, onVersionChanged }: OverviewPageProps) {
  const graph = useAsync(() => getSheetGraph(version.id), [version.id, model.data?.created_at]);
  const rules = useAsync(() => getRules(version.id), [version.id, model.data?.created_at]);
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);
  const [interpretError, setInterpretError] = useState<string | null>(null);

  const interpret = async () => {
    setInterpretError(null);
    onBusy(true, "Interpreting workbook");
    try {
      await interpretWorkbook(version.id);
      onVersionChanged();
      model.reload();
    } catch (err) {
      setInterpretError(describeError(err));
    } finally {
      onBusy(false);
    }
  };

  const header = (
    <header className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h1 className="text-xl font-semibold text-ink">{displayName ?? version.filename}</h1>
        <p className="mt-0.5 text-sm text-muted">
          {version.filename} · uploaded {formatTimestamp(version.uploaded_at)} · {formatBytes(version.size_bytes)}
          {version.summary && ` · ${formatCount(version.summary.sheets)} sheets, ${formatCount(version.summary.formula_cells)} formulas`}
        </p>
      </div>
      {model.status === "ready" && (
        <div className="flex items-center gap-2">
          <CycleChip descriptions={model.data.cycle_descriptions} />
          <Pill tone="neutral">interpreted in {formatSeconds(model.data.summary.seconds)}</Pill>
        </div>
      )}
    </header>
  );

  if (model.status === "error" && model.notFound) {
    return (
      <div className="space-y-4">
        {header}
        <EmptyState
          title="This version has not been interpreted yet"
          description="Interpretation reads every formula, dedupes them into templates and builds the sheet dependency graph. It takes about half a minute for the master workbook."
          action={
            <div className="space-y-1">
              <Button variant="primary" onClick={() => void interpret()}>
                Interpret workbook
              </Button>
              {interpretError && (
                <p role="alert" className="text-xs text-negative">
                  {interpretError}
                </p>
              )}
            </div>
          }
        />
      </div>
    );
  }

  if (model.status === "error") {
    return (
      <div className="space-y-4">
        {header}
        <EmptyState
          tone="error"
          title="Could not load the logic model"
          description={model.error}
          action={<Button onClick={model.reload}>Retry</Button>}
        />
      </div>
    );
  }

  if (model.status === "loading" && !model.data) {
    return (
      <div className="space-y-4" aria-busy="true">
        {header}
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-md border border-hairline bg-surface" />
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-md border border-hairline bg-surface" />
      </div>
    );
  }

  const m = model.data!;
  const s = m.summary;
  const inScope = m.sheets.filter((sh) => sh.in_scope);

  return (
    <div className="space-y-4">
      {header}

      <section className="grid grid-cols-2 gap-2 md:grid-cols-5" aria-label="Model summary">
        <StatTile label="Sheets in scope" value={formatCount(s.sheets_in_scope)} hint={`of ${formatCount(m.sheets.length)} in the workbook`} />
        <StatTile label="Formula templates" value={formatCount(s.templates)} hint={`from ${formatCount(s.formula_cells)} formula cells`} />
        <StatTile label="Formula blocks" value={formatCount(s.formula_blocks)} hint={`${formatCount(s.self_dependent_blocks)} self-referencing`} />
        <StatTile label="Input blocks" value={formatCount(s.input_blocks)} hint={`${formatCount(s.input_cells)} input cells`} />
        <StatTile label="Business rules" value={formatCount(s.rules)} hint={s.parse_errors ? `${s.parse_errors} parse errors` : "no parse errors"} />
      </section>

      <Card
        title="Sheet flow"
        action={
          selectedSheet && (
            <button type="button" className="font-heading text-xs text-accent" onClick={() => setSelectedSheet(null)}>
              clear highlight
            </button>
          )
        }
      >
        {graph.status === "ready" && graph.data.nodes.length > 0 && (
          <SheetFlow graph={graph.data} selected={selectedSheet} onSelect={setSelectedSheet} />
        )}
        {graph.status === "ready" && graph.data.nodes.length === 0 && (
          <EmptyState title="No sheets in scope" description="Interpret with at least one sheet to see the flow." />
        )}
        {graph.status === "loading" && <div className="h-40 animate-pulse rounded-md bg-surface-lifted" />}
        {graph.status === "error" && (
          <EmptyState tone="error" title="Could not load the sheet graph" description={graph.error} action={<Button onClick={graph.reload}>Retry</Button>} />
        )}
      </Card>

      <Card title="Sheet roles">
        <SheetRolesPanel versionId={version.id} sheets={inScope} onChanged={model.reload} />
      </Card>

      <Card title="Business rules">
        {rules.status === "ready" && rules.data.length > 0 && (
          <RulesPanel rules={rules.data} sheetOrder={m.sheets.map((sh) => sh.name)} />
        )}
        {rules.status === "ready" && rules.data.length === 0 && (
          <EmptyState title="No rules extracted" description="No IF, threshold, lookup or IFERROR patterns were found in the in-scope formulas." />
        )}
        {rules.status === "loading" && <div className="h-24 animate-pulse rounded-md bg-surface-lifted" />}
        {rules.status === "error" && (
          <EmptyState tone="error" title="Could not load rules" description={rules.error} action={<Button onClick={rules.reload}>Retry</Button>} />
        )}
      </Card>
    </div>
  );
}
