import type { ResearchSummary } from "@/api/research";
import type { ValidationStatus } from "@/api/validation";
import type { LogicModel, WorkbookVersion } from "@/api/workbooks";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import type { Theme } from "@/theme";
import { buildResearchNav, buildWorkbookNav, validationPill, type AppMode, type NavItem, type PageId } from "./navigation";

export interface SidebarProps {
  displayName: string | null;
  mode: AppMode;
  onMode: (mode: AppMode) => void;
  versions: WorkbookVersion[];
  selectedVersionId: string | null;
  onSelectVersion: (id: string) => void;
  model: LogicModel | null;
  activeItem: PageId;
  /** The sheet open in the workbook view, when the active page is a sheet page. */
  activeSheet?: string | null;
  onNavigate: (page: PageId, sheet?: string) => void;
  validationStatus: ValidationStatus | null;
  anomalyCount: number;
  summary: ResearchSummary | null;
  insightCount?: number;
  openFindings?: number;
  theme: Theme;
  onToggleTheme: () => void;
}

/** The rail: brand, version chip, the Research / Workbook switch, mode-specific groups, the foot. */
export function Sidebar({
  displayName,
  mode,
  onMode,
  versions,
  selectedVersionId,
  onSelectVersion,
  model,
  activeItem,
  activeSheet,
  onNavigate,
  validationStatus,
  anomalyCount,
  summary,
  insightCount,
  openFindings = 0,
  theme,
  onToggleTheme,
}: SidebarProps) {
  const selected = versions.find((v) => v.id === selectedVersionId) ?? null;
  const active = versions.find((v) => v.status === "active") ?? null;
  const chipVersion = mode === "research" ? (active ?? selected) : selected;
  const vpill = validationStatus ? validationPill[validationStatus] : null;
  const researchNav = buildResearchNav(summary, insightCount);
  const workbookGroups = buildWorkbookNav(model, anomalyCount);
  const adminDot = openFindings > 0 || anomalyCount > 0;

  const entry = (item: NavItem, current: boolean) => (
    <button
      key={item.id}
      type="button"
      disabled={!item.enabled}
      aria-current={current ? "page" : undefined}
      onClick={() => {
        if (item.id.startsWith("sheet:")) onNavigate("sheet", item.id.slice(6));
        else onNavigate(item.id as PageId);
      }}
      className={cn(
        "flex w-full items-center gap-2 rounded-sm px-[9px] py-[7px] text-left text-[13px] transition-colors",
        current ? "bg-rail-active font-semibold text-white" : "text-rail-muted hover:bg-rail-hover hover:text-rail-ink",
      )}
    >
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.count !== undefined && <span className="tabular text-[11px] text-rail-label">{item.count.toLocaleString("en-IN")}</span>}
      {item.badge !== undefined && (
        <span className="tabular rounded-full border border-warning/50 px-1.5 text-[11px] font-medium text-warning" aria-label={`${item.badge} anomalies`}>
          {item.badge}
        </span>
      )}
      {item.dot && <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-label="needs attention" />}
    </button>
  );

  return (
    <nav aria-label="Primary" className="flex h-full min-h-full flex-col gap-[18px] px-4 pb-5 pt-[22px] text-rail-ink">
      <div className="flex items-center gap-2.5">
        <div className="grid h-7 w-7 place-items-center rounded-sm bg-accent font-heading text-[13px] font-bold text-white" aria-hidden>
          {(displayName ?? "M").slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0">
          <div className="truncate font-heading text-sm font-semibold tracking-[-0.01em]">{displayName ?? "MF Analyser"}</div>
          <div className="-mt-0.5 text-[11px] text-rail-muted">{mode === "research" ? "Research console" : "Workbook view"}</div>
        </div>
      </div>

      {chipVersion ? (
        <div className="flex flex-col gap-[3px] rounded-[10px] border border-rail-line bg-rail-active px-[11px] py-[9px] text-[11.5px] text-rail-muted" data-testid="version-chip">
          <span>
            <span className={cn("mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-[1px]", chipVersion.status === "active" ? "bg-positive" : "bg-rail-muted")} aria-hidden />
            <b className="text-[12.5px] font-semibold text-rail-ink">{chipVersion.filename}</b>
          </span>
          <span>
            {formatDate(chipVersion.uploaded_at)} · {chipVersion.status.replace("_", " ")}
            {vpill ? ` · ${vpill.label}` : ""}
          </span>
        </div>
      ) : (
        <div className="text-[11.5px] text-rail-muted">No workbook uploaded</div>
      )}

      <div role="group" aria-label="View" className="flex gap-[3px] rounded-[10px] border border-rail-line bg-rail-active p-[3px]">
        {(["research", "workbook"] as AppMode[]).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => onMode(m)}
            className={cn(
              "flex-1 rounded-[7px] px-1 py-1.5 font-heading text-xs font-semibold",
              mode === m ? "bg-hero-ink text-rail" : "text-rail-muted hover:text-rail-ink",
            )}
          >
            {m === "research" ? "Research" : "Workbook"}
          </button>
        ))}
      </div>

      {mode === "research" ? (
        <div className="flex flex-col gap-0.5">{researchNav.map((item) => entry(item, item.id === activeItem || (item.id === "funds" && activeItem === "fund")))}</div>
      ) : (
        <div className="flex flex-col gap-0.5">
          {versions.length > 1 && (
            <label className="mb-2 block text-[11px] text-rail-muted">
              <span className="mb-1 block">Version</span>
              <select
                aria-label="Version"
                value={selectedVersionId ?? ""}
                onChange={(e) => onSelectVersion(e.target.value)}
                className="w-full rounded-sm border border-rail-line bg-rail-active px-2 py-1 font-heading text-xs text-rail-ink"
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.filename} · {formatDate(v.uploaded_at)}
                    {v.status === "active" ? " · active" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          {workbookGroups.map((group, gi) => (
            <div key={group.label ?? gi} className="flex flex-col gap-0.5">
              {group.label && <div className="mb-1 mt-2.5 px-2 text-[10px] font-semibold uppercase tracking-[0.13em] text-rail-label">{group.label}</div>}
              {group.items.map((item) =>
                entry(item, item.id.startsWith("sheet:") ? activeItem === "sheet" && item.sheets[0] === activeSheet : item.id === activeItem),
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-col gap-0.5 border-t border-rail-line pt-3.5">
        {entry({ id: "upload", label: "Upload version", enabled: true, sheets: [] }, activeItem === "upload")}
        {entry({ id: "admin", label: "Admin", enabled: true, sheets: [], dot: adminDot }, activeItem === "admin")}
        <button
          type="button"
          onClick={onToggleTheme}
          className="flex w-full items-center rounded-sm px-[9px] py-[7px] text-left text-[13px] text-rail-muted hover:bg-rail-hover hover:text-rail-ink"
        >
          {theme === "dark" ? "Light" : "Dark"} theme
        </button>
      </div>
    </nav>
  );
}
