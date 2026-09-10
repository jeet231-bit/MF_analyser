# mf-analyser — standing context for every session

Internal "Excel-driven research analytics platform". Monorepo: `backend/` (Python 3.12, FastAPI, Pydantic v2, uv) and `frontend/` (React 18, TypeScript, Vite, Tailwind, Recharts). The build proceeds in numbered phases 0–9, specified with acceptance criteria in `docs/BUILD_KIT.md`; one phase per session, one commit per phase. Phase 0 is done. Use plan mode for Phases 2, 3 and 7.

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
- Real master workbooks go in `samples/` (git-ignored). The pytest fixture workbook is generated in code with openpyxl, never committed as a binary.
- Commit per phase. After each phase, run the tests and demonstrate the acceptance criteria.

## Scale facts (drive every design decision from Phase 2 on)

The real master workbook (in `samples/`, git-ignored) has 39 sheets, ~1.57 million non-empty cells and ~794 thousand formula cells; a full openpyxl load takes minutes and gigabytes. Consequences already built into Phase 1 and binding afterwards:

- Parse with openpyxl `read_only=True` streaming, two passes (formulas, then cached values); merged ranges, tables, defined names and macro/pivot/external-link flags come from the OOXML parts directly (`app/parser/package.py`).
- Cells live in a columnar `CellColumns` (parallel lists), never one object per cell. Sheets are persisted one at a time as gzipped JSON blobs (`raw_sheets` table) so peak memory is one sheet.
- Dates are stored as Excel serial numbers with `value_type="date"`; the number format says how to display them.
- The function inventory strips string literals and `_xlfn.` prefixes; it is the contract for engine coverage. Real workbook inventory: IF, VLOOKUP, HLOOKUP, COUNTIFS, IFERROR, AND, OR, SEARCH, ISNUMBER, CONCATENATE, COUNTIF, SUMPRODUCT, SUMIF, COUNT, AVERAGEIF, LEFT, DATE, YEAR, MONTH, DAY.
- Phase 2 must not build 794k independent ASTs naively: parse each distinct formula text once (cache by text) and prefer R1C1-normalised patterns so a column of copied formulas shares one AST and one dependency template. Phase 3 needs the same reuse for evaluation.
- Pivot tables are not recalculated; their cached outputs are treated as constants (inputs). Flagged in `RawWorkbook.warnings`.

## Environment notes (this machine)

- Windows 11. No `make` or `winget` on PATH; the root `package.json` scripts (`npm run dev|test|lint`) mirror every Makefile target.
- `uv` lives at `~/.local/bin` and manages Python 3.12 independently of the system Python 3.11/3.14 installs.
- WeasyPrint (PDF export, Phase 8) is an optional extra (`uv sync --extra pdf`) because it needs the GTK/Pango runtime on Windows.
