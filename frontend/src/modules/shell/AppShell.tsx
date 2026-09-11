import type { ReactNode } from "react";

/** Slim fixed sidebar + main column capped at 1200px. */
export function AppShell({ sidebar, children }: { sidebar: ReactNode; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-ground text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-hairline bg-surface md:block">{sidebar}</aside>
      <div className="md:pl-60">
        <div className="border-b border-hairline bg-surface md:hidden">{sidebar}</div>
        <main className="mx-auto max-w-[1200px] px-4 py-4 md:px-6 md:py-6">{children}</main>
      </div>
    </div>
  );
}
