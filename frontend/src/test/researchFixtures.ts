import type { CategoriesResponse, EntitiesPage, EntityDetail, EntityRow, InsightsResponse, MeasureMeta, MovementResponse, ResearchConfig, ResearchSummary } from "@/api/research";

const envelope = {
  configured: true,
  problems: [],
  version_id: "abc12345def",
  run_id: "run00001",
  version: { id: "abc12345def", filename: "master.xlsx", uploaded_at: "2026-09-11T09:00:00Z", status: "active" },
  run: { id: "run00001", kind: "full", created_at: "2026-09-11T09:05:00Z" },
};

export const measures: MeasureMeta[] = [
  { key: "score", label: "Composite score", role: "score", format: "number", unit: null, higherIsBetter: true, primary: true },
  { key: "rank", label: "Composite rank", role: "rank", format: "integer", unit: null, higherIsBetter: false, primary: true },
  { key: "quartile", label: "Composite quartile", role: "quartile", format: "integer", unit: null, higherIsBetter: false, primary: true },
  { key: "roll1y", label: "1Y rolling", role: "return", format: "number", unit: "%", higherIsBetter: true, primary: false },
  { key: "roll3y", label: "3Y rolling", role: "return", format: "number", unit: "%", higherIsBetter: true, primary: false },
  { key: "bull", label: "Bull final score", role: "score", format: "number", unit: null, higherIsBetter: true, primary: false },
  { key: "bear", label: "Bear final score", role: "score", format: "number", unit: null, higherIsBetter: true, primary: false },
  { key: "corpus", label: "Corpus", role: "factor", format: "inr_crore", unit: null, higherIsBetter: true, primary: false },
  { key: "expense", label: "Expense ratio", role: "factor", format: "number", unit: "%", higherIsBetter: false, primary: false },
];

const row = (key: string, label: string, plan: string, amc: string, category: string, m: Partial<Record<string, number | null>>, delta: number | null = null): EntityRow => ({
  key,
  label,
  sub: `${plan} · ${amc}`,
  dims: { category, amc, plan, manager: "A. Rao" },
  measures: { score: 80, rank: 1, quartile: 1, roll1y: 18.4, roll3y: 16.1, bull: 22.8, bear: 6.35, corpus: 122954, expense: 0.5, ...m },
  raw: m.quartile === null ? { quartile: "--", rank: "--" } : {},
  rated: m.quartile !== null,
  delta: delta === null ? null : { rank: delta, quartileFrom: 1, new: false },
});

export const entityRows: EntityRow[] = [
  row("WhiteOak Aggressive - Reg", "WhiteOak Capital Aggressive Hybrid Fund", "Regular", "WhiteOak Capital", "Regular-Aggressive Hybrid", { rank: 3, score: 84.2 }, 4),
  row("Kotak Bank Index - Dir", "Kotak Nifty Bank Index Fund", "Direct", "Kotak", "Direct-Index Funds", { rank: 7, score: 81.7 }, 23),
  row("Axis Energy - Reg", "Axis Nifty Energy Index Fund", "Regular", "Axis", "Regular-Sectoral", { rank: 58, score: 58.3, quartile: 3 }, -27),
  row("Alphagrep Multi Asset - Dir", "Alphagrep Multi Asset Allocation Fund", "Direct", "Alphagrep", "Direct-Multi Asset", { rank: null, score: null, quartile: null }),
];

export const summary: ResearchSummary = {
  ...envelope,
  as_of: 46265,
  universe: { total: 3232, rated: 1434, complete: 1283, quartiles: { "1": 335, "2": 368, "3": 344, "4": 387 }, categories: 200, unranked_categories: 126, unrated_small_categories: 701, unrated_missing_data: 1030, outside_universe: 67, stats_only_categories: 4 },
  quartiles: { "1": 335, "2": 368, "3": 344, "4": 387 },
  category_averages: {
    measure: "roll1y",
    label: "1Y rolling",
    rows: [
      { key: "Direct-Thematic", value: 22.4, label: "22.40%", count: 184 },
      { key: "Direct-Multi Asset", value: 18.9, label: "18.90%", count: 35 },
    ],
    total: 45,
  },
  measures,
  validation: { status: "passed_with_warnings", checked: 789828, matched: 789828, anomalies: 10 },
  findings: { open: 1, fixed: 3 },
  movement: {
    previous: { id: "prev0001", filename: "master-aug.xlsx", date: "31 Aug" },
    same_month: false,
    moved: 86,
    up: 51,
    down: 35,
    repairs: 2,
    entries: 14,
    exits: 3,
    top: [
      { key: "Kotak Bank Index - Dir", label: "Kotak Nifty Bank Index Fund", sub: "Direct · Kotak", category: "Direct-Index Funds", rankFrom: 30, rankTo: 7, delta: 23, quartileFrom: 2, quartileTo: 1, cause: "market", note: null },
      { key: "Axis Energy - Reg", label: "Axis Nifty Energy Index Fund", sub: "Regular · Axis", category: "Regular-Sectoral", rankFrom: 31, rankTo: 58, delta: -27, quartileFrom: 2, quartileTo: 3, cause: "market", note: null },
    ],
  },
  held_q1: { available: true, count: 31, current_q1: 335, versions: 3, from: "30 Jun" },
  history: [
    { id: "old0001", date: "30 Jun", as_of: "2026-06-30" },
    { id: "prev0001", date: "31 Jul", as_of: "2026-07-31" },
    { id: "abc12345def", date: "31 Aug", as_of: "2026-08-31" },
  ],
  universe_narrative: "1,434 of 3,232 funds are rated. 126 of 200 categories have fewer than 4 ranked funds and are left unranked by the workbook's own rule (701 funds).",
  narrative: "86 funds changed rank since 31 Jul: 51 up, 35 down. 2 of those moves are data repairs, not market movement. 31 funds have held Q1 across all 3 genuine monthly uploads.",
  footer: "Test console · confidential",
};

export const notConfigured: ResearchSummary = { configured: false, problems: ["research section is absent from dashboard.config.json"], version_id: null, run_id: null };

export const entitiesPage: EntitiesPage = {
  ...envelope,
  total: 3232,
  page: 1,
  size: 100,
  sort: "rank",
  dir: "asc",
  measures,
  dimensions: [
    { key: "category", label: "Category" },
    { key: "amc", label: "AMC" },
    { key: "plan", label: "Plan" },
    { key: "manager", label: "Management team" },
  ],
  facets: { category: ["Direct-Index Funds", "Regular-Aggressive Hybrid", "Regular-Sectoral"], amc: ["Axis", "Kotak", "WhiteOak Capital"], plan: ["Direct", "Regular"] },
  previous: { id: "prev0001", filename: "master-aug.xlsx", date: "31 Jul" },
  groups: null,
  rows: entityRows,
};

export const groupedPage: EntitiesPage = {
  ...entitiesPage,
  groups: [
    { key: "Direct", label: "Direct", count: 2, subtotals: { count: 2, q1: 1, score: 81.7, roll1y: 18.4, roll3y: 16.1, bull: 22.8, bear: 6.35, corpus: 122954, expense: 0.5 } },
    { key: "Regular", label: "Regular", count: 2, subtotals: { count: 2, q1: 1, score: 71.25, roll1y: 18.4, roll3y: 16.1, bull: 22.8, bear: 6.35, corpus: 122954, expense: 0.5 } },
  ],
  rows: [
    { ...entityRows[1], group: "Direct" },
    { ...entityRows[3], group: "Direct" },
    { ...entityRows[0], group: "Regular" },
    { ...entityRows[2], group: "Regular" },
  ],
};

export const entityDetail: EntityDetail = {
  ...envelope,
  entity: entityRows[0],
  row: 412,
  measures: [
    { key: "score", label: "Composite score", role: "score", value: 84.2, display: "84.20", unit: null, format: "number", primary: true, categoryRank: 3, categoryCount: 42, cell: "Composite Ranks!T412" },
    { key: "rank", label: "Composite rank", role: "rank", value: 3, display: "3", unit: null, format: "integer", primary: true, categoryRank: null, categoryCount: 42, cell: "Composite Ranks!U412" },
    { key: "quartile", label: "Composite quartile", role: "quartile", value: 1, display: "1", unit: null, format: "integer", primary: true, categoryRank: null, categoryCount: 42, cell: "Composite Ranks!Z412" },
    { key: "roll1y", label: "1Y rolling", role: "return", value: 18.4, display: "18.40%", unit: "%", format: "number", primary: false, categoryRank: 5, categoryCount: 42, cell: "Summary-Performance!X412" },
    { key: "roll3y", label: "3Y rolling", role: "return", value: 16.1, display: "16.10%", unit: "%", format: "number", primary: false, categoryRank: 7, categoryCount: 42, cell: "Summary-Performance!Y412" },
    { key: "bull", label: "Bull final score", role: "score", value: 22.8, display: "22.80", unit: null, format: "number", primary: false, categoryRank: 12, categoryCount: 42, cell: "Bull-Bear Returns!AI412" },
    { key: "bear", label: "Bear final score", role: "score", value: 6.35, display: "6.35", unit: null, format: "number", primary: false, categoryRank: 14, categoryCount: 42, cell: "Bull-Bear Returns!AW412" },
  ],
  phases: [
    { group: "bull", groupLabel: "Bull", label: "11 Feb 16 – 28 Aug 18", value: 22.8, categoryMean: 19.1, unit: "%" },
    { group: "bear", groupLabel: "Bear", label: "28 Aug 18 – 26 Oct 18", value: -6.4, categoryMean: -8.2, unit: "%" },
  ],
  periods: [{ label: "1Y", value: 18.4, unit: "%" }],
  category: { key: "Regular-Aggressive Hybrid", count: 45, rated: 42, quartiles: { "1": 11, "2": 10, "3": 11, "4": 10 }, means: { roll1y: 14.1, roll3y: 12.0 } },
  peers: [
    { key: "HDFC Hybrid - Reg", label: "HDFC Hybrid Equity Fund", rank: 1, quartile: 1, score: 88.1, scoreLabel: "88.10", me: false },
    { key: "ICICI Equity Debt - Reg", label: "ICICI Pru Equity & Debt Fund", rank: 2, quartile: 1, score: 85.9, scoreLabel: "85.90", me: false },
    { key: "WhiteOak Aggressive - Reg", label: "WhiteOak Capital Aggressive Hybrid Fund", rank: 3, quartile: 1, score: 84.2, scoreLabel: "84.20", me: true },
  ],
  history: [
    { version_id: "prev0001", filename: "master-aug.xlsx", uploaded_at: "2026-08-11T09:00:00Z", date: "31 Jul", as_of: "2026-07-31", rank: 7, quartile: 1, score: 81.6 },
    { version_id: "abc12345def", filename: "master.xlsx", uploaded_at: "2026-09-11T09:00:00Z", date: "31 Aug", as_of: "2026-08-31", rank: 3, quartile: 1, score: 84.2 },
  ],
  delta: 4,
  deltaLabel: "up 4 places",
  previous: { id: "prev0001", filename: "master-aug.xlsx", date: "31 Jul" },
  quartileExplanation: ["OR(U412=0,U412=\"--\") is FALSE", "U412<=COUNTIFS(...)*0.25: 3 <= 10.5 is TRUE", "Result: 1"],
  narrative: "WhiteOak Capital Aggressive Hybrid Fund ranks 3 of 42 rated funds in Regular-Aggressive Hybrid (Q1). Up 4 places since 31 Jul.",
  cells: { score: "Composite Ranks!T412", rank: "Composite Ranks!U412", quartile: "Composite Ranks!Z412" },
};

export const categories: CategoriesResponse = {
  ...envelope,
  measure: "roll3y",
  measures: [
    { key: "roll1y", label: "1Y rolling" },
    { key: "roll3y", label: "3Y rolling" },
  ],
  unrankedBelow: 4,
  minGroupCount: 10,
  statsOnly: 4,
  rows: [
    { key: "Direct-Thematic", count: 190, rated: 184, quartiles: { "1": 46, "2": 46, "3": 46, "4": 46 }, means: { roll3y: 22.4 }, spreads: { roll3y: 28.4 }, stats: {}, statLabels: {}, unranked: false, value: 22.4, valueLabel: "22.40%" },
    { key: "Direct-Arbitrage", count: 3, rated: 0, quartiles: { "1": 0, "2": 0, "3": 0, "4": 0 }, means: { roll3y: 6.4 }, spreads: { roll3y: 1.1 }, stats: {}, statLabels: {}, unranked: true, value: 6.4, valueLabel: "6.40%" },
  ],
  narrative: "200 categories; 126 have fewer than 4 ranked funds and are left unranked by the workbook rule.",
};

export const movement: MovementResponse = {
  ...envelope,
  available: true,
  from: { id: "prev0001", filename: "master-aug.xlsx", date: "31 Jul" },
  to: { id: "abc12345def", filename: "master.xlsx", date: "31 Aug" },
  same_month: false,
  rated: 1434,
  moved: 86,
  up: 51,
  down: 35,
  avg_up: 8,
  avg_down: 11,
  quartileChanges: { total: 23, into_q1: 9, out_of_q1: 6 },
  risers: [
    { key: "Kotak Bank Index - Dir", label: "Kotak Nifty Bank Index Fund", sub: "Direct · Kotak", category: "Direct-Index Funds", rankFrom: 30, rankTo: 7, delta: 23, quartileFrom: 2, quartileTo: 1, cause: "market", note: null },
    { key: "WhiteOak Aggressive - Reg", label: "WhiteOak Capital Aggressive Hybrid Fund", sub: "Regular · WhiteOak Capital", category: "Regular-Aggressive Hybrid", rankFrom: 7, rankTo: 3, delta: 4, quartileFrom: 1, quartileTo: 1, cause: "repair", note: "row 3181 repaired" },
  ],
  fallers: [{ key: "Axis Energy - Reg", label: "Axis Nifty Energy Index Fund", sub: "Regular · Axis", category: "Regular-Sectoral", rankFrom: 31, rankTo: 58, delta: -27, quartileFrom: 2, quartileTo: 3, cause: "market", note: null }],
  entries: [{ key: "New Fund - Dir", label: "New Fund", category: "Direct-Thematic" }],
  exits: [],
  repairs: [{ key: "WhiteOak Aggressive - Reg", label: "WhiteOak Capital Aggressive Hybrid Fund", note: "row 3181 repaired" }],
  versions: [
    { id: "prev0001", filename: "master-aug.xlsx", date: "31 Jul", status: "validated", activated_at: "2026-08-11T10:00:00Z" },
    { id: "abc12345def", filename: "master.xlsx", date: "31 Aug", status: "active", activated_at: "2026-09-11T10:00:00Z" },
  ],
  narrative: "86 funds changed composite rank between 31 Jul and 31 Aug: 51 up and 35 down. 9 entered Q1 and 6 left it. 2 of the moves are data repairs rather than market movement.",
};

export const movementUnavailable: MovementResponse = { ...envelope, available: false, reason: "no earlier version with a baseline run to compare with", versions: [] };

export const insights: InsightsResponse = {
  ...envelope,
  sections: ["winning", "cost"],
  insights: [
    {
      key: "best_long_term",
      section: "winning",
      eyebrow: "Long term",
      title: "Best on long-term rank",
      sentence: "Across the 45 categories with 10 or more rated funds, Nippon India Taiwan Equity Fund leads its category (Direct-Thematic) on long-term rank.",
      count: 172,
      total: 1434,
      measure: "score",
      drill: { sort: "rank_lt", dir: "asc", keys: ["Kotak Bank Index - Dir", "WhiteOak Aggressive - Reg"] },
      problems: [],
      status: "ok",
      note: null,
      rows: [
        { key: "Nippon Taiwan - Dir", label: "Nippon India Taiwan Equity Fund", sub: "Direct · Nippon", value: 37.2, valueLabel: "37.20", extra: {} },
        { key: "DSP Gold - Reg", label: "DSP World Gold Mining FoF", sub: "Regular · DSP", value: 14.45, valueLabel: "14.45", extra: {} },
      ],
    },
    {
      key: "held_q1",
      section: "winning",
      eyebrow: "Consistency",
      title: "Held Q1 every version",
      sentence: "",
      count: 0,
      total: 1434,
      measure: null,
      drill: {},
      problems: [],
      status: "unavailable",
      note: "Becomes available after a second genuine monthly upload; every activated version so far carries the same as-of date.",
      rows: [],
    },
    {
      key: "amc_league",
      section: "cost",
      eyebrow: "AMC league table",
      title: "Q1 funds by house",
      sentence: "ICICI Prudential Mutual Fund has the most top-quartile funds (50 of 132 rated).",
      count: 20,
      total: 1434,
      measure: null,
      drill: {},
      problems: [],
      status: "ok",
      note: null,
      rows: [{ key: null, label: "ICICI Prudential Mutual Fund", sub: null, value: 50, valueLabel: "50 / 132", extra: { count: 50, total: 132 } }],
    },
  ],
  footer: "Test console · confidential",
};

export const researchConfig: ResearchConfig = {
  configured: true,
  problems: [],
  version_id: "abc12345def",
  entity: { sheet: "Composite Ranks", rows: [10, 3241], key: "Composite Ranks!B", label: "Composite Ranks!F", universe: "Composite Ranks!A = 'Yes'" },
  dimensions: [
    { key: "category", label: "Category", ref: "Composite Ranks!L", resolved: true, split: null },
    { key: "manager", label: "Management team", ref: "Composite Ranks!AC", resolved: true, split: null },
  ],
  measures: measures.map((m) => ({ key: m.key, label: m.label, role: m.role, ref: `Composite Ranks!${m.key.toUpperCase().slice(0, 2)}`, format: m.format, unit: m.unit, higherIsBetter: m.higherIsBetter, primary: m.primary, resolved: m.key !== "bear" })),
  phases: [],
  periods: [],
  categoryStats: [],
  insights: [
    { key: "best_long_term", section: "winning", eyebrow: "Long term", title: "Best on long-term rank", mode: "filter" },
    { key: "held_q1", section: "winning", eyebrow: "Consistency", title: "Held Q1 every version", mode: "acrossVersions" },
  ],
  narratives: {},
  footer: "Test console · confidential",
  findings: [
    { title: "Roll Perf row 3181 read another fund's row", detail: "9 cells pointed at row 3258.", status: "fixed" },
    { title: "Alphagrep Multi Asset absent from CY Returns", detail: "Two category averages read --.", status: "open" },
  ],
  quartileRule: { unrankedBelow: 4, unrankedValue: "--" },
  minGroupCount: 10,
};
