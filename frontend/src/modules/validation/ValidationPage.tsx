import { useState } from "react";
import {
  ANOMALY_LABELS,
  activateVersion,
  anomalyTotal,
  runValidation,
  type Anomaly,
  type AnomalyKind,
  type Mismatch,
  type SheetCoverage,
  type ValidationReport,
} from "@/api/validation";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button, Card, DataTable, EmptyState, Pill, StatTile, type Column } from "@/components";
import { formatCount, formatNumber, formatSeconds, formatTimestamp } from "@/lib/format";
import { describeError, type AsyncState } from "@/lib/useAsync";
import { validationPill } from "@/modules/shell/navigation";

export interface ValidationPageProps {
  version: WorkbookVersion;
  report: AsyncState<ValidationReport> & { reload: () => void };
  onBusy: (busy: boolean, label?: string) => void;
  onVersionChanged: () => void;
}

const classTone = { precision: "warning", semantics: "negative", data: "negative" } as const;
const KIND_ORDER: AnomalyKind[] = ["own_row", "fragmentation", "duplicate_keys", "stale"];

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return formatNumber(v, { decimals: Number.isInteger(v) ? 0 : 6 });
  if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
  return String(v);
}

export function ValidationPage({ version, report, onBusy, onVersionChanged }: ValidationPageProps) {
  const [error, setError] = useState<string | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [showOverride, setShowOverride] = useState(false);

  const validate = async () => {
    setError(null);
    onBusy(true, "Validating workbook");
    try {
      await runValidation(version.id);
      report.reload();
      onVersionChanged();
    } catch (err) {
      setError(describeError(err));
    } finally {
      onBusy(false);
    }
  };

  const activate = async (reason?: string) => {
    setError(null);
    onBusy(true, "Activating version");
    try {
      await activateVersion(version.id, reason);
      setShowOverride(false);
      setOverrideReason("");
      onVersionChanged();
    } catch (err) {
      setError(describeError(err));
    } finally {
      onBusy(false);
    }
  };

  const data = report.status === "ready" ? report.data : report.data;
  const isActive = version.status === "active";
  const failed = data?.status === "failed";

  const header = (
    <header className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h1 className="text-xl font-semibold text-ink">Validation</h1>
        <p className="mt-0.5 text-sm text-muted">
          {version.filename}
          {data && ` · validated ${formatTimestamp(data.created_at)} in ${formatSeconds(data.seconds)}`}
          {isActive && " · active version"}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {data && <Pill tone={validationPill[data.status].tone}>{validationPill[data.status].label}</Pill>}
        <Button onClick={() => void validate()}>{data ? "Re-run validation" : "Run validation"}</Button>
        {data && !isActive && (
          <Button
            variant="primary"
            onClick={() => (failed ? setShowOverride(true) : void activate())}
            aria-label={failed ? "Activate with override" : "Activate version"}
          >
            {failed ? "Activate anyway…" : "Activate version"}
          </Button>
        )}
      </div>
    </header>
  );

  return (
    <div className="space-y-4">
      {header}
      {error && (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      )}
      {showOverride && (
        <Card title="Override the validation gate">
          <p className="text-sm text-muted">
            The latest validation failed. Activating this version anyway is recorded with your reason.
          </p>
          <textarea
            aria-label="Override reason"
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            rows={2}
            className="mt-2 w-full rounded-sm border border-hairline bg-surface px-2 py-1 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <div className="mt-2 flex gap-2">
            <Button variant="primary" disabled={!overrideReason.trim()} onClick={() => void activate(overrideReason)}>
              Activate with this reason
            </Button>
            <Button variant="ghost" onClick={() => setShowOverride(false)}>
              Cancel
            </Button>
          </div>
        </Card>
      )}

      {report.status === "error" && report.notFound && !data && (
        <EmptyState
          title="This version has not been validated yet"
          description="Validation runs the engine with no overrides and compares every formula cell with the value Excel saved in the file. It also scans the workbook for structural anomalies."
          action={
            <Button variant="primary" onClick={() => void validate()}>
              Run validation
            </Button>
          }
        />
      )}
      {report.status === "error" && !report.notFound && (
        <EmptyState tone="error" title="Could not load the validation report" description={report.error} action={<Button onClick={report.reload}>Retry</Button>} />
      )}
      {report.status === "loading" && !data && (
        <div aria-busy="true" className="grid grid-cols-2 gap-2 md:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-md border border-hairline bg-surface" />
          ))}
        </div>
      )}
      {data && <Report data={data} />}
    </div>
  );
}

function Report({ data }: { data: ValidationReport }) {
  const t = data.totals;
  const skipped = t.skipped_unsupported + t.skipped_stale;
  const anomalies = anomalyTotal(data.anomaly_counts);
  const coverageColumns: Column<SheetCoverage>[] = [
    { key: "sheet", header: "Sheet", render: (s) => <span className="font-medium">{s.sheet}</span> },
    { key: "formula_cells", header: "Formula cells", numeric: true },
    { key: "checked", header: "Checked", numeric: true },
    { key: "matched", header: "Matched", numeric: true },
    {
      key: "mismatched",
      header: "Mismatched",
      numeric: true,
      render: (s) => <span className={s.mismatched ? "text-negative" : undefined}>{formatCount(s.mismatched)}</span>,
    },
    { key: "skipped", header: "Skipped", numeric: true, value: (s) => s.skipped_unsupported + s.skipped_stale },
  ];
  const mismatchColumns: Column<Mismatch>[] = [
    { key: "cell", header: "Cell", render: (m) => <span className="tabular font-medium">{`${m.sheet}!${m.cell}`}</span> },
    { key: "formula", header: "Formula", render: (m) => <span className="break-all text-xs text-muted">{m.formula ?? ""}</span> },
    { key: "excel", header: "Excel", numeric: true, render: (m) => renderValue(m.excel) },
    { key: "engine", header: "Engine", numeric: true, render: (m) => renderValue(m.engine) },
    { key: "delta", header: "Delta", numeric: true, render: (m) => (m.delta === null ? "—" : formatNumber(m.delta, { decimals: 6 })) },
    { key: "classification", header: "Class", render: (m) => <Pill tone={classTone[m.classification]}>{m.classification}</Pill> },
  ];

  return (
    <>
      {data.reasons.length > 0 && (
        <ul className="space-y-0.5 text-sm text-muted">
          {data.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <section className="grid grid-cols-2 gap-2 md:grid-cols-5" aria-label="Validation totals">
        <StatTile label="Cells checked" value={formatCount(t.checked)} />
        <StatTile label="Matched" value={formatCount(t.matched)} hint={t.checked ? `${((100 * t.matched) / t.checked).toFixed(2)}%` : undefined} />
        <StatTile label="Mismatched" value={formatCount(t.mismatched)} hint={t.mismatched ? "see table below" : "none"} />
        <StatTile label="Skipped" value={formatCount(skipped)} hint={`${formatCount(t.skipped_unsupported)} unsupported · ${formatCount(t.skipped_stale)} stale`} />
        <StatTile label="Anomalies" value={formatCount(anomalies)} hint={anomalies ? "warnings, not failures" : "none found"} />
      </section>

      <Card title="Coverage by sheet">
        <DataTable columns={coverageColumns} rows={data.by_sheet} rowKey={(s) => s.sheet} dense />
      </Card>

      <Card title={`Mismatches${data.mismatches_truncated ? " (first 2,000)" : ""}`}>
        {data.mismatches.length === 0 ? (
          <EmptyState title="Every checked cell matches Excel" description="Numbers agree to 15 significant digits; text, booleans and errors agree exactly." />
        ) : (
          <DataTable columns={mismatchColumns} rows={data.mismatches} rowKey={(m) => `${m.sheet}!${m.cell}`} dense maxHeight="30rem" />
        )}
      </Card>

      {data.unsupported.length > 0 && (
        <Card title="Unsupported functions (skipped)">
          <ul className="space-y-1 text-sm">
            {data.unsupported.map((u) => (
              <li key={`${u.sheet}!${u.cell}`}>
                <span className="font-medium">{u.function}</span> in {u.sheet}!{u.cell} · {formatCount(u.cells)} cell(s) kept at their cached values
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Structural anomalies">
        {data.anomalies.length === 0 ? (
          <EmptyState title="No structural anomalies" description="No pasted rows, pattern breaks, duplicate lookup keys or stale cells were found in the in-scope sheets." />
        ) : (
          <div className="space-y-2">
            {KIND_ORDER.filter((k) => data.anomalies.some((a) => a.kind === k)).map((kind) => (
              <AnomalyGroup key={kind} kind={kind} items={data.anomalies.filter((a) => a.kind === kind)} />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

function AnomalyGroup({ kind, items }: { kind: AnomalyKind; items: Anomaly[] }) {
  return (
    <details open className="rounded-md border border-hairline bg-surface">
      <summary className="cursor-pointer select-none px-3 py-2 font-heading text-sm font-medium text-ink">
        {ANOMALY_LABELS[kind]} <span className="tabular ml-1 text-xs text-muted">{items.length}</span>
      </summary>
      <ul className="divide-y divide-hairline border-t border-hairline">
        {items.map((a) => (
          <li key={a.id} className="px-3 py-2 text-sm">
            <div className="flex flex-wrap items-baseline gap-2">
              <Pill tone="warning" dot={false}>
                {a.sheet}
              </Pill>
              <span className="tabular text-xs text-muted">{a.location}</span>
              <span className="font-medium text-ink">{a.title}</span>
            </div>
            <p className="mt-1 text-muted">{a.explanation}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
