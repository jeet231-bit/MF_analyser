import { runExportUrl } from "@/api/exports";
import { getResearchEntities, researchExportUrl, type ResearchSummary } from "@/api/research";
import { Button, EmptyState, ExportMenu } from "@/components";
import { formatCount, formatTimestamp } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { formatRankDelta } from "./format";
import type { ResearchActions } from "./types";
import { BarList, ConfidentialFooter, Hero, HeroTiles, LinkButton, MoverRow, Narrative, NotConfigured, PageHead, QuartileBar, QuartileLegend, QuartilePill, RCard, Skeleton } from "./ui";
import { useWatchlist } from "./useWatchlist";

export function DashboardPage({ summary, actions, reload }: { summary: ReturnType<typeof useAsync<ResearchSummary>>; actions: ResearchActions; reload?: () => void }) {
  if (summary.status === "error") {
    return <EmptyState tone="error" title="Could not load the research summary" description={summary.error} action={<Button onClick={reload ?? summary.reload}>Retry</Button>} />;
  }
  if (summary.status === "loading" && !summary.data) return <Skeleton rows={3} />;
  const s = summary.data!;
  if (!s.configured) return <NotConfigured problems={s.problems} onOpenAdmin={actions.openAdmin} />;
  const u = s.universe!;
  const q1 = s.quartiles?.["1"] ?? 0;
  const movement = s.movement;
  const asOf = s.history?.find((h) => h.id === s.version_id)?.date ?? s.history?.[s.history.length - 1]?.date ?? null;

  return (
    <div>
      <PageHead
        title="Research overview"
        sub={
          <>
            {asOf ? `Universe as of ${asOf} · ` : ""}
            {s.version?.filename} · recalculated {s.run ? formatTimestamp(s.run.created_at) : "—"}
          </>
        }
        actions={
          s.run_id && (
            <ExportMenu
              items={[
                { label: "Funds (csv)", url: researchExportUrl("entities", "csv"), hint: "Every fund with its dimensions and measures" },
                { label: "Insights brief (xlsx)", url: researchExportUrl("insights", "xlsx"), hint: "Every card with its sentence and rows" },
                { label: "Analysis report (PDF)", url: runExportUrl(s.run_id, "pdf"), hint: "Headline numbers, insights brief, changelog" },
              ]}
            />
          )
        }
      />

      <div className="mb-[18px] grid gap-[18px] md:grid-cols-12">
        <Hero
          className="md:col-span-4"
          eyebrow="Rated universe"
          big={formatCount(u.rated)}
          bigSuffix={`of ${formatCount(u.total)}`}
          sub={`funds across ${formatCount(u.categories)} categories · ${formatCount(u.complete)} with a complete record`}
        >
          <Narrative text={s.universe_narrative} onHero className="text-[12.5px]" />
          <Narrative text={s.narrative} onHero className="text-[12.5px]" />
          <HeroTiles
            tiles={[
              { value: formatCount(q1), label: "Top quartile" },
              { value: movement ? formatCount(movement.moved) : "—", label: "Rank changes" },
              { value: movement ? formatCount(movement.entries) : "—", label: "New funds" },
            ]}
          />
        </Hero>

        <RCard
          className="md:col-span-5"
          title="Quartile distribution"
          sub={`Composite quartile within category · ${formatCount(u.rated)} rated funds`}
          action={<LinkButton onClick={actions.openCategories}>Break down</LinkButton>}
        >
          <QuartileBar counts={s.quartiles ?? {}} className="mb-3 mt-1" />
          <QuartileLegend />
          <p className="m-0 mt-3.5 text-xs text-muted">
            {formatCount(u.unranked_categories)} of {formatCount(u.categories)} categories are left unranked by the workbook rule and show “--”; {formatCount(u.unrated_missing_data)} more funds are unrated because part of their composite is missing.
          </p>
        </RCard>

        <RCard className="md:col-span-3">
          <div className="text-[11.5px] font-medium text-muted">Engine agreement with Excel</div>
          <div className="tabular mt-0.5 font-heading text-[27px] font-semibold tracking-[-0.02em] text-ink">
            {s.validation && s.validation.checked > 0 ? `${((100 * s.validation.matched) / s.validation.checked).toFixed(2)}%` : "—"}
          </div>
          <div className="text-xs font-semibold text-positive">
            {s.validation ? `${formatCount(s.validation.matched)} of ${formatCount(s.validation.checked)} cells` : "not validated"}
          </div>
          <div className="my-[15px] h-px bg-hairline" />
          <dl className="m-0 flex flex-col gap-2 text-[12.5px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Last upload</dt>
              <dd className="m-0 font-semibold text-ink">{s.version ? formatTimestamp(s.version.uploaded_at) : "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Validation</dt>
              <dd className={`m-0 font-semibold ${s.validation?.anomalies ? "text-warning" : "text-ink"}`}>
                {s.validation ? `${s.validation.status.replace(/_/g, " ")}${s.validation.anomalies ? ` · ${s.validation.anomalies} warnings` : ""}` : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Data findings</dt>
              <dd className="m-0 font-semibold text-ink">{s.findings ? `${s.findings.open} open` : "—"}</dd>
            </div>
          </dl>
          <LinkButton className="mt-3.5" onClick={actions.openAdmin}>
            Open admin →
          </LinkButton>
        </RCard>
      </div>

      <div className="grid gap-[18px] md:grid-cols-12">
        <RCard
          className="md:col-span-5"
          title="Biggest rank movers"
          sub={movement ? `Composite rank vs version of ${movement.previous.date ?? movement.previous.filename}` : "Needs an earlier activated version"}
          action={movement && <LinkButton onClick={actions.openMovement}>All {formatCount(movement.moved)} →</LinkButton>}
        >
          {movement && movement.top.length > 0 ? (
            <div>
              {movement.top.map((m) => (
                <MoverRow
                  key={m.key}
                  name={m.label}
                  context={[m.sub, m.category, m.cause === "repair" ? "repaired row" : null].filter(Boolean).join(" · ")}
                  right={<div className="tabular font-heading text-sm font-semibold text-ink">{m.rankTo}</div>}
                  delta={formatRankDelta(m.delta)}
                  onClick={() => actions.openFund(m.key)}
                />
              ))}
            </div>
          ) : (
            <p className="m-0 text-[13px] text-muted">{movement ? "No fund changed rank since the previous version." : "Movement appears once a second version has been activated."}</p>
          )}
        </RCard>

        <RCard
          className="md:col-span-4"
          title="Category averages"
          sub={s.category_averages ? `${s.category_averages.label} · top ${s.category_averages.rows.length} of ${s.category_averages.total}` : "No return measure configured"}
          action={<LinkButton onClick={actions.openCategories}>All →</LinkButton>}
        >
          {s.category_averages && s.category_averages.rows.length > 0 ? (
            <BarList rows={s.category_averages.rows.map((r) => ({ key: r.key, label: r.key, value: r.value, valueLabel: r.label }))} onSelect={(key) => actions.openFunds({ category: key })} />
          ) : (
            <p className="m-0 text-[13px] text-muted">Nothing to average yet.</p>
          )}
        </RCard>

        <WatchlistCard actions={actions} />
      </div>
      <ConfidentialFooter text={s.footer} />
    </div>
  );
}

function WatchlistCard({ actions }: { actions: ResearchActions }) {
  const { items, remove } = useWatchlist();
  const keys = items.map((i) => i.key);
  const rows = useAsync(() => (keys.length ? getResearchEntities({ keys, size: 50 }) : Promise.resolve(null)), [keys.join(" ")]);
  const byKey = new Map((rows.data?.rows ?? []).map((r) => [r.key, r]));
  const qKey = rows.data?.measures.find((m) => m.role === "quartile" && m.primary)?.key ?? rows.data?.measures.find((m) => m.role === "quartile")?.key;
  return (
    <RCard className="md:col-span-3" title="Watchlist" sub="Pinned by you, in this browser">
      {items.length === 0 ? (
        <p className="m-0 text-[13px] text-muted">Open a fund and choose “Watch” to pin it here.</p>
      ) : (
        <div>
          {items.map((i) => {
            const row = byKey.get(i.key);
            const q = row && qKey ? row.measures[qKey] : null;
            return (
              <MoverRow
                key={i.key}
                name={i.label}
                context={i.sub ?? row?.sub ?? undefined}
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
    </RCard>
  );
}
