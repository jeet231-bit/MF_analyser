import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Fixed sidebar + main column. `tone="rail"` renders the research console's constant dark rail
 * (238 px, no hairline); the default is the quiet light sidebar.
 */
export function AppShell({ sidebar, children, tone = "light" }: { sidebar: ReactNode; children: ReactNode; tone?: "light" | "rail" }) {
  const rail = tone === "rail";
  return (
    <div className="min-h-screen bg-ground text-ink">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 hidden overflow-y-auto md:block",
          rail ? "w-[238px] bg-rail text-rail-ink" : "w-60 border-r border-hairline bg-surface",
        )}
      >
        {sidebar}
      </aside>
      <div className={rail ? "md:pl-[238px]" : "md:pl-60"}>
        <div className={cn("md:hidden", rail ? "bg-rail text-rail-ink" : "border-b border-hairline bg-surface")}>{sidebar}</div>
        <main className={cn("mx-auto min-w-0 px-4 py-4 md:px-6 md:py-6", rail ? "max-w-[1280px] md:px-[30px] md:pb-16 md:pt-[26px]" : "max-w-[1200px]")}>
          {children}
        </main>
      </div>
    </div>
  );
}
