import { cn } from "@/lib/cn";

export type PillTone = "neutral" | "positive" | "warning" | "negative" | "accent";

const tones: Record<PillTone, string> = {
  neutral: "border-hairline text-muted",
  positive: "border-positive/30 text-positive",
  warning: "border-warning/30 text-warning",
  negative: "border-negative/30 text-negative",
  accent: "border-accent/30 text-accent",
};

/** Small status marker. Semantic tones are reserved for validation and deltas. */
export function Pill({ tone = "neutral", children }: { tone?: PillTone; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-heading text-xs font-medium",
        tones[tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {children}
    </span>
  );
}
