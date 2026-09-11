import type { GraphResponse } from "@/api/model";
import type { BusinessRule, LogicModel, SheetModel, WorkbookVersion } from "@/api/workbooks";

export const version: WorkbookVersion = {
  id: "abc12345def",
  filename: "master.xlsx",
  uploaded_at: "2026-09-11T09:00:00Z",
  status: "interpreted",
  size_bytes: 13_000_000,
  parse_seconds: 50,
  summary: {
    filename: "master.xlsx",
    sheets: 5,
    cells: 100,
    formula_cells: 40,
    named_ranges: 1,
    tables: 1,
    distinct_functions: 6,
    functions: { IF: 10 },
    has_macros: false,
    warnings: [],
    sheet_names: ["Inputs", "Lookup", "Calc", "Series", "Outputs"],
  },
};

const sheet = (partial: Partial<SheetModel> & { name: string; index: number; role: SheetModel["role"] }): SheetModel => ({
  state: "visible",
  in_scope: true,
  role_source: "heuristic",
  role_reason: "inferred",
  used_range: "A1:B10",
  cell_count: 20,
  formula_cells: 0,
  input_cells: 0,
  output_cells: 0,
  static_cells: 0,
  formula_block_ids: [],
  input_block_ids: [],
  feeds: [],
  reads: [],
  ...partial,
});

export const model: LogicModel = {
  version_id: version.id,
  created_at: "2026-09-11T09:01:00Z",
  scope: ["Inputs", "Lookup", "Calc", "Series", "Outputs"],
  sheets: [
    sheet({ name: "Inputs", index: 0, role: "input", feeds: ["Calc", "Series"], input_cells: 3 }),
    sheet({ name: "Lookup", index: 1, role: "reference", feeds: ["Calc", "Series"], state: "hidden" }),
    sheet({ name: "Calc", index: 2, role: "output", reads: ["Inputs", "Lookup"], formula_cells: 11, output_cells: 11 }),
    sheet({ name: "Series", index: 3, role: "calculation", reads: ["Inputs", "Lookup"], feeds: ["Outputs"], formula_cells: 100, output_cells: 40 }),
    sheet({ name: "Outputs", index: 4, role: "output", reads: ["Series"], formula_cells: 3, output_cells: 3 }),
  ],
  summary: {
    sheets_in_scope: 5,
    templates: 17,
    formula_blocks: 19,
    input_blocks: 4,
    external_blocks: 0,
    formula_cells: 114,
    input_cells: 26,
    output_cells: 54,
    static_cells: 40,
    rules: 10,
    parse_errors: 0,
    cycles: 0,
    self_dependent_blocks: 1,
    unresolved_references: 0,
    seconds: 0.4,
    peak_mb: 90,
  },
  cycles: [],
  cycle_descriptions: [],
  unresolved: [],
  rules: [],
  execution_order: [],
};

export const graph: GraphResponse = {
  level: "sheet",
  nodes: [
    { id: "Inputs", label: "Inputs", kind: "input", depth: 0, data: { input_cells: 3, formula_cells: 0 } },
    { id: "Lookup", label: "Lookup", kind: "reference", depth: 0, data: { input_cells: 6, formula_cells: 0 } },
    { id: "Calc", label: "Calc", kind: "output", depth: 1, data: { formula_cells: 11 } },
    { id: "Series", label: "Series", kind: "calculation", depth: 1, data: { formula_cells: 100 } },
    { id: "Outputs", label: "Outputs", kind: "output", depth: 2, data: { formula_cells: 3 } },
  ],
  edges: [
    { source: "Inputs", target: "Calc", weight: 5, label: null },
    { source: "Inputs", target: "Series", weight: 1, label: null },
    { source: "Lookup", target: "Calc", weight: 2, label: null },
    { source: "Lookup", target: "Series", weight: 1, label: null },
    { source: "Series", target: "Outputs", weight: 4, label: null },
  ],
};

export const rules: BusinessRule[] = [
  {
    id: 1,
    kind: "condition",
    template_id: 3,
    sheet: "Series",
    cells: ["D2:D21"],
    description: 'if B2<=120 → "Low"; if B2<=200 → "Mid"; otherwise → "High"',
    detail: {},
  },
  {
    id: 2,
    kind: "lookup",
    template_id: 4,
    sheet: "Series",
    cells: ["E2:E21"],
    description: "VLOOKUP: look up D2 in Lookup!$D$1:$E$3, return 2 (exact match); table of 3 rows",
    detail: {},
  },
  {
    id: 3,
    kind: "error_fallback",
    template_id: 1,
    sheet: "Calc",
    cells: ["B5"],
    description: 'if 1/0 errors → "n/a"',
    detail: {},
  },
];
