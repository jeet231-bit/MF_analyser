import type { LogicModel, SheetRole } from "@/api/workbooks";

export interface NavItem {
  id: string;
  label: string;
  enabled: boolean;
  /** Sheets in this module, derived from roles; empty for non-module entries. */
  sheets: string[];
  note?: string;
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
export function buildNavigation(model: LogicModel | null): NavItem[] {
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
  items.push({ id: "versions", label: "Versions", enabled: false, sheets: [], note: ENGINE_NOTE });
  items.push({ id: "validation", label: "Validation", enabled: false, sheets: [], note: ENGINE_NOTE });
  return items;
}
