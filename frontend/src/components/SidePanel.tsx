import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Right-hand panel for detail views (cell lineage later). Closes on Escape. */
export function SidePanel({
  open,
  title,
  onClose,
  children,
  width = "28rem",
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <aside
      role="dialog"
      aria-label={typeof title === "string" ? title : undefined}
      className={cn("fixed inset-y-0 right-0 z-30 flex flex-col border-l border-hairline bg-surface")}
      style={{ width, maxWidth: "100vw" }}
    >
      <header className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <h2 className="font-heading text-sm font-semibold text-ink">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="rounded-sm px-2 py-1 font-heading text-xs text-muted hover:bg-accent-soft hover:text-accent"
        >
          Close
        </button>
      </header>
      <div className="flex-1 overflow-auto p-3">{children}</div>
    </aside>
  );
}
