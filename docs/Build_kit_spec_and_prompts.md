# MF Analyser — Build Kit (Spec + Prompt Pack)

Published artifact: https://claude.ai/code/artifact/57eed594-e316-4da1-a21e-88578c38a155
Status: v1.0 — approved direction: React + TypeScript frontend, Python/FastAPI backend, workbook-agnostic.

## Architecture

Master Excel -> Parser/Logic Layer -> Analytical Engine -> Dashboard -> Export.

The workbook is ingested into a structured, versioned **Workbook Logic Model**: Inputs -> Formulas (ASTs) -> Dependencies (networkx DAG) -> Transformations -> Business Rules -> Outputs. Everything downstream (engine, dashboard) consumes only this model. Hard rule: no sheet names, cell addresses, or business terms from any particular workbook in engine/frontend code; display preferences live in an editable dashboard.config.json overlay.

Key stack: openpyxl (formulas + cached values), `formulas` library evaluated as execution core (custom AST layer + function registry as fallback), networkx, SQLite->Postgres, React 18 + Vite + Tailwind tokens + Recharts, openpyxl/xlsxwriter + WeasyPrint exports.

Validation gates activation: engine output reconciled cell-by-cell against Excel's cached values (numeric rel. tolerance 1e-9). New workbook versions are immutable, diffed in logic terms with DAG impact analysis, and activated after review.

UI register: minimal Apple/CRED — ground #F6F6F4, surface #FFFFFF, ink #17191D, accent #2F55D4 (interactive/selected only), semantic color only for validation/deltas, Schibsted Grotesk + Instrument Sans, tabular figures, 8pt grid, hairline borders, full dark theme (#0E1013 / #16181D / accent #8CA2EE).

Known constraints: VBA not interpreted (flagged); function coverage bounded by Phase 1 inventory (unsupported functions fail loudly); volatile/external refs treated as declared inputs; circular refs unsupported in v1; all classifications user-overridable.

## Prompt pack (run in order, one phase per session, in Claude for VS Code)

Workflow: `git init` first; commit per phase; CLAUDE.md (created in Phase 0) carries standing context; after each phase ask "Run the tests and demonstrate the acceptance criteria for this phase"; put the real workbook in samples/ from Phase 1; use plan mode for Phases 2, 3, 7.

### PHASE 0 — Scaffold & standing context

*Set up the monorepo, tooling, and the CLAUDE.md that anchors every later session.*

```
Create a monorepo for an internal "Excel-driven research analytics platform" called mf-analyser.

Structure:
- backend/ — Python 3.12, FastAPI, Pydantic v2, managed with uv (or pip + venv). Packages: app/api, app/parser, app/model, app/engine, app/validation, app/exports, app/storage. Include pytest, ruff, and a pyproject.toml.
- frontend/ — React 18 + TypeScript + Vite + Tailwind CSS + Recharts. Folders: src/api, src/components, src/modules, src/theme, src/lib.
- A root README.md and a Makefile (or justfile) with: dev (runs both servers), test, lint.

Also create a CLAUDE.md at the repo root containing these standing rules for all future sessions:
1. ARCHITECTURE: Master Excel → Parser/Logic Layer → Analytical Engine → Dashboard → Export. The uploaded Excel workbook is the source of analytical truth. The app interprets and executes it; it never re-implements its business logic.
2. The parser converts any workbook into a structured Workbook Logic Model: Inputs → Formulas (as ASTs) → Dependencies (a DAG) → Transformations → Business Rules → Outputs. Everything downstream consumes only this model.
3. HARD RULE: no sheet names, cell addresses, or business-specific terms from any particular workbook may appear in engine or frontend code. Workbook-specific display preferences live only in an editable dashboard.config.json overlay.
4. The engine's results must be reconcilable cell-by-cell against Excel's own cached values; validation is a first-class feature.
5. UI register: minimal, professional, Apple/CRED-like. Off-white ground, white cards, hairline borders, one blue accent (#2F55D4) used only for interactive/selected states, semantic colors only for validation and deltas, Schibsted Grotesk for headings, Instrument Sans for body, tabular figures for numbers, 8pt spacing grid, full dark-mode token set.
6. Write tests alongside every feature; backend features need pytest coverage before they count as done.

Wire up a health-check endpoint and a frontend page that calls it, so `make dev` proves the loop works end to end.
```

**Accept when:** Both servers start with one command; frontend shows backend health; lint and an initial test pass; CLAUDE.md is in place.

### PHASE 1 — Excel ingestion & raw extraction

*Read any .xlsx into a faithful raw representation — formulas and cached values both.*

```
Build the ingestion layer in backend/app/parser.

Using openpyxl, load an uploaded .xlsx twice — once with formulas (data_only=False) and once with cached values (data_only=True) — and merge into a RawWorkbook structure (Pydantic models) capturing:
- workbook metadata: sheet names, order, visibility, defined names/named ranges, tables
- per sheet: used range, and for every non-empty cell: address, raw formula (if any), cached value, inferred type (number/text/date/bool/error), number format string, and whether it belongs to a merged range or table
- shared formulas and array formulas expanded so every cell knows its own effective formula

Add:
- POST /api/workbooks — accepts an .xlsx upload, stores the file and its RawWorkbook JSON in SQLite (schema: workbook_versions table with id, filename, uploaded_at, status), returns version id + summary counts (sheets, cells, formula cells, named ranges, distinct Excel functions used, with per-function counts)
- GET /api/workbooks/{id}/raw — returns the RawWorkbook
- The "distinct functions used" report matters: it later tells us exactly which functions the engine must support.

Testing: generate a small fixture workbook in a pytest fixture using openpyxl (inputs sheet, a calc sheet with cross-sheet formulas including IF, SUM, VLOOKUP, a named range) and assert the extraction round-trips correctly. Handle .xlsm gracefully by ingesting cells and flagging "contains macros — macro logic is not interpreted".
```

**Accept when:** Fixture tests pass; uploading a real workbook returns accurate counts and a function inventory; cached values are captured for every formula cell.

### PHASE 2 — Logic interpretation — AST, DAG, classification

*Turn the raw extraction into the executable, diffable Workbook Logic Model.*

```
Build the logic interpretation layer in backend/app/model, producing a WorkbookLogicModel from a RawWorkbook.

1. Formula ASTs: parse every formula into an AST (function calls, binary/unary ops, cell refs, range refs, named refs, structured table refs, literals). Evaluate the `formulas` library (vinci1it2000/formulas) first — if its parser is solid, wrap it rather than writing our own tokenizer; either way our AST node types are our own Pydantic models so the rest of the system doesn't depend on the library's internals.
2. Dependency graph: walk each AST's references and build a networkx DiGraph of cell-level dependencies, with cross-sheet and named-range edges resolved. Detect cycles (report them; Excel iterative-calc workbooks are flagged unsupported for now). Compute a topological execution order. Also produce the sheet-level rollup graph (which sheets feed which).
3. Cell classification: input (constant with dependents), calculation (has formula), output (formula cell with no dependents, i.e. DAG sink — plus anything on sheets later marked as output sheets), static (constant nothing reads: labels/headers). Associate probable labels with inputs and outputs by scanning adjacent text cells (same row to the left, or column header).
4. Sheet roles: classify each sheet as input / transformation / calculation / reference / output using composition heuristics (share of inputs vs formulas vs external references, in-degree vs out-degree in the sheet graph). Roles are defaults, overridable later via API.
5. Business rules: extract readable rule descriptions from ASTs — IF/IFS condition trees (condition, then, else), threshold comparisons against constants or named cells, and classification bands implied by VLOOKUP/XLOOKUP/INDEX+MATCH against small lookup tables. Store as structured BusinessRule objects with source cell references.

Persist the model JSON against the workbook version. Endpoints:
- POST /api/workbooks/{id}/interpret → builds and stores the model, returns summary
- GET /api/workbooks/{id}/model → full model
- GET /api/workbooks/{id}/graph?level=sheet|cell → graph for visualisation
- GET /api/workbooks/{id}/rules → extracted business rules

Extend the fixture workbook to cover every classification and rule pattern, and test each.
```

**Accept when:** The fixture yields correct classifications, a cycle-free ordered DAG, and readable extracted rules; the real workbook interprets without errors and the sheet graph looks right.

### PHASE 3 — Analytical engine

*Execute the logic model — full runs and what-if recalculation, no Excel required.*

```
Build the analytical engine in backend/app/engine.

The engine executes a WorkbookLogicModel with no access to the original file:
1. Core: evaluate cells in topological order over the dependency DAG. Preferred path: drive the `formulas` library's computation graph, keyed by our model. Fallback path (design the interface so both fit): our own evaluator over our ASTs with an Excel-function registry — implement exactly the functions the Phase 1 inventory reports, and raise UnsupportedFunctionError (listing cell + function) rather than silently mis-computing anything.
2. Semantics: match Excel — empty cells coerce to 0 in arithmetic, error values (#DIV/0!, #N/A, #VALUE!) propagate through dependents, text/number coercion follows Excel rules, dates are Excel serial numbers under the hood.
3. Runs: a Run = model version + input overrides map {cell_or_named_ref: value}. Full run executes everything; incremental run recomputes only descendants of overridden inputs (networkx descendants). Results (all computed cell values + run metadata + timing) persist per run.
4. Endpoints:
- POST /api/workbooks/{id}/runs — body: {overrides?} → run id + results summary
- GET /api/runs/{run_id} — full results
- GET /api/runs/{run_id}/values?sheet=… — computed values for a sheet
- GET /api/workbooks/{id}/lineage/{cellref} — the evaluation tree for one cell: its formula, the values it consumed, and so on recursively (this powers "explain this number" in the UI).

Test against the fixture: full run reproduces every cached value exactly; an override recomputes exactly the affected descendants; error propagation and unsupported-function reporting behave as specified.
```

**Accept when:** Fixture runs match Excel's cached values 100%; overrides trigger correct incremental recomputation; lineage endpoint explains any cell.

### PHASE 4 — Validation & reconciliation

*Prove the engine agrees with Excel — the trust layer that gates everything.*

```
Build backend/app/validation.

After interpretation, run the engine with zero overrides and reconcile every formula cell's computed value against the cached value Excel stored in the file:
- numeric: relative tolerance 1e-9 (configurable); text/bool/date: exact; error values must match the same error
- produce a ValidationReport: totals (cells checked, matched, mismatched, skipped-unsupported), per-sheet breakdown, and per-mismatch detail (cell, formula, Excel value, engine value, delta, classification: unsupported function / precision / logic difference)
- status: passed / passed-with-warnings / failed, with thresholds configurable
- a workbook version may only be marked "active" for the dashboard when its latest validation passed, or a user explicitly overrides with a logged reason

Endpoints:
- POST /api/workbooks/{id}/validate → run + report
- GET /api/workbooks/{id}/validation → latest report
- POST /api/workbooks/{id}/activate — enforces the gate, records override reasons

Tests: a fixture where the engine is correct (passes), one with an unsupported function injected (reports skip, not mismatch), and a deliberately perturbed value (fails with correct detail).
```

**Accept when:** Reports are accurate on all three fixtures; activation gate enforces validation; the real workbook's report gives a truthful coverage picture.

### PHASE 5 — Versioning & logic diff

*Uploading an evolved workbook becomes a reviewed, explained change — not a mystery.*

```
Build workbook versioning and logic diffing in backend/app/model/diff.py.

Diff two WorkbookLogicModel versions in logic terms, not file terms:
- sheets added/removed/renamed (renames matched by content-similarity, not just name)
- inputs added/removed; input reclassifications
- formulas added/removed/changed — for changed, an AST-level description ("IF threshold changed from 0.75 to 0.8", "SUM range extended B2:B40 → B2:B60"), falling back to old/new formula text
- business rules added/removed/changed
- named ranges and outputs added/removed/changed
- impact analysis: for every change, the set of downstream outputs affected (DAG descendants), rolled up into a headline: "9 changes affecting 14 of 31 outputs"

Endpoints:
- GET /api/workbooks/{a}/diff/{b} → structured DiffReport
- POST /api/workbooks — extend upload so a new version of the same master automatically parses, interprets, validates, and returns its diff vs the currently active version

Workflow: new versions land as "pending review"; activating one (validation gate from Phase 4) makes it the dashboard's source. Previous versions remain queryable — rollback is re-activating an older version.

Tests: fixture pairs covering each diff category, including a rename plus a threshold change, asserting both the diff detail and the impact set.
```

**Accept when:** Diff reports read like a changelog a researcher would trust; impact sets are exact; upload → diff → activate flow works end to end.

### PHASE 6 — Dashboard shell & design system

*The visual foundation — tokens, layout, and navigation derived from the model.*

```
Build the frontend shell and design system (see CLAUDE.md rule 5 for the visual register — minimal, Apple/CRED-like, quiet).

1. Theme: define design tokens in src/theme (CSS variables consumed by Tailwind): light — ground #F6F6F4, surface #FFFFFF, ink #17191D, muted #6B7078, hairline #E3E3DF, accent #2F55D4, positive #1E7F4F, warning #A16207, negative #B4232A; dark equivalents on #0E1013 ground with #16181D surfaces and a lifted accent #8CA2EE. Fonts: Schibsted Grotesk (headings/UI), Instrument Sans (body), tabular-nums wherever digits align. 8pt spacing grid, 12–16px radii, hairline borders instead of shadows, one elevation level. Light/dark follow the system with a manual toggle.
2. Shell: slim fixed left sidebar (workbook name, version badge, module navigation, validation status pill) + main content area, max-width 1200px. Sidebar items and order come from GET /api/workbooks/{id}/model sheet roles — nothing hard-coded: Overview, then one entry per module (grouped sheet roles: Inputs, Analysis, Calculations, Outputs), then Versions, then Validation.
3. Core components (build these first, use them everywhere): Card, StatTile (label, value, delta with direction), DataTable (sticky header, tabular numbers, right-aligned numerics, Indian-format grouping option), Pill (semantic states), EmptyState, SidePanel (for cell lineage later), and a quiet top progress bar for runs in flight.
4. Overview page: workbook name, active version, upload date, counts (sheets, inputs, formulas, outputs), validation status pill, and a sheet-level dependency graph rendered as a clean left-to-right flow (simple SVG layout by topological depth — no heavy graph library).

Populate against the fixture workbook's API responses. No placeholder lorem anywhere; loading, empty, and error states designed, not defaulted.
```

**Accept when:** The shell renders entirely from API data; both themes hold up; the sheet-flow diagram reads clearly; components look like one product.

### PHASE 7 — Module views — inputs, calculations, outputs

*The working dashboard: review inputs, run what-ifs, read results, trace any number.*

```
Build the module views, all schema-driven from the logic model.

1. Inputs module: input cells grouped by sheet/section with their inferred labels, current values, and types. Designated inputs are editable (typed controls with validation); edits accumulate into an overrides draft with a clear "n changes · Run analysis / Reset" bar. Running posts overrides to /runs and streams the quiet progress affordance.
2. Calculations module: per calculation sheet, results in DataTables mirroring the sheet's own layout (headers from label detection). Every computed cell opens the lineage SidePanel via /lineage: formula, consumed values, recursively expandable — "explain this number".
3. Outputs module: the research result, presented like a report page, not a grid — output metrics as StatTiles with deltas vs the no-override baseline when overrides are active; ranked/classified lists as DataTables; business rules that produced a classification shown inline in readable form ("Rated A — score 0.84 ≥ 0.80"). Add charts with Recharts only where the data shape earns them (time series → line, composition → stacked bar); no decorative charts.
4. Versions module: version list with status; the DiffReport rendered as a readable changelog grouped by change type, each entry showing its affected outputs; activate / rollback actions with the validation gate and override-reason dialog.
5. Validation module: the ValidationReport — headline pass/fail, per-sheet coverage, mismatch table with cell, Excel value, engine value, delta.

Keep every screen quiet: summary before detail, accent only on interactive elements, semantic color only for validation and deltas.
```

**Accept when:** A researcher can review inputs, run a what-if, see recalculated outputs with deltas, trace any number to its formula, and review a version diff — without touching Excel.

### PHASE 8 — Exports

*Results leave the system as cleanly as they entered.*

```
Build backend/app/exports and the frontend export affordances.

- Excel: export a run's results as .xlsx mirroring the original sheet structure — computed values in place, a cover sheet with run metadata (version, timestamp, overrides applied, validation status). Optionally include original formulas as a second tab-set for auditability.
- CSV: any DataTable view exports what it shows.
- PDF: an "Analysis report" via WeasyPrint — cover, key output metrics, charts, business-rule summary, and the version changelog if overrides or a new version are involved. Typography and palette match the app (print-safe, light theme).
- Endpoints: GET /api/runs/{run_id}/export?format=xlsx|csv|pdf (+ scope params). Frontend: one consistent Export menu on Outputs, Calculations, and Versions views.

Test xlsx round-trip: exported values re-ingest and match the run's stored results.
```

**Accept when:** All three formats download correctly; the PDF looks like the product; the xlsx round-trip test passes.

### PHASE 9 — Hardening & real-workbook QA

*Point the finished system at the real master workbook and close every gap it exposes.*

```
QA pass against the real master workbook.

1. Ingest the real master workbook end to end: upload → interpret → validate → activate → dashboard → export. Log every failure or gap as a checklist in QA.md and fix in priority order: (a) validation mismatches, (b) unsupported functions (implement them in the registry), (c) misclassified cells/sheets (improve heuristics, or expose the override UI), (d) label detection misses, (e) UI issues with real data volumes.
2. Performance: interpretation and a full run must feel interactive for a workbook of this size; profile and cache (parsed model reused across runs; incremental runs for overrides). Report timings in QA.md.
3. Robustness: oversized uploads, corrupt files, .xls rejection with a clear message, concurrent runs, empty sheets, merged-cell edge cases.
4. Add an end-to-end test that uploads the fixture, activates it, runs an override, and exports — asserting on the full chain.
5. Update README.md with setup, architecture summary (link CLAUDE.md), and the operational runbook: how the research team uploads a new master version and reviews its diff.

Do not "fix" a validation mismatch by special-casing this workbook's sheet names or cells — improve the general parser/engine, per CLAUDE.md rule 3.
```

**Accept when:** The real workbook validates clean (or every residual mismatch is understood and documented); the e2e test passes; a non-developer can follow the runbook.

---

## Build log & plan amendments

### 2026-09-10 — Phase 0 complete
Committed. uv + Python 3.12, FastAPI backend packages scaffolded, React 18 + Vite + Tailwind v4 frontend with token themes, CLAUDE.md standing rules, Makefile/npm scripts, health-check loop proven. Note: repo currently lives in a OneDrive folder on C:; advised moving to D:\dev (OneDrive sync locks break watchers/installs and filled C:).

### 2026-09-10 — Phase 1 complete (commit 473b176)
Streaming openpyxl parser (formulas + cached values), shared/array formulas expanded, function inventory with string-literal stripping, per-sheet gzipped JSON storage, upload/read API with clear rejections. 34 tests passing.

**Scale findings (drive all later phases):** real workbook = 39 sheets, 1.57M non-empty cells, 793,919 formula cells, only 20 distinct functions. Ingest 52s, zero formula cells missing cached values.

### Plan amendments (agreed)
1. **Phase 2 amended for scale:** dedupe formulas into R1C1-normalised FormulaTemplates (one AST per template + ranges using it); primary dependency graph at template/range-block level in networkx with acyclicity + topo order proven there; cell-level edges derived lazily (arrays/scipy sparse if ever materialised); interpretation streams sheet-by-sheet, budget ~2 min on real workbook; record the 20-function inventory verbatim in CLAUDE.md as the Phase 3 engine contract. Amended prompt was issued in-session.
2. **Phase 6 shell pulled forward:** after Phase 2, build the dashboard shell + design system + overview page (sheet-flow diagram, role classifications) from model endpoints, so the researcher can verify/correct sheet roles before the engine is built. Phase 7 modules still wait for the engine. New order: 2 → 6(shell) → 3 → 4 → 5 → 7 → 8 → 9.
3. **Phase 3 note (upcoming):** evaluation should run template-by-template over ranges (vectorised where possible), not cell-by-cell loops, given 794k formula cells.