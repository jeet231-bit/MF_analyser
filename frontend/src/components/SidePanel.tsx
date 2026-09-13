import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Right-hand panel for detail views (cell lineage). Closes on Escape. */
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
      className={cn("fixed inset-y-[12px] right-[12px] z-30 flex flex-col rounded-xl glass-strong rise")}
      style={{ width, maxWidth: "calc(100vw - 24px)" }}
    >
      <header className="flex items-center justify-between px-[20px] pb-[8px] pt-[18px]">
        <h2 className="font-heading text-[15px] font-bold text-ink">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="rounded-full bg-surface-lifted px-[12px] py-[5px] font-heading text-xs font-semibold text-muted hover:bg-accent-soft hover:text-accent"
        >
          Close
        </button>
      </header>
      <div className="flex-1 overflow-auto px-[20px] pb-[20px] pt-[8px]">{children}</div>
    </aside>
  );
}
