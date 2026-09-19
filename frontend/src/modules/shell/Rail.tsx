import type { ResearchSummary } from "@/api/research";
import type { LogicModel } from "@/api/workbooks";
import { cn } from "@/lib/cn";
import { Icon, type IconName } from "./icons";
import { buildResearchNav, buildWorkbookNav, type AppMode, type NavItem, type PageId } from "./navigation";

export interface RailProps {
  displayName: string | null;
  mode: AppMode;
  model: LogicModel | null;
  activeItem: PageId;
  activeSheet?: string | null;
  onNavigate: (page: PageId, sheet?: string) => void;
  anomalyCount: number;
  summary: ResearchSummary | null;
  insightCount?: number;
  pivotCount?: number;
  openFindings?: number;
  pinned: boolean;
  onPin: (pinned: boolean) => void;
}

const PAGE_ICONS: Record<string, IconName> = {
  dashboard: "dashboard",
  insights: "insights",
  funds: "funds",
  categories: "categories",
  pivots: "pivots",
  movement: "movement",
  overview: "overview",
  inputs: "inputs",
  versions: "versions",
  validation: "validation",
  upload: "upload",
  admin: "admin",
};

const GROUP_ICONS: Record<string, IconName> = { Outputs: "output", Calculations: "calculation", Analysis: "calculation", Inputs: "inputs", Model: "versions" };

/**
 * The icon rail: 68 px of icons that expands to 238 px with labels on hover, or stays open when
 * pinned (Workbook mode pins it, since sheet names cannot be icons). It overlays the content
 * when open, so the page keeps its width.
 */
export function Rail({ displayName, mode, model, activeItem, activeSheet, onNavigate, anomalyCount, summary, insightCount, pivotCount, openFindings = 0, pinned, onPin }: RailProps) {
  const researchNav = buildResearchNav(summary, insightCount, pivotCount);
  const groups = buildWorkbookNav(model, anomalyCount);
  const adminDot = openFindings > 0 || anomalyCount > 0;
  const label = (text: string, extra?: string) => (
    <span className="rail-label flex min-w-0 flex-1 items-center gap-[8px]">
      <span className="truncate">{text}</span>
      {extra && <span className="tabular ml-auto text-[10.5px] text-rail-label">{extra}</span>}
    </span>
  );

  const entry = (item: NavItem, current: boolean, icon: IconName) => (
    <button
      key={item.id}
      type="button"
      title={item.label}
      aria-label={item.label}
      aria-current={current ? "page" : undefined}
      onClick={() => (item.id.startsWith("sheet:") ? onNavigate("sheet", item.id.slice(6)) : onNavigate(item.id as PageId))}
      className={cn(
        "flex h-[44px] w-full items-center gap-[13px] whitespace-nowrap rounded-full px-[12px] text-left text-[13.5px] transition-colors",
        current ? "bg-rail-active font-bold text-rail-active-ink shadow-soft [&_svg]:text-rail-active-ink" : "text-rail-muted hover:bg-rail-hover hover:text-rail-ink",
      )}
    >
      <Icon name={icon} />
      {label(item.label, item.count !== undefined ? item.count.toLocaleString("en-IN") : item.badge !== undefined ? String(item.badge) : undefined)}
      {item.dot && <span className="rail-label ml-auto h-[6px] w-[6px] flex-none rounded-full bg-warning" aria-label="needs attention" />}
    </button>
  );

  return (
    <nav
      aria-label="Main"
      data-pinned={pinned || undefined}
      className={cn(
        "group/rail fixed bottom-[12px] left-[12px] top-[12px] z-40 flex w-[calc(var(--rail-w)-12px)] flex-col gap-[4px] overflow-y-auto overflow-x-hidden rounded-[28px] border border-rail-line/60 bg-rail/90 px-[12px] py-[16px] text-rail-ink shadow-elevated backdrop-blur-md transition-[width] duration-200",
        "hover:w-[var(--rail-open)] data-[pinned]:w-[var(--rail-open)]",
        "[&_.rail-label]:pointer-events-none [&_.rail-label]:opacity-0 hover:[&_.rail-label]:pointer-events-auto hover:[&_.rail-label]:opacity-100 data-[pinned]:[&_.rail-label]:pointer-events-auto data-[pinned]:[&_.rail-label]:opacity-100",
      )}
    >
      <div className="flex items-center gap-[11px] whitespace-nowrap px-[6px] pb-[14px] pt-[4px]">
        <div className="grid h-[40px] w-[40px] flex-none place-items-center rounded-[14px] bg-highlight font-heading text-[15px] font-extrabold text-rail" aria-hidden>
          {(displayName ?? "M").slice(0, 1).toUpperCase()}
        </div>
        <div className="rail-label min-w-0">
          <div className="truncate font-heading text-sm font-semibold leading-tight">{displayName ?? "MF Analyser"}</div>
          <div className="text-[10.5px] text-rail-muted">{mode === "research" ? "Research console" : "Workbook view"}</div>
        </div>
      </div>

      {mode === "research" ? (
        <div className="flex flex-col gap-[3px]">{researchNav.map((item) => entry(item, item.id === activeItem || (item.id === "funds" && activeItem === "fund"), PAGE_ICONS[item.id] ?? "funds"))}</div>
      ) : (
        <div className="flex flex-col gap-[3px]">
          {groups.map((group, gi) => (
            <div key={group.label ?? gi} className="flex flex-col gap-[3px]">
              {group.label && <div className="rail-label mb-[4px] mt-[14px] h-[12px] whitespace-nowrap px-[10px] text-[9.5px] font-bold uppercase tracking-[0.14em] text-rail-label">{group.label}</div>}
              {group.items.map((item) =>
                entry(
                  item,
                  item.id.startsWith("sheet:") ? activeItem === "sheet" && item.sheets[0] === activeSheet : item.id === activeItem,
                  item.id.startsWith("sheet:") ? (GROUP_ICONS[group.label ?? ""] ?? "calculation") : (PAGE_ICONS[item.id] ?? "calculation"),
                ),
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-col gap-[3px] border-t border-rail-line pt-[12px]">
        {entry({ id: "upload", label: "Upload version", enabled: true, sheets: [] }, activeItem === "upload", "upload")}
        {entry({ id: "admin", label: "Admin", enabled: true, sheets: [], dot: adminDot }, activeItem === "admin", "admin")}
        <button
          type="button"
          aria-pressed={pinned}
          aria-label={pinned ? "Collapse menu" : "Keep menu open"}
          title={pinned ? "Collapse menu" : "Keep menu open"}
          onClick={() => onPin(!pinned)}
          className="flex h-[44px] w-full items-center gap-[13px] whitespace-nowrap rounded-full px-[12px] text-left text-[13.5px] text-rail-label hover:bg-rail-hover hover:text-rail-ink"
        >
          <Icon name="pin" />
          {label(pinned ? "Collapse menu" : "Keep menu open")}
        </button>
      </div>
    </nav>
  );
}
