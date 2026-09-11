import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function EmptyState({
  title,
  description,
  action,
  tone = "neutral",
  className,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  tone?: "neutral" | "error";
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className={cn(
        "flex flex-col items-start gap-2 rounded-md border border-dashed border-hairline bg-surface px-4 py-6",
        className,
      )}
    >
      <div className={cn("font-heading text-sm font-semibold", tone === "error" ? "text-negative" : "text-ink")}>
        {title}
      </div>
      {description && <div className="max-w-prose text-sm text-muted">{description}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
