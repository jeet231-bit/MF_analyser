import { useEffect, useRef, useState } from "react";
import { downloadExport } from "@/api/exports";
import { describeError } from "@/lib/useAsync";
import { cn } from "@/lib/cn";

export interface ExportItem {
  label: string;
  url: string;
  /** Shown under the label: what the file contains. */
  hint?: string;
}

/** One consistent Export menu: a quiet button, a list of files, a status line while it works. */
export function ExportMenu({ items, label = "Export", className }: { items: ExportItem[]; label?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const run = async (item: ExportItem) => {
    setOpen(false);
    setError(null);
    setBusy(true);
    try {
      await downloadExport(item.url, setStatus);
    } catch (err) {
      setError(describeError(err));
      setStatus(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={ref} className={cn("relative inline-flex items-center gap-2", className)}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={busy || items.length === 0}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 rounded-sm border border-hairline bg-surface px-2 py-1 font-heading text-xs font-medium text-ink hover:border-accent disabled:opacity-50"
      >
        {busy ? "Exporting…" : label}
        <span aria-hidden className="text-muted">
          ▾
        </span>
      </button>
      {open && (
        <ul
          role="menu"
          aria-label={label}
          className="absolute right-0 top-full z-20 mt-1 min-w-[16rem] rounded-md border border-hairline bg-surface p-1 shadow-none"
        >
          {items.map((item) => (
            <li key={item.url} role="none">
              <button
                type="button"
                role="menuitem"
                onClick={() => void run(item)}
                className="block w-full rounded-sm px-2 py-1.5 text-left hover:bg-accent-soft"
              >
                <div className="font-heading text-xs font-medium text-ink">{item.label}</div>
                {item.hint && <div className="text-[11px] text-muted">{item.hint}</div>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {status && !error && (
        <span role="status" className="text-xs text-muted">
          {status}
        </span>
      )}
      {error && (
        <span role="alert" className="text-xs text-negative">
          {error}
        </span>
      )}
    </div>
  );
}
