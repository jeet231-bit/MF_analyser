import type { LineageNode } from "@/api/lineage";
import type { GridWindow, RunOut } from "@/api/runs";
import type { InputsCatalogue, OutputsSummary } from "@/api/views";
import { version } from "./fixtures";

export const baselineRun: RunOut = {
  id: "run-base",
  version_id: version.id,
  kind: "full",
  parent_run_id: null,
  overrides: {},
  status: "ok",
  error: null,
  created_at: "2026-09-11T09:05:00Z",
  summary: {
    kind: "full",
    blocks_evaluated: 19,
    cells_evaluated: 114,
    seconds: 0.4,
    peak_mb: 90,
    error_cells: 0,
    hot_templates: [],
    evaluated_block_ids: [],
    skipped_blocks: 0,
    skipped_template_ids: [],
    notes: [],
  },
};

export const whatIfRun: RunOut = {
  ...baselineRun,
  id: "run-whatif",
  kind: "incremental",
  parent_run_id: baselineRun.id,
  overrides: { "Inputs!B3": 200 },
  summary: { ...baselineRun.summary, kind: "incremental", blocks_evaluated: 3, cells_evaluated: 60, seconds: 0.1 },
};

export const seriesGrid: GridWindow = {
  run_id: baselineRun.id,
  sheet: "Series",
  r1: 2,
  r2: 4,
  c1: 1,
  c2: 4,
  used_range: "A1:G21",
  body_start: 2,
  total_rows: 21,
  total_cols: 7,
  row_label_col: null,
  baseline_run_id: null,
  columns: [
    { col: 1, letter: "A", label: "Month", kind: "static", format: "integer" },
    { col: 2, letter: "B", label: "Sales", kind: "input", format: "integer" },
    { col: 3, letter: "C", label: "Cumulative", kind: "formula", format: "integer" },
    { col: 4, letter: "D", label: "Band", kind: "formula", format: "general" },
  ],
  rows: [
    { row: 2, label: null, cells: [{ v: 1, t: "number" }, { v: 97, t: "number" }, { v: 97, t: "number", f: true }, { v: "Low", t: "text", f: true }] },
    { row: 3, label: null, cells: [{ v: 2, t: "number" }, { v: 104, t: "number" }, { v: 201, t: "number", f: true }, { v: "Low", t: "text", f: true }] },
    { row: 4, label: null, cells: [{ v: 3, t: "number" }, { v: 111, t: "number", o: true }, { v: 312, t: "number", f: true, b: 300 }, { v: "Low", t: "text", f: true }] },
  ],
};

export const inputs: InputsCatalogue = {
  run_id: baselineRun.id,
  sheets: [
    {
      sheet: "Inputs",
      role: "input",
      role_source: "heuristic",
      blocks: [
        {
          id: 20,
          sheet: "Inputs",
          rect: "B2:B5",
          r1: 2,
          c1: 2,
          r2: 5,
          c2: 2,
          cell_count: 4,
          kind: "input",
          editable: true,
          shape: "parameters",
          section: "Assumptions",
          value_types: { number: 2, date: 1, bool: 1 },
          column_labels: ["Value"],
          row_label_col: 1,
          cells: [
            { address: "B2", label: "Threshold", value: 0.75, type: "number", override: false },
            { address: "B3", label: "Units", value: 120, type: "number", override: false },
            { address: "B4", label: "Start date", value: 46053, type: "date", override: false },
            { address: "B5", label: "Active", value: true, type: "bool", override: false },
          ],
        },
      ],
    },
    {
      sheet: "Series",
      role: "calculation",
      role_source: "heuristic",
      blocks: [
        {
          id: 21,
          sheet: "Series",
          rect: "B2:B21",
          r1: 2,
          c1: 2,
          r2: 21,
          c2: 2,
          cell_count: 20,
          kind: "input",
          editable: true,
          shape: "table",
          section: "Sales",
          value_types: { number: 20 },
          column_labels: ["Sales"],
          row_label_col: null,
          cells: [],
        },
      ],
    },
  ],
};

export const outputs: OutputsSummary = {
  run_id: baselineRun.id,
  baseline_run_id: null,
  sheets: [
    {
      sheet: "Outputs",
      role: "output",
      role_source: "config",
      body_start: 1,
      table_rect: null,
      blocks: [{ id: 18, rect: "B1:B3", cell_count: 3, kind: "metric", labels: [] }],
      metrics: [
        { address: "B1", label: "Total sales", value: 3410, type: "number", format: "general", baseline: null, delta: null },
        { address: "B2", label: "Peak cumulative", value: 3410, type: "number", format: "general", baseline: null, delta: null },
        { address: "B3", label: "High months", value: 5, type: "number", format: "general", baseline: null, delta: null },
      ],
      rules: [],
      series: null,
      changed_cells: 0,
    },
  ],
};

export const whatIfOutputs: OutputsSummary = {
  ...outputs,
  run_id: whatIfRun.id,
  baseline_run_id: baselineRun.id,
  sheets: [
    {
      ...outputs.sheets[0],
      metrics: [
        { address: "B1", label: "Total sales", value: 3410, type: "number", format: "general", baseline: 3410, delta: null },
        { address: "B2", label: "Peak cumulative", value: 3490, type: "number", format: "general", baseline: 3410, delta: 80 },
        { address: "B3", label: "High months", value: 4, type: "number", format: "general", baseline: 5, delta: -1 },
      ],
      changed_cells: 2,
    },
  ],
};

export const lineage: LineageNode = {
  sheet: "Series",
  cell: "D6",
  kind: "formula",
  formula: '=IF(B6<=120,"Low",IF(B6<=200,"Mid","High"))',
  template_id: 3,
  value: "Mid",
  type: "text",
  explanation: ["B6<=120: 125 <= 120 is FALSE", "B6<=200: 125 <= 200 is TRUE", 'Result: "Mid"'],
  rule: 'if B6<=120 → "Low"; if B6<=200 → "Mid"; otherwise → "High"',
  reads: [{ sheet: "Series", range: "B6", count: 1, cells: [{ address: "B6", value: 125, type: "number" }] }],
};
