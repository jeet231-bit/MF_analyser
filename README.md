# mf-analyser

Internal Excel-driven research analytics platform. A master Excel workbook is uploaded, interpreted into a versioned **Workbook Logic Model** (inputs → formula ASTs → dependency DAG → business rules → outputs), executed by an analytical engine that reconciles cell-by-cell against Excel's own cached values, and presented in a quiet dashboard with what-if runs, lineage ("explain this number"), version diffs, and exports.

Standing rules for every session live in [CLAUDE.md](CLAUDE.md). Read it first.

## Architecture

```
Master Excel ──► Parser / Logic Layer ──► Analytical Engine ──► Dashboard ──► Export
                 (RawWorkbook →            (topological eval,     (React,        (xlsx / csv / pdf)
                  WorkbookLogicModel)       what-if runs,          Recharts)
                                            lineage)
                        ▲
                        └── Validation: engine output reconciled against Excel cached values
```

- **backend/** — Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy (SQLite → Postgres) · openpyxl · networkx · `formulas`. Packages: `app/api`, `app/parser`, `app/model`, `app/engine`, `app/validation`, `app/exports`, `app/storage`.
- **frontend/** — React 18 · TypeScript · Vite · Tailwind v4 (token-driven) · Recharts · Vitest. Folders: `src/api`, `src/components`, `src/modules`, `src/theme`, `src/lib`.
- **dashboard.config.json** — the only place workbook-specific display preferences may live.
- **samples/** — real master workbooks (git-ignored).

## Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| uv | ≥ 0.8 | `irm https://astral.sh/uv/install.ps1 \| iex` (Windows) or `curl -LsSf https://astral.sh/uv/install.sh \| sh`. uv installs Python 3.12 itself: `uv python install 3.12`. |
| Node.js | ≥ 20 | with npm |
| GNU make | optional | every target has an `npm run` equivalent |

## Setup

```bash
git clone <repo> && cd mf-analyser
npm run install:all        # root tooling, backend venv (uv sync), frontend packages
# or: make install
```

## Run

```bash
npm run dev                # or: make dev
```

Starts the API on http://127.0.0.1:8000 (docs at `/api/docs`) and the web app on http://localhost:5173, which proxies `/api/*` to the backend. The landing page calls `GET /api/health` and shows the backend's status, so a green pill proves the loop end to end.

Run one side only: `npm run dev:backend` / `npm run dev:frontend`.

## Test and lint

```bash
npm test                   # pytest + vitest        (make test)
npm run lint               # ruff + eslint + tsc    (make lint)
```

Backend settings are read from environment variables prefixed `MFA_` (see `backend/.env.example`).

The integration test against the real master workbook is opt-in because it parses over a million cells:

```bash
cd backend && uv run pytest -m real -s
```

## API (so far)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness, DB check |
| POST | `/api/workbooks` | Upload `.xlsx`/`.xlsm`; parses into an immutable version, returns summary counts and the Excel function inventory |
| GET | `/api/workbooks` | List versions |
| GET | `/api/workbooks/{id}` | One version with its summary |
| GET | `/api/workbooks/{id}/raw?sheet=` | The RawWorkbook extraction (all sheets, or one) |
| POST | `/api/workbooks/{id}/interpret` | Build the logic model (`{"sheets": [...]}` or the config `sheetScope`) |
| GET | `/api/workbooks/{id}/model?sheet=&include=ast` | Templates, blocks, sheet roles, edges, execution order |
| GET | `/api/workbooks/{id}/graph?level=sheet\|block\|cell&cell=Sheet!A1&depth=` | Dependency graph at the chosen level |
| GET | `/api/workbooks/{id}/rules?sheet=&kind=` | Extracted business rules |
| PATCH | `/api/workbooks/{id}/model/sheets/{name}` | Override a sheet's role with a reason |

Interactive docs: http://127.0.0.1:8000/api/docs

## Build phases

The system is built one phase per session; each phase is committed separately and ends by running its tests and demonstrating its acceptance criteria. After the Phase 1 scale findings the order was amended to 0 → 1 → 2 → 6 (shell and overview only) → 3 → 4 → 5 → 7 → 8 → 9. The full specification and per-phase prompts are in [docs/BUILD_KIT.md](docs/BUILD_KIT.md); the research methodology the workbook implements is in `docs/Mutual Fund Analytics/`.

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Scaffold, tooling, CLAUDE.md, health-check loop | done |
| 1 | Excel ingestion → RawWorkbook (formulas + cached values, function inventory) | done |
| 2 | Logic interpretation: formula templates, block-level dependency DAG, classification, business rules | done |
| 3 | Analytical engine: full and incremental runs, lineage | |
| 4 | Validation and reconciliation; activation gate | |
| 5 | Versioning and logic diff with impact analysis | |
| 6 | Dashboard shell and design system | |
| 7 | Module views: inputs, calculations, outputs, versions, validation | |
| 8 | Exports: xlsx, csv, pdf | |
| 9 | Hardening and real-workbook QA; runbook | |

## Known constraints (v1)

VBA is not interpreted (flagged). Function coverage is bounded by the Phase 1 inventory; unsupported functions fail loudly. Volatile and external references are treated as declared inputs. Circular references are unsupported. All automatic classifications are user-overridable.
