import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type PillTone = "neutral" | "positive" | "warning" | "negative" | "accent";

const tones: Record<PillTone, string> = {
  neutral: "bg-surface-lifted text-muted",
  positive: "bg-positive-soft text-positive",
  warning: "bg-warning-soft text-warning",
  negative: "bg-negative-soft text-negative",
  accent: "bg-accent-soft text-accent",
};

/** Small tinted status pill. Semantic tones are reserved for validation and deltas. */
export function Pill({
  tone = "neutral",
  children,
  dot = true,
  className,
}: {
  tone?: PillTone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-[5px] whitespace-nowrap rounded-full px-[10px] py-[3px] font-heading text-[11.5px] font-bold",
        tones[tone],
        className,
      )}
    >
      {dot && <span className="h-[6px] w-[6px] shrink-0 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}
