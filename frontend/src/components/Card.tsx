import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  action?: ReactNode;
}

/** White 24 px surface with a soft shadow. The single elevation level in the system. */
export function Card({ title, action, className, children, ...rest }: CardProps) {
  return (
    <section className={cn("rounded-xl glass rise", className)} {...rest}>
      {(title || action) && (
        <header className="flex items-center justify-between px-[20px] pb-[4px] pt-[18px]">
          {title && <h2 className="font-heading text-[15px] font-bold text-ink">{title}</h2>}
          {action}
        </header>
      )}
      <div className="px-[20px] pb-[18px] pt-[12px]">{children}</div>
    </section>
  );
}
