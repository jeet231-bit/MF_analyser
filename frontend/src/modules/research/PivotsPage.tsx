import { useMemo, useState, type ReactNode } from "react";
import { getPivot, pivotExportUrl, type PivotListing, type PivotQuery, type PivotSummary, type PivotTable, type PivotValueSpec, type Scope } from "@/api/research";
import { Button, EmptyState, ExportMenu, Select } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount, formatDate, formatNumber } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { AGGREGATIONS as AGGS, aggLabel, defaultQuery, type PivotLocation } from "./pivotQuery";
import type { ResearchActions } from "./types";
import { Chip, ConfidentialFooter, LinkButton, Note, PageHead, RCard, SectionHeader, Skeleton } from "./ui";

export function PivotsPage({
  pivots,
  location,
  onOpen,
  onQuery,
  scope,
  actions,
  footer,
}: {
  pivots: ReturnType<typeof useAsync<PivotListing>>;
  location: PivotLocation;
  onOpen: (id: string | null) => void;
  onQuery: (query: PivotQuery) => void;
  scope?: Scope;
  actions: ResearchActions;
  footer?: string | null;
}) {
  if (pivots.status === "error") return <EmptyState tone="error" title="Could not load the pivots" description={pivots.error} action={<Button onClick={pivots.reload}>Retry</Button>} />;
  if (!pivots.data) return <Skeleton rows={3} />;
  const listing = pivots.data;
  if (!listing.configured || listing.pivots.length === 0) {
    return (
      <div>
        <PageHead title="Pivots" sub="The workbook's own pivot tables, recomputed from the engine" />
        <EmptyState title="No pivot tables in the active workbook" description={listing.problems.join(" · ") || "Add a pivot table to the master and upload it again."} action={<Button onClick={actions.openUpload}>Upload a version</Button>} />
      </div>
    );
  }
  const selected = location.id ? listing.pivots.find((p) => p.id === location.id) : undefined;
  if (location.id && !selected) {
    return <EmptyState title="This pivot is not in the active workbook" description={location.id} action={<Button onClick={() => onOpen(null)}>All pivots</Button>} />;
  }
  if (!selected) return <PivotList listing={listing} onOpen={onOpen} footer={footer} />;
  return <PivotView pivot={selected} listing={listing} query={location.query ?? defaultQuery(selected, scope, listing.scopeFields)} isDefault={!location.query} onQuery={onQuery} onBack={() => onOpen(null)} actions={actions} footer={footer} />;
}

function sourceLabel(p: PivotSummary): ReactNode {
  return p.source.live ? (
    <span className="rounded-full bg-positive-soft px-[8px] py-[2px] text-[10.5px] font-bold text-positive">live from the engine</span>
  ) : (
    <span className="rounded-full bg-warning-soft px-[8px] py-[2px] text-[10.5px] font-bold text-warning">cached values (sheet outside the engine scope)</span>
  );
}

function PivotList({ listing, onOpen, footer }: { listing: PivotListing; onOpen: (id: string) => void; footer?: string | null }) {
  const bySource = new Map<string, PivotSummary[]>();
  for (const p of listing.pivots) bySource.set(p.source.sheet, [...(bySource.get(p.source.sheet) ?? []), p]);
  let i = 0;
  return (
    <div>
      <PageHead title="Pivots" sub={`${formatCount(listing.pivots.length)} pivot tables defined in the workbook · each one recomputed here from the engine's numbers, with every filter available`} />
      {[...bySource.entries()].map(([source, items]) => (
        <section key={source} aria-label={`Pivots over ${source}`}>
          <SectionHeader icon="▦" title={`Over ${source}`} sub={`${formatCount(items[0].source.records)} records · ${items.length} ${items.length === 1 ? "pivot" : "pivots"}`} />
          <div className="grid gap-[18px] md:grid-cols-12">
            {items.map((p) => (
              <RCard key={p.id} className="md:col-span-4 lift cursor-pointer" index={i++} eyebrow={p.name} title={p.sheet} badge={formatCount(p.source.records)} data-testid="pivot-card">
                <button type="button" className="block w-full text-left" onClick={() => onOpen(p.id)} aria-label={`Open pivot ${p.sheet}`}>
                  <dl className="m-0 grid gap-[4px] text-[12.5px]">
                    <div>
                      <dt className="inline text-muted">Rows: </dt>
                      <dd className="inline text-ink">{p.layout.rows.join(" › ") || "—"}</dd>
                    </div>
                    {p.layout.cols.length > 0 && (
                      <div>
                        <dt className="inline text-muted">Columns: </dt>
                        <dd className="inline text-ink">{p.layout.cols.join(" › ")}</dd>
                      </div>
                    )}
                    <div>
                      <dt className="inline text-muted">Filters: </dt>
                      <dd className="inline text-ink">{p.layout.filters.join(", ") || "none"}</dd>
                    </div>
                    <div>
                      <dt className="inline text-muted">Values: </dt>
                      <dd className="inline text-ink">{p.layout.values.map((v) => v.label).join(", ")}</dd>
                    </div>
                  </dl>
                  <div className="mt-[10px] flex flex-wrap items-center gap-[6px] text-[11px] text-muted">
                    {sourceLabel(p)}
                    {p.source.refreshed && <span>Excel last refreshed it {formatDate(p.source.refreshed)}</span>}
                  </div>
                </button>
              </RCard>
            ))}
          </div>
        </section>
      ))}
      <ConfidentialFooter text={footer} />
    </div>
  );
}

function PivotView({
  pivot,
  listing,
  query,
  isDefault,
  onQuery,
  onBack,
  actions,
  footer,
}: {
  pivot: PivotSummary;
  listing: PivotListing;
  query: PivotQuery;
  isDefault: boolean;
  onQuery: (q: PivotQuery) => void;
  onBack: () => void;
  actions: ResearchActions;
  footer?: string | null;
}) {
  const settings = useFormat();
  const key = JSON.stringify(query);
  const table = useAsync(() => getPivot(pivot.id, query), [pivot.id, key]);
  const kinds = table.data?.fieldKinds ?? {};
  const textFields = pivot.fields.filter((f) => (kinds[f.name] ?? (f.numeric ? "number" : "text")) === "text").map((f) => f.name);
  const numberFields = pivot.fields.filter((f) => (kinds[f.name] ?? (f.numeric ? "number" : "text")) === "number").map((f) => f.name);
  const filterFields = useMemo(() => [...new Set([...pivot.layout.filters, ...Object.keys(query.filters)])], [pivot.layout.filters, query.filters]);
  const update = (patch: Partial<PivotQuery>) => onQuery({ ...query, ...patch });
  const toggle = (list: string[], name: string) => (list.includes(name) ? list.filter((x) => x !== name) : [...list, name]);
  const valueFor = (field: string) => query.values.find((v) => v.field === field);
  const toggleValue = (field: string) => {
    const existing = valueFor(field);
    if (existing) update({ values: query.values.filter((v) => v.field !== field) });
    else {
      const agg = numberFields.includes(field) ? "average" : "count";
      update({ values: [...query.values, { label: `${aggLabel(agg)} of ${field}`, field, agg }] });
    }
  };
  const setAgg = (field: string, agg: string) =>
    update({ values: query.values.map((v) => (v.field === field ? { ...v, agg, label: `${aggLabel(agg)} of ${field}` } : v)) });
  const filterText = filterFields
    .filter((f) => (query.filters[f] ?? []).length > 0)
    .map((f) => `${f}: ${(query.filters[f] ?? []).join(", ")}`)
    .join(" · ");
  const spare = textFields.filter((f) => !filterFields.includes(f));

  return (
    <div>
      <PageHead
        back={
          <LinkButton onClick={onBack} className="mb-[6px]">
            ← All pivots
          </LinkButton>
        }
        title={pivot.sheet}
        sub={
          <>
            {pivot.name} over {pivot.source.sheet} · {formatCount(pivot.source.records)} records · {sourceLabel(pivot)}
            {pivot.source.refreshed ? <span className="ml-[6px]">· Excel last refreshed its copy {formatDate(pivot.source.refreshed)}; this one is recomputed now</span> : null}
          </>
        }
        actions={
          <>
            {!isDefault && <LinkButton onClick={() => onQuery(defaultQuery(pivot, undefined, listing.scopeFields))}>Reset to Excel's layout</LinkButton>}
            <ExportMenu
              items={[
                { label: "This pivot (xlsx)", url: pivotExportUrl(pivot.id, "xlsx", query), hint: "The table as shown, with subtotals" },
                { label: "This pivot (csv)", url: pivotExportUrl(pivot.id, "csv", query) },
              ]}
            />
          </>
        }
      />

      <RCard className="mb-[18px]" eyebrow="Filters" title="Show only" sub={filterText || "Everything: no filter applied"} data-testid="pivot-filters">
        <div className="flex flex-wrap items-start gap-[8px]">
          {filterFields.map((f) => (
            <FilterPicker key={f} field={f} options={table.data?.options[f] ?? []} chosen={query.filters[f] ?? []} onChange={(next) => update({ filters: { ...query.filters, [f]: next } })} onRemove={pivot.layout.filters.includes(f) ? undefined : () => {
              const rest = { ...query.filters };
              delete rest[f];
              update({ filters: rest });
            }} />
          ))}
          {spare.length > 0 && (
            <Select aria-label="Add a filter" value="" onChange={(e) => e.target.value && update({ filters: { ...query.filters, [e.target.value]: [] } })} className="py-[8px]">
              <option value="">+ Add a filter…</option>
              {spare.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </Select>
          )}
        </div>
      </RCard>

      <div className="mb-[18px] grid gap-[18px] md:grid-cols-12">
        <RCard className="md:col-span-4" eyebrow="Rows" title="Group by" sub={query.rows.join(" › ") || "Pick at least one row field"}>
          <div role="group" aria-label="Row fields" className="flex flex-wrap gap-[6px]">
            {textFields.map((f) => (
              <Chip key={f} pressed={query.rows.includes(f)} onClick={() => update({ rows: toggle(query.rows, f) })}>
                {query.rows.includes(f) ? `${query.rows.indexOf(f) + 1}. ${f}` : f}
              </Chip>
            ))}
          </div>
        </RCard>
        <RCard className="md:col-span-3" eyebrow="Columns" title="Across" sub={query.cols.join(" › ") || "Optional: a field to spread across columns"}>
          <div role="group" aria-label="Column fields" className="flex flex-wrap gap-[6px]">
            {textFields
              .filter((f) => !query.rows.includes(f))
              .map((f) => (
                <Chip key={f} pressed={query.cols.includes(f)} onClick={() => update({ cols: toggle(query.cols, f) })}>
                  {f}
                </Chip>
              ))}
          </div>
        </RCard>
        <RCard className="md:col-span-5" eyebrow="Values" title="Measure" sub={`${query.values.length} ${query.values.length === 1 ? "value" : "values"} · choose how each is aggregated`}>
          <div role="group" aria-label="Value fields" className="flex flex-wrap gap-[6px]">
            {[...numberFields, ...textFields].map((f) => {
              const v = valueFor(f);
              return (
                <span key={f} className="inline-flex items-center gap-[4px]">
                  <Chip pressed={!!v} onClick={() => toggleValue(f)}>
                    {f}
                  </Chip>
                  {v && (
                    <Select aria-label={`Aggregation for ${f}`} value={v.agg} onChange={(e) => setAgg(f, e.target.value)} className="py-[4px] text-[11px]">
                      {AGGS.map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
                      ))}
                    </Select>
                  )}
                </span>
              );
            })}
          </div>
        </RCard>
      </div>

      {table.status === "error" ? (
        <EmptyState tone="error" title="This layout cannot be computed" description={table.error} action={<Button onClick={() => onQuery(defaultQuery(pivot, undefined, listing.scopeFields))}>Back to Excel's layout</Button>} />
      ) : !table.data ? (
        <Skeleton rows={2} />
      ) : (
        <PivotGrid table={table.data} settings={settings} onLabel={(label) => actions.openFunds({ q: label })} />
      )}
      {table.data && !table.data.live && (
        <Note className="mt-[12px]">This pivot reads a sheet outside the engine's scope, so its numbers are the workbook's cached values, not a recalculation.</Note>
      )}
      <ConfidentialFooter text={footer} />
    </div>
  );
}

/** A filter field: a pill that opens a checklist of every value the data holds. */
function FilterPicker({ field, options, chosen, onChange, onRemove }: { field: string; options: string[]; chosen: string[]; onChange: (next: string[]) => void; onRemove?: () => void }) {
  const [search, setSearch] = useState("");
  const shown = search ? options.filter((o) => o.toLowerCase().includes(search.toLowerCase())) : options;
  const summary = chosen.length === 0 ? "All" : chosen.length <= 2 ? chosen.join(", ") : `${chosen.length} selected`;
  return (
    <details className="group relative" data-testid={`filter-${field}`}>
      <summary className={cn("flex cursor-pointer list-none items-center gap-[6px] rounded-full px-[12px] py-[6px] text-[12.5px] font-semibold", chosen.length ? "bg-accent text-white" : "glass-inset text-ink-2")}>
        <span className="text-[10px] font-bold uppercase tracking-[0.1em] opacity-80">{field}</span>
        {summary}
        <span aria-hidden>▾</span>
      </summary>
      <div className="absolute left-0 z-20 mt-[6px] w-[300px] rounded-[16px] glass-strong p-[12px] shadow-elevated">
        {options.length > 12 && <input type="search" aria-label={`Search ${field}`} placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} className="mb-[8px] w-full rounded-full border border-hairline bg-surface px-[12px] py-[6px] text-[12.5px] text-ink outline-none focus:border-accent" />}
        <div className="mb-[8px] flex gap-[10px] text-[11.5px]">
          <LinkButton onClick={() => onChange([])}>All</LinkButton>
          <LinkButton onClick={() => onChange(shown)}>Only these {shown.length}</LinkButton>
          {onRemove && <LinkButton onClick={onRemove}>Remove filter</LinkButton>}
        </div>
        <ul className="m-0 max-h-[260px] list-none overflow-auto p-0">
          {shown.map((o) => (
            <li key={o}>
              <label className="flex cursor-pointer items-center gap-[8px] rounded-sm px-[6px] py-[4px] text-[12.5px] text-ink hover:bg-ink/5">
                <input type="checkbox" checked={chosen.includes(o)} onChange={(e) => onChange(e.target.checked ? [...chosen, o] : chosen.filter((c) => c !== o))} />
                {o}
              </label>
            </li>
          ))}
          {shown.length === 0 && <li className="px-[6px] py-[4px] text-[12px] text-muted">No value matches.</li>}
        </ul>
      </div>
    </details>
  );
}

function fmt(v: number | null, spec: PivotValueSpec, settings: ReturnType<typeof useFormat>): string {
  if (v === null || v === undefined) return "";
  if (spec.agg === "count" || spec.agg === "countNums") return formatCount(v);
  return formatNumber(v, { decimals: settings.decimals });
}

function PivotGrid({ table, settings, onLabel }: { table: PivotTable; settings: ReturnType<typeof useFormat>; onLabel: (label: string) => void }) {
  const depth = Math.max(table.rowFields.length, 1);
  const groups = table.colKeys.length ? table.colKeys : [[]];
  const th = "sticky top-0 whitespace-nowrap border-b border-hairline bg-surface-lifted px-[12px] py-[9px] text-left font-heading text-[10.5px] font-semibold uppercase tracking-[0.07em] text-muted";
  const rows = [...table.rows, table.total];
  return (
    <div className="overflow-x-auto rounded-lg glass rise" data-testid="pivot-grid">
      <table className="w-full min-w-[640px] border-collapse text-[13px]">
        <thead>
          {table.colFields.length > 0 && (
            <tr>
              <th className={th} colSpan={depth + 1}>
                {table.rowFields.join(" › ")}
              </th>
              {groups.map((g, gi) => (
                <th key={gi} className={cn(th, "text-center")} colSpan={table.values.length}>
                  {g.join(" › ")}
                </th>
              ))}
            </tr>
          )}
          <tr>
            {table.rowFields.length ? table.rowFields.map((f) => <th key={f} className={th}>{f}</th>) : <th className={th}>Row</th>}
            <th className={cn(th, "text-right")}>Records</th>
            {groups.map((_g, gi) => table.values.map((v, vi) => <th key={`${gi}-${vi}`} className={cn(th, "text-right")}>{v.label}</th>))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => {
            const isTotal = r.kind === "total";
            const isSub = r.kind === "subtotal";
            return (
              <tr key={ri} className={cn("border-b border-hairline last:border-b-0", isSub && "bg-surface-lifted/60 font-semibold", isTotal && "bg-accent-soft font-bold")} data-kind={r.kind}>
                {Array.from({ length: depth }, (_, d) => {
                  const label = r.keys[d];
                  if (isTotal) return d === 0 ? <td key={d} className="px-[12px] py-[8px] text-ink" colSpan={depth}>Grand total</td> : null;
                  if (label === undefined) return <td key={d} className="px-[12px] py-[8px] text-muted">{isSub && d === r.keys.length ? "subtotal" : ""}</td>;
                  return (
                    <td key={d} className="whitespace-nowrap px-[12px] py-[8px] text-ink">
                      {r.kind === "leaf" && d === depth - 1 ? (
                        <button type="button" onClick={() => onLabel(label)} className="text-left hover:text-accent" title="Find in Funds">
                          {label}
                        </button>
                      ) : (
                        label
                      )}
                    </td>
                  );
                })}
                <td className="tabular px-[12px] py-[8px] text-right text-muted">{formatCount(r.n)}</td>
                {(r.cells.length ? r.cells : groups.map(() => table.values.map(() => null))).map((group, gi) =>
                  group.map((v, vi) => (
                    <td key={`${gi}-${vi}`} className="tabular whitespace-nowrap px-[12px] py-[8px] text-right text-ink">
                      {fmt(v, table.values[vi], settings)}
                    </td>
                  )),
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="m-0 px-[12px] py-[8px] text-[11.5px] text-muted">
        {formatCount(table.matched)} of {formatCount(table.records)} records match the filters · {table.rows.filter((r) => r.kind === "leaf").length} rows
      </p>
    </div>
  );
}
