# Findings in the master workbook

This note is for the research team. It lists what the analyser found in the Equity MF Analyser master while it was being interpreted, checked and reconciled against Excel's own results, cell by cell. Five things came up. Three were defects in the workbook and are fixed; two are data gaps that the workbook handles as designed but that are worth knowing about.

Each item says what it was, what it affected, and where it stands now.

## 1. Roll Perf, row 3181: a row that read another row's data

**What it was.** The formulas in row 3181 of Roll Perf (columns K to U) pointed at row 3258 instead of their own row. Every other row in that table reads its own row. The signature is a row that was cut and pasted from further down the sheet: the formulas kept their original references.

**What it affected.** Row 3181's fund showed the rolling-return figures and ranks of a different fund. Because Composite Ranks and Summary-Performance look those figures up by scheme name, the wrong numbers flowed into that fund's composite rank and into the summary.

**Status: fixed** in the master on 11 September 2026. The analyser's structural check flags this pattern ("formulas read row 3258 instead of their own row") and reported it as resolved when the corrected file was uploaded. The version diff records it as 9 repaired cells.

## 2. Bull-Bear Returns, row 3182: the same cut-and-paste pattern

**What it was.** Row 3182 of Bull-Bear Returns (37 formula cells from column O to BA) read row 3259 instead of row 3182.

**What it affected.** That fund's bull-market and bear-market returns, and its bull/bear ranks and quartiles, belonged to another fund. Those feed Composite Ranks (RANK-Bull, RANK-Bear) and Summary-Performance (QRTL-BULL, QRTL-BEAR).

**Status: fixed** in the same master update. The diff records 37 repaired cells, and the structural check reports the anomaly as resolved.

## 3. Averages sheet: a circular reference around the Report averages

**What it was.** The category averages on the Averages sheet (F8 to L49) were computed with AVERAGEIF over whole Report columns, for example `AVERAGEIF(Report!$AC:$AC, $C8, Report!G:G)`. Report's forty "AVERAGE-..." rows at the bottom (rows 1510 to 1549) look those averages up from Averages. So Averages read Report, and Report read Averages: a circular reference. Excel tolerated it only because the criterion never matched the AVERAGE rows themselves.

**What it affected.** Nothing numerically, as long as Excel kept calculating in the same order. It is still a genuine circularity: Excel's recalculation of the Report page depended on the order in which it happened to visit cells, and any tool that evaluates the workbook by its dependencies (this analyser included) has to refuse it.

**Status: fixed** on 11 September 2026 by bounding the 280 AVERAGEIF ranges to the fund rows, `Report!$AC$10:$AC$1509` and `Report!G$10:G$1509` and so on. Values are unchanged. The master now evaluates with zero circular references.

## 4. CY Returns: Alphagrep Multi Asset Allocation is missing

**What it is.** Both plans of Alphagrep Multi Asset Allocation Fund (Direct IDCW and Regular IDCW) are in the Report's fund list but are not present in the CY Returns sheet. Their calendar-year returns on Report (columns G to M) therefore show `#N/A`.

**What it affects.** Excel's AVERAGEIF returns an error as soon as one matched cell in the averaged range is an error. Because these two funds sit inside the "Multi Asset Allocation" category, the category averages for Regular-Multi Asset Allocation and Direct-Multi Asset Allocation on the Averages sheet come out as "--" rather than as numbers, and the corresponding AVERAGE rows on Report show "--" too. The other thirty-plus funds in that category do have values; they are simply not averaged.

This is not a calculation error. The analyser reproduces exactly what Excel does here (it initially did not, and was corrected to match). It is a data gap: the two funds need CY Returns rows, or they should be excluded from the category, for the category averages to appear.

**Status: open, for the research team to decide.** No change was made to the master.

## 5. First NAV: 34 funds have no first-NAV date, so their "--" cannot be explained

**What it is.** The research console explains every unrated fund: 126 categories have fewer than four ranked funds (the workbook's own rule), 67 funds sit outside the Universe flag, and the rest show "--" for part of the composite. For that last group the console compares the fund's first-NAV date (First NAV, column B) with the start of the earliest bull phase (11 February 2016, from the Bull-Bear Returns header): a fund launched after that date is too young to rate, a fund launched before it with "--" is a data gap. On the current master 1,605 unrated funds are too young and none is a data gap.

Thirty-four funds cannot be classified either way: their First NAV row reads "--" for the date while their composite also reads "--". They are seventeen schemes, both plans each (Direct and Regular, or ETF and index fund):

- Bank of India Value Fund
- DSP CRISIL-IBX Financial Services 3-6 Months Debt Index Fund
- ICICI Prudential Dynamic Asset Allocation Passive FOF
- Invesco India Pharma and Healthcare Fund
- ITI Multi Asset Allocation Fund
- JioBlackRock Balanced Advantage Fund
- Mirae Asset CRISIL-IBX Financial Services 3-6 Months Debt Index Fund
- Motilal Oswal Quality Fund
- Navi Nifty REITs & Realty Index Fund
- Nippon India Income Plus Arbitrage Omni Fund of Fund
- quant Income Plus Arbitrage Active FoF
- Quantum Flexi Cap Fund
- SBI Balanced Hybrid Fund
- The Wealth Company Multi Cap Fund
- UTI Balanced Hybrid Fund
- UTI BSE India Sector Leaders (the ETF and both plans of the index fund)
- Zerodha Life Cycle Fund 2031 (Direct plan only)

Most of these names look like recent launches, which would make them "too young" rather than incomplete, but the workbook cannot say so until a first-NAV date is entered.

**What it affects.** Nothing in the rankings: these funds are unrated either way. It affects the coverage explanation on the dashboard ("34 funds have a missing composite and no first NAV date on record") and the Insights page, where the "Cannot tell young from incomplete" card lists them.

**Status: open, for the research team.** Entering the first-NAV date for these seventeen schemes on the First NAV sheet closes the item; the card empties by itself on the next upload.

## 6. The pivot sheets hold stale outputs

**What the workbook says.** Sixteen sheets carry pivot tables (17 in all) that summarise Composite Ranks, Summary-Performance, CY Returns, Bull-Bear Returns, Report, P2P Perf and the two index sheets. Excel refreshes a pivot only when someone asks it to, and each pivot records when that last happened. In the 11 September master: the two Composite Ranks pivots were refreshed on 10 September; the CY Returns and Summary-Performance pivots on 4 September; Bull-Bear on 3 September; the index pivots on 5 September; the three Report pivots on 15 August; the P2P Perf expense-ratio pivots on 11 August; the Index-CY ranking pivot on 13 August.

**What the analyser found.** Recomputing each pivot from the same source range, with the filters Excel saved, the two Composite Ranks pivots reconcile cell for cell (418 numbers on PIVOT-Composite, none out). The Report pivots (Perf-Category, Perf-Category-Scheme, Perf-AMC-Scheme), the expense-ratio pivots and the index-roll pivots do not: their cached rows carry the numbers of the data as it stood a month earlier. For instance the Perf-Category row for Aggressive Hybrid Fund shows CY averages that differ from the current Report rows by around a third of a percentage point.

**What it affects.** Nothing in the rankings; pivots are outputs. It affects anyone reading a pivot sheet in Excel as if it were current. The analyser's Pivots screen recomputes every pivot from the engine's numbers each time it is opened, so the console never shows a stale pivot; each pivot card names the date Excel last refreshed its own copy.

**Status: open, for the research team.** Press "Refresh All" (Data ribbon) before saving the monthly master, or treat the Pivots screen as the reference.

## Smaller observations

- Six index funds appear twice as lookup keys on the Domain sheet (rows 386 to 397): Axis Nifty Energy, Edelweiss Nifty REITs, Kotak Nifty Bank, Navi Nifty REITs, UTI BSE India Sector Leaders and UTI Nifty 500. Excel's exact-match lookups take the first occurrence silently. If the two rows ever carry different classifications, the second one will never be used. Harmless today; worth deduplicating.
- Header labels such as "Scheme Name" repeat inside several lookup ranges (for instance CY Returns rows 1 and 9). This is by design in the workbook and is only listed so the duplicate-key warning in the Validation module is not mistaken for a data problem.
- A stray formula sat at Averages!G28 in an earlier copy (a misplaced member of the B30:B49 label pattern). It was already gone from the recalculated master and has no effect.

## How these were found

Every uploaded copy of the master is interpreted into formula patterns, then recalculated by the analyser and compared with Excel's own cached results for all 789,828 formula cells in the fifteen sheets in scope. A structural check looks for short runs of formulas that break the pattern of the rows around them, for rows that read a different row, for duplicate lookup keys and for circular references. The results are on the Validation page of the dashboard for each version, and the Versions page shows what changed between any two uploads.
