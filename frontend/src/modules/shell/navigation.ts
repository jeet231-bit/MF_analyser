import type { ValidationStatus } from "@/api/validation";
import type { LogicModel, SheetRole } from "@/api/workbooks";
import type { PillTone } from "@/components";

export type PageId = "overview" | "validation" | "versions";

export interface NavItem {
  id: string;
  label: string;
  enabled: boolean;
  /** Sheets in this module, derived from roles; empty for non-module entries. */
  sheets: string[];
  note?: string;
  badge?: number;
}

/** Module groups are grouped sheet roles; the mapping is the only fixed thing here. */
const MODULE_GROUPS: { id: string; label: string; roles: SheetRole[] }[] = [
  { id: "inputs", label: "Inputs", roles: ["input", "reference"] },
  { id: "analysis", label: "Analysis", roles: ["transformation"] },
  { id: "calculations", label: "Calculations", roles: ["calculation"] },
  { id: "outputs", label: "Outputs", roles: ["output"] },
];

export const ENGINE_NOTE = "arrives with the engine";

/** Sidebar entries: Overview, one per module present in the model, then Versions and Validation. */
export function buildNavigation(model: LogicModel | null, anomalyCount = 0): NavItem[] {
  const items: NavItem[] = [{ id: "overview", label: "Overview", enabled: true, sheets: [] }];
  if (model) {
    const inScope = model.sheets.filter((s) => s.in_scope);
    for (const group of MODULE_GROUPS) {
      const sheets = inScope.filter((s) => group.roles.includes(s.role)).map((s) => s.name);
      if (sheets.length > 0) {
        items.push({ id: group.id, label: group.label, enabled: false, sheets, note: ENGINE_NOTE });
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

export const validationPill: Record<ValidationStatus, { tone: PillTone; label: string }> = {
  passed: { tone: "positive", label: "passed" },
  passed_with_warnings: { tone: "warning", label: "passed with warnings" },
  failed: { tone: "negative", label: "failed" },
};
