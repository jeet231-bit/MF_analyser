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
| GTK3 runtime (Windows, PDF export only) | 3.24 | WeasyPrint needs Pango and GObject. Install the [GTK for Windows Runtime Environment Installer](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) (`gtk3-runtime-3.24.31-2022-01-04-ts-win64.exe`, default options, which adds `C:\Program Files\GTK3-Runtime Win64\bin` to PATH), then restart the terminal that runs the backend. Linux: `apt install libpango-1.0-0 libpangoft2-1.0-0`; macOS: `brew install pango`. |

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

**Where the data lives (developers).** Since Phase 11 the database and uploaded workbooks default to `C:\MFAnalyser\data` (Linux/macOS: `~/.local/share/mf-analyser`), never `backend/data` and never anywhere under OneDrive: the app refuses to start when the data directory is inside a synced folder, because the sync client locks and corrupts an open SQLite file. Move an existing development database once with `robocopy backend\data C:\MFAnalyser\data /E`; stored file paths are relative to the data directory, so the copy is the whole migration. Override with `MFA_DATA_DIR` in `backend/.env`.

**Production shape.** `npm run build` then `npm run serve` (or `make start`) runs one uvicorn process that serves the API under `/api` and the built UI from `frontend/dist` with SPA fallback, on `0.0.0.0:8000`. `npm run dev` is unchanged for development.

The integration test against the real master workbook is opt-in because it parses over a million cells:

```bash
cd backend && uv run pytest -m real -s
```

## API (so far)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness, DB check |
| GET | `/api/config` | Display settings from `dashboard.config.json` (name, scope, number format) |
| POST | `/api/workbooks` | Upload `.xlsx`/`.xlsm`; parses into an immutable version, returns summary counts and the Excel function inventory |
| GET | `/api/workbooks` | List versions |
| GET | `/api/workbooks/{id}` | One version with its summary |
| GET | `/api/workbooks/{id}/raw?sheet=` | The RawWorkbook extraction (all sheets, or one) |
| POST | `/api/workbooks/{id}/interpret` | Build the logic model (`{"sheets": [...]}` or the config `sheetScope`) |
| GET | `/api/workbooks/{id}/model?sheet=&include=ast` | Templates, blocks, sheet roles, edges, execution order |
| GET | `/api/workbooks/{id}/graph?level=sheet\|block\|cell&cell=Sheet!A1&depth=` | Dependency graph at the chosen level |
| GET | `/api/workbooks/{id}/rules?sheet=&kind=` | Extracted business rules |
| PATCH | `/api/workbooks/{id}/model/sheets/{name}` | Override a sheet's role with a reason |
| POST | `/api/workbooks/{id}/runs` | Execute the model: `{overrides: {"Sheet!A1": v}, mode: "auto"|"full"}`; the first override-free run is the baseline, later override runs are incremental |
| GET | `/api/workbooks/{id}/runs`, `/api/runs/{run_id}` | Run list and one run's summary (blocks, cells, seconds, hot templates) |
| GET | `/api/runs/{run_id}/values?sheet=&range=` | Computed and input values of a sheet for a run |
| GET | `/api/workbooks/{id}/lineage/{Sheet!A1}?run_id=&depth=` | Explain a cell: formula, consumed values, expandable |
| POST | `/api/workbooks/{id}/validate` | Zero-override run reconciled cell by cell against Excel's cached values, plus structural anomalies |
| GET | `/api/workbooks/{id}/validation` | Latest validation report |
| POST | `/api/workbooks/{id}/activate` | Activate the version (or roll back to it); a failed validation needs `{"override_reason": "..."}` |
| GET | `/api/workbooks/{a}/diff/{b}?refresh=` | Logic diff from version a to b: LOGIC (itemised, with affected outputs), DATA (counts), STRUCTURAL |
| GET | `/api/runs/{run_id}/grid?sheet=&r1=&r2=&c1=&c2=` | A window of a sheet as the run computed it: labelled columns and rows, formula / override / baseline-delta markers (≤ 200 × 120 cells) |
| GET | `/api/workbooks/{id}/inputs?run_id=` | Input blocks grouped by sheet; small blocks carry labelled, typed cells (the what-if levers), tables page through `/grid` |
| GET | `/api/workbooks/{id}/outputs?run_id=` | Output sheets in display order: headline metrics with deltas vs the baseline, business rules, a series descriptor when the sheet is a dated time series |
| POST | `/api/workbooks/{id}/runs` with `background: true` | 202: the run executes on a worker thread; poll `GET /api/runs/{run_id}` until `status` is `ok` or `failed` |
| GET | `/api/workbooks/{id}/lineage/{Sheet!A1}?explanation=` | Lineage now carries `explanation` (which IF / IFERROR branches fired, with the compared values) and `rule` (the template's business rule) |
| GET | `/api/runs/{run_id}/export?format=xlsx\|csv\|pdf&scope=outputs\|all\|sheet&sheet=&window=&formulas=&background=` | Download a run's results: xlsx with a cover sheet and values in place (output sheets by default; `scope=all` and large exports become 202 jobs), csv of exactly one grid window, the PDF analysis report |
| GET | `/api/runs/{run_id}/report.html` | The analysis report as HTML (what the PDF renders) |
| GET | `/api/exports/{job_id}`, `/api/exports/{job_id}/file` | Poll a background export, then download its file |
| GET | `/api/workbooks/{a}/diff/{b}/export?format=csv\|xlsx` | The version changelog as a table |

Interactive docs: http://127.0.0.1:8000/api/docs

## Build phases

The system is built one phase per session; each phase is committed separately and ends by running its tests and demonstrating its acceptance criteria. After the Phase 1 scale findings the order was amended to 0 → 1 → 2 → 6 (shell and overview only) → 3 → 4 → 5 → 7 → 8 → 9. The full specification and per-phase prompts are in [docs/BUILD_KIT.md](docs/BUILD_KIT.md); the research methodology the workbook implements is in `docs/Mutual Fund Analytics/`.

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Scaffold, tooling, CLAUDE.md, health-check loop | done |
| 1 | Excel ingestion → RawWorkbook (formulas + cached values, function inventory) | done |
| 2 | Logic interpretation: formula templates, block-level dependency DAG, classification, business rules | done |
| 3 | Analytical engine: vectorised block-by-block runs, incremental what-ifs, lineage | done |
| 4 | Validation and reconciliation, structural anomaly report, activation gate, Validation module | done |
| 5 | Versioning, upload pipeline, logic diff (data / logic / structural) with impact, Versions module | done |
| 6 | Dashboard shell, design system, overview page (pulled forward; module views wait for the engine) | done |
| 7 | Stage A: scope extension to the Report layer (upstream-closed, 15 sheets). Stage B: Inputs, Calculations, Outputs modules with what-if runs and lineage | done |
| 8 | Exports: xlsx (in place, cover sheet, background jobs), csv (grid windows), PDF analysis report, changelog export, one Export menu | done |
| 9 | Hardening: run limiter and bounded caches for two users, robustness and end-to-end tests, QA.md timings, master findings for the research team | done |
| 10 | Research views. Stage A: the semantic map, research API, declarative insights, snapshots. Stage B: the research console (rail with Research / Workbook switch, Dashboard, Insights, Funds with pivots, Fund detail, Categories, Movement, Admin, Upload) | done |
| 12 | Pivots: the master's 17 pivot tables parsed from the OOXML pivot parts, recomputed live from the engine over any layout (filters, rows, columns, values, aggregation), reconciled against Excel's cached output, with a dedicated screen and exports | done |
| 11 | Deployment on one Windows machine: one process serves API and UI, data outside the repo and OneDrive, NSSM service (or Scheduled Task), SQLite WAL + daily backups with a tested restore, firewall and URL, shared-password gate, runbook and go-live checklist | done |

## Runbook: a new master version

1. Close the workbook in Excel. Excel holds an exclusive lock on OneDrive files, and an upload or test that reads a locked file fails with "permission denied".
2. Save a **copy** of the master as `samples/master.xlsx`. Never point the system at the file Excel has open; `samples/` is a drop zone for copies and is git-ignored.
3. Upload it (the dashboard's upload control, or `POST /api/workbooks`). The upload pipeline parses the file, interprets it, validates it, and diffs it against the currently active version; the new version lands as **pending review**.
4. Open the Versions module. Read the changelog: logic changes first (each with the outputs it affects), then data changes as counts, then structural changes including new or resolved anomalies. Open the Validation module for the mismatch table and anomaly detail; fix real defects in the master and re-upload rather than accepting them.
5. Activate the version. A failed validation can only be activated with a written override reason, which is stored with the version. Rolling back is activating an older version.

## Runbook: a what-if

1. Open **Inputs**. Sheets with parameter blocks (weights, dates, thresholds) come first; tables page through the grid and any input cell can be edited in place. Every edit lands in the draft bar at the bottom: "n changes · Run analysis / Reset".
2. **Run analysis.** Incremental runs are synchronous (typically 1–5 s on the master; a change to the master table's key column is closer to a full run). The quiet top bar shows progress. A full recalculation from the UI runs in the background with a status chip.
3. Open **Outputs**. The Report layer comes first: headline metrics as tiles with signed deltas against the baseline, then the ranked table (tick "changed rows only" to see what moved), then the rules that produced the classifications. **Calculations** shows every intermediate sheet the same way.
4. Click any computed cell to open **explain this number**: the formula at that cell, which IF / IFERROR branches fired with the compared values, the business rule, and every value it consumed. Consumed formula cells open in place; the trail leads back.
5. "Back to baseline" in the bar drops the what-if; nothing is written to the workbook.

## Exports

The **Export** menu on Outputs, Calculations and Versions offers, per view: Excel of the output sheets (cover sheet with version, run, overrides and validation status; computed values in place at their original addresses with the original number formats; errors as Excel errors), Excel of every in-scope sheet (runs as a background job; optionally with a formulas tab-set for audit), CSV of exactly the grid window on screen, the PDF analysis report, and the version changelog as CSV or Excel. Every export is built from one view descriptor (rows, columns, labels, title, provenance), so a new kind of view exports through the same writers.

PDF rendering needs WeasyPrint: `cd backend && uv sync --extra pdf`. On Windows WeasyPrint also needs the GTK3 runtime, see Prerequisites; without it the PDF export answers 501 and the same report is available as HTML at `/api/runs/{run_id}/report.html`.

## Research views and the semantic map

The research API (`/api/research/*`) presents the same numbers entity by entity: which funds are top quartile, who moved between versions, how a fund compares with its category peers, and a set of computed insights. What a row *means* is declared in the `research` section of `dashboard.config.json`, never in code:

- `entity`: the sheet, row range, identity column and label column of the unit of analysis (a fund); `asOf` names the cell holding the as-of date (narratives say "since 31 Aug", never a filename); `universe` names a flag column whose non-matching rows are counted as "outside the universe" rather than dropped (`includeWhen` drops them).
- `dimensions`: category, AMC, plan, management team and any other grouping column. A dimension may declare `split` (the separator inside one cell, for example `","`) and `attribute`: `team` (default) keeps the cell as one group and renders it as "the team of A, B and C"; `person` attributes every fund to each member.
- `measures`: an ordered list of `{key, label, role, sheet, column, keyColumn, format, unit, higherIsBetter, primary}`; roles are `score`, `rank`, `quartile`, `return`, `factor`; formats include `number`, `integer`, `percent` and `inr_crore` (a corpus held in crore renders as "₹39.1 lakh crore" / "₹86,785 crore"). Measures on other sheets join on `keyColumn`.
- `phases` and `periods`: the bull/bear windows and the point-to-point periods, with labels read from a header row.
- `categoryStats`: where category averages live and which column keys them. Keys with no fund behind them are excluded from the categories view and counted as `statsOnly`.
- `constants`: named values read from cells (`{cell: "Sheet!A1", parse: number | firstDate | lastDate}`; the date parses pick a "dd Mon yyyy" token out of a header such as "11 Feb 2016 To 28 Aug 2018"). Predicates may compare against them with `"value": "$name"`, and may test a `dimension` (text) instead of a `measure`; `isnull` complements `notnull`.
- `coverage`: `{measure, constant}` (an inception-date measure against the earliest phase start) splits the funds whose composite reads "--" into too young to rate, a data gap, and no date on record; the dashboard's universe line and the three coverage cards read the same partition.
- `sectionLabels`: display names for insight sections ("winning" → "Who is winning").
- `quartileRule.unrankedBelow`: the workbook's own "fewer than N ranked funds means no quartiles" rule, used to explain unrated funds and unranked categories.
- `minGroupCount` (default 10): a league table or a dispersion card ignores groups with fewer rated members, so a tiny or exotic category never tops it forever; override per insight with the same key. On a `filter` insight it restricts the rows to categories of that size and exposes `{groups}` and `{min_group}`.
- `insights`: declarative questions with a computed sentence each (`where` predicates with `eq ne lt lte gt gte in top bottom notnull`; `top`/`bottom` take a `fraction`, 0.25 by default and 0.5 for "top half"; `sort`, `limit`, and modes `filter`, `groupBy`, `acrossVersions`, `aggregate`). Sentence placeholders are validated at load: `{count} {total} {pct} {sum} {versions} {groups} {min_group} {top.label} {top.value} {top.sub} {top.group} {group.label} {group.value} {group.count} {group.total} {hit.label} {hit.value} {hit.count} {hit.total} {measure.label}`. Every computed insight carries a `status`: `ok`, `empty` (no fund meets the test), `unavailable` (with a `note`, for example the consistency card before a second genuine month), or `problem`.
- `narratives`: the computed sentences on the dashboard (`universe` and `dashboard`), `movement`, `categories` and `fund` pages; `footer`; `findings` for the research team's data findings.

Sentences, in insights and narratives alike, are a string, an object or a list of objects `{default, zero, trigger, requires}`. `default` renders when every placeholder has a value; `zero` replaces it when the trigger placeholder (the first one in `default` unless `trigger` names one or several) is zero; without a `zero` variant a zero-triggered sentence is omitted, so a sentence made of zeros is never emitted. `requires` lists placeholders that must be present and non-zero for the sentence to appear at all ("of those moves" needs moves); `unless` lists placeholders that must be absent or zero (the coverage clauses of the executive summary appear only when nothing in scope is rated); `one` is the singular variant when the trigger is exactly one ("sits in the one fund ranked Q3 or Q4"). KPI tiles (`research.kpis`) follow the same rule: a tile whose value is zero is omitted unless `keepZero` is set, and a zero note is dropped. A card that needs composite ranks reports `unavailable` when the scope holds no rated fund, and a league table needs at least two eligible groups, so "the most Q1 funds (1 of 1)" cannot appear. Three tests pin the extreme scopes: unrated funds only, a single category below `minGroupCount`, and an AMC with exactly one rated fund. `{n|fund|funds}` renders the number with the right word and `{n?is|are}` renders only the word.

Consistency across months, fund history and movement read **per-version snapshots** (`research_snapshots`: entity → rank, quartile, score, label, category, plus the as-of date), taken when a version is activated and on first demand for versions activated earlier. Two activations with the same as-of date (a re-upload of the same master) are one genuine month; "held Q1 across all N genuine monthly uploads" therefore waits for a second month and says so.

`GET /api/research/config` shows how every reference resolved against the active version and lists problems in plain words ("measures[7] 'roll1y': sheet 'Summary-Perf' is not in scope; did you mean 'Summary-Performance'?"). An absent or broken section never breaks the app: every research endpoint answers `configured: false` with the problems. `MFA_DASHBOARD_CONFIG_PATH` points the backend at another config file (tests and deployments).

Endpoints: `/research/summary`, `/research/entities` (search, category, AMC, plan, quartile filters; sort; paging; `groupBy=<dimension>` or `<measure>_band` for pivots), `/research/entities/{key}`, `/research/categories`, `/research/movement?from=&to=`, `/research/insights?section=`, and `/research/{entities|categories|movement|insights}/export?format=csv|xlsx` through the same export view descriptor as every other export. The PDF analysis report carries an "Insights brief" section.

## The research console

The shell is an **icon rail** (68 px; it expands with labels on hover, and "Keep menu open" pins it, which Workbook mode does by itself because sheet names cannot be icons) and a **top bar** with the Research / Workbook switch, a global search that opens Funds, the active version pill, the theme toggle and the viewer's initials. The rail overlays the page when open, so the content keeps its width. **Workbook** mode keeps every sheet-shaped page from the earlier phases: the in-scope sheets grouped by role (each opens its grid with what-ifs and lineage), Weights & dates, Overview, Versions and Validation. The mode, page and pin persist per browser.

**Scope applies to every view.** The slim scope bar under the page title reads "All funds · every category · every AMC · both plans" and expands to the filter grid (every dimension, quartile, a band of any factor measure such as corpus or expense, rating status, a text match). Apply it once and the executive summary, the KPI tiles, the insights, the tables, movement and every export recompute for that scope: "executive summary for Direct plan, large-cap only" is one interaction, not a report request. The scope is sent as one `scope` parameter (JSON) to every research endpoint; band boundaries always come from the full table, and the coverage strip keeps the master's totals.

- **Dashboard**: the greeting ("Good morning, Jeet", from the browser clock and the viewer's name), the scope bar, the **executive summary** band (computed sentences leading with what is true: rated count, top quartile, who leads, the all-weather set, best value, the movement fact folded in), four KPI tiles with the coloured top rail (from `research.kpis` in the config), the quartile distribution with median and largest category, category leaders, the watchlist, and one quiet **coverage strip** at the bottom (a small bar, one sentence, and a link to the full breakdown in Admin). A card renders only when it has content; a zero-state fact is absorbed into the narrative.
- **Insights**: the configured cards by section, each with its computed sentence and rows; a card whose inputs are not yet available (held-Q1 before a second genuine month) says so instead of showing zeros. "See all" opens the Funds page on exactly those funds.
- **Funds**: the "Analyse funds by" pivot row (any dimension, or a quantile band of any factor measure such as corpus or expense) groups the table with subtotals; search, category, AMC, plan and quartile filters apply within groups; headers sort; the Δ rank column compares with the previous activated version. Export the current view as csv or xlsx.
- **Fund detail**: stat tiles (click any to trace the number through the workbook), the rank hero with the quartile rule in words as the engine evaluated it, bull and bear phases against the category average, peers, history across genuine uploads, and every measure with its cell. "Watch" pins the fund to the dashboard watchlist.
- **Categories**: a card per category with the chosen average, the quartile bar or the "fewer than N ranked funds" note, and a link into Funds.
- **Movement**: any two activated versions; tiles, the narrative, the data-repair note, moved-up and moved-down lists with repaired rows labelled.
- **Pivots**: the workbook's own pivot tables, read from the file's pivot definitions (never configured by hand) and recomputed from the engine's numbers. The list groups them by source sheet and says whether each is live (its source sheet is in the engine scope) or reads cached values, and when Excel last refreshed its own copy. Open one and every filter field offers every value in the data; rows, columns and values (with their aggregation) are chips over the pivot's fields; Excel's saved layout is the default and the global scope pre-fills the filter fields that `research.pivots.scopeFields` maps. A leaf row label finds that name in Funds. Exports as xlsx or csv with subtotals and the grand total.
- **Admin**: active version, reconciliation, structural warnings and data findings tiles; the findings list and the column map (both from `dashboard.config.json`); the rating-coverage breakdown; "Your name" for the greeting; then the Versions and Validation panels.

Two interim, per-browser settings exist until the platform has accounts: the **watchlist** and the **viewer's name** (the greeting). Both live in the browser's local storage, wrapped so that blocked storage never breaks a page. The name falls back to `viewer.defaultName` in `dashboard.config.json` ("Jeet" today) and to a plain "Good morning" when neither is set. The Phase 11 access gate is one shared password, not accounts: when real accounts arrive they replace it, supply the viewer's name from the signed-in identity, and own the watchlist.

## Deployment on one Windows machine

This is the runbook for the always-on office machine that serves the console to the team over the LAN. It assumes no cloud, SQLite, two users, and a person who is not a developer. Every command is run on that machine in **PowerShell opened as administrator** from the app folder (`C:\MFAnalyser\app` below). Print `deploy/CHECKLIST.md` and tick it off the first time.

**1. Install the prerequisites (once).**

- Put the app at `C:\MFAnalyser\app`: either `git clone <repo> C:\MFAnalyser\app` or unzip a copy of the repository there. Not under OneDrive, not on a network drive.
- Install uv, which installs Python by itself: `irm https://astral.sh/uv/install.ps1 | iex`, then close and reopen PowerShell. (The installer does this for you if uv is missing.)
- Install Node.js 20 or later from nodejs.org **or** copy a `frontend\dist` folder built on another machine (`npm run build`) into `C:\MFAnalyser\app\frontend\dist`. Node is only needed to build the web app.
- PDF export only: install the GTK3 runtime named in Prerequisites above. Everything else works without it. The installer checks for it and warns; `deploy\status.ps1` and `/api/health` report `PDF: available` or `PDF: unavailable: GTK not found …` so nobody discovers a 501 weeks later.
- Decide where the **off-machine backup copy** goes: a network share (`\\fileserver\mfa-backups`) or a OneDrive folder on this machine. OneDrive is fine for backups; the ban is only on the live database. Pass it to the installer as `-BackupMirror`.

**2. Run the installer.**

```powershell
cd C:\MFAnalyser\app
powershell -ExecutionPolicy Bypass -File deploy\install.ps1
```

It installs the backend, builds the web app, creates `C:\MFAnalyser\data` (database, uploaded workbooks, logs, an `inbox` folder) and `C:\MFAnalyser\backups`, writes `C:\MFAnalyser\config.env`, asks you to choose the **shared password**, registers the `MFAnalyser` Windows service (starts at boot, restarts itself within 5 s if it crashes, keeps running when nobody is signed in to Windows), opens TCP port 8000 in the Windows firewall for the office network, schedules the daily backup at 02:00, starts the service, waits until it answers, and prints the address to share. Options: `-BackupMirror \\fileserver\mfa-backups` (or a OneDrive folder) for the off-machine copy of every backup; `-DataDir D:\MFAnalyser\data` and `-BackupDir D:\MFAnalyser\backups` to put data or the local backup ring elsewhere; `-Port 8080`; `-DryRun` to see what it would do. **Without `-BackupMirror` the installer warns, in capitals, that backups are single-disk only**: a backup beside the data dies with the drive. If antivirus quarantines `deploy\tools\nssm.exe` (its SHA-256 is pinned in `deploy\tools\nssm.sha256` and verified before use), run the installer again with `-UseScheduledTask`: the app is then a Scheduled Task with the same start-at-boot and restart-on-failure behaviour, and every other script works unchanged. Run the installer again at any time to repair or update; it is idempotent.

**3. The address.** The installer prints it; it is `http://<machine-name>:8000/`, for example `http://research-pc:8000/`, and also `http://<ip-address>:8000/`. The other person types it into any browser on the office network and signs in with the shared password. The name form keeps working if the address changes; ask IT for a **DHCP reservation or a static address** for the machine so that the numeric form is stable too. Sessions last 12 hours of inactivity; "Sign out" is in the top bar.

**4. Is it running?** `deploy\status.ps1` prints the service state, the health check (including `PDF: available` or why not), the latest backup and whether its off-machine copy succeeded, and the last log lines. In the browser the top bar shows the active version. `Get-Service MFAnalyser` is the raw Windows view.

**5. Restart.** `deploy\restart.ps1`. Restart after editing `C:\MFAnalyser\config.env` or changing the password.

**6. Logs.** `C:\MFAnalyser\data\logs\mf-analyser.log` is the application log (rotates at 10 MB, ten files kept); `service.out.log` and `service.err.log` are the process output captured by the service; `backup.log` is the nightly backup. Send `mf-analyser.log` with any problem report.

**7. Backups and restore.** Every night at 02:00 the `MFAnalyser Backup` task writes `C:\MFAnalyser\backups\<YYYY-MM-DD>\` containing a consistent copy of the database (taken with SQLite's online backup API, safe while the app runs), every uploaded workbook, and a `manifest.json`; folders older than 30 days are removed. `deploy\backup-now.ps1` takes one immediately. To go back to a day: `deploy\restore.ps1 -Date 2026-09-13`, which first backs up the current state, stops the app, restores the database and workbooks, and starts it again; the restore refuses to run while the app holds the database. Rehearse it once after installing (checklist section F).

**Off the machine.** The local ring is a snapshot, not a backup: it sits on the same disk as the data. With `-BackupMirror` set, every nightly run also copies the newest dated folder to that share or OneDrive folder and keeps the **last 4 weekly copies** there (the newest backup of each of the last four weeks); `backup.log` and `deploy\status.ps1` say whether the copy succeeded, and a mirror that is offline is reported, not fatal. To restore from the mirror, copy its dated folder into `C:\MFAnalyser\backups\` and run `deploy\restore.ps1 -Date <that date>`. If no mirror was given, the installer, the nightly log and `status.ps1` all warn that backups are single-disk only; rerun the installer with `-BackupMirror` as soon as a share or OneDrive folder exists.

**8. Change the password.** `deploy\set-password.ps1` asks twice, stores only a hash in `config.env`, and restarts the service. Tell the other user the new one.

**9. The monthly routine.** (1) Close Excel so the master is not locked. (2) Save a copy of this month's master workbook, for example into `C:\MFAnalyser\data\inbox` on the server or anywhere on your own PC (never point the app at the live OneDrive file). (3) In the console open **Upload** and choose the copy; wait for the validation result. (4) Open the new version under **Versions** and review the diff against the active version: logic changes are listed formula by formula, data growth and structural changes are counted. (5) **Activate** it. Dashboards, funds and movement now read the new month; the previous version stays available for comparison.

**10. Uninstall.** `deploy\uninstall.ps1` removes the service, the backup task and the firewall rule and keeps the data, backups and config.

## Deployment notes

- **One backend process.** Run uvicorn with a single worker (the default; never `--workers 2+`). The engine state cache, the sheet cache, the run limiter and background jobs are all in-process; a second process would double memory and split the caches.
- **Sizing.** On the 15-sheet master each live engine state is about 300 MB. `MFA_STATE_CACHE_ENTRIES` (default 3) bounds how many stay cached: the baseline plus the two most recent what-ifs. `MFA_MAX_CONCURRENT_RUNS` (default 1) serialises engine runs: a second user's run answers 409 with `Retry-After` and the dashboard waits and retries by itself ("another run is in progress"). Budget 2 GB of RAM for two concurrent users plus interpretation headroom, and 500 MB of disk per uploaded version (raw sheets, run values, exports).
- **Concurrency behaviour.** Two users may run what-ifs against the same version; runs execute one at a time and each is persisted with its own overrides. Uploading and activating a new version while another user is mid-session is safe: versions are immutable, the other user's runs and views keep reading their own version, and the version list simply shows which one is active.
- **Settings** come from `MFA_*` environment variables (`backend/.env.example`), from `backend/.env` in development, and in production from the config file the installer writes (`C:\MFAnalyser\config.env`, or `MFA_CONFIG_FILE`): data, backup, log and static directories, host and port, database URL (SQLite by default; Postgres via SQLAlchemy), upload limit, validation thresholds, run concurrency and cache sizes, the password hash and cookie secret. `MFA_ENVIRONMENT=production` refuses to start without the password hash and secret.
- **SQLite** runs in WAL mode with `synchronous=NORMAL`, a 5 s busy timeout and foreign keys on (set on every connection in `app/storage/db.py`), so the nightly backup and a reader never block a writer.
- **The access gate** is one shared password: PBKDF2-HMAC-SHA256 hash in the config, an HttpOnly `SameSite=Lax` session cookie signed with `itsdangerous`, every `/api` route behind it except health and the auth endpoints, three free failures per address and then a growing delay. The LAN is plain HTTP, so the cookie is not marked `Secure`; put a TLS proxy in front before exposing it beyond the office network. Without a hash (development, tests) there is no gate.

Keep the master free of circular references: the analyser reports a cycle readably and refuses to evaluate it rather than iterating around it. After fixing formulas in the master, force a full recalculation in Excel (Ctrl+Alt+F9) before saving the copy, so the cached values the validator compares against are current.

Changing the sheet scope: `sheetScope` in `dashboard.config.json` must be upstream-closed (every sheet an in-scope formula reads is itself in scope). Derive it rather than guess it: `app/model/scope.py` computes the closure from formula text, and `cd backend && uv run pytest -m real -s tests/test_real_scope.py` checks the configured scope against the master.

## Known constraints (v1)

VBA is not interpreted (flagged). Function coverage is bounded by the Phase 1 inventory; unsupported functions fail loudly. Volatile and external references are treated as declared inputs. Circular references are unsupported. All automatic classifications are user-overridable.
