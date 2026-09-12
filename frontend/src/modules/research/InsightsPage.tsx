import { runExportUrl } from "@/api/exports";
import type { ReactNode } from "react";
import { getResearchInsights, researchExportUrl, scopeParam, type Insight, type Scope } from "@/api/research";
import { Button, EmptyState, ExportMenu } from "@/components";
import { formatCount } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import type { ResearchActions } from "./types";
import { ConfidentialFooter, LinkButton, Narrative, NotConfigured, PageHead, QuartilePill, SectionHeader, Skeleton } from "./ui";

const SECTION_ICONS = ["◎", "◑", "⌸", "₹", "◈", "✦"];

function sectionTitle(key: string): string {
  return key.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function InsightsPage({ actions, runId, scope, scopeBar }: { actions: ResearchActions; runId: string | null; scope?: Scope; scopeBar?: ReactNode; }) {
  const data = useAsync(() => getResearchInsights(undefined, scope), [scopeParam(scope)]);
  if (data.status === "error") return <EmptyState tone="error" title="Could not compute the insights" description={data.error} action={<Button onClick={data.reload}>Retry</Button>} />;
  if (data.status === "loading" && !data.data) return <Skeleton rows={3} />;
  const body = data.data!;
  if (!body.configured) return <NotConfigured problems={body.problems} onOpenAdmin={actions.openAdmin} />;
  const bySection = new Map<string, Insight[]>();
  for (const ins of body.insights) bySection.set(ins.section, [...(bySection.get(ins.section) ?? []), ins]);

  return (
    <div>
      <PageHead
        title="Insights"
        sub="Questions this data answers · every line computed from the active version, nothing written by hand"
        actions={
          <ExportMenu
            items={[
              { label: "Insights brief (xlsx)", url: researchExportUrl("insights", "xlsx", {}, scope), hint: "Every card with its sentence and rows, in scope" },
              { label: "Insights brief (csv)", url: researchExportUrl("insights", "csv", {}, scope) },
              ...(runId ? [{ label: "Analysis report (PDF)", url: runExportUrl(runId, "pdf"), hint: "Includes the insights brief" }] : []),
            ]}
          />
        }
      />
      {scopeBar}
      {body.sections.map((section, i) => (
        <section key={section} aria-label={body.sectionLabels?.[section] ?? sectionTitle(section)}>
          <SectionHeader icon={SECTION_ICONS[i % SECTION_ICONS.length]} title={body.sectionLabels?.[section] ?? sectionTitle(section)} sub={`${bySection.get(section)?.length ?? 0} cards`} />
          <div className="grid gap-[18px] md:grid-cols-12">
            {(bySection.get(section) ?? []).map((ins) => (
              <InsightCard key={ins.key} insight={ins} actions={actions} />
            ))}
          </div>
        </section>
      ))}
      <ConfidentialFooter text={body.footer} />
    </div>
  );
}

export function InsightCard({ insight: ins, actions }: { insight: Insight; actions: ResearchActions }) {
  const ranked = ins.rows.length > 0 && ins.rows.every((r) => r.key !== null);
  const drillKeys = ins.drill.keys ?? [];
  return (
    <article className="flex min-w-0 flex-col rounded-xl border border-hairline bg-surface px-[20px] py-[19px] md:col-span-4" aria-label={ins.title}>
      <div className="mb-[7px] text-[10.5px] font-bold uppercase tracking-[0.1em] text-accent">{ins.eyebrow}</div>
      <h3 className="m-0 mb-[7px] font-heading text-[15.5px] font-semibold tracking-[-0.01em] text-ink">{ins.title}</h3>
      {ins.status === "ok" && <Narrative text={ins.sentence} className="mb-[12px]" />}
      {ins.status !== "ok" && (
        <p className="m-0 mb-[12px] rounded-sm border border-hairline bg-surface-lifted px-[12px] py-[8px] text-xs text-muted" role="note">
          {ins.note ?? (ins.problems.length ? ins.problems.join("; ") : "Not available on this version.")}
        </p>
      )}
      {ins.rows.length > 0 && (
        <ol className="m-0 flex list-none flex-col p-0">
          {ins.rows.map((r, i) => (
            <li key={`${r.key ?? r.label}-${i}`} className="flex items-center gap-[10px] border-b border-hairline py-[8px] last:border-b-0">
              {ranked && <span className="tabular w-[19px] flex-none text-[11.5px] text-muted">{i + 1}</span>}
              {r.key ? (
                <button type="button" onClick={() => actions.openFund(r.key!)} className="min-w-0 flex-1 truncate text-left text-[12.5px] font-semibold text-ink hover:text-accent">
                  {r.label}
                  {r.sub && <span className="font-normal text-muted"> · {r.sub}</span>}
                </button>
              ) : (
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-ink">{r.label}</span>
              )}
              {/^Q\d \/ Q\d$/.test(r.valueLabel) ? (
                <QuartilePill q={1} label={r.valueLabel} />
              ) : (
                <span className="tabular whitespace-nowrap text-[12.5px] font-semibold text-ink">{r.valueLabel}</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {drillKeys.length > 0 && ins.count > 0 && (
        <div className="mt-auto pt-[13px]">
          <LinkButton onClick={() => actions.openFunds({ keys: drillKeys, sort: ins.drill.sort, dir: ins.drill.dir })}>See all {formatCount(ins.count)} →</LinkButton>
        </div>
      )}
    </article>
  );
}
