import { useState } from "react";
import { Pill } from "@/components";

/** Quiet warning that expands to the readable cycle explanations from the model. */
export function CycleChip({ descriptions }: { descriptions: string[] }) {
  const [open, setOpen] = useState(false);
  if (descriptions.length === 0) return null;
  const n = descriptions.length;
  return (
    <div className="space-y-1">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="rounded-full">
        <Pill tone="warning">
          {n} circular reference{n > 1 ? "s" : ""} · {open ? "hide" : "explain"}
        </Pill>
      </button>
      {open && (
        <ul className="space-y-1 rounded-md border border-warning/30 bg-surface px-3 py-2 text-xs text-ink">
          {descriptions.map((d, i) => (
            <li key={i} className="break-words">
              {d}
            </li>
          ))}
          <li className="pt-1 text-muted">
            The engine will refuse to evaluate these cells. Fix the reference in the master workbook and upload a new version.
          </li>
        </ul>
      )}
    </div>
  );
}
