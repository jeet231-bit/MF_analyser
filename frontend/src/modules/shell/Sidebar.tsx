import type { LogicModel, WorkbookVersion } from "@/api/workbooks";
import { Pill, Select } from "@/components";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import type { Theme } from "@/theme";
import { buildNavigation } from "./navigation";

export interface SidebarProps {
  displayName: string | null;
  versions: WorkbookVersion[];
  selectedVersionId: string | null;
  onSelectVersion: (id: string) => void;
  model: LogicModel | null;
  activeItem: string;
  theme: Theme;
  onToggleTheme: () => void;
}

const statusTone: Record<string, "neutral" | "accent" | "positive" | "warning"> = {
  uploaded: "neutral",
  interpreted: "accent",
  validated: "positive",
  active: "positive",
  pending_review: "warning",
};

export function Sidebar({
  displayName,
  versions,
  selectedVersionId,
  onSelectVersion,
  model,
  activeItem,
  theme,
  onToggleTheme,
}: SidebarProps) {
  const selected = versions.find((v) => v.id === selectedVersionId) ?? null;
  const nav = buildNavigation(model);

  return (
    <nav aria-label="Primary" className="flex h-full flex-col gap-3 px-3 py-3">
      <div>
        <div className="font-heading text-sm font-semibold text-ink">{displayName ?? selected?.filename ?? "MF Analyser"}</div>
        <div className="mt-0.5 text-xs text-muted">Excel-driven research analytics</div>
      </div>

      <div className="space-y-1">
        <label htmlFor="version-select" className="text-xs font-medium text-muted">
          Version
        </label>
        {versions.length > 0 ? (
          <Select
            id="version-select"
            className="w-full"
            value={selectedVersionId ?? ""}
            onChange={(e) => onSelectVersion(e.target.value)}
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.filename} · {formatDate(v.uploaded_at)}
              </option>
            ))}
          </Select>
        ) : (
          <div className="text-xs text-muted">No workbook uploaded</div>
        )}
        {selected && (
          <div className="flex flex-wrap items-center gap-1 pt-0.5">
            <Pill tone={statusTone[selected.status] ?? "neutral"}>{selected.status.replace("_", " ")}</Pill>
            <span className="tabular text-[11px] text-muted" title={selected.id}>
              {selected.id.slice(0, 8)}
            </span>
          </div>
        )}
      </div>

      <ul className="space-y-0.5">
        {nav.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              disabled={!item.enabled}
              aria-current={item.id === activeItem ? "page" : undefined}
              aria-disabled={!item.enabled}
              className={cn(
                "flex w-full items-baseline justify-between rounded-sm px-2 py-1 text-left font-heading text-sm",
                item.id === activeItem ? "bg-accent-soft font-medium text-accent" : "text-ink",
                item.enabled ? "hover:bg-accent-soft" : "cursor-not-allowed text-muted",
              )}
            >
              <span>
                {item.label}
                {item.sheets.length > 0 && (
                  <span className="tabular ml-1 text-[11px] text-muted">{item.sheets.length}</span>
                )}
              </span>
              {item.note && <span className="text-[11px] italic text-muted">{item.note}</span>}
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-auto space-y-2 border-t border-hairline pt-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">Validation</span>
          <Pill tone="neutral">not yet validated</Pill>
        </div>
        <button
          type="button"
          onClick={onToggleTheme}
          className="w-full rounded-sm border border-hairline px-2 py-1 font-heading text-xs font-medium text-ink hover:border-accent"
        >
          {theme === "dark" ? "Light" : "Dark"} theme
        </button>
      </div>
    </nav>
  );
}
