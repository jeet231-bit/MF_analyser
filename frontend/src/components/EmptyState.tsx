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
        "flex flex-col items-start gap-[8px] rounded-xl border border-dashed border-hairline bg-glass px-[24px] py-[28px] backdrop-blur-md rise",
        className,
      )}
    >
      <div className={cn("font-heading text-[15px] font-bold", tone === "error" ? "text-negative" : "text-ink")}>
        {title}
      </div>
      {description && <div className="max-w-prose text-sm text-muted">{description}</div>}
      {action && <div className="mt-[4px]">{action}</div>}
    </div>
  );
}
