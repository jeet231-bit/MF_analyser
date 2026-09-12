"""A small rated universe for the research views: twelve funds in three categories, scores,
category ranks, the workbook's quartile ladder (with the '< 4 funds' unranked rule), expense
ranks, returns and phases keyed by fund name, and category averages. Cached values are
computed here in Python so the engine has something to reconcile against.

Variants: ``shift`` moves two funds' inputs so ranks change; ``repair`` makes one fund's score
formula read the row above (the cut-and-pasted-row defect the diff labels as a repair)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import openpyxl

from tests.fixtures.workbook import inject_cached_values, workbook_bytes

FIRST, LAST = 2, 13
# name, label, plan, amc, category, manager, input1, input2, corpus, expense
FUNDS: list[tuple] = [
    (
        "Alpha One - Dir",
        "Alpha One",
        "Direct",
        "Alpha AMC",
        "Direct-Alpha",
        "A. Rao",
        80,
        70,
        1200,
        0.5,
    ),
    (
        "Alpha Two - Dir",
        "Alpha Two",
        "Direct",
        "Alpha AMC",
        "Direct-Alpha",
        "A. Rao",
        60,
        65,
        900,
        0.9,
    ),
    (
        "Beta One - Dir",
        "Beta One",
        "Direct",
        "Beta AMC",
        "Direct-Alpha",
        "B. Sen",
        90,
        85,
        2500,
        0.4,
    ),
    (
        "Gamma One - Dir",
        "Gamma One",
        "Direct",
        "Gamma AMC",
        "Direct-Alpha",
        "C. Iyer",
        "--",
        50,
        300,
        1.2,
    ),
    (
        "Delta One - Dir",
        "Delta One",
        "Direct",
        "Delta AMC",
        "Direct-Alpha",
        "D. Das",
        40,
        45,
        700,
        1.5,
    ),
    (
        "Alpha One - Reg",
        "Alpha One",
        "Regular",
        "Alpha AMC",
        "Regular-Alpha",
        "A. Rao",
        78,
        68,
        4000,
        1.4,
    ),
    (
        "Beta One - Reg",
        "Beta One",
        "Regular",
        "Beta AMC",
        "Regular-Alpha",
        "B. Sen, E. Roy",
        88,
        83,
        5200,
        1.1,
    ),
    (
        "Gamma One - Reg",
        "Gamma One",
        "Regular",
        "Gamma AMC",
        "Regular-Alpha",
        "C. Iyer",
        55,
        52,
        800,
        2.1,
    ),
    (
        "Delta One - Reg",
        "Delta One",
        "Regular",
        "Delta AMC",
        "Regular-Alpha",
        "D. Das",
        38,
        43,
        600,
        2.3,
    ),
    (
        "Beta Two - Dir",
        "Beta Two",
        "Direct",
        "Beta AMC",
        "Direct-Beta",
        "B. Sen",
        70,
        72,
        1500,
        0.6,
    ),
    (
        "Alpha Three - Dir",
        "Alpha Three",
        "Direct",
        "Beta AMC",
        "Direct-Beta",
        "A. Rao",
        66,
        61,
        400,
        0.8,
    ),
    (
        "Delta Two - Dir",
        "Delta Two",
        "Direct",
        "Delta AMC",
        "Direct-Beta",
        "D. Das",
        50,
        58,
        350,
        1.0,
    ),
]
# name -> (ret1y, ret3y, bull1, bull2, bear1, bear2)
PERF: dict[str, tuple[float, ...]] = {
    f[0]: (10 + i * 1.5, 8 + i * 1.1, 20 + i, 15 + i * 0.5, -8 + i * 0.3, -5 + i * 0.2)
    for i, f in enumerate(FUNDS)
}
PERF_HEADERS = [
    "Name",
    "1Y",
    "3Y",
    "Bull 2020-21",
    "Bull 2022-24",
    "Bear 2020",
    "Bear 2022",
    "First date",
]
# First NAV as an Excel serial: everyone launched in 2015 except two 2024 launches; the fund
# whose composite reads "--" (Gamma One - Dir) is old, so it is a data gap, not a young fund.
INCEPTION: dict[str, int] = {f[0]: 42000 for f in FUNDS}
INCEPTION["Delta Two - Dir"] = 45500
INCEPTION["Alpha Three - Dir"] = 45400
CATEGORIES = ["Direct-Alpha", "Regular-Alpha", "Direct-Beta"]
GHOST_CATEGORY = "Direct-Ghost"  # in the averages table, with no fund behind it


def _inputs(variant: str) -> list[tuple]:
    rows = [list(f) for f in FUNDS]
    if variant == "shift":
        rows[0][6], rows[0][7] = 95, 92  # Alpha One - Dir jumps to the top of Direct-Alpha
        rows[6][6], rows[6][7] = 50, 48  # Beta One - Reg drops in Regular-Alpha
    return [tuple(r) for r in rows]


def expected(variant: str = "base") -> dict[str, dict[str, object]]:
    """name -> {score, rank, quartile, rank_expense, qrtl_expense} as Excel would compute."""
    rows = _inputs(variant)
    score: dict[str, object] = {}
    for i, r in enumerate(rows):
        name, g, h = r[0], r[6], r[7]
        if variant == "repair" and i == 2:  # row 4 reads row 3's inputs
            g, h = rows[1][6], rows[1][7]
        score[name] = "--" if g == "--" or h == "--" else g * 0.6 + h * 0.4
    out: dict[str, dict[str, object]] = {}
    for r in rows:
        name, cat, expense = r[0], r[4], r[9]
        members = [x for x in rows if x[4] == cat]
        n = len(members)
        s = score[name]
        if s == "--":
            rank: object = "--"
        else:
            rank = sum(1 for x in members if score[x[0]] != "--" and score[x[0]] > s) + 1
        exp_rank = sum(1 for x in members if x[9] < expense) + 1

        def ladder(rk: object, n: int = n) -> object:
            if rk == "--" or n < 4:
                return "--"
            for q, f in ((1, 0.25), (2, 0.5), (3, 0.75)):
                if rk <= n * f:
                    return q
            return 4

        out[name] = {
            "score": s,
            "rank": rank,
            "quartile": ladder(rank),
            "rank_expense": exp_rank,
            "qrtl_expense": ladder(exp_rank),
        }
    return out


def category_averages(variant: str = "base") -> dict[str, object]:
    exp = expected(variant)
    rows = _inputs(variant)
    out: dict[str, object] = {}
    for cat in CATEGORIES:
        vals = [exp[r[0]]["score"] for r in rows if r[4] == cat and exp[r[0]]["score"] != "--"]
        out[cat] = sum(vals) / len(vals) if vals else "--"  # type: ignore[arg-type]
    return out


def build_research_workbook(variant: str = "base") -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Funds"
    headers = ["Name", "Fund", "Plan", "AMC", "Category", "Manager", "Input1", "Input2", "Score",
               "Rank", "Quartile", "Corpus", "Expense", "ExpRank", "ExpQuartile"]  # fmt: skip
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    rows = _inputs(variant)
    cat_range = f"$E${FIRST}:$E${LAST}"
    for i, r in enumerate(rows):
        row = FIRST + i
        for c, v in enumerate(r[:8], start=1):
            ws.cell(row=row, column=c, value=v)
        g, h = f"G{row}", f"H{row}"
        if variant == "repair" and i == 2:
            g, h = f"G{row - 1}", f"H{row - 1}"
        ws[f"I{row}"] = f'=IF(OR({g}="--",{h}="--"),"--",{g}*0.6+{h}*0.4)'
        ws[f"J{row}"] = (
            f'=IF(I{row}="--","--",COUNTIFS({cat_range},E{row},$I${FIRST}:$I${LAST},">"&I{row})+1)'
        )
        n = f"COUNTIF({cat_range},E{row})"
        ws[f"K{row}"] = (
            f'=IF(J{row}="--","--",IF({n}<4,"--",IF(J{row}<={n}*0.25,1,IF(J{row}<={n}*0.5,2,IF(J{row}<={n}*0.75,3,4)))))'
        )
        ws[f"L{row}"] = r[8]
        ws[f"M{row}"] = r[9]
        ws[f"N{row}"] = f'=COUNTIFS({cat_range},E{row},$M${FIRST}:$M${LAST},"<"&M{row})+1'
        ws[f"O{row}"] = (
            f'=IF({n}<4,"--",IF(N{row}<={n}*0.25,1,IF(N{row}<={n}*0.5,2,IF(N{row}<={n}*0.75,3,4))))'
        )
    perf = wb.create_sheet("Perf")
    for c, h in enumerate(PERF_HEADERS, start=1):
        perf.cell(row=1, column=c, value=h)
    for i, r in enumerate(rows):
        perf.cell(row=FIRST + i, column=1, value=r[0])
        for c, v in enumerate(PERF[r[0]], start=2):
            perf.cell(row=FIRST + i, column=c, value=v)
        perf.cell(row=FIRST + i, column=8, value=INCEPTION[r[0]])
    cat = wb.create_sheet("CatAvg")
    cat["A1"], cat["B1"] = "Category", "Average score"
    cat["D1"] = "Phases from 11 Feb 2016 To 28 Aug 2018"  # the constant a coverage test reads
    for i, name in enumerate([*CATEGORIES, GHOST_CATEGORY], start=2):
        cat[f"A{i}"] = name
        cat[f"B{i}"] = (
            f'=IFERROR(AVERAGEIF(Funds!{cat_range},A{i},Funds!$I${FIRST}:$I${LAST}),"--")'
        )
    return wb


def research_fixture_xlsx_bytes(variant: str = "base") -> bytes:
    exp = expected(variant)
    cached: dict[tuple[str, str], object] = {}
    for i, r in enumerate(_inputs(variant)):
        row = FIRST + i
        e = exp[r[0]]
        cached[("Funds", f"I{row}")] = e["score"]
        cached[("Funds", f"J{row}")] = e["rank"]
        cached[("Funds", f"K{row}")] = e["quartile"]
        cached[("Funds", f"N{row}")] = e["rank_expense"]
        cached[("Funds", f"O{row}")] = e["qrtl_expense"]
    for i, (_cat, avg) in enumerate(category_averages(variant).items(), start=2):
        cached[("CatAvg", f"B{i}")] = avg
    cached[("CatAvg", f"B{2 + len(CATEGORIES)}")] = "--"
    return inject_cached_values(workbook_bytes(build_research_workbook(variant)), cached)


def research_map() -> dict:
    """The semantic map for this fixture (what dashboard.config.json's ``research`` holds)."""
    return {
        "entity": {"sheet": "Funds", "rows": [FIRST, LAST], "keyColumn": "A", "labelColumn": "B"},
        "dimensions": {
            "category": {"column": "E", "label": "Category"},
            "amc": {"column": "D", "label": "AMC"},
            "plan": {"column": "C", "label": "Plan"},
            "manager": {"column": "F", "label": "Manager", "split": ","},
        },
        "measures": [
            {"key": "score", "label": "Score", "role": "score", "column": "I", "primary": True},
            {"key": "rank", "label": "Rank", "role": "rank", "column": "J", "format": "integer", "higherIsBetter": False, "primary": True},
            {"key": "quartile", "label": "Quartile", "role": "quartile", "column": "K", "format": "integer", "higherIsBetter": False, "primary": True},
            {"key": "corpus", "label": "Corpus", "role": "factor", "column": "L", "format": "inr_crore"},
            {"key": "expense", "label": "Expense", "role": "factor", "column": "M", "unit": "%", "higherIsBetter": False},
            {"key": "rank_expense", "label": "Expense rank", "role": "rank", "column": "N", "format": "integer", "higherIsBetter": False},
            {"key": "qrtl_expense", "label": "Expense quartile", "role": "quartile", "column": "O", "format": "integer", "higherIsBetter": False},
            {"key": "ret1y", "label": "1Y return", "role": "return", "sheet": "Perf", "column": "B", "keyColumn": "A", "unit": "%"},
            {"key": "ret3y", "label": "3Y return", "role": "return", "sheet": "Perf", "column": "C", "keyColumn": "A", "unit": "%"},
            {"key": "inception", "label": "First NAV", "role": "factor", "sheet": "Perf", "column": "H", "keyColumn": "A", "format": "date", "higherIsBetter": False},
        ],
        "phases": {"sheet": "Perf", "keyColumn": "A", "headerRow": 1, "unit": "%",
                   "groups": [{"key": "bull", "label": "Bull", "columns": ["D", "E"]},
                              {"key": "bear", "label": "Bear", "columns": ["F", "G"]}]},
        "periods": {"sheet": "Perf", "keyColumn": "A", "headerRow": 1, "columns": ["B", "C"], "unit": "%"},
        "categoryStats": {"sheet": "CatAvg", "keyColumn": "A", "rows": [2, 5], "headerRow": 1, "columns": ["B"]},
        "minGroupCount": 2,
        "constants": {"since": {"cell": "CatAvg!D1", "parse": "firstDate"}},
        "coverage": {"measure": "inception", "constant": "since"},
        "sectionLabels": {"winning": "Who is winning", "cost": "Cost and scale"},
        "insights": [
            {"key": "best_score", "section": "winning", "eyebrow": "Leaders", "title": "Highest scores",
             "where": [{"measure": "score", "op": "notnull"}], "sort": {"measure": "score", "dir": "desc"}, "limit": 3,
             "show": ["measure:score"], "sentence": "{count} funds carry a score; {top.label} leads at {top.value}."},
            {"key": "held_q1", "section": "winning", "eyebrow": "Consistency", "title": "Held Q1 every version",
             "mode": "acrossVersions", "across": {"where": [{"measure": "quartile", "op": "eq", "value": 1}]}, "limit": 5,
             "sentence": {"default": "{count} of {total} current Q1 funds {count?has|have} been Q1 in all {versions} genuine uploads.",
                          "zero": "No current Q1 fund has held Q1 across all {versions} genuine uploads."}},
            {"key": "amc_league", "section": "houses", "eyebrow": "AMC league", "title": "Q1 funds by house",
             "mode": "groupBy", "groupBy": {"dimension": "amc", "aggregate": "count_where",
                                            "where": [{"measure": "quartile", "op": "eq", "value": 1}]}, "limit": 4,
             "sentence": "{group.label} has the most Q1 funds ({group.count} of {group.total})."},
            {"key": "team_league", "section": "houses", "eyebrow": "Teams", "title": "Q1 funds by team",
             "mode": "groupBy", "minGroupCount": 1, "groupBy": {"dimension": "manager", "aggregate": "count_where",
                                            "where": [{"measure": "quartile", "op": "eq", "value": 1}]}, "limit": 6,
             "sentence": "{group.label} manages {group.count|Q1 fund|Q1 funds}."},
            {"key": "leaders", "section": "winning", "eyebrow": "Leaders", "title": "Category leaders",
             "where": [{"measure": "rank", "op": "eq", "value": 1}], "minGroupCount": 4, "sort": {"measure": "score", "dir": "desc"},
             "limit": 5, "show": ["measure:score"],
             "sentence": "Across the {groups} categories with {min_group} or more rated funds, {top.label} leads {top.group}."},
            {"key": "cheap_half", "section": "cost", "eyebrow": "Cost", "title": "Top half on expense",
             "where": [{"measure": "rank_expense", "op": "top", "fraction": 0.5}], "sort": {"measure": "expense", "dir": "asc"},
             "limit": 3, "show": ["measure:expense"], "sentence": "{count|fund is|funds are} in the cheaper half of their category."},
            {"key": "cheap_quarter", "section": "cost", "eyebrow": "Cost", "title": "Top quarter on expense",
             "where": [{"measure": "rank_expense", "op": "top"}], "sort": {"measure": "expense", "dir": "asc"},
             "limit": 3, "show": ["measure:expense"], "sentence": "{count|fund is|funds are} in the cheapest quarter of their category."},
            {"key": "best_value", "section": "cost", "eyebrow": "Best value", "title": "Q1 at Q1 cost",
             "where": [{"measure": "quartile", "op": "eq", "value": 1}, {"measure": "qrtl_expense", "op": "eq", "value": 1}],
             "sort": {"measure": "expense", "dir": "asc"}, "limit": 3, "show": ["measure:expense"],
             "sentence": "{count} funds are Q1 on rank and Q1 on expense."},
            {"key": "corpus_at_risk", "section": "cost", "eyebrow": "Investor impact", "title": "Corpus in the bottom half",
             "mode": "aggregate", "aggregate": {"measure": "corpus", "fn": "sum"},
             "where": [{"measure": "quartile", "op": "gte", "value": 3}], "limit": 3,
             "sentence": {"default": "{sum} sits in {count|fund|funds} ranked Q3 or Q4.", "zero": "No fund sits in Q3 or Q4."}},
            {"key": "unrated_gap", "section": "coverage", "eyebrow": "Data gap", "title": "Old enough, still --",
             "where": [{"measure": "score", "op": "isnull"}, {"measure": "inception", "op": "lt", "value": "$since"}],
             "sort": {"measure": "inception", "dir": "asc"}, "limit": 5, "show": ["measure:inception"],
             "sentence": {"default": "{count|fund|funds} older than {count?the|the} earliest phase still {count?shows|show} --.", "zero": "No old fund is unrated."}},
            {"key": "unrated_young", "section": "coverage", "eyebrow": "Too young", "title": "First NAV after the earliest phase",
             "where": [{"measure": "score", "op": "isnull"}, {"measure": "inception", "op": "gte", "value": "$since"}],
             "limit": 5, "show": ["measure:inception"],
             "sentence": {"default": "{count|fund is|funds are} too young to rate.", "zero": "Every unrated fund is old enough to rate."}},
            {"key": "direct_leaders", "section": "winning", "eyebrow": "Direct", "title": "Direct-plan leaders",
             "where": [{"dimension": "plan", "op": "eq", "value": "Direct"}, {"measure": "rank", "op": "eq", "value": 1}],
             "limit": 5, "show": ["measure:score"], "sentence": "{count|direct fund leads|direct funds lead} a category."},
            {"key": "dispersion", "section": "houses", "eyebrow": "Selection", "title": "Widest dispersion",
             "mode": "groupBy", "groupBy": {"dimension": "category", "aggregate": "dispersion", "measure": "ret3y", "minMembers": 3}, "limit": 3,
             "sentence": "{group.label} spans {group.value} on {measure.label}.", "sort": {"measure": "ret3y", "dir": "desc"}},
        ],
        "narratives": {
            "universe": [{"default": "{rated} of {total} funds are rated."},
                         {"default": "{unranked} of {categories} categories {unranked?has|have} fewer than {unranked_below} funds ({unrated_small|fund|funds})."},
                         {"default": "{unrated_other|fund is|funds are} unrated for missing data: {unrated_young} too young (first NAV after {coverage_since}) and {unrated_gap} with a data gap."}],
            "dashboard": [{"default": "{moved|fund|funds} changed rank since {previous}: {up} up, {down} down.", "zero": "No fund changed rank since {previous}."},
                          {"default": "{repairs} of those {repairs?is a data repair|are data repairs}.", "zero": "None of those moves is a data repair.", "requires": ["moved"]},
                          {"default": "{held_q1|fund has|funds have} held Q1 across all {versions} genuine uploads.", "zero": "No fund has held Q1 across all {versions} genuine uploads."}],
            "movement": [{"default": "{moved|fund|funds} changed rank between {previous} and {current}: {up} up, {down} down.", "zero": "No fund changed rank between {previous} and {current}."},
                         {"default": "{repairs} of those {repairs?is a data repair|are data repairs}.", "zero": "None of the moves is a data repair.", "requires": ["moved"]}],
            "categories": [{"default": "{categories} categories, {unranked} unranked.", "zero": "{categories} categories, none unranked.", "trigger": "unranked"},
                           {"default": "Among the {eligible} categories with {min_group} or more rated funds, {widest.label} has the widest spread ({widest.value})."}],
            "fund": [{"default": "{label} ranks {rank} of {category_count} in {category} ({quartile})."},
                     {"default": "{delta_text} since {previous}.", "zero": "Unchanged since {previous}.", "trigger": "delta"}],
        },
        "footer": "Test console · confidential",
        "findings": [{"title": "One fund reads the row above", "detail": "Repaired in the fixed version.", "status": "fixed"}],
    }  # fmt: skip


def write_config(path: Path, research: dict | None) -> Path:
    """A dashboard.config.json for tests: no sheet scope (all sheets), optional research map."""
    cfg = {"version": 1, "workbook": {"displayName": "Test console"}, "sheetScope": [], "outputSheets": ["Funds"],
           "numberFormat": {"grouping": "indian", "decimals": 2}}  # fmt: skip
    if research is not None:
        cfg["research"] = research
    path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return path


assert math.isfinite(sum(v[0] for v in PERF.values()))
