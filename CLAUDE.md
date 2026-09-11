# mf-analyser — standing context for every session

Internal "Excel-driven research analytics platform". Monorepo: `backend/` (Python 3.12, FastAPI, Pydantic v2, uv) and `frontend/` (React 18, TypeScript, Vite, Tailwind, Recharts). The build proceeds in numbered phases 0–9, specified with acceptance criteria in `docs/BUILD_KIT.md`; one phase per session, one commit per phase. Phases 0, 1, 2 and 6 (shell + design system + overview only) are done. Agreed order from here: **3 → 4 → 5 → 7 → 8 → 9**. Use plan mode for Phases 3 and 7. Phase 3 must evaluate template-by-template over ranges (vectorised where possible), never cell by cell, and may assume a clean DAG: the master's one circular reference was fixed in the file (`samples/master.xlsx`); cycles are still reported readably and refused.

Frontend layout (Phase 6): `src/api` (typed clients mirroring `backend/app/model/schema.py`), `src/components` (Card, StatTile, DataTable, Pill, EmptyState, SidePanel, ProgressBar, Button, Select), `src/modules/shell` (AppShell, Sidebar, role-derived navigation), `src/modules/overview` (stat tiles, SVG sheet flow with a pure `layoutByDepth`, editable roles panel, grouped rules, cycle chip, upload). Data loading goes through `src/lib/useAsync.ts`. Tests mock `fetch` with `src/test/mockApi.ts`. Disabled sidebar modules carry an "arrives with the engine" note until Phase 7.

## Standing rules

1. **ARCHITECTURE:** Master Excel → Parser/Logic Layer → Analytical Engine → Dashboard → Export. The uploaded Excel workbook is the source of analytical truth. The app interprets and executes it; it never re-implements its business logic.

2. **The parser converts any workbook into a structured Workbook Logic Model:** Inputs → Formulas (as ASTs) → Dependencies (a DAG) → Transformations → Business Rules → Outputs. Everything downstream (engine, validation, dashboard, exports) consumes only this model, never the raw file.

3. **HARD RULE, workbook-agnostic code:** no sheet names, cell addresses, or business-specific terms from any particular workbook may appear in engine or frontend code. Workbook-specific display preferences (labels, ordering, which sheets are "outputs") live only in the editable `dashboard.config.json` overlay at the repo root. Never fix a validation mismatch by special-casing a sheet or cell; improve the general parser/engine.

4. **Validation is a first-class feature.** The engine's results must be reconcilable cell-by-cell against Excel's own cached values (numeric relative tolerance 1e-9; text/bool/date/error exact). A workbook version becomes "active" only after its validation passes, or after an explicitly logged override.

5. **UI register:** minimal, professional, Apple/CRED-like, quiet. Off-white ground `#F6F6F4`, white surface cards, hairline borders `#E3E3DF` instead of shadows, ink `#17191D`, muted `#6B7078`. One blue accent `#2F55D4` used only for interactive/selected states. Semantic colors only for validation and deltas (positive `#1E7F4F`, warning `#A16207`, negative `#B4232A`). Schibsted Grotesk for headings/UI, Instrument Sans for body, tabular figures wherever digits align. 8pt spacing grid, 12–16px radii, one elevation level. Full dark-mode token set: ground `#0E1013`, surface `#16181D`, lifted accent `#8CA2EE`. Light/dark follow the system with a manual toggle. No placeholder lorem; loading, empty, and error states are designed, not defaulted.

6. **Tests ship with every feature.** Backend features need pytest coverage before they count as done. Frontend components get vitest coverage where logic exists. Run `make test` (or `npm test`) before declaring a phase complete.

## Known constraints (v1)

- VBA / macros are not interpreted; `.xlsm` files are ingested and flagged "contains macros — macro logic is not interpreted".
- Excel function coverage is bounded by the Phase 1 function inventory; unsupported functions must fail loudly (`UnsupportedFunctionError` naming cell + function), never silently mis-compute.
- Volatile functions (NOW, RAND, …) and external references are treated as declared inputs.
- Circular references / iterative calculation are unsupported and reported.
- Every automatic classification (cell role, sheet role, label) is user-overridable via API.

## Conventions

- Backend: `uv` manages the venv (`backend/.venv`); Python is pinned by `backend/.python-version`. Lint with `ruff check` + `ruff format`. API routers live in `app/api`, one file per resource, aggregated in `app/api/router.py`. Domain packages: `parser`, `model`, `engine`, `validation`, `exports`, `storage`. Settings come from `app/config.py` (env prefix `MFA_`).
- Frontend: Vite dev server proxies `/api` to the backend on port 8000. Design tokens are CSS variables in `src/theme/tokens.css`, exposed to Tailwind v4 via `@theme`. Never hard-code a colour outside the token file. Pages live in `src/modules/<module>/`, shared UI in `src/components/`, API clients in `src/api/`.
- Storage: SQLite in `backend/data/` for development, via SQLAlchemy so the same models move to Postgres.
- `samples/master.xlsx` is a **copy** of the master dropped in for each new version, never the file Excel has open (Excel locks OneDrive files; reads then fail with PermissionError). The pytest fixture workbook is generated in code with openpyxl, never committed as a binary.
- Commit per phase. After each phase, run the tests and demonstrate the acceptance criteria.

## Scale facts (drive every design decision from Phase 2 on)

The real master workbook (in `samples/`, git-ignored) has 39 sheets, ~1.57 million non-empty cells and ~794 thousand formula cells; a full openpyxl load takes minutes and gigabytes. Consequences already built into Phase 1 and binding afterwards:

- Parse with openpyxl `read_only=True` streaming, two passes (formulas, then cached values); merged ranges, tables, defined names and macro/pivot/external-link flags come from the OOXML parts directly (`app/parser/package.py`).
- Cells live in a columnar `CellColumns` (parallel lists), never one object per cell. Sheets are persisted one at a time as gzipped JSON blobs (`raw_sheets` table) so peak memory is one sheet.
- Dates are stored as Excel serial numbers with `value_type="date"`; the number format says how to display them.
- The function inventory strips string literals and `_xlfn.` prefixes; it is the contract for engine coverage. Real workbook inventory: IF, VLOOKUP, HLOOKUP, COUNTIFS, IFERROR, AND, OR, SEARCH, ISNUMBER, CONCATENATE, COUNTIF, SUMPRODUCT, SUMIF, COUNT, AVERAGEIF, LEFT, DATE, YEAR, MONTH, DAY.
- Pivot tables are not recalculated; their cached outputs are treated as constants (inputs). Flagged in `RawWorkbook.warnings`.

## Logic model design (Phase 2, binding for every later phase)

- **Templates, not per-cell ASTs.** Every formula is normalised to R1C1 relative to its cell (`app/model/templates.py`: fast regex key, then one parse per group, merged by canonical AST text). The real workbook's 793,919 formulas collapse to 282 templates; the 10 in-scope sheets hold 145. A template count in the tens of thousands means a normalisation bug.
- **Own formula grammar** in `app/model/formula/` (tokenizer + Pratt parser → Pydantic AST with `Axis(abs, v)` references). The `formulas` library is not used for parsing; it remains available as a reference for function semantics.
- **Blocks and a two-level graph.** A `FormulaBlock` is a maximal rectangle of one template; its read footprints are rectangles computed by rectangle arithmetic (`ref_footprint`). `InputBlock`s are rectangles of constants covered by footprints (numpy masks in `app/model/blocks.py`). The networkx graph lives at block level only; cell-level dependencies are derived lazily from a block's template (`cell_dependencies`, `cell_dependents` in `app/model/interpreter.py`). Never materialise a cell-level graph.
- Array formulas evaluate at their anchor: footprints and lazy dependencies use the anchor cell, not the block.
- A block whose footprint overlaps itself is `self_dependent` with an evaluation order (`top_to_bottom`, `left_to_right`, `row_major`) or flagged `cycle`. Cross-block cycles are reported as SCCs with readable `cycle_descriptions`; they are unsupported for evaluation in v1.
- Real-workbook history: the original master had one reference-level circularity on Bull-Bear Returns (two scratch COUNTIF cells parked in rows 3–4, which every `HLOOKUP(…, $3:$4, …)` scans, while they counted a column derived from the lookups). It was fixed in the file by moving the two cells to AZ1:AZ2 (a sheet-XML cut/paste that kept formula text verbatim); `samples/master.xlsx` interprets with zero cycles. Never engineer around cycles in the engine; fix the master.
- **Scope is data.** `dashboard.config.json` `sheetScope` lists the sheets to interpret; `POST /interpret {sheets}` overrides it. Out-of-scope sheets referenced by in-scope formulas become `external` input blocks (declared inputs with cached values).
- Sheet roles and block classification are heuristics with a precedence chain: heuristic → `dashboard.config.json` (`sheetRoleOverrides`, `outputSheets`) → user override (`PATCH /model/sheets/{name}`, persisted per version).
- Business rules are extracted per template (`app/model/rules.py`): condition bands from IF/IFS ladders, thresholds against literals or absolute labelled cells, lookups with small fixed tables materialised, IFERROR fallbacks.

## Engine function contract (Phase 3)

The real workbook's in-scope formulas use exactly these Excel functions (Phase 1 inventory, counts are formulas using the function): IF 417,915 · VLOOKUP 396,052 · HLOOKUP 329,221 · IFERROR 214,758 · COUNTIFS 196,613 · AND 116,504 · OR 78,867 · CONCATENATE 57,785 · COUNTIF 26,715 · SUMPRODUCT 25,945 · SEARCH 23,612 · ISNUMBER 23,560 · SUMIF 16,231 · COUNT 3,250 · AVERAGEIF 280 · LEFT 52 · DATE 2 · DAY 2 · MONTH 2 · YEAR 2. The engine must implement all twenty with Excel semantics and raise `UnsupportedFunctionError` for anything else.

## Environment notes (this machine)

- Windows 11. No `make` or `winget` on PATH; the root `package.json` scripts (`npm run dev|test|lint`) mirror every Makefile target.
- `uv` lives at `~/.local/bin` and manages Python 3.12 independently of the system Python 3.11/3.14 installs.
- WeasyPrint (PDF export, Phase 8) is an optional extra (`uv sync --extra pdf`) because it needs the GTK/Pango runtime on Windows.
