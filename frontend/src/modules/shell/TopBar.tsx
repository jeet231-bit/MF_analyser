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
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-[14px] bg-ground/90 px-[14px] py-[12px] backdrop-blur md:px-[26px]">
      <div role="group" aria-label="View" className="flex flex-none gap-[3px] rounded-full bg-surface p-[4px] shadow-soft">
        {(["research", "workbook"] as AppMode[]).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => onMode(m)}
            className={cn("rounded-full px-[16px] py-[7px] font-heading text-[12.5px] font-bold", mode === m ? "bg-accent text-white" : "text-muted hover:text-ink")}
          >
            {m === "research" ? "Research" : "Workbook"}
          </button>
        ))}
      </div>
      <form
        role="search"
        className="flex min-w-[120px] max-w-[460px] flex-1 items-center gap-[8px] rounded-full bg-surface px-[16px] shadow-soft"
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
      <div className="ml-auto flex items-center gap-[8px]">
        {version && (
          <span className="flex items-center gap-[8px] whitespace-nowrap rounded-full bg-surface px-[14px] py-[8px] text-xs text-muted shadow-soft" data-testid="version-pill">
            <span className={cn("h-[6px] w-[6px] flex-none rounded-full", version.status === "active" ? "bg-positive" : "bg-muted")} aria-hidden />
            <b className="font-semibold text-ink">{version.filename}</b> · {formatDate(version.uploaded_at)} · {version.status.replace("_", " ")}
            {validationLabel ? ` · ${validationLabel}` : ""}
          </span>
        )}
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Light theme" : "Dark theme"}
          className="grid h-[38px] w-[38px] place-items-center rounded-full bg-surface text-ink-2 shadow-soft hover:text-accent"
        >
          <Icon name="theme" className="inline-block h-[16px] w-[16px] [&>svg]:h-full [&>svg]:w-full" />
        </button>
        <button
          type="button"
          onClick={onOpenProfile}
          aria-label={viewerName ? `${viewerName}: open settings` : "Set your name"}
          title={viewerName ?? "Set your name in Admin"}
          className="flex items-center gap-[10px] rounded-full bg-surface py-[4px] pl-[14px] pr-[4px] shadow-soft"
        >
          {viewerName && <span className="font-heading text-[13px] font-bold text-ink">{viewerName}</span>}
          <span className="grid h-[32px] w-[32px] place-items-center rounded-full bg-accent font-heading text-[12px] font-bold text-white" aria-hidden>
            {viewerInitials}
          </span>
        </button>
      </div>
    </header>
  );
}
