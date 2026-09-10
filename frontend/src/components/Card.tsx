import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  action?: ReactNode;
}

/** White surface with a hairline border. The single elevation level in the system. */
export function Card({ title, action, className, children, ...rest }: CardProps) {
  return (
    <section className={cn("rounded-md border border-hairline bg-surface", className)} {...rest}>
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-hairline px-3 py-2">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {action}
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}
