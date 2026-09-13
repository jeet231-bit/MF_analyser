import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getResearchEntities, researchExportUrl, scopeParam, type EntitiesPage, type EntityQuery, type EntityRow, type MeasureMeta, type Scope } from "@/api/research";
import { Button, EmptyState, ExportMenu, Select } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { formatMeasure, formatRankDelta, tableMeasures } from "./format";
import type { ResearchActions } from "./types";
import { Chip, Chips, ConfidentialFooter, LinkButton, NotConfigured, PageHead, QuartilePill, Skeleton } from "./ui";

const PAGE = 100;

/** Pivots whose group rows drill into that group's funds (they are also filters). */
const DRILLABLE = ["category", "amc", "plan"] as const;
type Drillable = (typeof DRILLABLE)[number];
const isDrillable = (key: string | undefined): key is Drillable => (DRILLABLE as readonly string[]).includes(key ?? "");

/**
 * The funds list. Its query (filters, pivot, sort, page) is owned by the caller so that the
 * screen comes back exactly as it was after a drill-through: App keeps it in the history entry.
 */
export function FundsPage({
  actions,
  query: outer,
  onQuery,
  footer,
  scope,
  scopeBar,
}: {
  actions: ResearchActions;
  query?: EntityQuery;
  onQuery: (next: EntityQuery) => void;
  footer?: string | null;
  scope?: Scope;
  scopeBar?: ReactNode;
}) {
  const settings = useFormat();
  const query = useMemo<EntityQuery>(() => ({ page: 1, size: PAGE, ...outer }), [outer]);
  const [search, setSearch] = useState(query.q ?? "");
  useEffect(() => {
    const t = setTimeout(() => {
      if (query.q !== (search || undefined)) onQuery({ ...query, q: search || undefined, page: 1 });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- debounce the typed text only
  }, [search]);

  const data = useAsync(() => getResearchEntities(query, scope), [JSON.stringify(query), scopeParam(scope)]);
  const body = data.data;
  const columns = useMemo(() => (body ? tableMeasures(body.measures) : []), [body]);
  const rankKey = body?.measures.find((m) => m.role === "rank" && m.primary)?.key;
  const qKey = body?.measures.find((m) => m.role === "quartile" && m.primary)?.key;

  const update = (patch: Partial<EntityQuery>) => onQuery({ ...query, ...patch, page: patch.page ?? 1 });

  if (data.status === "error") return <EmptyState tone="error" title="Could not load the funds" description={data.error} action={<Button onClick={data.reload}>Retry</Button>} />;
  if (!body) return <Skeleton rows={2} />;
  if (!body.configured) return <NotConfigured problems={body.problems} onOpenAdmin={actions.openAdmin} />;

  const dimLabel = (key: string) => body.dimensions.find((d) => d.key === key)?.label ?? key;
  const pivots: { key: string; label: string }[] = [
    ...body.dimensions,
    ...body.measures.filter((m) => m.role === "factor").map((m) => ({ key: `${m.key}_band`, label: `${m.label} band` })),
  ];
  const start = (body.page - 1) * body.size;
  const end = Math.min(start + body.rows.length, body.total);
  const sortable = (key: string, dirDefault: "asc" | "desc") => () =>
    update({ sort: key, dir: body.sort === key ? (body.dir === "asc" ? "desc" : "asc") : dirDefault });
  const exportQuery = { ...query, page: undefined, size: undefined };
  const active: { key: Drillable; value: string }[] = DRILLABLE.flatMap((k) => (query[k] ? [{ key: k, value: query[k] as string }] : []));
  const drill = isDrillable(query.groupBy) ? query.groupBy : null;
  const title = active.length === 1 ? active[0].value : "Funds";

  return (
    <div>
      <PageHead
        title={title}
        sub={
          active.length === 1
            ? `${dimLabel(active[0].key)} · ${formatCount(body.total)} funds · click any row for the full record`
            : `${formatCount(body.total)} funds${query.keys ? " in this selection" : ""} · click any row for the full record`
        }
        actions={
          <ExportMenu
            items={[
              { label: "This view (csv)", url: researchExportUrl("entities", "csv", exportQuery, scope), hint: "The current filter within the scope, every measure" },
              { label: "This view (xlsx)", url: researchExportUrl("entities", "xlsx", exportQuery, scope) },
            ]}
          />
        }
      />
      {scopeBar}

      {active.length > 0 && (
        <div className="mb-[12px] flex flex-wrap items-center gap-[6px] text-[12.5px] text-muted" data-testid="active-filters">
          <span>Showing</span>
          {active.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => update({ [f.key]: undefined })}
              className="inline-flex items-center gap-[6px] rounded-full glass-inset px-[10px] py-[3px] font-semibold text-ink hover:text-negative"
              aria-label={`Remove ${dimLabel(f.key)} filter ${f.value}`}
            >
              <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-muted">{dimLabel(f.key)}</span>
              {f.value}
              <span aria-hidden>×</span>
            </button>
          ))}
          <LinkButton onClick={() => actions.openFunds({})}>All funds</LinkButton>
        </div>
      )}

      <div className="mb-[16px] flex flex-wrap items-center gap-[7px] rounded-lg glass px-[14px] py-[12px]" role="group" aria-label="Analyse funds by">
        <span className="mr-[4px] text-[10.5px] font-bold uppercase tracking-[0.1em] text-muted">Analyse funds by</span>
        <Chip pressed={!query.groupBy} onClick={() => update({ groupBy: undefined })}>
          None
        </Chip>
        {pivots.map((p) => (
          <Chip key={p.key} pressed={query.groupBy === p.key} onClick={() => update({ groupBy: query.groupBy === p.key ? undefined : p.key })}>
            {p.label}
          </Chip>
        ))}
        {drill && <span className="ml-auto text-[11.5px] text-muted">Click a {dimLabel(drill).toLowerCase()} row to see only its funds</span>}
      </div>

      <div className="mb-[16px] flex flex-wrap items-center gap-[8px]">
        <label className="flex min-w-[200px] flex-1 items-center gap-[8px] rounded-full glass px-[14px]">
          <span className="text-muted" aria-hidden>
            ⌕
          </span>
          <input
            type="search"
            aria-label="Search fund or AMC"
            placeholder="Search fund or AMC…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent py-[9px] text-[13px] text-ink outline-none"
          />
        </label>
        {body.facets.category && (
          <Select aria-label="Category" value={query.category ?? ""} onChange={(e) => update({ category: e.target.value || undefined })} className="py-[8px]">
            <option value="">All categories</option>
            {body.facets.category.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )}
        {body.facets.amc && (
          <Select aria-label="AMC" value={query.amc ?? ""} onChange={(e) => update({ amc: e.target.value || undefined })} className="py-[8px]">
            <option value="">All AMCs</option>
            {body.facets.amc.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )}
        {body.facets.plan && (
          <div role="group" aria-label="Plan" className="flex gap-[6px]">
            <Chip pressed={!query.plan} onClick={() => update({ plan: undefined })}>
              All
            </Chip>
            {body.facets.plan.map((p) => (
              <Chip key={p} pressed={query.plan === p} onClick={() => update({ plan: query.plan === p ? undefined : p })}>
                {p}
              </Chip>
            ))}
          </div>
        )}
        <Chips
          label="Quartile"
          options={[1, 2, 3, 4].map((q) => ({ value: String(q), label: `Q${q}` }))}
          value={(query.quartile ?? []).map(String)}
          onChange={(next) => update({ quartile: next.length ? next.map(Number) : undefined })}
        />
        {query.keys && <LinkButton onClick={() => actions.openFunds({})}>Clear selection ×</LinkButton>}
      </div>

      <FundsTable
        body={body}
        columns={columns}
        rankKey={rankKey}
        qKey={qKey}
        onSort={sortable}
        onOpen={actions.openFund}
        onOpenGroup={drill ? (value) => update({ [drill]: value, groupBy: undefined }) : undefined}
        settings={settings}
      />

      <p className="m-0 mt-[12px] flex flex-wrap items-center gap-[12px] px-[2px] text-xs text-muted">
        <span>
          Showing {body.total === 0 ? 0 : formatCount(start + 1)}–{formatCount(end)} of {formatCount(body.total)}
        </span>
        {body.page > 1 && <LinkButton onClick={() => update({ page: body.page - 1 })}>← Previous</LinkButton>}
        {end < body.total && <LinkButton onClick={() => update({ page: body.page + 1 })}>Next {formatCount(Math.min(PAGE, body.total - end))} →</LinkButton>}
      </p>
      <ConfidentialFooter text={footer} />
    </div>
  );
}

function FundsTable({
  body,
  columns,
  rankKey,
  qKey,
  onSort,
  onOpen,
  onOpenGroup,
  settings,
}: {
  body: EntitiesPage;
  columns: MeasureMeta[];
  rankKey?: string;
  qKey?: string;
  onSort: (key: string, dirDefault: "asc" | "desc") => () => void;
  onOpen: (key: string) => void;
  onOpenGroup?: (value: string) => void;
  settings: ReturnType<typeof useFormat>;
}) {
  const th = (label: string, key?: string, numeric = true, dirDefault: "asc" | "desc" = "desc") => (
    <th
      key={label}
      scope="col"
      aria-sort={key && body.sort === key ? (body.dir === "asc" ? "ascending" : "descending") : undefined}
      className={cn("sticky top-0 whitespace-nowrap border-b border-hairline bg-surface-lifted px-[14px] py-[11px] text-left font-heading text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted", numeric && "text-right")}
    >
      {key ? (
        <button type="button" onClick={onSort(key, dirDefault)} className="font-heading uppercase hover:text-accent">
          {label}
          {body.sort === key ? (body.dir === "asc" ? " ↑" : " ↓") : ""}
        </button>
      ) : (
        label
      )}
    </th>
  );
  const groups = body.groups;
  const rowsByGroup = new Map<string, EntityRow[]>();
  if (groups) for (const r of body.rows) rowsByGroup.set(r.group ?? "—", [...(rowsByGroup.get(r.group ?? "—") ?? []), r]);

  const row = (r: EntityRow) => (
    <tr key={r.key} onClick={() => onOpen(r.key)} className="cursor-pointer border-b border-hairline last:border-b-0 hover:bg-surface-lifted">
      <td className="whitespace-nowrap px-[14px] py-[11px]">
        <div className="font-semibold text-ink">{r.label}</div>
        <div className="text-[11.5px] text-muted">{r.sub}</div>
      </td>
      <td className="whitespace-nowrap px-[14px] py-[11px] text-ink-2">{r.dims.category ?? "—"}</td>
      {columns.map((m) =>
        m.key === qKey ? (
          <td key={m.key} className="px-[14px] py-[11px]">
            <QuartilePill q={r.measures[m.key]} />
          </td>
        ) : (
          <td key={m.key} className="tabular whitespace-nowrap px-[14px] py-[11px] text-right text-ink">
            {formatMeasure(r.measures[m.key], m, settings, r.raw[m.key])}
          </td>
        ),
      )}
      <td className={cn("tabular whitespace-nowrap px-[14px] py-[11px] text-right font-semibold", deltaClass(r))}>{r.delta?.new ? "new" : formatRankDelta(r.delta?.rank).text}</td>
    </tr>
  );

  return (
    <div className="overflow-x-auto rounded-lg glass rise">
      <table className="w-full min-w-[720px] border-collapse text-[13px]">
        <thead>
          <tr>
            {th("Fund", undefined, false)}
            {th("Category", undefined, false)}
            {columns.map((m) => th(m.label, m.key, true, m.role === "rank" || m.role === "quartile" || !m.higherIsBetter ? "asc" : "desc"))}
            {th(`Δ rank${body.previous ? ` vs ${body.previous.date ?? body.previous.filename}` : ""}`, undefined)}
          </tr>
        </thead>
        <tbody>
          {body.rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + 3} className="px-[14px] py-[24px] text-center text-muted">
                No fund matches this filter.
              </td>
            </tr>
          )}
          {groups
            ? groups.map((g) => {
                const members = rowsByGroup.get(g.key) ?? [];
                if (members.length === 0) return null;
                return [
                  <tr
                    key={`g-${g.key}`}
                    className={cn("bg-surface-lifted", onOpenGroup && "cursor-pointer hover:bg-accent-soft")}
                    data-testid="group-row"
                    onClick={onOpenGroup ? () => onOpenGroup(g.key) : undefined}
                    title={onOpenGroup ? `Show only ${g.label}` : undefined}
                  >
                    <td className="px-[14px] py-[8px] font-heading text-xs font-semibold text-ink" colSpan={2}>
                      {onOpenGroup ? (
                        <button type="button" className="font-heading text-xs font-semibold text-accent hover:underline" aria-label={`Show only ${g.label}`}>
                          {g.label} →
                        </button>
                      ) : (
                        g.label
                      )}{" "}
                      <span className="tabular font-normal text-muted">· {formatCount(g.count)} funds</span>
                    </td>
                    {columns.map((m) => (
                      <td key={m.key} className="tabular px-[14px] py-[8px] text-right text-xs font-semibold text-ink-2">
                        {m.key === qKey ? (g.subtotals.q1 !== undefined ? `${g.subtotals.q1} Q1` : "") : m.key === rankKey ? "" : subtotal(g.subtotals[m.key], m, settings)}
                      </td>
                    ))}
                    <td />
                  </tr>,
                  ...members.map(row),
                ];
              })
            : body.rows.map(row)}
        </tbody>
      </table>
    </div>
  );
}

function subtotal(v: number | null | undefined, m: MeasureMeta, settings: ReturnType<typeof useFormat>): string {
  if (v === null || v === undefined) return "";
  return `avg ${formatMeasure(v, m, settings)}`;
}

function deltaClass(r: EntityRow): string {
  const d = r.delta?.rank;
  if (d === null || d === undefined) return "text-muted";
  return d > 0 ? "text-positive" : d < 0 ? "text-negative" : "text-muted";
}
