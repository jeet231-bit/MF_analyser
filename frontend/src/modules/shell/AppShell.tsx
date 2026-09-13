import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * The icon rail plus a column with the sticky top bar and the page. A hover-expanded rail
 * overlays the content; a pinned rail pushes it, so nothing hides behind the menu.
 */
export function AppShell({ rail, topBar, pinned = false, children }: { rail: ReactNode; topBar: ReactNode; pinned?: boolean; children: ReactNode }) {
  return (
    <div className="min-h-screen text-ink">
      {rail}
      <div className={cn("min-w-0 transition-[padding] duration-200", pinned ? "pl-[calc(var(--rail-open)+12px)]" : "pl-[var(--rail-w)]")} data-testid="shell-column" data-pinned={pinned || undefined}>
        {topBar}
        <main className="mx-auto min-w-0 max-w-[1320px] px-[14px] pb-[48px] pt-[18px] md:px-[26px] md:pb-[56px] md:pt-[22px]">{children}</main>
      </div>
    </div>
  );
}
