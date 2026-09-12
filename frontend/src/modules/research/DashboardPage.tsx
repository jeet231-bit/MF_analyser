import type { ReactNode } from "react";
import { runExportUrl } from "@/api/exports";
import { getResearchEntities, researchExportUrl, type ResearchSummary, type Scope } from "@/api/research";
import { Button, EmptyState, ExportMenu } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount, formatTimestamp } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Icon } from "@/modules/shell/icons";
import type { ResearchActions } from "./types";
import { BarList, ConfidentialFooter, LinkButton, MoverRow, Narrative, NotConfigured, PageHead, QuartileBar, QuartileLegend, QuartilePill, RCard, Skeleton } from "./ui";
import { useWatchlist } from "./useWatchlist";

const KPI_TONES: Record<string, string> = {
  q1: "bg-q1",
  q2: "bg-q2",
  accent: "bg-accent",
  violet: "bg-violet",
  positive: "bg-positive",
  warning: "bg-warning",
};

export function DashboardPage({
  summary,
  scope,
  scopeBar,
  greeting,
  actions,
  reload,
}: {
  summary: ReturnType<typeof useAsync<ResearchSummary>>;
  scope: Scope;
  scopeBar: ReactNode;
  greeting: string;
  actions: ResearchActions;
  reload?: () => void;
}) {
  if (summary.status === "error") {
    return <EmptyState tone="error" title="Could not load the research summary" description={summary.error} action={<Button onClick={reload ?? summary.reload}>Retry</Button>} />;
  }
  if (summary.status === "loading" && !summary.data) return <Skeleton rows={3} />;
  const s = summary.data!;
  if (!s.configured) return <NotConfigured problems={s.problems} onOpenAdmin={actions.openAdmin} />;
  const u = s.universe!;
  const all = s.universe_all ?? u;
  const asOf = s.history?.find((h) => h.id === s.version_id)?.date ?? s.history?.[s.history.length - 1]?.date ?? null;
  const scopeText = (s.scope?.description ?? []).join(" · ");
  const leaders = s.category_averages;

  return (
    <div>
      <PageHead
        title={greeting}
        sub={
          <>
            Fund research · {asOf ? `universe as of ${asOf} · ` : ""}
            {s.version?.filename} · recalculated {s.run ? formatTimestamp(s.run.created_at) : "—"}
          </>
        }
        actions={
          s.run_id && (
            <ExportMenu
              label="Export brief"
              items={[
                { label: "Insights brief (xlsx)", url: researchExportUrl("insights", "xlsx", {}, scope), hint: "Every card with its sentence and rows, in scope" },
                { label: "Funds in scope (csv)", url: researchExportUrl("entities", "csv", {}, scope) },
                { label: "Analysis report (PDF)", url: runExportUrl(s.run_id, "pdf"), hint: "Headline numbers, insights brief, changelog" },
              ]}
            />
          )
        }
      />

      {scopeBar}

      {s.executive && (
        <section
          aria-label="Executive summary"
          className="mb-[18px] rounded-xl border border-hero-line px-[22px] py-5 text-hero-ink"
          style={{ background: "linear-gradient(118deg, var(--hero-a) 0%, var(--hero) 62%)" }}
        >
          <div className="mb-[11px] flex items-center gap-[11px]">
            <span className="grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] bg-hero-link/20 text-hero-link" aria-hidden>
              <Icon name="spark" className="inline-block h-4 w-4 [&>svg]:h-full [&>svg]:w-full" />
            </span>
            <h2 className="m-0 font-heading text-[11.5px] font-bold uppercase tracking-[0.11em]">Executive summary</h2>
            <span className="ml-auto whitespace-nowrap rounded-full border border-hero-line px-3 py-1 text-[11px] text-hero-muted">
              {scopeText}
              {asOf ? ` · as of ${asOf}` : ""}
            </span>
          </div>
          <Narrative text={s.executive} onHero className="max-w-[88ch] text-[14.5px] leading-[1.62] text-hero-ink/85" />
        </section>
      )}

      {s.kpis && s.kpis.length > 0 && (
        <div className="mb-[18px] grid gap-[18px] sm:grid-cols-2 lg:grid-cols-4" data-testid="kpi-row">
          {s.kpis.map((k) => (
            <div key={k.label} className="relative overflow-hidden rounded-xl border border-hairline bg-surface px-5 py-[19px]">
              <span className={cn("absolute inset-x-0 top-0 h-[3px]", KPI_TONES[k.tone] ?? "bg-accent")} aria-hidden />
              <div className="text-[10.5px] font-bold uppercase tracking-[0.09em] text-muted">{k.label}</div>
              <div className="tabular mt-1.5 font-heading text-[30px] font-semibold leading-[1.1] tracking-[-0.025em] text-ink">{k.value}</div>
              {k.note && <div className="mt-1 text-xs text-muted">{k.note}</div>}
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-[18px] md:grid-cols-12">
        <RCard
          className="md:col-span-5"
          title="Quartile distribution"
          sub={`Composite quartile within category · ${formatCount(u.rated)} rated funds`}
          action={<LinkButton onClick={actions.openCategories}>Break down</LinkButton>}
        >
          <QuartileBar counts={s.quartiles ?? {}} className="mb-3 mt-1" />
          <QuartileLegend />
          <Narrative text={s.distribution_narrative} className="mt-4" />
          {(u.median_category_rated !== undefined || u.largest_category) && (
            <div className="mt-3.5 grid grid-cols-2 gap-2.5">
              <div className="rounded-md border border-hairline bg-surface-lifted px-[13px] py-[11px]">
                <div className="text-[11px] font-semibold text-muted">Median ranked category</div>
                <div className="tabular mt-0.5 font-heading text-lg font-semibold text-ink">{formatCount(u.median_category_rated ?? 0)} funds</div>
              </div>
              <div className="rounded-md border border-hairline bg-surface-lifted px-[13px] py-[11px]" title={u.largest_category?.key}>
                <div className="text-[11px] font-semibold text-muted">Largest category</div>
                <div className="tabular mt-0.5 font-heading text-lg font-semibold text-ink">{formatCount(u.largest_category?.rated ?? 0)} funds</div>
              </div>
            </div>
          )}
        </RCard>

        {leaders && leaders.rows.length > 0 && (
          <RCard
            className="md:col-span-4"
            title="Category leaders"
            sub={`${leaders.label} average · categories with ${leaders.minGroupCount ?? 10}+ rated funds`}
            action={<LinkButton onClick={actions.openCategories}>All {formatCount(u.categories)}</LinkButton>}
          >
            <BarList rows={leaders.rows.map((r) => ({ key: r.key, label: r.key, value: r.value, valueLabel: r.label }))} onSelect={(key) => actions.openFunds({ category: key })} />
          </RCard>
        )}

        <WatchlistCard actions={actions} className={leaders && leaders.rows.length > 0 ? "md:col-span-3" : "md:col-span-7"} />
      </div>

      {s.coverage_narrative && (
        <div className="mt-[18px] flex flex-wrap items-center gap-2.5 rounded-lg border border-hairline bg-surface-lifted px-4 py-[11px] text-[12.5px] text-muted" data-testid="coverage-strip">
          <span className="flex h-[7px] w-[170px] flex-none gap-0.5 overflow-hidden rounded-sm" role="img" aria-label={`Coverage: ${formatCount(all.rated)} rated, ${formatCount(all.total - all.rated)} not rated`}>
            <span className="bg-q1" style={{ flex: all.rated }} />
            <span className="bg-hairline" style={{ flex: Math.max(all.total - all.rated, 0) }} />
          </span>
          <Narrative text={s.coverage_narrative} className="min-w-0 flex-1 text-[12.5px] text-muted [&_b]:text-ink-2" />
          <LinkButton onClick={actions.openAdmin}>Coverage detail →</LinkButton>
        </div>
      )}
      <ConfidentialFooter text={s.footer} />
    </div>
  );
}

function WatchlistCard({ actions, className }: { actions: ResearchActions; className?: string }) {
  const { items, remove } = useWatchlist();
  const keys = items.map((i) => i.key);
  const rows = useAsync(() => (keys.length ? getResearchEntities({ keys, size: 50 }) : Promise.resolve(null)), [keys.join(" ")]);
  const byKey = new Map((rows.data?.rows ?? []).map((r) => [r.key, r]));
  const qKey = rows.data?.measures.find((m) => m.role === "quartile" && m.primary)?.key ?? rows.data?.measures.find((m) => m.role === "quartile")?.key;
  const rankKey = rows.data?.measures.find((m) => m.role === "rank" && m.primary)?.key;
  return (
    <RCard className={className} title="Watchlist" sub="Pinned by you, in this browser">
      {items.length === 0 ? (
        <p className="m-0 text-[13px] text-muted">Open a fund and choose “Watch” to pin it here.</p>
      ) : (
        <div>
          {items.map((i) => {
            const row = byKey.get(i.key);
            const q = row && qKey ? row.measures[qKey] : null;
            const rank = row && rankKey ? row.measures[rankKey] : null;
            return (
              <MoverRow
                key={i.key}
                name={i.label}
                context={[i.sub ?? row?.sub, rank !== null && rank !== undefined ? `rank ${rank}` : null].filter(Boolean).join(" · ") || undefined}
                right={
                  <>
                    <QuartilePill q={q ?? null} />
                    <button type="button" aria-label={`Remove ${i.label} from watchlist`} onClick={() => remove(i.key)} className="text-xs text-muted hover:text-negative">
                      ×
                    </button>
                  </>
                }
                onClick={() => actions.openFund(i.key)}
              />
            );
          })}
        </div>
      )}
      <LinkButton className="mt-3" onClick={() => actions.openFunds({})}>
        Add a fund →
      </LinkButton>
    </RCard>
  );
}
