import type { CSSProperties, ReactNode } from "react";
import { runExportUrl } from "@/api/exports";
import { getResearchEntities, researchExportUrl, type Insight, type ResearchSummary, type Scope } from "@/api/research";
import { Button, EmptyState, ExportMenu } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount, formatTimestamp } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Icon, type IconName } from "@/modules/shell/icons";
import { formatRankDelta } from "./format";
import type { ResearchActions } from "./types";
import { BarList, ConfidentialFooter, LinkButton, MoverRow, Narrative, NotConfigured, PageHead, QuartileBar, QuartileLegend, QuartilePill, RCard, Skeleton } from "./ui";
import { useWatchlist } from "./useWatchlist";

/* The dashboard answers three questions in order: what is true, what changed, and where to
   look. Counts that are only counts sit in one quiet strip; every card below them is a list
   the reader can open. */

const CALLOUT_TONES: { tint: string; bubble: string; icon: IconName }[] = [
  { tint: "tint-mint", bubble: "bg-accent text-white", icon: "funds" },
  { tint: "tint-sun", bubble: "bg-highlight text-ink", icon: "insights" },
  { tint: "tint-violet", bubble: "bg-violet text-white", icon: "categories" },
  { tint: "tint-sky", bubble: "bg-hero-link text-white", icon: "validation" },
];

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
  const callouts = (s.callouts ?? []).filter((c) => c.status === "ok" && c.count > 0);

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
        <section aria-label="Executive summary" className="mb-[18px] rounded-xl glass tint-sky rise px-[22px] py-[20px] text-hero-ink">
          <div className="mb-[11px] flex items-center gap-[11px]">
            <span className="grid h-[32px] w-[32px] flex-none place-items-center rounded-full glass-inset text-hero-link" aria-hidden>
              <Icon name="spark" className="inline-block h-[16px] w-[16px] [&>svg]:h-full [&>svg]:w-full" />
            </span>
            <h2 className="m-0 font-heading text-[11.5px] font-bold uppercase tracking-[0.11em]">Executive summary</h2>
            <span className="ml-auto whitespace-nowrap rounded-full glass-inset px-[12px] py-[4px] text-[11px] text-hero-muted">
              {scopeText}
              {asOf ? ` · as of ${asOf}` : ""}
            </span>
          </div>
          <Narrative text={s.executive} onHero className="text-[14.5px] leading-[1.62]" />
          {s.kpis && s.kpis.length > 0 && (
            <dl className="mt-[15px] flex flex-wrap gap-x-[26px] gap-y-[8px] border-t border-hero-line pt-[13px]" data-testid="kpi-row">
              {s.kpis.map((k) => (
                <div key={k.label} className="flex items-baseline gap-[7px]">
                  <dt className="text-[11.5px] text-hero-muted">{k.label}</dt>
                  <dd className="tabular m-0 font-heading text-[15.5px] font-bold text-hero-ink">{k.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      )}

      <WhatChanged summary={s} actions={actions} />

      {callouts.length > 0 && (
        <section aria-label="Where to look" className="mb-[18px]">
          <div className="grid gap-[18px] sm:grid-cols-2 lg:grid-cols-4" data-testid="callout-row">
            {callouts.map((c, i) => (
              <Callout key={c.key} insight={c} tone={CALLOUT_TONES[i % CALLOUT_TONES.length]} index={i + 1} actions={actions} />
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-[18px] md:grid-cols-12">
        <RCard
          className="md:col-span-5"
          index={5}
          eyebrow="Universe"
          title="Quartile distribution"
          badge={`${formatCount(u.rated)} rated`}
          sub="Composite quartile within category"
          action={<LinkButton onClick={actions.openCategories}>Break down</LinkButton>}
        >
          <QuartileBar counts={s.quartiles ?? {}} className="mb-[12px] mt-[4px]" />
          <QuartileLegend />
          <Narrative text={s.distribution_narrative} className="mt-[16px]" />
          {(u.median_category_rated !== undefined || u.largest_category) && (
            <div className="mt-[14px] grid grid-cols-2 gap-[10px]">
              <div className="rounded-md glass-inset px-[13px] py-[11px]">
                <div className="text-[11px] font-semibold text-muted">Median ranked category</div>
                <div className="tabular mt-[2px] font-heading text-lg font-semibold text-ink">{formatCount(u.median_category_rated ?? 0)} funds</div>
              </div>
              <div className="rounded-md glass-inset px-[13px] py-[11px]" title={u.largest_category?.key}>
                <div className="text-[11px] font-semibold text-muted">Largest category</div>
                <div className="tabular mt-[2px] font-heading text-lg font-semibold text-ink">{formatCount(u.largest_category?.rated ?? 0)} funds</div>
              </div>
            </div>
          )}
        </RCard>

        {leaders && leaders.rows.length > 0 && (
          <RCard
            className="md:col-span-4"
            index={6}
            eyebrow="Categories"
            title="Category leaders"
            badge={leaders.rows.length}
            sub={`${leaders.label} average · categories with ${leaders.minGroupCount ?? 10}+ rated funds`}
            action={<LinkButton onClick={actions.openCategories}>All {formatCount(u.categories)}</LinkButton>}
          >
            <BarList rows={leaders.rows.map((r) => ({ key: r.key, label: r.key, value: r.value, valueLabel: r.label }))} onSelect={(key) => actions.openFunds({ category: key })} />
          </RCard>
        )}

        <WatchlistCard actions={actions} className={leaders && leaders.rows.length > 0 ? "md:col-span-3" : "md:col-span-7"} />
      </div>

      {s.coverage_narrative && (
        <div className="mt-[18px] flex flex-wrap items-center gap-[10px] rounded-lg glass rise px-[16px] py-[11px] text-[12.5px] text-muted" data-testid="coverage-strip">
          <span className="flex h-[7px] w-[170px] flex-none gap-[2px] overflow-hidden rounded-sm" role="img" aria-label={`Coverage: ${formatCount(all.rated)} rated, ${formatCount(all.total - all.rated)} not rated`}>
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

/** The month, not the statistics: what moved since the previous upload, and who moved most. */
function WhatChanged({ summary, actions }: { summary: ResearchSummary; actions: ResearchActions }) {
  const m = summary.movement;
  if (!m || m.same_month) return null;
  const changed = m.moved + m.entries + m.exits;
  if (changed === 0) return null;
  const since = m.previous.date ?? m.previous.filename;
  const figures: { label: string; value: number; onClick?: () => void }[] = [
    { label: "Changed rank", value: m.moved, onClick: actions.openMovement },
    { label: "Moved up", value: m.up, onClick: actions.openMovement },
    { label: "Moved down", value: m.down, onClick: actions.openMovement },
    { label: "New to the universe", value: m.entries },
    { label: "Gone", value: m.exits },
  ].filter((f) => f.value > 0);

  return (
    <section aria-label="What changed" className="mb-[18px] rounded-xl glass rise px-[22px] py-[18px]" data-testid="what-changed">
      <header className="mb-[13px] flex flex-wrap items-center gap-[11px]">
        <span className="grid h-[32px] w-[32px] flex-none place-items-center rounded-full bg-accent-soft text-accent" aria-hidden>
          <Icon name="movement" className="inline-block h-[16px] w-[16px] [&>svg]:h-full [&>svg]:w-full" />
        </span>
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">Since {since}</div>
          <h2 className="m-0 font-heading text-[15.5px] font-bold text-ink">What changed</h2>
        </div>
        <LinkButton className="ml-auto" onClick={actions.openMovement}>
          Open movement →
        </LinkButton>
      </header>

      <dl className="m-0 mb-[14px] flex flex-wrap gap-x-[24px] gap-y-[8px]">
        {figures.map((f) => (
          <div key={f.label} className="flex items-baseline gap-[7px]">
            <dd className="tabular m-0 font-heading text-[19px] font-bold text-ink">{formatCount(f.value)}</dd>
            <dt className="text-[12px] text-muted">
              {f.onClick ? (
                <button type="button" onClick={f.onClick} className="hover:text-accent">
                  {f.label}
                </button>
              ) : (
                f.label
              )}
            </dt>
          </div>
        ))}
        {m.repairs > 0 && (
          <div className="flex items-baseline gap-[7px]">
            <dd className="tabular m-0 font-heading text-[19px] font-bold text-warning">{formatCount(m.repairs)}</dd>
            <dt className="text-[12px] text-muted">of those are data repairs, not market movement</dt>
          </div>
        )}
      </dl>

      {m.top.length > 0 && (
        <div className="grid gap-x-[24px] md:grid-cols-2">
          {m.top.map((mv) => {
            const delta = formatRankDelta(mv.delta);
            return (
              <MoverRow
                key={mv.key}
                name={mv.label}
                context={
                  <>
                    {mv.category ?? mv.sub} · rank {formatCount(mv.rankFrom)} → {formatCount(mv.rankTo)}
                    {mv.cause === "repair" ? " · repaired row" : ""}
                  </>
                }
                right={<QuartilePill q={mv.quartileTo} />}
                delta={delta}
                onClick={() => actions.openFund(mv.key)}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

/** One "where to look" card: a computed insight as a count with its own list behind it. */
function Callout({ insight, tone, index, actions }: { insight: Insight; tone: (typeof CALLOUT_TONES)[number]; index: number; actions: ResearchActions }) {
  const keys = insight.drill.keys ?? [];
  const open = () => keys.length > 0 && actions.openFunds({ keys, sort: insight.drill.sort, dir: insight.drill.dir });
  return (
    <button
      type="button"
      onClick={open}
      disabled={keys.length === 0}
      style={{ "--i": index } as CSSProperties}
      className={cn("rounded-[24px_24px_24px_10px] glass rise lift px-[20px] py-[18px] text-left disabled:cursor-default", tone.tint)}
      data-testid="callout"
    >
      <div className="flex items-center gap-[10px]">
        <span className={cn("grid h-[34px] w-[34px] flex-none place-items-center rounded-full", tone.bubble)} aria-hidden>
          <Icon name={tone.icon} className="inline-block h-[17px] w-[17px] [&>svg]:h-full [&>svg]:w-full" />
        </span>
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-accent">{insight.eyebrow}</div>
          <div className="truncate text-[13px] font-semibold text-ink-2">{insight.title}</div>
        </div>
      </div>
      <div className="tabular mt-[12px] font-heading text-[30px] font-extrabold leading-[1.1] tracking-[-0.025em] text-ink">{formatCount(insight.count)}</div>
      <Narrative text={insight.sentence} className="mt-[4px] text-[12px] leading-[1.5]" />
      {keys.length > 0 && <div className="mt-[8px] font-heading text-[12px] font-semibold text-accent">See all {formatCount(insight.count)} →</div>}
    </button>
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
    <RCard className={className} index={7} tone="sun" eyebrow="Yours" title="Watchlist" badge={items.length || undefined} sub="Pinned by you, in this browser">
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
                    <button type="button" aria-label={`Remove ${i.label} from watchlist`} onClick={() => remove(i.key)} className="px-[4px] text-[14px] leading-none text-ink-2 hover:text-negative">
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
      <LinkButton className="mt-[12px]" onClick={() => actions.openFunds({})}>
        Add a fund →
      </LinkButton>
    </RCard>
  );
}
