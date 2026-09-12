import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-white hover:opacity-90 border border-transparent shadow-soft",
  secondary: "bg-surface text-ink border border-hairline hover:border-accent hover:text-accent",
  ghost: "bg-transparent text-accent hover:bg-accent-soft border border-transparent",
};

/** Pill buttons: a teal primary, a white secondary, a text ghost. */
export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center gap-[6px] rounded-full font-heading font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-[12px] py-[6px] text-xs" : "px-[16px] py-[9px] text-[13px]",
        variants[variant],
        className,
      )}
      {...rest}
    />
  );
}
