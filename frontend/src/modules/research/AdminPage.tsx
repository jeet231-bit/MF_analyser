import type { ReactNode } from "react";
import { getResearchConfig, type ResearchSummary } from "@/api/research";
import type { ValidationReport } from "@/api/validation";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button, EmptyState } from "@/components";
import { useState } from "react";
import { formatCount, formatDate } from "@/lib/format";
import { useAsync, type AsyncState } from "@/lib/useAsync";
import type { ResearchActions } from "./types";
import { ConfidentialFooter, LinkButton, Narrative, PageHead, RCard, SectionHeader, Skeleton, StatCard } from "./ui";

export function AdminPage({
  summary,
  versions,
  validation,
  versionsPanel,
  validationPanel,
  footer,
  viewer,
  actions,
}: {
  summary: ResearchSummary | null;
  versions: WorkbookVersion[];
  validation: AsyncState<ValidationReport>;
  versionsPanel: ReactNode;
  validationPanel: ReactNode;
  footer?: string | null;
  viewer?: { name: string | null; localName: string | null; setName: (name: string) => void };
  actions?: ResearchActions;
}) {
  const [nameDraft, setNameDraft] = useState(viewer?.localName ?? "");
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

      {summary?.configured && summary.universe_all && (
        <RCard className="mb-[18px]" title="Rating coverage" sub="Why every unrated fund is unrated · the same partition the dashboard strip and the coverage cards use" data-testid="coverage-detail">
          <Narrative text={summary.universe_narrative} className="mb-3" />
          <CoverageTable universe={summary.universe_all} />
          {actions && (
            <LinkButton className="mt-3" onClick={actions.openInsights}>
              Open the coverage cards →
            </LinkButton>
          )}
        </RCard>
      )}
      {viewer && (
        <RCard className="mb-[18px]" title="Your name" sub="Used for the greeting. Kept in this browser until sign-in exists; then it comes from your account.">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              viewer.setName(nameDraft);
            }}
          >
            <input
              aria-label="Your name"
              className="rounded-[9px] border border-hairline bg-surface-lifted px-3 py-2 text-[13px] text-ink"
              placeholder={viewer.name ?? "First name"}
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
            />
            <Button type="submit">Save</Button>
            {viewer.localName && (
              <Button
                onClick={() => {
                  setNameDraft("");
                  viewer.setName("");
                }}
              >
                Clear
              </Button>
            )}
            <span className="text-xs text-muted">{viewer.localName ? `Greeting you as ${viewer.localName}.` : viewer.name ? `Default from the config: ${viewer.name}.` : "No name yet: the greeting is plain."}</span>
          </form>
        </RCard>
      )}
      <SectionHeader icon="◫" title="Versions" sub="Upload history, activation and the logic diff" />
      {versionsPanel}
      <SectionHeader icon="✓" title="Validation" sub="Reconciliation against Excel's own cached values" />
      {validationPanel}
      <ConfidentialFooter text={footer} />
    </div>
  );
}

function CoverageTable({ universe: u }: { universe: NonNullable<ResearchSummary["universe_all"]> }) {
  const rows: [string, number, string][] = [
    ["Rated", u.rated, "carry a composite quartile"],
    ["Too young to rate", u.unrated_young ?? 0, "first NAV after the earliest bull phase"],
    ["Data gap", u.unrated_gap ?? 0, "old enough to rate, composite still \"--\""],
    ["No first-NAV date", u.unrated_unknown ?? 0, "cannot be told apart from young launches"],
    ["Small category only", u.unrated_small_categories, "fewer ranked funds than the workbook rule needs"],
    ["Outside the universe flag", u.outside_universe ?? 0, "excluded by the master itself"],
  ];
  return (
    <table className="w-full border-collapse text-[13px]">
      <tbody>
        {rows.map(([label, n, why]) => (
          <tr key={label} className="border-b border-hairline last:border-b-0">
            <td className="py-2 pr-3 font-semibold text-ink">{label}</td>
            <td className="tabular py-2 pr-3 text-right text-ink">{formatCount(n)}</td>
            <td className="py-2 text-muted">{why}</td>
          </tr>
        ))}
        <tr>
          <td className="pt-2 font-semibold text-muted">Universe</td>
          <td className="tabular pt-2 pr-3 text-right font-semibold text-ink">{formatCount(u.total)}</td>
          <td className="pt-2 text-muted">funds on the master</td>
        </tr>
      </tbody>
    </table>
  );
}
