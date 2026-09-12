import { useState } from "react";
import type { WorkbookVersion } from "@/api/workbooks";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import type { Theme } from "@/theme";
import { Icon } from "./icons";
import type { AppMode } from "./navigation";

export interface TopBarProps {
  mode: AppMode;
  onMode: (mode: AppMode) => void;
  onSearch: (query: string) => void;
  version: WorkbookVersion | null;
  validationLabel?: string | null;
  theme: Theme;
  onToggleTheme: () => void;
  viewerInitials: string;
  viewerName: string | null;
  onOpenProfile: () => void;
}

/** Mode switch, global search, the version pill, the theme toggle and the viewer avatar. */
export function TopBar({ mode, onMode, onSearch, version, validationLabel, theme, onToggleTheme, viewerInitials, viewerName, onOpenProfile }: TopBarProps) {
  const [query, setQuery] = useState("");
  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-3.5 border-b border-hairline bg-ground/90 px-3.5 py-[11px] backdrop-blur md:px-[26px]">
      <div role="group" aria-label="View" className="flex flex-none gap-[3px] rounded-[11px] border border-hairline bg-surface p-[3px]">
        {(["research", "workbook"] as AppMode[]).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => onMode(m)}
            className={cn("rounded-sm px-[15px] py-1.5 font-heading text-[12.5px] font-semibold", mode === m ? "bg-ink text-ground" : "text-muted hover:text-ink")}
          >
            {m === "research" ? "Research" : "Workbook"}
          </button>
        ))}
      </div>
      <form
        role="search"
        className="flex min-w-[120px] max-w-[460px] flex-1 items-center gap-2 rounded-[11px] border border-hairline bg-surface px-[13px]"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) onSearch(query.trim());
        }}
      >
        <Icon name="search" className="inline-block h-[15px] w-[15px] flex-none text-muted [&>svg]:h-full [&>svg]:w-full" />
        <input
          type="search"
          aria-label="Search a fund, category or AMC"
          placeholder="Search a fund, category or AMC…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full bg-transparent py-[9px] text-[13px] text-ink outline-none"
        />
      </form>
      <div className="ml-auto flex items-center gap-2">
        {version && (
          <span className="flex items-center gap-2 whitespace-nowrap rounded-[11px] border border-hairline bg-surface px-3 py-1.5 text-xs text-muted" data-testid="version-pill">
            <span className={cn("h-1.5 w-1.5 flex-none rounded-full", version.status === "active" ? "bg-positive" : "bg-muted")} aria-hidden />
            <b className="font-semibold text-ink">{version.filename}</b> · {formatDate(version.uploaded_at)} · {version.status.replace("_", " ")}
            {validationLabel ? ` · ${validationLabel}` : ""}
          </span>
        )}
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Light theme" : "Dark theme"}
          className="grid h-9 w-9 place-items-center rounded-[11px] border border-hairline bg-surface text-ink-2 hover:border-accent hover:text-accent"
        >
          <Icon name="theme" className="inline-block h-4 w-4 [&>svg]:h-full [&>svg]:w-full" />
        </button>
        <button
          type="button"
          onClick={onOpenProfile}
          aria-label={viewerName ? `${viewerName}: open settings` : "Set your name"}
          title={viewerName ?? "Set your name in Admin"}
          className="grid h-9 w-9 place-items-center rounded-full bg-accent font-heading text-[12.5px] font-semibold text-white"
        >
          {viewerInitials}
        </button>
      </div>
    </header>
  );
}
