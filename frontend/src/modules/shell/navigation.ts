import type { ResearchSummary } from "@/api/research";
import type { ValidationStatus } from "@/api/validation";
import type { LogicModel, SheetRole } from "@/api/workbooks";
import type { PillTone } from "@/components";

export type AppMode = "research" | "workbook";

export type ResearchPageId = "dashboard" | "insights" | "funds" | "fund" | "categories" | "movement" | "admin" | "upload";
export type WorkbookPageId = "overview" | "inputs" | "analysis" | "calculations" | "outputs" | "validation" | "versions" | "sheet";
export type PageId = ResearchPageId | WorkbookPageId;

export type ModuleId = "inputs" | "analysis" | "calculations" | "outputs";

export interface NavItem {
  id: string;
  label: string;
  enabled: boolean;
  /** Sheets in this module, derived from roles; empty for non-module entries. */
  sheets: string[];
  note?: string;
  badge?: number;
  /** A count shown at the right of a research entry (funds, categories, moves). */
  count?: number;
  /** A warning dot (admin with open findings or anomalies). */
  dot?: boolean;
}

export interface NavGroup {
  label: string | null;
  items: NavItem[];
}

/** Module groups are grouped sheet roles; the mapping is the only fixed thing here. */
export const MODULE_GROUPS: { id: ModuleId; label: string; roles: SheetRole[] }[] = [
  { id: "inputs", label: "Inputs", roles: ["input", "reference"] },
  { id: "analysis", label: "Analysis", roles: ["transformation"] },
  { id: "calculations", label: "Calculations", roles: ["calculation"] },
  { id: "outputs", label: "Outputs", roles: ["output"] },
];

/** In-scope sheets that belong to a module, in workbook order. */
export function moduleSheets(model: LogicModel | null, moduleId: ModuleId): string[] {
  if (!model) return [];
  const group = MODULE_GROUPS.find((g) => g.id === moduleId);
  if (!group) return [];
  return model.sheets.filter((s) => s.in_scope && group.roles.includes(s.role)).map((s) => s.name);
}

/** Sidebar entries: Overview, one per module present in the model, then Versions and Validation. */
export function buildNavigation(model: LogicModel | null, anomalyCount = 0): NavItem[] {
  const items: NavItem[] = [{ id: "overview", label: "Overview", enabled: true, sheets: [] }];
  if (model) {
    for (const group of MODULE_GROUPS) {
      const sheets = moduleSheets(model, group.id);
      if (sheets.length > 0) {
        items.push({ id: group.id, label: group.label, enabled: true, sheets });
      }
    }
  }
  items.push({ id: "versions", label: "Versions", enabled: true, sheets: [] });
  items.push({
    id: "validation",
    label: "Validation",
    enabled: true,
    sheets: [],
    badge: anomalyCount > 0 ? anomalyCount : undefined,
  });
  return items;
}

/** Research rail: the six screens, with live counts where the summary has them. */
export function buildResearchNav(summary: ResearchSummary | null, insightCount?: number): NavItem[] {
  const u = summary?.configured ? summary.universe : undefined;
  const movement = summary?.configured ? summary.movement : undefined;
  return [
    { id: "dashboard", label: "Dashboard", enabled: true, sheets: [] },
    { id: "insights", label: "Insights", enabled: true, sheets: [], count: insightCount },
    { id: "funds", label: "Funds", enabled: true, sheets: [], count: u?.total },
    { id: "categories", label: "Categories", enabled: true, sheets: [], count: u?.categories },
    { id: "movement", label: "Movement", enabled: true, sheets: [], count: movement ? movement.moved : undefined },
  ];
}

/**
 * Workbook rail: the sheets grouped by role (each opens its sheet in the matching module page),
 * plus the model-level pages. Sheet entries are `sheet:<name>` ids.
 */
export function buildWorkbookNav(model: LogicModel | null, anomalyCount = 0): NavGroup[] {
  const groups: NavGroup[] = [{ label: null, items: [{ id: "overview", label: "Overview", enabled: true, sheets: [] }] }];
  if (model) {
    const order: ModuleId[] = ["outputs", "calculations", "analysis", "inputs"];
    for (const id of order) {
      const group = MODULE_GROUPS.find((g) => g.id === id)!;
      const sheets = moduleSheets(model, id);
      if (sheets.length === 0) continue;
      const items: NavItem[] =
        id === "inputs"
          ? [{ id: "inputs", label: "Weights & dates", enabled: true, sheets }]
          : sheets.map((name) => ({ id: `sheet:${name}`, label: name, enabled: true, sheets: [name] }));
      groups.push({ label: group.label, items });
    }
  }
  groups.push({
    label: "Model",
    items: [
      { id: "versions", label: "Versions", enabled: true, sheets: [] },
      { id: "validation", label: "Validation", enabled: true, sheets: [], badge: anomalyCount > 0 ? anomalyCount : undefined },
    ],
  });
  return groups;
}

export const validationPill: Record<ValidationStatus, { tone: PillTone; label: string }> = {
  passed: { tone: "positive", label: "passed" },
  passed_with_warnings: { tone: "warning", label: "passed with warnings" },
  failed: { tone: "negative", label: "failed" },
};

// ---- persisted view (mode + page), per browser ------------------------------------------------

export const VIEW_KEY = "mfa-view";
export const RAIL_KEY = "mfa-rail";

/** Whether the viewer pinned the rail open (Workbook mode pins it regardless). */
export function readPinned(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "pinned";
  } catch {
    return false;
  }
}

export function writePinned(pinned: boolean): void {
  try {
    if (pinned) localStorage.setItem(RAIL_KEY, "pinned");
    else localStorage.removeItem(RAIL_KEY);
  } catch {
    /* storage unavailable */
  }
}

export interface ViewState {
  mode: AppMode;
  page: PageId;
}

const RESEARCH_PAGES: ResearchPageId[] = ["dashboard", "insights", "funds", "fund", "categories", "movement", "admin", "upload"];
const WORKBOOK_PAGES: WorkbookPageId[] = ["overview", "inputs", "analysis", "calculations", "outputs", "validation", "versions", "sheet"];

export function isResearchPage(page: PageId): page is ResearchPageId {
  return (RESEARCH_PAGES as string[]).includes(page);
}

export function readView(): ViewState {
  try {
    const raw = localStorage.getItem(VIEW_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ViewState>;
      const mode: AppMode = parsed.mode === "workbook" ? "workbook" : "research";
      const pages: string[] = mode === "research" ? RESEARCH_PAGES : WORKBOOK_PAGES;
      const page = parsed.page && pages.includes(parsed.page) && parsed.page !== "fund" && parsed.page !== "sheet" ? parsed.page : mode === "research" ? "dashboard" : "overview";
      return { mode, page };
    }
  } catch {
    /* storage unavailable or corrupt */
  }
  return { mode: "research", page: "dashboard" };
}

export function writeView(view: ViewState): void {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(view));
  } catch {
    /* storage unavailable */
  }
}
