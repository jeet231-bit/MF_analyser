import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/** Native select with the system's hairline styling; keyboard and screen-reader friendly by default. */
export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "rounded-sm border border-hairline bg-surface px-2 py-1 font-heading text-xs font-medium text-ink hover:border-accent focus:border-accent focus:outline-none disabled:opacity-50",
        className,
      )}
      {...rest}
    />
  );
}
