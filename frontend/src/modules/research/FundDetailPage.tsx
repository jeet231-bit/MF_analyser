import { useState } from "react";
import { getResearchEntity, type EntityMeasure } from "@/api/research";
import { Button, EmptyState } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { LineagePanel, type LineageTarget } from "@/modules/lineage/LineagePanel";
import { formatMeasure, formatRankDelta } from "./format";
import type { ResearchActions } from "./types";
import { ConfidentialFooter, Hero, LinkButton, MoverRow, Narrative, NotConfigured, PageHead, PhaseBars, QuartilePill, RCard, Skeleton } from "./ui";
import { useWatchlist } from "./useWatchlist";

function cellTarget(cell: string | null | undefined): LineageTarget | null {
  if (!cell) return null;
  const i = cell.lastIndexOf("!");
  if (i < 0) return null;
  return { sheet: cell.slice(0, i).replace(/^'|'$/g, ""), cell: cell.slice(i + 1) };
}

export function FundDetailPage({ fundKey, actions, footer }: { fundKey: string; actions: ResearchActions; footer?: string | null }) {
  const data = useAsync(() => getResearchEntity(fundKey), [fundKey]);
  const settings = useFormat();
  const watch = useWatchlist();
  const [trace, setTrace] = useState<LineageTarget | null>(null);

  if (data.status === "error") {
    return (
      <EmptyState
        tone="error"
        title={data.notFound ? "This fund is not in the active version" : "Could not load the fund"}
        description={data.error}
        action={<Button onClick={data.notFound ? () => actions.openFunds({}) : data.reload}>{data.notFound ? "All funds" : "Retry"}</Button>}
      />
    );
  }
  if (data.status === "loading" && !data.data) return <Skeleton rows={3} />;
  const d = data.data!;
  if (!d.configured) return <NotConfigured problems={d.problems} onOpenAdmin={actions.openAdmin} />;

  const byRole = (role: EntityMeasure["role"]) => d.measures.filter((m) => m.role === role);
  const primary = (role: EntityMeasure["role"]) => d.measures.find((m) => m.role === role && m.primary) ?? byRole(role)[0];
  const score = primary("score");
  const rank = primary("rank");
  const quartile = primary("quartile");
  const secondaryScores = byRole("score").filter((m) => m.key !== score?.key).slice(0, 2);
  const returns = byRole("return").slice(0, 2);
  const firstReturn = byRole("return")[0];
  const categoryMean = firstReturn ? d.category.means[firstReturn.key] : null;
  const rankValue = rank?.value ?? null;
  const qValue = quartile?.value ?? null;
  const delta = formatRankDelta(d.delta);
  const watching = watch.has(d.entity.key);
  const explanation = d.quartileExplanation ?? [];
  const versionId = d.version_id ?? "";

  const tile = (label: string, value: string, note?: string, tone: "up" | "down" | "muted" = "muted", target?: LineageTarget | null) => (
    <button
      key={label}
      type="button"
      disabled={!target}
      onClick={target ? () => setTrace(target) : undefined}
      className={cn("rounded-xl glass rise lift px-[16px] py-[14px] text-left", target && "hover:border-accent")}
      aria-label={target ? `${label}: ${value}. Trace this number` : undefined}
    >
      <div className="text-[11.5px] font-medium text-muted">{label}</div>
      <div className="tabular mt-[2px] font-heading text-[27px] font-semibold leading-[1.15] tracking-[-0.02em] text-ink">{value}</div>
      {note && <div className={cn("mt-[2px] text-xs font-semibold", tone === "up" ? "text-positive" : tone === "down" ? "text-negative" : "text-muted")}>{note}</div>}
    </button>
  );

  return (
    <div>
      <PageHead
        back={
          <LinkButton onClick={() => actions.openFunds({})} className="mb-[6px]">
            ← All funds
          </LinkButton>
        }
        title={d.entity.label}
        sub={d.entity.sub ?? d.entity.key}
        actions={
          <Button aria-pressed={watching} onClick={() => watch.toggle({ key: d.entity.key, label: d.entity.label, sub: d.entity.sub })}>
            {watching ? "★ Watching" : "☆ Watch"}
          </Button>
        }
      />
      <div className="-mt-[12px] mb-[18px] flex flex-wrap gap-[6px]">
        {Object.entries(d.entity.dims)
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <span key={k} className="rounded-[6px] border border-hairline bg-surface-lifted px-[8px] py-[3px] text-[11.5px] text-ink-2">
              {v}
            </span>
          ))}
        <span className="rounded-[6px] border border-hairline bg-surface-lifted px-[8px] py-[3px] text-[11.5px] text-ink-2">Row {d.row}</span>
      </div>
      <Narrative text={d.narrative} className="mb-[16px]" />

      <div className="mb-[18px] grid gap-[18px] md:grid-cols-[1.4fr_1fr]">
        <div className="grid grid-cols-2 gap-[14px] md:grid-cols-3">
          {score && tile(score.label, score.display, score.categoryRank ? `rank ${score.categoryRank} of ${score.categoryCount} in category` : undefined, "muted", cellTarget(score.cell))}
          {secondaryScores.map((m) => tile(m.label, m.display, m.categoryRank ? `rank ${m.categoryRank} in category` : undefined, "muted", cellTarget(m.cell)))}
          {returns.map((m) => tile(m.label, m.display, m.categoryRank ? `rank ${m.categoryRank} of ${m.categoryCount}` : undefined, "muted", cellTarget(m.cell)))}
          {firstReturn && tile(`Category average · ${firstReturn.label}`, formatMeasure(categoryMean, firstReturn, settings), `${formatCount(d.category.rated)} funds rated`)}
        </div>
        <Hero eyebrow={rank?.label ?? "Rank"} big={rankValue !== null ? formatCount(rankValue) : "—"} bigSuffix={rankValue !== null ? `/ ${formatCount(d.category.rated)}` : undefined} sub={d.category.key ? `within ${d.category.key}` : undefined}>
          <div className="flex items-center gap-[8px]">
            <QuartilePill q={qValue} size="md" label={qValue !== null ? `Q${qValue} · ${["", "top quartile", "second quartile", "third quartile", "bottom quartile"][qValue]}` : "unranked"} />
            {d.delta !== null && (
              <span className={cn("text-[12.5px] font-semibold", delta.direction === "up" ? "text-hero-up" : delta.direction === "down" ? "text-negative" : "text-hero-muted")}>
                {delta.direction === "flat" ? "unchanged" : `${delta.text} places`} {d.previous?.date ? `since ${d.previous.date}` : ""}
              </span>
            )}
          </div>
          {explanation.length > 0 && (
            <div className="border-t border-hero-line pt-[13px]">
              <ol className="m-0 list-none p-0 text-[11.5px] leading-[1.6] text-hero-muted" aria-label="Why this quartile">
                {explanation.map((line, i) => (
                  <li key={i} className={cn(i === explanation.length - 1 && "font-semibold text-hero-ink")}>
                    {line}
                  </li>
                ))}
              </ol>
              {quartile?.cell && (
                <button type="button" onClick={() => setTrace(cellTarget(quartile.cell))} className="mt-[8px] font-heading text-[12.5px] font-semibold text-hero-link hover:underline">
                  Trace this number →
                </button>
              )}
            </div>
          )}
        </Hero>
      </div>

      <div className="grid gap-[18px] md:grid-cols-12">
        <RCard className="md:col-span-7" title="Bull and bear phase returns" sub={`Fund vs category average · ${d.phases.length} phases defined in the workbook`}>
          {d.phases.length > 0 ? <PhaseBars phases={d.phases} unit={d.phases[0]?.unit} /> : <p className="m-0 text-[13px] text-muted">No phases configured.</p>}
        </RCard>
        <RCard className="md:col-span-5" title="Peers in category" sub={`${d.category.key ?? "—"} · by ${rank?.label.toLowerCase() ?? "rank"}`}>
          {d.peers.map((p) => (
            <MoverRow
              key={p.key}
              highlight={p.me}
              name={
                <>
                  <span className={cn("tabular mr-[8px] inline-block min-w-[22px]", p.me ? "text-accent" : "text-muted")}>{p.rank ?? "—"}</span>
                  {p.label}
                </>
              }
              right={
                <>
                  <QuartilePill q={p.quartile} />
                  <span className={cn("tabular min-w-[44px] text-right text-[11.5px] font-bold", p.me ? "text-accent" : "text-ink")}>{p.scoreLabel}</span>
                </>
              }
              onClick={p.me ? undefined : () => actions.openFund(p.key)}
            />
          ))}
        </RCard>
        {d.history.length > 1 && (
          <RCard className="md:col-span-12" title="History" sub="Rank and quartile in every genuine monthly upload">
            <ol className="m-0 flex list-none flex-wrap gap-[8px] p-0">
              {d.history.map((h) => (
                <li key={h.version_id} className="min-w-[120px] rounded-sm border border-hairline bg-surface-lifted px-[12px] py-[8px]">
                  <div className="text-[11px] text-muted">{h.date ?? h.filename}</div>
                  <div className="tabular font-heading text-lg font-semibold text-ink">{h.rank ?? "—"}</div>
                  <QuartilePill q={h.quartile} />
                </li>
              ))}
            </ol>
          </RCard>
        )}
        <RCard className="md:col-span-12" title="Every measure" sub="Click a value to trace it back through the workbook">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  {["Measure", "Value", "Rank in category", "Cell"].map((h, i) => (
                    <th key={h} scope="col" className={cn("border-b border-hairline px-[12px] py-[8px] text-left font-heading text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted", i > 0 && "text-right")}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.measures.map((m) => (
                  <tr key={m.key} className="border-b border-hairline last:border-b-0">
                    <td className="px-[12px] py-[8px] text-ink-2">{m.label}</td>
                    <td className="tabular px-[12px] py-[8px] text-right font-semibold text-ink">{m.role === "quartile" ? <QuartilePill q={m.value} /> : m.display}</td>
                    <td className="tabular px-[12px] py-[8px] text-right text-muted">{m.categoryRank ? `${m.categoryRank} / ${m.categoryCount}` : "—"}</td>
                    <td className="px-[12px] py-[8px] text-right">
                      {m.cell ? (
                        <button type="button" onClick={() => setTrace(cellTarget(m.cell))} className="tabular text-xs text-accent hover:underline" aria-label={`Trace ${m.label}`}>
                          {m.cell} →
                        </button>
                      ) : (
                        <span className="text-xs text-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RCard>
      </div>
      <ConfidentialFooter text={footer} />
      {versionId && <LineagePanel versionId={versionId} runId={d.run_id ?? null} target={trace} onClose={() => setTrace(null)} />}
    </div>
  );
}
