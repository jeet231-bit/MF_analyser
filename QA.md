# QA record: the real master workbook

Measured on 11 September 2026 against `samples/master.xlsx` (the recalculated 15-sheet master, version `12acdba8`), on the development laptop (Windows 11, Python 3.12, single uvicorn worker). Numbers are wall-clock unless marked engine. Re-measure with `cd backend && uv run pytest -m real -s` after any engine change; the tests print every figure below.

## Workbook

| Fact | Value |
| --- | --- |
| Sheets in the file / in scope | 39 / 15 |
| Non-empty cells / formula cells in the file | 1,565,814 / 793,919 |
| Formula cells in scope | 789,828 |
| Formula templates / formula blocks / input blocks | 223 / 250 / 69 |
| Business rules extracted | 317 |
| Excel functions used (all inside the 20-function contract) | IF, VLOOKUP, HLOOKUP, IFERROR, COUNTIFS, AND, OR, CONCATENATE, COUNTIF, SUMPRODUCT, SEARCH, ISNUMBER, SUMIF, COUNT, AVERAGEIF, LEFT, DATE, DAY, MONTH, YEAR |

## Timings

| Step | Measured | Notes |
| --- | --- | --- |
| Ingest (parse the 17.8 MB file into a version) | 70 s | streaming openpyxl, two passes; peak memory is one sheet |
| Interpret (templates, blocks, DAG, rules) | 35 s, peak 333 MB | |
| Validate (full run + cell-by-cell reconciliation + anomalies) | 41 to 44 s | 789,828 / 789,828 reconciled |
| Upload pipeline end to end (ingest + interpret + validate + diff) | 156 s | the upload request returns when it lands as pending review |
| Full run | 7.2 s (engine 5.8 s), peak 350 MB | 250 blocks |
| Incremental what-if, typical (a master-table value) | 3.6 s | 128 blocks recomputed |
| Incremental what-if, worst case (a master-table key column) | 3.4 s in isolation, 6.5 s under load | every lookup in the workbook re-resolves |
| Incremental what-if, a ranking weight | 0.6 s engine, about 1 s wall | 18 blocks |
| First what-if after a backend restart | about 9 s | the baseline grids are rebuilt once from stored values, then cloned |
| Background full run from the UI | 15 s wall | |
| Export xlsx, output sheets (default) | 6.6 s, 1.2 MB | synchronous |
| Export xlsx, all 15 sheets | 38 s, 8.0 MB | background job |
| Export csv, one grid window (100 rows) | 0.2 s, 28 KB | |
| Analysis report, HTML | 2.2 s, 32 KB | |
| Analysis report, PDF (WeasyPrint with the GTK3 runtime) | 4.3 s, 50 KB | |
| Live engine state (grids + string table) | about 300 MB each | `MFA_STATE_CACHE_ENTRIES` bounds how many are kept, default 3 |
| Research table build (3,232 entities, 34 measures, phases, periods, category stats) | 1.6 s cold, then cached | per (version, run); built once at activation together with the version's snapshot |
| Research summary | 0.02 s warm | movement, history and held-Q1 read per-version snapshots (about 60 KB gzipped each), never other versions' tables |
| Research entities page / fund detail / categories | 0.02 s / 0.09 s / 0.02 s | detail includes the quartile rule in words (engine re-evaluation with tracing) |
| Insights (12 cards) | 0.2 s cold, 0.17 s warm | flat in the number of stored versions |

Budgets asserted by the real tests: full run under 90 s, typical what-if under 5 s, worst-case what-if under 8 s, sampled reconciliation at least 99 percent (measured 100 percent).

## Sizing guidance

For two concurrent users on one backend process: about 2 GB of RAM (three cached engine states plus interpretation headroom), 500 MB of disk per uploaded version (raw sheets, run values, exports), and four CPU cores are comfortable. Runs are serialised by the run limiter, so a second user's what-if waits a few seconds behind the first rather than doubling memory.

## Validation and anomaly status

- Reconciliation: 789,828 of 789,828 formula cells match Excel at 15 significant digits; text, booleans and errors match exactly.
- Structural anomalies: 10 duplicate-key warnings. Nine are header labels repeated inside lookup ranges (harmless by construction); one is real: six index funds appear twice on Domain rows 386 to 397 (see docs/MASTER_FINDINGS.md).
- Cycles: none in the recalculated master. The earlier Report/Averages circularity and the two pasted rows are documented in docs/MASTER_FINDINGS.md.

## Robustness checks (automated, `backend/tests/test_robustness.py`, `test_end_to_end.py`, `test_workbooks_api.py`)

| Case | Behaviour |
| --- | --- |
| Oversized upload | 413 with the limit named; nothing stored |
| Corrupt file / not a workbook | 422 "could not be read as an Excel workbook"; nothing stored |
| Legacy .xls | 415 with the "save as .xlsx" message |
| Empty sheet | interprets, runs, exports; empty grid windows |
| Merged header over a table | labels still detected from the header row |
| Workbook with a circular reference | validates as failed with the cycle described; can never be activated |
| Scoped sheet missing from the file | explicit scope → 422 naming the sheet; config scope → ignored, all sheets interpreted |
| Unrelated workbook uploaded | lands as pending review with its own diff; the active version is untouched |
| Two users running what-ifs at once | runs serialise; the second gets 409 + Retry-After and the dashboard retries; both persist |
| One user uploads and activates mid-session | the other user's version, runs and views are unaffected |

## Known gaps

- PDF export on Windows needs the GTK3 runtime (README Prerequisites). Without it the endpoint answers 501 and the HTML report remains available.
- openpyxl writes 16 significant digits to xlsx; Excel's own comparison is at 15, which is the round-trip criterion.
- Label detection reads the workbook's own header text; sensible names for the few cells that read oddly (as-of dates, column-index helpers, ranking-weight sections) come from `labelOverrides` in `dashboard.config.json`.
