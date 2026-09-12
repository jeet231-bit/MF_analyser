import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/** Native select in a rounded field; keyboard and screen-reader friendly by default. */
export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "rounded-full border border-hairline bg-surface px-[12px] py-[7px] font-heading text-xs font-semibold text-ink hover:border-accent focus:border-accent focus:outline-none disabled:opacity-50",
        className,
      )}
      {...rest}
    />
  );
}
