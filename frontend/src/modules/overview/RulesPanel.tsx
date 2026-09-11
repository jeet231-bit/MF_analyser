import { useMemo, useState } from "react";
import type { BusinessRule, RuleKind } from "@/api/workbooks";
import { Pill } from "@/components";
import { cn } from "@/lib/cn";

const KINDS: { id: RuleKind; label: string }[] = [
  { id: "condition", label: "Conditions" },
  { id: "threshold", label: "Thresholds" },
  { id: "lookup", label: "Lookups" },
  { id: "error_fallback", label: "Error fallbacks" },
];

const kindLabel: Record<RuleKind, string> = {
  condition: "condition",
  threshold: "threshold",
  lookup: "lookup",
  error_fallback: "fallback",
};

/** Extracted rules grouped by sheet, filterable by kind. Native <details> keeps it accessible. */
export function RulesPanel({ rules, sheetOrder }: { rules: BusinessRule[]; sheetOrder: string[] }) {
  const [kinds, setKinds] = useState<Set<RuleKind>>(new Set(KINDS.map((k) => k.id)));

  const grouped = useMemo(() => {
    const bySheet = new Map<string, BusinessRule[]>();
    for (const r of rules) {
      if (!kinds.has(r.kind)) continue;
      const list = bySheet.get(r.sheet) ?? [];
      list.push(r);
      bySheet.set(r.sheet, list);
    }
    const order = new Map(sheetOrder.map((s, i) => [s, i]));
    return [...bySheet.entries()].sort((a, b) => (order.get(a[0]) ?? 99) - (order.get(b[0]) ?? 99));
  }, [rules, kinds, sheetOrder]);

  const toggle = (kind: RuleKind) =>
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rules) c[r.kind] = (c[r.kind] ?? 0) + 1;
    return c;
  }, [rules]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter rules by kind">
        {KINDS.map((k) => (
          <button
            key={k.id}
            type="button"
            aria-pressed={kinds.has(k.id)}
            onClick={() => toggle(k.id)}
            className={cn(
              "rounded-full border px-2 py-0.5 font-heading text-xs font-medium",
              kinds.has(k.id) ? "border-accent/40 bg-accent-soft text-accent" : "border-hairline text-muted",
            )}
          >
            {k.label} <span className="tabular">{counts[k.id] ?? 0}</span>
          </button>
        ))}
      </div>
      {grouped.length === 0 && <p className="text-sm text-muted">No rules match the current filter.</p>}
      {grouped.map(([sheet, list]) => (
        <details key={sheet} className="rounded-md border border-hairline bg-surface" open={grouped.length <= 3}>
          <summary className="cursor-pointer select-none px-3 py-2 font-heading text-sm font-medium text-ink">
            {sheet} <span className="tabular ml-1 text-xs text-muted">{list.length}</span>
          </summary>
          <ul className="divide-y divide-hairline border-t border-hairline">
            {list.map((r) => (
              <li key={r.id} className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <div className="space-y-1">
                  <Pill tone="neutral" dot={false}>
                    {kindLabel[r.kind]}
                  </Pill>
                  <div className="tabular text-[11px] text-muted">{r.cells.slice(0, 2).join(", ")}{r.cells.length > 2 ? ", …" : ""}</div>
                </div>
                <div className="break-words text-ink">{r.description}</div>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}
