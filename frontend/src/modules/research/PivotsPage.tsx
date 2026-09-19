import { type ReactNode } from "react";
import {
  exploreExportUrl,
  getExplore,
  scopeParam,
  type EntityQuery,
  type ExploreGroup,
  type ExploreQuery,
  type ExploreResponse,
  type PivotListing,
  type PivotQuery,
  type Scope,
} from "@/api/research";
import { Button, EmptyState, ExportMenu, Select } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount, formatNumber } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { formatMeasure } from "./format";
import { defaultQuery, type PivotLocation } from "./pivotQuery";
import type { ResearchActions } from "./types";
import { ConfidentialFooter, LinkButton, Narrative, NotConfigured, PageHead, QuartileBar, RCard, Skeleton } from "./ui";
import { WorkbookPivot } from "./WorkbookPivot";

/** Groupings the Funds page can filter by, so a row can drill into its own funds. */
const FUND_FILTERS: (keyof EntityQuery)[] = ["category", "amc", "plan"];

const AGG_LABELS: Record<string, string> = {
  mean: "average",
  median: "median",
  sum: "total",
  min: "lowest",
  max: "highest",
};

export function PivotsPage({
  query,
  onQuery,
  pivots,
  location,
  onOpen,
  onPivotQuery,
  scope,
  scopeBar,
  actions,
  footer,
}: {
  query: ExploreQuery;
  onQuery: (q: ExploreQuery) => void;
  pivots: ReturnType<typeof useAsync<PivotListing>>;
  location: PivotLocation;
  onOpen: (id: string | null) => void;
  onPivotQuery: (q: PivotQuery) => void;
  scope?: Scope;
  scopeBar?: ReactNode;
  actions: ResearchActions;
  footer?: string | null;
}) {
  const listing = pivots.data;
  const selected = location.id && listing?.configured ? listing.pivots.find((p) => p.id === location.id) : undefined;
  if (location.id && listing && !selected) {
    return <EmptyState title="That layout is not in the active workbook" description={location.id} action={<Button onClick={() => onOpen(null)}>Back to Pivots</Button>} />;
  }
  if (selected && listing) {
    return (
      <WorkbookPivot
        pivot={selected}
        listing={listing}
        query={location.query ?? defaultQuery(selected, scope, listing.scopeFields)}
        isDefault={!location.query}
        onQuery={onPivotQuery}
        onBack={() => onOpen(null)}
        actions={actions}
        footer={footer}
      />
    );
  }
  return <ExploreBoard query={query} onQuery={onQuery} pivots={pivots} onOpen={onOpen} scope={scope} scopeBar={scopeBar} actions={actions} footer={footer} />;
}

/** Owns the request, so it only runs while the builder is the screen on show. */
function ExploreBoard(props: {
  query: ExploreQuery;
  onQuery: (q: ExploreQuery) => void;
  pivots: ReturnType<typeof useAsync<PivotListing>>;
  onOpen: (id: string) => void;
  scope?: Scope;
  scopeBar?: ReactNode;
  actions: ResearchActions;
  footer?: string | null;
}) {
  const { query, scope } = props;
  const explore = useAsync(() => getExplore(query, scope), [JSON.stringify(query), scopeParam(scope)]);
  return <ExploreView {...props} explore={explore} />;
}

function ExploreView({
  explore,
  query,
  onQuery,
  pivots,
  onOpen,
  scopeBar,
  actions,
  footer,
}: {
  explore: ReturnType<typeof useAsync<ExploreResponse>>;
  query: ExploreQuery;
  onQuery: (q: ExploreQuery) => void;
  pivots: ReturnType<typeof useAsync<PivotListing>>;
  onOpen: (id: string) => void;
  scopeBar?: ReactNode;
  actions: ResearchActions;
  footer?: string | null;
}) {
  const settings = useFormat();
  if (explore.status === "error") {
    return <EmptyState tone="error" title="Could not group the funds" description={explore.error} action={<Button onClick={explore.reload}>Retry</Button>} />;
  }
  if (!explore.data) return <Skeleton rows={3} />;
  const body = explore.data;
  if (!body.configured) return <NotConfigured problems={body.problems} onOpenAdmin={actions.openAdmin} />;

  const update = (patch: Partial<ExploreQuery>) => onQuery({ ...query, ...patch });
  const previous = body.compare.previous?.date ?? null;
  const comparing = body.compare.available && query.compare !== false;
  const showingAll = body.limit === 0 || body.groups.length >= body.groupCount;
  const drillKey = FUND_FILTERS.find((k) => k === body.by.key);

  return (
    <div>
      <PageHead
        title="Pivots"
        sub="Group every fund by anything the master knows, and see what moved since last month."
        actions={
          <ExportMenu
            items={[
              { label: "This table (xlsx)", url: exploreExportUrl({ ...query, limit: 0 }, "xlsx"), hint: "Every group, with its change" },
              { label: "This table (csv)", url: exploreExportUrl({ ...query, limit: 0 }, "csv") },
            ]}
          />
        }
      />
      {scopeBar}

      <RCard className="mb-[18px]" tone="sky" eyebrow="The question" title={<span className="sr-only">Build the question</span>} data-testid="question-bar">
        <div className="flex flex-wrap items-center gap-x-[8px] gap-y-[10px] font-heading text-[16px] text-ink">
          <span>Show the</span>
          <Select aria-label="Aggregation" value={body.agg} onChange={(e) => update({ agg: e.target.value })} className="py-[7px] text-[13.5px]">
            {body.options.aggs.map((a) => (
              <option key={a} value={a}>
                {AGG_LABELS[a] ?? a}
              </option>
            ))}
          </Select>
          <Select aria-label="Measure" value={body.measure.key} onChange={(e) => update({ measure: e.target.value, sort: undefined, dir: undefined })} className="py-[7px] text-[13.5px]">
            {body.options.measures.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </Select>
          <span>by</span>
          <Select aria-label="Grouping" value={body.by.key} onChange={(e) => update({ by: e.target.value, sort: undefined, dir: undefined })} className="py-[7px] text-[13.5px]">
            {body.options.by.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          {body.compare.available ? (
            <label className="ml-[4px] flex cursor-pointer items-center gap-[6px] rounded-full glass-inset px-[12px] py-[6px] text-[12.5px] font-semibold text-ink-2">
              <input type="checkbox" checked={comparing} onChange={(e) => update({ compare: e.target.checked })} />
              compared with {previous ?? "last month"}
            </label>
          ) : (
            <span className="ml-[4px] text-[12px] text-muted">{body.compare.note}</span>
          )}
        </div>
        {body.presets.length > 0 && (
          <div className="mt-[14px] flex flex-wrap items-center gap-[6px]" role="group" aria-label="Starting points">
            <span className="mr-[2px] text-[10.5px] font-bold uppercase tracking-[0.1em] text-muted">Start from</span>
            {body.presets.map((p) => {
              const on = p.by === body.by.key && (!p.measure || p.measure === body.measure.key);
              return (
                <button
                  key={p.label}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onQuery({ ...query, by: p.by, measure: p.measure, agg: p.agg ?? "mean", sort: p.sort, dir: undefined })}
                  className={cn("rounded-full px-[12px] py-[5px] text-[12px] font-semibold", on ? "bg-accent text-white" : "glass-inset text-ink-2 hover:text-accent")}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        )}
      </RCard>

      <Narrative text={body.narrative} className="mb-[16px] text-[14px]" />

      <ExploreGrid
        body={body}
        settings={settings}
        comparing={comparing}
        onDrill={drillKey ? (label) => actions.openFunds({ [drillKey]: label }) : undefined}
      />

      <p className="m-0 mt-[12px] flex flex-wrap items-center gap-[12px] px-[2px] text-xs text-muted">
        <span>
          {showingAll ? `All ${formatCount(body.groupCount)}` : `Top ${formatCount(body.groups.length)} of ${formatCount(body.groupCount)}`} by {body.sort === "value" ? body.measure.label.toLowerCase() : body.sort.replace("_", " ")}
        </span>
        {!showingAll && <LinkButton onClick={() => update({ limit: 0 })}>Show all {formatCount(body.groupCount)} →</LinkButton>}
        {showingAll && body.groupCount > 15 && <LinkButton onClick={() => update({ limit: 15 })}>Show the top 15</LinkButton>}
        {body.groups.some((g) => g.small) && <span>A group with fewer than {body.minGroupCount} rated funds is marked "few rated" and never ranked.</span>}
      </p>

      <WorkbookLayouts pivots={pivots} onOpen={onOpen} />
      <ConfidentialFooter text={footer ?? body.footer} />
    </div>
  );
}

/** ▲ / ▼ against the previous month, coloured by whether the move is good for this measure. */
function Delta({
  value,
  betterWhen = "higher",
  render,
  className,
}: {
  value: number | null | undefined;
  betterWhen?: "higher" | "lower" | "neither";
  render: (abs: number) => string;
  className?: string;
}) {
  if (value === null || value === undefined || Math.abs(value) < 1e-9) return null;
  const up = value > 0;
  const good = betterWhen === "neither" ? null : (betterWhen === "higher") === up;
  return (
    <div className={cn("tabular text-[11px] font-semibold", good === null ? "text-muted" : good ? "text-positive" : "text-negative", className)}>
      {up ? "▲" : "▼"} {render(Math.abs(value))}
    </div>
  );
}

function ExploreGrid({
  body,
  settings,
  comparing,
  onDrill,
}: {
  body: ExploreResponse;
  settings: ReturnType<typeof useFormat>;
  comparing: boolean;
  onDrill?: (label: string) => void;
}) {
  const meta = { ...body.measure, primary: false };
  const values = body.groups.map((g) => g.value).filter((v): v is number => v !== null);
  const low = values.length ? Math.min(...values) : 0;
  const high = values.length ? Math.max(...values) : 0;
  const heat = (v: number | null): number => {
    if (v === null || high === low) return 0;
    const share = (v - low) / (high - low);
    return Math.round((body.measure.higherIsBetter ? share : 1 - share) * 100);
  };
  const th = "sticky top-0 whitespace-nowrap border-b border-hairline bg-surface-lifted px-[12px] py-[10px] text-left font-heading text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted";
  const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${formatNumber(v * 100, { decimals: 0 })}%`);

  const cells = (g: ExploreGroup | ExploreResponse["totals"], total = false) => (
    <>
      <td className="px-[12px] py-[10px] text-right">
        <div className="tabular text-ink">{formatCount(g.funds)}</div>
        {comparing && <Delta value={g.delta?.funds} betterWhen="neither" render={(n) => formatCount(n)} className="text-right" />}
      </td>
      <td className="px-[12px] py-[10px]">
        <QuartileBar counts={g.quartiles} height={18} className="min-w-[110px]" />
      </td>
      <td className="px-[12px] py-[10px] text-right">
        <div className="tabular text-ink">{pct(g.q1Share)}</div>
        {comparing && <Delta value={g.delta?.q1Share} render={(n) => `${formatNumber(n * 100, { decimals: 0 })}pp`} className="text-right" />}
      </td>
      <td className="relative px-[12px] py-[10px] text-right">
        {!total && (
          <span
            aria-hidden
            className="absolute inset-y-[6px] left-0 rounded-sm bg-accent-soft"
            style={{ width: `${heat(g.value as number | null)}%` }}
          />
        )}
        <div className="tabular relative text-ink">{formatMeasure(g.value, meta, settings)}</div>
        {comparing && <Delta value={g.delta?.value} betterWhen={body.measure.higherIsBetter ? "higher" : "lower"} render={(n) => formatMeasure(n, meta, settings)} className="relative text-right" />}
      </td>
      <td className="px-[12px] py-[10px] text-right">
        <div className="tabular text-ink">{g.medianRank === null ? "—" : formatNumber(g.medianRank, { decimals: 0 })}</div>
        {comparing && <Delta value={g.delta?.medianRank} betterWhen="lower" render={(n) => formatNumber(n, { decimals: 0 })} className="text-right" />}
      </td>
    </>
  );

  return (
    <div className="overflow-x-auto rounded-lg glass rise" data-testid="explore-grid">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            <th className={th}>{body.by.label}</th>
            <th className={cn(th, "text-right")}>Funds</th>
            <th className={th}>Quartile mix</th>
            <th className={cn(th, "text-right")}>Top quartile</th>
            <th className={cn(th, "text-right")}>
              {AGG_LABELS[body.agg] ?? body.agg} {body.measure.label.toLowerCase()}
            </th>
            <th className={cn(th, "text-right")}>Median rank</th>
          </tr>
        </thead>
        <tbody>
          {body.groups.length === 0 && (
            <tr>
              <td colSpan={6} className="px-[12px] py-[24px] text-center text-muted">
                No fund in scope carries this grouping.
              </td>
            </tr>
          )}
          {body.groups.map((g) => (
            <tr key={g.key} className="border-b border-hairline last:border-b-0 hover:bg-ink/5" data-testid="explore-row">
              <td className="max-w-[320px] px-[12px] py-[10px]">
                {onDrill ? (
                  <button type="button" onClick={() => onDrill(g.label)} className="text-left font-semibold text-ink hover:text-accent" title={`Show the funds in ${g.label}`}>
                    {g.label}
                  </button>
                ) : (
                  <span className="font-semibold text-ink">{g.label}</span>
                )}
                <div className="flex flex-wrap items-center gap-[6px] text-[11px] text-muted">
                  <span>{formatCount(g.rated)} rated</span>
                  {g.small && <span className="rounded-full bg-warning-soft px-[6px] py-px font-semibold text-warning">few rated</span>}
                  {comparing && g.delta?.new && <span className="rounded-full bg-accent-soft px-[6px] py-px font-semibold text-accent">new</span>}
                </div>
              </td>
              {cells(g)}
            </tr>
          ))}
          <tr className="bg-accent-soft font-bold" data-testid="explore-total">
            <td className="px-[12px] py-[10px] text-ink">
              All funds in scope
              <div className="text-[11px] font-normal text-ink-2">{formatCount(body.totals.rated)} rated</div>
            </td>
            {cells(body.totals, true)}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** The seventeen layouts frozen into the workbook, for anyone who wants the familiar shape. */
function WorkbookLayouts({ pivots, onOpen }: { pivots: ReturnType<typeof useAsync<PivotListing>>; onOpen: (id: string) => void }) {
  const listing = pivots.data;
  if (!listing?.configured || listing.pivots.length === 0) return null;
  return (
    <details className="mt-[26px] rounded-xl glass px-[20px] py-[16px]" data-testid="workbook-layouts">
      <summary className="cursor-pointer list-none font-heading text-[14px] font-bold text-ink">
        The workbook's own pivot layouts <span className="tabular ml-[6px] rounded-full glass-inset px-[9px] py-[2px] text-[11px] font-semibold text-ink-2">{listing.pivots.length}</span>
        <span className="ml-[8px] text-[12px] font-normal text-muted">recomputed from today's numbers, not the copy Excel saved</span>
      </summary>
      <ul className="m-0 mt-[12px] grid list-none gap-[6px] p-0 md:grid-cols-2">
        {listing.pivots.map((p) => (
          <li key={p.id}>
            <button type="button" onClick={() => onOpen(p.id)} className="flex w-full items-baseline gap-[8px] rounded-sm px-[8px] py-[6px] text-left text-[12.5px] hover:bg-ink/5">
              <span className="font-semibold text-ink">{p.sheet}</span>
              <span className="text-muted">
                {p.layout.rows.join(" › ") || "—"} over {p.source.sheet}
              </span>
              {!p.source.live && <span className="ml-auto rounded-full bg-warning-soft px-[6px] py-px text-[10px] font-semibold text-warning">cached</span>}
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}
