import { useState } from "react";
import { EMPTY_SCOPE, isScopeEmpty, type Scope, type ScopeOptions } from "@/api/research";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button } from "@/components";
import { cn } from "@/lib/cn";
import { Icon } from "@/modules/shell/icons";

export interface ScopeBarProps {
  scope: Scope;
  description: string[] | undefined;
  options: ScopeOptions | undefined;
  onApply: (scope: Scope) => void;
  /** Activated versions for the version picker; the active one is the default. */
  versions?: WorkbookVersion[];
  versionId?: string | null;
  onVersion?: (id: string | null) => void;
  compact?: boolean;
}

const QUARTILE_CHOICES: { value: string; label: string; quartile: number[] }[] = [
  { value: "", label: "All quartiles", quartile: [] },
  { value: "1", label: "Q1 only", quartile: [1] },
  { value: "1,2", label: "Q1 and Q2", quartile: [1, 2] },
  { value: "3,4", label: "Q3 and Q4", quartile: [3, 4] },
  { value: "4", label: "Q4 only", quartile: [4] },
];

/**
 * The global scope: one slim row that reads "All funds · every category · every AMC · both
 * plans" and expands to the filter grid. Applying it recomputes every view, sentence and
 * export, so "executive summary for Direct plan, large-cap only" is one interaction.
 */
export function ScopeBar({ scope, description, options, onApply, versions, versionId, onVersion, compact = false }: ScopeBarProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Scope>(scope);
  const [seen, setSeen] = useState<Scope>(scope);
  if (seen !== scope) {
    // A scope applied elsewhere (reset, another page) replaces the draft.
    setSeen(scope);
    setDraft(scope);
  }
  const applied = !isScopeEmpty(scope);
  const dims = options?.dims ?? [];
  const bands = options?.bands ?? [];
  const quartileValue = QUARTILE_CHOICES.find((c) => c.quartile.join(",") === [...draft.quartile].sort().join(","))?.value ?? "";
  const fieldClass = "w-full rounded-[9px] border border-hairline bg-surface-lifted px-[10px] py-[8px] text-[13px] text-ink";
  const labelClass = "mb-[4px] block text-[9.5px] font-bold uppercase tracking-[0.1em] text-muted";

  return (
    <section className={cn("mb-[18px] overflow-hidden rounded-lg border border-hairline bg-surface", applied && "border-accent/40")} aria-label="Scope">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-[11px] px-[16px] py-[11px] text-left"
      >
        <span className="grid h-[28px] w-[28px] flex-none place-items-center rounded-[9px] bg-accent-soft text-accent" aria-hidden>
          <Icon name="scope" className="inline-block h-[15px] w-[15px] [&>svg]:h-full [&>svg]:w-full" />
        </span>
        <span className="min-w-0">
          <span className="block text-[10.5px] font-bold uppercase tracking-[0.1em] text-muted">Scope</span>
          <span className="flex flex-wrap items-center gap-[6px] text-[12.5px] text-ink-2" data-testid="scope-description">
            {(description ?? ["All funds"]).map((part, i) => (
              <span key={`${part}-${i}`} className={cn(i === 0 && "font-semibold text-ink")}>
                {i > 0 && <span className="text-muted"> · </span>}
                {part}
              </span>
            ))}
          </span>
        </span>
        <span className="ml-auto text-xs text-muted">{open ? "Collapse ▴" : "Refine ▾"}</span>
      </button>
      {open && (
        <form
          className={cn("grid gap-[13px] border-t border-hairline p-[16px]", compact ? "md:grid-cols-3" : "md:grid-cols-3 lg:grid-cols-5")}
          onSubmit={(e) => {
            e.preventDefault();
            onApply(draft);
            setOpen(false);
          }}
        >
          {dims.map((d) => (
            <label key={d.key} className="block">
              <span className={labelClass}>{d.label}</span>
              <select className={fieldClass} value={draft.dims[d.key] ?? ""} onChange={(e) => setDraft({ ...draft, dims: { ...draft.dims, [d.key]: e.target.value } })}>
                <option value="">All</option>
                {d.values.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <label className="block">
            <span className={labelClass}>Quartile</span>
            <select className={fieldClass} value={quartileValue} onChange={(e) => setDraft({ ...draft, quartile: QUARTILE_CHOICES.find((c) => c.value === e.target.value)?.quartile ?? [] })}>
              {QUARTILE_CHOICES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          {bands.map((b) => (
            <label key={b.key} className="block">
              <span className={labelClass}>{b.label} band</span>
              <select className={fieldClass} value={draft.bands[b.key] ?? ""} onChange={(e) => setDraft({ ...draft, bands: { ...draft.bands, [b.key]: e.target.value } })}>
                <option value="">Any</option>
                {b.options.map((o) => (
                  <option key={o.code} value={o.code}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <label className="block">
            <span className={labelClass}>Rating status</span>
            <select className={fieldClass} value={draft.rated} onChange={(e) => setDraft({ ...draft, rated: e.target.value as Scope["rated"] })}>
              <option value="all">Include unrated</option>
              <option value="only">Rated funds only</option>
              <option value="unrated">Unrated only</option>
            </select>
          </label>
          {versions && versions.length > 0 && onVersion && (
            <label className="block">
              <span className={labelClass}>Version</span>
              <select className={fieldClass} value={versionId ?? ""} onChange={(e) => onVersion(e.target.value || null)}>
                <option value="">Active version</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.filename} · {v.status.replace("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block">
            <span className={labelClass}>Text match</span>
            <input className={fieldClass} type="search" placeholder="fund, category or AMC" value={draft.q ?? ""} onChange={(e) => setDraft({ ...draft, q: e.target.value || undefined })} />
          </label>
          <div className="col-span-full flex flex-wrap items-center gap-[8px] pt-[4px]">
            <Button type="submit" variant="primary">
              Apply scope
            </Button>
            <Button
              onClick={() => {
                setDraft(EMPTY_SCOPE);
                onApply(EMPTY_SCOPE);
                setOpen(false);
              }}
            >
              Reset
            </Button>
            <span className="ml-auto text-[11.5px] text-muted">Scope applies to every view — dashboard, insights, funds, categories, movement and exports.</span>
          </div>
        </form>
      )}
    </section>
  );
}
