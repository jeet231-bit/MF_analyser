import { useState } from "react";
import { getGrid, type CellValue, type GridCell } from "@/api/runs";
import { getInputs, type InputBlock, type InputSheet } from "@/api/views";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button, Card, EmptyState, GridTable, Pill, ValueEditor } from "@/components";
import { formatCount } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import type { RunSession } from "@/modules/runs/useRunSession";

export interface InputsPageProps {
  version: WorkbookVersion;
  session: RunSession;
  /** Run whose values to show (the active what-if, else the baseline id, else null). */
  runId: string | null;
}

/**
 * Every input block in scope, grouped by sheet and section. Small blocks are labelled parameter
 * controls; tables page through the grid. Edits accumulate in the session draft.
 */
export function InputsPage({ version, session, runId }: InputsPageProps) {
  const catalogue = useAsync(() => getInputs(version.id, runId), [version.id, runId]);
  const [sheet, setSheet] = useState<string | null>(null);
  const settings = useFormat();

  if (catalogue.status === "error") {
    return (
      <EmptyState
        tone="error"
        title={catalogue.notFound ? "This version has no logic model yet" : "Could not load inputs"}
        description={catalogue.error}
        action={<Button onClick={catalogue.reload}>Retry</Button>}
      />
    );
  }
  if (catalogue.status === "loading" && !catalogue.data) {
    return (
      <div aria-busy="true" className="space-y-2">
        <div className="h-8 w-56 animate-pulse rounded-md bg-surface" />
        <div className="h-40 animate-pulse rounded-md border border-hairline bg-surface" />
      </div>
    );
  }
  const sheets = catalogue.data?.sheets ?? [];
  if (sheets.length === 0) {
    return <EmptyState title="No inputs in scope" description="The logic model found no constant cells that formulas read." />;
  }
  // Sheets with the most numeric parameters first: they are the what-if levers.
  const ordered = [...sheets].sort((a, b) => leverCount(b) - leverCount(a));
  const current = ordered.find((s) => s.sheet === sheet) ?? ordered[0];
  const totalCells = sheets.reduce((n, s) => n + s.blocks.reduce((m, b) => m + b.cell_count, 0), 0);

  return (
    <div className="space-y-3 pb-16">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-heading text-xl font-semibold text-ink">Inputs</h1>
          <p className="text-sm text-muted">
            {formatCount(totalCells, settings.grouping)} input cells across {sheets.length} sheets. Edit a value to add it to the
            draft; nothing changes until you run the analysis.
          </p>
        </div>
      </header>
      <nav aria-label="Input sheets" className="flex flex-wrap gap-1">
        {ordered.map((s) => (
          <button
            key={s.sheet}
            type="button"
            aria-pressed={s.sheet === current.sheet}
            onClick={() => setSheet(s.sheet)}
            className={
              s.sheet === current.sheet
                ? "rounded-full border border-accent/40 bg-accent-soft px-2.5 py-0.5 font-heading text-xs font-medium text-accent"
                : "rounded-full border border-hairline px-2.5 py-0.5 font-heading text-xs font-medium text-ink hover:border-accent"
            }
          >
            {s.sheet}
            <span className="tabular ml-1 text-muted">{s.blocks.length}</span>
          </button>
        ))}
      </nav>
      <SheetInputs key={current.sheet} sheet={current} session={session} runId={runId} />
    </div>
  );
}

function isLever(type: string): boolean {
  return type === "number" || type === "date" || type === "bool";
}

function leverCount(s: InputSheet): number {
  return s.blocks
    .filter((b) => b.shape === "parameters" && b.editable)
    .reduce((n, b) => n + b.cells.filter((c) => isLever(c.type)).length, 0);
}

function SheetInputs({ sheet, session, runId }: { sheet: InputSheet; session: RunSession; runId: string | null }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className="font-heading text-sm font-semibold text-ink">{sheet.sheet}</span>
        <Pill>{sheet.role}</Pill>
        {sheet.role === "reference" && <span>reference data: editable, but usually left as the master has it</span>}
      </div>
      {sheet.blocks
        .filter((b) => b.shape === "parameters")
        .sort((a, b) => b.cells.filter((c) => isLever(c.type)).length - a.cells.filter((c) => isLever(c.type)).length)
        .map((block) => (
          <ParameterBlock key={block.id} block={block} session={session} />
        ))}
      {sheet.blocks
        .filter((b) => b.shape === "table")
        .map((block) => (
          <TableBlock key={block.id} block={block} session={session} runId={runId} />
        ))}
      {sheet.blocks.some((b) => b.shape === "labels") && (
        <details className="rounded-md border border-hairline bg-surface">
          <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-ink">
            Header labels read by lookups
            <span className="ml-2 text-xs font-normal text-muted">
              {sheet.blocks.filter((b) => b.shape === "labels").length} block(s) · editable, rarely changed
            </span>
          </summary>
          <div className="space-y-3 border-t border-hairline p-3">
            {sheet.blocks
              .filter((b) => b.shape === "labels")
              .map((block) => (
                <ParameterBlock key={block.id} block={block} session={session} />
              ))}
          </div>
        </details>
      )}
    </div>
  );
}

function ParameterBlock({ block, session }: { block: InputBlock; session: RunSession }) {
  const title = block.section ?? `${block.sheet} ${block.rect}`;
  const levers = block.cells.filter((c) => isLever(c.type));
  const texts = block.cells.filter((c) => !isLever(c.type));
  return (
    <Card title={title} action={<span className="tabular text-xs text-muted">{block.rect}</span>}>
      {!block.editable && <div className="mb-2 text-xs text-muted">External to the scope: values come from the workbook as uploaded.</div>}
      {levers.length > 0 && <CellEditors block={block} cells={levers} session={session} />}
      {texts.length > 0 &&
        (levers.length > 0 ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-muted">
              {texts.length} text label{texts.length === 1 ? "" : "s"} in this block
            </summary>
            <div className="mt-2">
              <CellEditors block={block} cells={texts} session={session} />
            </div>
          </details>
        ) : (
          <CellEditors block={block} cells={texts} session={session} />
        ))}
    </Card>
  );
}

function CellEditors({ block, cells, session }: { block: InputBlock; cells: InputBlock["cells"]; session: RunSession }) {
  return (
    <>
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        {cells.map((cell) => {
          const ref = `${block.sheet}!${cell.address}`;
          const draft = session.draft.get(ref);
          return (
            <div key={cell.address} className="space-y-0.5">
              <dt className="flex items-baseline justify-between text-xs text-muted">
                <label htmlFor={`input-${block.id}-${cell.address}`} className="truncate" title={cell.address}>
                  {cell.label ?? cell.address}
                </label>
                {cell.override && <Pill tone="accent" dot={false}>override</Pill>}
                {draft && <Pill tone="accent" dot={false}>pending</Pill>}
              </dt>
              <dd>
                <ValueEditor
                  id={`input-${block.id}-${cell.address}`}
                  label={cell.label ?? cell.address}
                  type={cell.type}
                  value={cell.value}
                  draft={draft?.value ?? null}
                  disabled={!block.editable}
                  onChange={(value) =>
                    session.setDraft(
                      ref,
                      value === null ? null : { value, type: cell.type, label: cell.label, sheet: block.sheet, address: cell.address },
                    )
                  }
                />
              </dd>
            </div>
          );
        })}
      </dl>
    </>
  );
}

function TableBlock({ block, session, runId }: { block: InputBlock; session: RunSession; runId: string | null }) {
  const [window, setWindow] = useState<{ r1: number; r2: number } | null>(null);
  const settings = useFormat();
  const grid = useAsync(
    () =>
      runId
        ? getGrid(runId, block.sheet, { r1: window?.r1 ?? block.r1, r2: window?.r2 ?? block.r1 + 49, c1: block.c1, c2: block.c2 })
        : Promise.reject(new Error("No run yet: validate the version to get a baseline.")),
    [runId, block.sheet, block.rect, window?.r1, window?.r2],
  );
  const title = block.section ?? `${block.sheet} ${block.rect}`;
  const onEdit = (sheet: string, address: string, cell: GridCell, value: CellValue | null) => {
    const ref = `${sheet}!${address}`;
    if (value === null || value === cell.v) session.setDraft(ref, null);
    else session.setDraft(ref, { value, type: cell.t, label: null, sheet, address });
  };
  return (
    <Card
      title={title}
      action={
        <span className="tabular text-xs text-muted">
          {block.rect} · {formatCount(block.cell_count, settings.grouping)} cells
        </span>
      }
    >
      {grid.status === "error" ? (
        <EmptyState tone="error" title="Could not load this table" description={grid.error} action={<Button onClick={grid.reload}>Retry</Button>} />
      ) : grid.data ? (
        <GridTable
          grid={grid.data}
          loading={grid.status === "loading"}
          onWindow={setWindow}
          onCellEdit={block.editable ? onEdit : undefined}
          draft={session.draft}
          maxHeight="24rem"
        />
      ) : (
        <div aria-busy="true" className="h-24 animate-pulse rounded-md bg-surface-lifted" />
      )}
    </Card>
  );
}
