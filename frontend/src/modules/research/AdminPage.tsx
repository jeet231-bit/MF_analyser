import type { ReactNode } from "react";
import { getResearchConfig, type ResearchSummary } from "@/api/research";
import type { ValidationReport } from "@/api/validation";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button, EmptyState } from "@/components";
import { formatCount, formatDate } from "@/lib/format";
import { useAsync, type AsyncState } from "@/lib/useAsync";
import { ConfidentialFooter, PageHead, RCard, SectionHeader, Skeleton, StatCard } from "./ui";

export function AdminPage({
  summary,
  versions,
  validation,
  versionsPanel,
  validationPanel,
  footer,
}: {
  summary: ResearchSummary | null;
  versions: WorkbookVersion[];
  validation: AsyncState<ValidationReport>;
  versionsPanel: ReactNode;
  validationPanel: ReactNode;
  footer?: string | null;
}) {
  const config = useAsync(() => getResearchConfig(), []);
  const active = versions.find((v) => v.status === "active") ?? null;
  const report = validation.status === "ready" ? validation.data : null;
  const anomalies = report ? Object.values(report.anomaly_counts ?? {}).reduce((a, b) => a + (b ?? 0), 0) : summary?.validation?.anomalies ?? 0;
  const findings = config.data?.findings ?? [];
  const open = findings.filter((f) => f.status === "open").length;
  const fixed = findings.length - open;

  return (
    <div>
      <PageHead title="Admin" sub="Versions, validation, data findings and the column map" />
      <div className="mb-[18px] grid gap-[18px] md:grid-cols-4">
        <StatCard label="Active version" value={<span className="text-lg">{active ? formatDate(active.uploaded_at) : "none"}</span>} note={`${formatCount(versions.length)} versions stored`} />
        <StatCard
          label="Reconciliation"
          value={report && report.totals.checked > 0 ? `${((100 * report.totals.matched) / report.totals.checked).toFixed(2)}%` : "—"}
          note={report ? (report.totals.mismatched === 0 ? "no mismatches" : `${formatCount(report.totals.mismatched)} mismatches`) : "not validated"}
          tone={report && report.totals.mismatched === 0 ? "up" : "warn"}
        />
        <StatCard label="Structural warnings" value={formatCount(anomalies)} note={anomalies ? "see validation below" : "none"} tone={anomalies ? "warn" : "muted"} />
        <StatCard label="Data findings" value={formatCount(findings.length)} note={`${fixed} fixed · ${open} open`} tone={open ? "warn" : "muted"} />
      </div>

      <div className="mb-[18px] grid gap-[18px] md:grid-cols-12">
        <RCard className="md:col-span-7" title="Data findings in the master" sub="Defects this platform found that Excel was not showing · recorded in dashboard.config.json">
          {config.status === "error" ? (
            <EmptyState tone="error" title="Could not read the research config" description={config.error} action={<Button onClick={config.reload}>Retry</Button>} />
          ) : config.data ? (
            findings.length === 0 ? (
              <p className="m-0 text-[13px] text-muted">No findings recorded.</p>
            ) : (
              <ul className="m-0 list-none p-0">
                {findings.map((f) => (
                  <li key={f.title} className="flex items-center gap-3 border-b border-hairline py-2.5 last:border-b-0">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-ink">{f.title}</div>
                      <div className="text-[11.5px] text-muted">{f.detail}</div>
                    </div>
                    <span className={`rounded-[7px] border border-hairline px-[11px] py-1.5 text-xs font-semibold ${f.status === "fixed" ? "text-positive" : "text-warning"}`}>{f.status === "fixed" ? "Fixed" : "Open"}</span>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <Skeleton rows={1} />
          )}
        </RCard>
        <RCard className="md:col-span-5" title="Column map" sub="What the research views read · edited in dashboard.config.json, not code">
          {config.data ? (
            <div className="text-[12.5px]">
              {config.data.problems.length > 0 && (
                <ul className="m-0 mb-3 list-disc rounded-sm border border-warning/40 bg-surface-lifted py-2 pl-6 pr-3 text-xs text-warning" aria-label="Column map problems">
                  {config.data.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
              {config.data.entity && (
                <div className="flex justify-between gap-2 border-b border-hairline py-2">
                  <span className="font-semibold text-ink">Identity</span>
                  <span className="tabular text-muted">{config.data.entity.key}</span>
                </div>
              )}
              {(config.data.dimensions ?? []).map((d) => (
                <div key={d.key} className="flex justify-between gap-2 border-b border-hairline py-2">
                  <span className="font-semibold text-ink">
                    {d.label}
                    {d.split ? <span className="font-normal text-muted"> · split on “{d.split}”</span> : null}
                  </span>
                  <span className={`tabular ${d.resolved ? "text-muted" : "text-negative"}`}>{d.ref}</span>
                </div>
              ))}
              {(config.data.measures ?? []).map((m) => (
                <div key={m.key} className="flex justify-between gap-2 border-b border-hairline py-2 last:border-b-0">
                  <span className="text-ink">
                    {m.label}
                    <span className="text-muted"> · {m.role}</span>
                  </span>
                  <span className={`tabular ${m.resolved ? "text-muted" : "text-negative"}`}>{m.ref}</span>
                </div>
              ))}
              {config.data.minGroupCount !== undefined && <p className="m-0 mt-3 text-xs text-muted">League tables ignore groups with fewer than {config.data.minGroupCount} rated funds (minGroupCount).</p>}
            </div>
          ) : (
            <Skeleton rows={1} />
          )}
        </RCard>
      </div>

      <SectionHeader icon="◫" title="Versions" sub="Upload history, activation and the logic diff" />
      {versionsPanel}
      <SectionHeader icon="✓" title="Validation" sub="Reconciliation against Excel's own cached values" />
      {validationPanel}
      <ConfidentialFooter text={footer} />
    </div>
  );
}
