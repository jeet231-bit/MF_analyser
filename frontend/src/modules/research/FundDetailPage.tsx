import { useState } from "react";
import { getResearchEntities, getResearchEntity, type EntityMeasure } from "@/api/research";
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

/** The dimensions whose facts open a filtered fund list. */
const LINKED: Record<string, "category" | "amc" | "plan"> = { category: "category", amc: "amc", plan: "plan" };

export function FundDetailPage({
  fundKey,
  actions,
  footer,
  backLabel,
}: {
  fundKey: string;
  actions: ResearchActions;
  footer?: string | null;
  /** Name of the screen Back returns to ("all funds", "funds · Axis", "dashboard"); null when there is none. */
  backLabel?: string | null;
}) {
  const data = useAsync(() => getResearchEntity(fundKey), [fundKey]);
  const settings = useFormat();
  const watch = useWatchlist();
  const [trace, setTrace] = useState<LineageTarget | null>(null);
  const amc = data.data?.configured ? (data.data.entity.dims.amc ?? null) : null;
  const siblings = useAsync(() => (amc ? getResearchEntities({ amc, size: 200 }) : Promise.resolve(null)), [amc]);

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
  const dimLabel = (key: string) => d.dimensions?.find((x) => x.key === key)?.label ?? key;
  const facts = Object.entries(d.entity.dims).filter(([, v]) => v);

  const family = siblings.data?.configured ? siblings.data.rows : [];
  const me = family.findIndex((r) => r.key === d.entity.key);
  const prev = me > 0 ? family[me - 1] : null;
  const next = me >= 0 && me < family.length - 1 ? family[me + 1] : null;
  const others = family.filter((r) => r.key !== d.entity.key);
  const familyQ = siblings.data?.configured ? siblings.data.measures.find((m) => m.role === "quartile" && m.primary)?.key : undefined;

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
          <LinkButton onClick={actions.goBack} className="mb-[6px]">
            ← Back to {backLabel ?? "all funds"}
          </LinkButton>
        }
        title={d.entity.label}
        sub={d.entity.sub ?? d.entity.key}
        actions={
          <>
            {amc && family.length > 1 && (
              <span className="flex items-center gap-[4px]" role="group" aria-label={`Other funds from ${amc}`}>
                <Button size="sm" disabled={!prev} onClick={prev ? () => actions.openFund(prev.key) : undefined} title={prev?.label} aria-label={prev ? `Previous fund from ${amc}: ${prev.label}` : "No previous fund from this AMC"}>
                  ← Prev
                </Button>
                <span className="tabular text-[11.5px] text-muted">
                  {me + 1} of {family.length}
                </span>
                <Button size="sm" disabled={!next} onClick={next ? () => actions.openFund(next.key) : undefined} title={next?.label} aria-label={next ? `Next fund from ${amc}: ${next.label}` : "No next fund from this AMC"}>
                  Next →
                </Button>
              </span>
            )}
            <Button aria-pressed={watching} onClick={() => watch.toggle({ key: d.entity.key, label: d.entity.label, sub: d.entity.sub })}>
              {watching ? "★ Watching" : "☆ Watch"}
            </Button>
          </>
        }
      />

      {/* Who this fund is: every dimension labelled, in words a newcomer can read. */}
      <dl className="-mt-[6px] mb-[18px] grid gap-[8px] sm:grid-cols-2 lg:grid-cols-4" aria-label="About this fund">
        {facts.map(([key, value]) => {
          const filter = LINKED[key];
          return (
            <div key={key} className="min-w-0 rounded-md glass-inset px-[12px] py-[8px]">
              <dt className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted">{dimLabel(key)}</dt>
              <dd className="m-0 mt-[1px] flex flex-wrap items-baseline gap-x-[8px] text-[13px] font-semibold text-ink">
                <span className="min-w-0 break-words">{String(value)}</span>
                {filter && (
                  <LinkButton className="text-[11.5px] font-semibold" onClick={() => actions.openFunds({ [filter]: String(value) })}>
                    all funds →
                  </LinkButton>
                )}
              </dd>
            </div>
          );
        })}
        <div className="min-w-0 rounded-md glass-inset px-[12px] py-[8px]">
          <dt className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted">Position in the master</dt>
          <dd className="m-0 mt-[1px] text-[13px] font-semibold text-ink">
            Row {formatCount(d.row)} <span className="font-normal text-muted">of the fund sheet</span>
          </dd>
        </div>
      </dl>
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
        {amc && others.length > 0 && (
          <RCard
            className="md:col-span-12"
            eyebrow={dimLabel("amc")}
            title={`More from ${amc}`}
            badge={formatCount(family.length)}
            sub="Every other fund this house runs, in rank order · click one to open it"
            action={<LinkButton onClick={() => actions.openFunds({ amc })}>Open the list →</LinkButton>}
            data-testid="amc-siblings"
          >
            <div className="grid gap-x-[24px] md:grid-cols-2">
              {others.map((r) => (
                <MoverRow key={r.key} name={r.label} context={r.dims.category ?? r.sub} right={familyQ ? <QuartilePill q={r.measures[familyQ]} /> : undefined} onClick={() => actions.openFund(r.key)} />
              ))}
            </div>
          </RCard>
        )}
        {d.history.length > 1 && (
          <RCard className="md:col-span-12" title="History" sub="Rank and quartile in every genuine monthly upload">
            <ol className="m-0 flex list-none flex-wrap gap-[8px] p-0">
              {d.history.map((h) => (
                <li key={h.version_id} className="min-w-[120px] rounded-sm glass-inset px-[12px] py-[8px]">
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
