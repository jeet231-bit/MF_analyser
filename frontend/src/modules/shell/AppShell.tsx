import type { ReactNode } from "react";

/**
 * The icon rail (fixed, 68 px; it overlays the content when it opens) plus a column with the
 * sticky top bar and the page. The page keeps its width whatever the rail does.
 */
export function AppShell({ rail, topBar, children }: { rail: ReactNode; topBar: ReactNode; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-ground text-ink">
      {rail}
      <div className="min-w-0 pl-[var(--rail-w)]">
        {topBar}
        <main className="mx-auto min-w-0 max-w-[1320px] px-[14px] pb-[48px] pt-[18px] md:px-[26px] md:pb-[56px] md:pt-[22px]">{children}</main>
      </div>
    </div>
  );
}
