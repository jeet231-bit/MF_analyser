import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { getResearchSummary, listPivots, type EntityQuery, type ExploreQuery, type PivotQuery } from "@/api/research";
import { useAsync } from "@/lib/useAsync";
import { mockApi } from "@/test/mockApi";
import { version } from "@/test/fixtures";
import { EMPTY_SCOPE } from "@/api/research";
import { categories, entitiesPage, entityDetail, exploreResponse, groupedPage, insights, movement, movementUnavailable, notConfigured, pivotListing, pivotTable, researchConfig, summary } from "@/test/researchFixtures";
import { AdminPage } from "./AdminPage";
import { CategoriesPage } from "./CategoriesPage";
import { DashboardPage } from "./DashboardPage";
import { FundDetailPage } from "./FundDetailPage";
import { FundsPage } from "./FundsPage";
import { InsightsPage } from "./InsightsPage";
import { MovementPage } from "./MovementPage";
import { defaultQuery, type PivotLocation } from "./pivotQuery";
import { PivotsPage } from "./PivotsPage";
import type { ResearchActions } from "./types";
import { UploadPage } from "./UploadPage";
import { WATCHLIST_KEY } from "./useWatchlist";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.removeItem(WATCHLIST_KEY);
});

/** Narratives set numbers in <b>, so match on the paragraph's whole text. */
const narrative = (re: RegExp) => (_: string, el: Element | null) => el?.tagName === "P" && re.test(el.textContent ?? "");

function makeActions(): ResearchActions {
  return {
    openFund: vi.fn(),
    openFunds: vi.fn(),
    openCategories: vi.fn(),
    openMovement: vi.fn(),
    openInsights: vi.fn(),
    openAdmin: vi.fn(),
    openVersions: vi.fn(),
    openUpload: vi.fn(),
    goBack: vi.fn(),
  };
}

/** The Funds page is controlled by App; this stands in for it. */
function Funds({ actions, initial }: { actions: ResearchActions; initial?: EntityQuery }) {
  const [query, setQuery] = useState<EntityQuery | undefined>(initial);
  return <FundsPage actions={actions} query={query} onQuery={setQuery} />;
}

function Dashboard({ actions }: { actions: ResearchActions }) {
  const s = useAsync(() => getResearchSummary(), []);
  return <DashboardPage summary={s} scope={EMPTY_SCOPE} scopeBar={<div data-testid="scope-bar" />} greeting="Good morning, Jeet" actions={actions} />;
}

describe("DashboardPage", () => {
  it("leads with the greeting, the scope bar, the executive summary and four KPI tiles, then the distribution, leaders and the coverage strip", async () => {
    mockApi({ "GET /api/research/summary": summary, "GET /api/research/entities": entitiesPage });
    const actions = makeActions();
    render(<Dashboard actions={actions} />);
    expect(await screen.findByRole("heading", { name: "Good morning, Jeet" })).toBeInTheDocument();
    expect(screen.getByTestId("scope-bar")).toBeInTheDocument();
    const exec = screen.getByRole("region", { name: "Executive summary" });
    expect(exec).toHaveTextContent("All funds · every category · every AMC · both plans · as of 31 Aug");
    expect(within(exec).getByText(narrative(/ICICI Prudential Mutual Fund holds the most Q1 funds/))).toBeInTheDocument();
    // The counts that are only counts sit in one quiet strip inside the summary.
    const kpis = within(screen.getByTestId("kpi-row"));
    expect(kpis.getByText("All-weather funds")).toBeInTheDocument();
    expect(kpis.getByText("100.00%")).toBeInTheDocument();

    // Then the month: what moved, and who moved most.
    const changed = within(screen.getByTestId("what-changed"));
    expect(changed.getByText("Since 31 Aug")).toBeInTheDocument();
    expect(changed.getByText("86").closest("div")).toHaveTextContent("Changed rank");
    expect(changed.getByText(/data repairs/)).toBeInTheDocument();
    fireEvent.click(changed.getByRole("button", { name: /Kotak Nifty Bank Index Fund/ }));
    expect(actions.openFund).toHaveBeenCalledWith("Kotak Bank Index - Dir");
    fireEvent.click(changed.getByRole("button", { name: "Open movement →" }));
    expect(actions.openMovement).toHaveBeenCalled();

    // Then where to look: only the cards that have something in them, each opening its list.
    const cards = within(screen.getByTestId("callout-row")).getAllByTestId("callout");
    expect(cards).toHaveLength(2); // the unavailable one is not rendered
    expect(cards[0]).toHaveTextContent("Q1 in bull and bear");
    expect(cards[0]).toHaveTextContent("36");
    // A name like "All weather" is never a black box: the card says how it is counted.
    expect(within(cards[0]).getByTestId("rule")).toHaveTextContent("Counted as: QRTL-BULL = 1 (Bull-Bear Returns, column AZ) and QRTL-BEAR = 1");
    fireEvent.click(cards[0]);
    expect(actions.openFunds).toHaveBeenCalledWith({ keys: ["Kotak Bank Index - Dir", "WhiteOak Aggressive - Reg"], sort: "rank", dir: "asc" });
    expect(screen.getByRole("img", { name: /Quartile distribution: Q1 335 funds/ })).toBeInTheDocument();
    expect(screen.getByText(narrative(/draws from all 74 ranked categories/))).toBeInTheDocument();
    expect(screen.getByText("Median ranked category")).toBeInTheDocument();
    expect(screen.getByText("Category leaders")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Direct-Thematic" }));
    expect(actions.openFunds).toHaveBeenCalledWith({ category: "Direct-Thematic" });
    expect(screen.queryByText("Biggest rank movers")).not.toBeInTheDocument(); // its fact lives in the summary
    const strip = screen.getByTestId("coverage-strip");
    expect(within(strip).getByRole("img", { name: "Coverage: 1,434 rated, 1,798 not rated" })).toBeInTheDocument();
    expect(within(strip).getByText(narrative(/1,605 are too young to rate/))).toBeInTheDocument();
    fireEvent.click(within(strip).getByRole("button", { name: "Coverage detail →" }));
    expect(actions.openAdmin).toHaveBeenCalled();
    expect(screen.getByText("Test console · confidential")).toBeInTheDocument();
  });

  it("renders the not-configured panel with the problems", async () => {
    mockApi({ "GET /api/research/summary": notConfigured });
    const actions = makeActions();
    render(<Dashboard actions={actions} />);
    expect(await screen.findByText("Research views are not set up for this workbook")).toBeInTheDocument();
    expect(screen.getByText("research section is absent from dashboard.config.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open admin" }));
    expect(actions.openAdmin).toHaveBeenCalled();
  });

  it("lists the watchlist with live quartiles", async () => {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify([{ key: "Axis Energy - Reg", label: "Axis Nifty Energy Index Fund" }]));
    const calls = mockApi({ "GET /api/research/summary": summary, "GET /api/research/entities": { ...entitiesPage, rows: entitiesPage.rows.filter((r) => r.key === "Axis Energy - Reg") } });
    render(<Dashboard actions={makeActions()} />);
    const card = (await screen.findByText("Watchlist")).closest("section")!;
    await waitFor(() => expect(within(card).getByText("Q3")).toBeInTheDocument());
    expect(calls.some((c) => c.url.includes("keys=Axis+Energy+-+Reg"))).toBe(true);
    fireEvent.click(within(card).getByLabelText("Remove Axis Nifty Energy Index Fund from watchlist"));
    expect(within(card).getByText(/Open a fund and choose/)).toBeInTheDocument();
  });
});

describe("InsightsPage", () => {
  it("groups cards by section, shows unavailable notes and drills through the keys", async () => {
    const calls = mockApi({ "GET /api/research/insights": insights });
    const actions = makeActions();
    render(<InsightsPage actions={actions} runId="run00001" scope={{ ...EMPTY_SCOPE, dims: { plan: "Direct" } }} scopeBar={<div data-testid="scope-bar" />} />);
    expect(await screen.findByRole("heading", { name: "Who is winning" })).toBeInTheDocument();
    expect(screen.getByTestId("scope-bar")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Cost" })).toBeInTheDocument(); // no label configured: the key, capitalised
    const card = screen.getByRole("article", { name: "Best on long-term rank" });
    expect(within(card).getByText(/leads its category/)).toBeInTheDocument();
    expect(within(card).getByText("37.20")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "See all 172 →" }));
    expect(actions.openFunds).toHaveBeenCalledWith({ keys: ["Kotak Bank Index - Dir", "WhiteOak Aggressive - Reg"], sort: "rank_lt", dir: "asc" });
    fireEvent.click(within(card).getByRole("button", { name: /Nippon India Taiwan/ }));
    expect(actions.openFund).toHaveBeenCalledWith("Nippon Taiwan - Dir");
    const held = screen.getByRole("article", { name: "Held Q1 every version" });
    expect(within(held).getByRole("note")).toHaveTextContent("second genuine monthly upload");
    expect(within(held).queryByRole("button")).not.toBeInTheDocument();
    const league = screen.getByRole("article", { name: "Q1 funds by house" });
    expect(within(league).getByText("50 / 132")).toBeInTheDocument();
    expect(calls[0].url).toContain("scope=%7B%22dims%22%3A%7B%22plan%22%3A%22Direct%22%7D");
  });
});

describe("FundsPage", () => {
  it("filters, sorts, pages and pivots through the query, and opens a fund", async () => {
    const calls = mockApi({
      "GET /api/research/entities": () => {
        const url = calls[calls.length - 1]?.url ?? "";
        return url.includes("groupBy=plan") ? groupedPage : entitiesPage;
      },
    });
    const actions = makeActions();
    render(<Funds actions={actions} initial={{ quartile: [1] }} />);
    expect(await screen.findByText("WhiteOak Capital Aggressive Hybrid Fund")).toBeInTheDocument();
    expect(calls[0].url).toContain("quartile=1");
    expect(screen.getByRole("group", { name: "Quartile" }).querySelector('[aria-pressed="true"]')).toHaveTextContent("Q1");
    expect(screen.getAllByText("--").length).toBeGreaterThanOrEqual(1); // the unrated fund keeps the workbook's text
    expect(screen.getByText("▲ 23")).toHaveClass("text-positive");
    expect(screen.getByText(/Showing 1–4 of 3,232/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "Direct-Index Funds" } });
    await waitFor(() => expect(calls.at(-1)!.url).toContain("category=Direct-Index+Funds"));
    fireEvent.click(screen.getByRole("button", { name: "Composite score" }));
    await waitFor(() => expect(calls.at(-1)!.url).toContain("sort=score&dir=desc"));
    fireEvent.click(screen.getByRole("button", { name: "Next 100 →" }));
    await waitFor(() => expect(calls.at(-1)!.url).toContain("page=2"));
    fireEvent.change(screen.getByLabelText("Search fund or AMC"), { target: { value: "kotak" } });
    await waitFor(() => expect(calls.at(-1)!.url).toContain("q=kotak"));
    expect(calls.at(-1)!.url).toContain("page=1");

    const pivot = screen.getByRole("group", { name: "Analyse funds by" });
    expect(within(pivot).getByRole("button", { name: "Corpus band" })).toBeInTheDocument();
    fireEvent.click(within(pivot).getByRole("button", { name: "Plan" }));
    await waitFor(() => expect(calls.at(-1)!.url).toContain("groupBy=plan"));
    expect(await screen.findAllByTestId("group-row")).toHaveLength(2);
    expect(screen.getAllByTestId("group-row")[0]).toHaveTextContent(/Direct.*2 funds/);
    expect(screen.getAllByTestId("group-row")[0]).toHaveTextContent("avg 81.70");

    fireEvent.click(screen.getByText("Kotak Nifty Bank Index Fund"));
    expect(actions.openFund).toHaveBeenCalledWith("Kotak Bank Index - Dir");

    // A group row of a drillable pivot opens only that group's funds, and the filter is shown and removable.
    fireEvent.click(screen.getByRole("button", { name: "Show only Direct" }));
    await waitFor(() => expect(calls.at(-1)!.url).toContain("plan=Direct"));
    expect(calls.at(-1)!.url).not.toContain("groupBy");
    const filters = await screen.findByTestId("active-filters");
    expect(filters).toHaveTextContent("Direct");
    fireEvent.click(within(filters).getByRole("button", { name: "Remove Plan filter Direct" }));
    await waitFor(() => expect(calls.at(-1)!.url).not.toContain("plan=Direct"));
  });
});

describe("FundDetailPage", () => {
  it("shows tiles, the rank hero with the quartile rule, peers, history, and opens lineage on a cell", async () => {
    const calls = mockApi({
      "GET /api/research/entities/WhiteOak%20Aggressive%20-%20Reg": entityDetail,
      "GET /api/research/entities": entitiesPage,
      "GET /api/workbooks/abc12345def/lineage/Composite%20Ranks!Z412": { sheet: "Composite Ranks", cell: "Z412", value: 1, type: "number", kind: "formula", formula: "=IF(...)", reads: [] },
    });
    const actions = makeActions();
    render(<FundDetailPage fundKey="WhiteOak Aggressive - Reg" actions={actions} backLabel="funds · WhiteOak Capital" />);
    expect(await screen.findByRole("heading", { name: "WhiteOak Capital Aggressive Hybrid Fund" })).toBeInTheDocument();

    // Who this fund is, labelled in words: every dimension with its name, and the master row.
    const about = screen.getByLabelText("About this fund");
    expect(within(about).getByText("AMC")).toBeInTheDocument();
    expect(within(about).getByText("WhiteOak Capital")).toBeInTheDocument();
    expect(within(about).getByText("Position in the master")).toBeInTheDocument();
    expect(within(about).getByText(/Row 412/)).toBeInTheDocument();
    // Back goes to the previous screen by name.
    fireEvent.click(screen.getByRole("button", { name: "← Back to funds · WhiteOak Capital" }));
    expect(actions.goBack).toHaveBeenCalled();
    // The AMC's other funds: prev/next in the head, the list below, and the drill-through.
    const siblings = await screen.findByTestId("amc-siblings");
    expect(siblings).toHaveTextContent("More from WhiteOak Capital");
    expect(calls.some((c) => c.url.includes("/api/research/entities?") && c.url.includes("amc=WhiteOak+Capital"))).toBe(true);
    fireEvent.click(within(siblings).getByRole("button", { name: "Open the list →" }));
    expect(actions.openFunds).toHaveBeenCalledWith({ amc: "WhiteOak Capital" });
    expect(screen.getByText(narrative(/ranks 3 of 42 rated funds/))).toBeInTheDocument();
    expect(screen.getAllByText("84.20").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("/ 42")).toBeInTheDocument();
    expect(screen.getByText("Q1 · top quartile")).toBeInTheDocument();
    expect(screen.getByText(/▲ 4 places since 31 Jul/)).toBeInTheDocument();
    const why = screen.getByRole("list", { name: "Why this quartile" });
    expect(within(why).getByText("Result: 1")).toHaveClass("font-semibold");
    const peers = screen.getByText("Peers in category").closest("section")!;
    expect(within(peers).getAllByText(/Q1/).length).toBeGreaterThanOrEqual(3);
    fireEvent.click(within(peers).getByRole("button", { name: /HDFC Hybrid Equity Fund/ }));
    expect(actions.openFund).toHaveBeenCalledWith("HDFC Hybrid - Reg");
    expect(screen.getByText("History")).toBeInTheDocument();
    expect(screen.getByText("Category average · 1Y rolling")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Trace this number →" }));
    expect(await screen.findByRole("dialog", { name: "Composite Ranks!Z412" })).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/lineage/Composite%20Ranks!Z412") && c.url.includes("run_id=run00001"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "☆ Watch" }));
    expect(JSON.parse(localStorage.getItem(WATCHLIST_KEY)!)[0].key).toBe("WhiteOak Aggressive - Reg");
    expect(screen.getByRole("button", { name: "★ Watching" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("CategoriesPage", () => {
  it("renders a card per category with the quartile bar or the unranked note, and opens one", async () => {
    const calls = mockApi({ "GET /api/research/categories": categories });
    const actions = makeActions();
    render(<CategoriesPage actions={actions} />);
    const thematic = await screen.findByRole("article", { name: "Direct-Thematic" });
    expect(within(thematic).getByText("184 of 190 funds rated")).toBeInTheDocument();
    expect(within(thematic).getByRole("img", { name: /Q1 46 funds/ })).toBeInTheDocument();
    const arb = screen.getByRole("article", { name: "Direct-Arbitrage" });
    expect(within(arb).getByText(/Fewer than 4 ranked funds/)).toBeInTheDocument();
    expect(screen.getByText(/4 keys in the averages table have no fund behind them/)).toBeInTheDocument();
    fireEvent.click(within(thematic).getByRole("button", { name: "Open category →" }));
    expect(actions.openFunds).toHaveBeenCalledWith({ category: "Direct-Thematic" });
    fireEvent.change(screen.getByLabelText("Average measure"), { target: { value: "roll1y" } });
    await waitFor(() => expect(calls.at(-1)!.url).toContain("measure=roll1y"));
  });
});

describe("MovementPage", () => {
  it("shows the four tiles, the repair note and labels repaired rows", async () => {
    mockApi({ "GET /api/research/movement": movement });
    const actions = makeActions();
    render(<MovementPage actions={actions} />);
    expect(await screen.findByText("9 into Q1, 6 out of Q1")).toBeInTheDocument();
    expect(screen.getAllByText("86").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/One of these moves is a data repair/)).toBeInTheDocument();
    const up = screen.getByRole("heading", { name: "Moved up" }).closest("section")!;
    expect(within(up).getByText(/7 → 3 · repaired row/)).toBeInTheDocument();
    expect(within(up).getByText("▲ 23")).toHaveClass("text-positive");
    fireEvent.click(within(up).getByRole("button", { name: /Kotak Nifty Bank/ }));
    expect(actions.openFund).toHaveBeenCalledWith("Kotak Bank Index - Dir");
    fireEvent.click(screen.getByRole("button", { name: "Open version diff" }));
    expect(actions.openVersions).toHaveBeenCalled();
    expect(screen.getByText(/1 funds are new to the universe/)).toBeInTheDocument();
  });

  it("explains when nothing can be compared yet", async () => {
    mockApi({ "GET /api/research/movement": movementUnavailable });
    const actions = makeActions();
    render(<MovementPage actions={actions} />);
    expect(await screen.findByText("Nothing to compare yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upload a version" }));
    expect(actions.openUpload).toHaveBeenCalled();
  });
});

describe("AdminPage and UploadPage", () => {
  it("shows tiles, findings with status and the column map with unresolved refs marked", async () => {
    mockApi({ "GET /api/research/config": researchConfig });
    const setName = vi.fn();
    const actions = makeActions();
    render(
      <AdminPage
        summary={summary}
        versions={[{ ...version, status: "active" }]}
        validation={{ status: "ready", data: { status: "passed_with_warnings", totals: { checked: 100, matched: 100, mismatched: 0, skipped_unsupported: 0, skipped_stale: 0 }, anomaly_counts: { duplicate_keys: 3 } } as never }}
        versionsPanel={<div>versions panel</div>}
        validationPanel={<div>validation panel</div>}
        viewer={{ name: "Jeet", localName: null, setName }}
        actions={actions}
      />,
    );
    expect(await screen.findByText("Roll Perf row 3181 read another fund's row")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("1 fixed · 1 open")).toBeInTheDocument();
    expect(screen.getByText("no mismatches")).toBeInTheDocument();
    expect(screen.getByText("Composite Ranks!B")).toBeInTheDocument();
    const bear = screen.getByText(/Bear final score/).parentElement!.parentElement!;
    expect(bear.querySelector(".text-negative")).not.toBeNull();
    expect(screen.getByText("versions panel")).toBeInTheDocument();
    expect(screen.getByText("validation panel")).toBeInTheDocument();
    const coverage = screen.getByTestId("coverage-detail");
    expect(within(coverage).getByText("Too young to rate")).toBeInTheDocument();
    expect(within(coverage).getByText("1,605")).toBeInTheDocument();
    fireEvent.click(within(coverage).getByRole("button", { name: "Open the coverage cards →" }));
    expect(actions.openInsights).toHaveBeenCalled();
    expect(screen.getByText("Default from the config: Jeet.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Jeet" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(setName).toHaveBeenCalledWith("Jeet");
  });

  it("frames the upload panel with what happens next", () => {
    render(<UploadPage onBusy={() => {}} onDone={() => {}} />);
    expect(screen.getByRole("heading", { name: "Upload version" })).toBeInTheDocument();
    expect(screen.getByText("Recalculate and check against Excel")).toBeInTheDocument();
    expect(screen.getByText("You activate it")).toBeInTheDocument();
  });
});

function Pivots({ actions, location, onOpen, onQuery, onPivotQuery }: { actions: ResearchActions; location: PivotLocation; onOpen: (id: string | null) => void; onQuery: (q: ExploreQuery) => void; onPivotQuery?: (q: PivotQuery) => void }) {
  const pivots = useAsync(() => listPivots(), []);
  return <PivotsPage query={{}} onQuery={onQuery} pivots={pivots} location={location} onOpen={onOpen} onPivotQuery={onPivotQuery ?? vi.fn()} scope={{ ...EMPTY_SCOPE, dims: { plan: "Regular" } }} actions={actions} />;
}

describe("PivotsPage", () => {
  it("asks one question in words, carries the change since last month, and drills into a group", async () => {
    const calls = mockApi({ "GET /api/research/pivots": pivotListing, "GET /api/research/explore": exploreResponse });
    const onQuery = vi.fn();
    const actions = makeActions();
    render(<Pivots actions={actions} location={{ id: null }} onOpen={vi.fn()} onQuery={onQuery} />);
    expect(await screen.findByRole("heading", { name: "Pivots" })).toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/api/research/explore"))).toBe(true);

    const question = screen.getByTestId("question-bar");
    expect(within(question).getByLabelText("Measure")).toHaveValue("rank");
    expect(within(question).getByLabelText("Grouping")).toHaveValue("amc");
    expect(within(question).getByLabelText("Aggregation")).toHaveValue("mean");
    expect(within(question).getByRole("checkbox", { name: /compared with 31 Aug/ })).toBeChecked();
    expect(screen.getByText(narrative(/47 in all, 22 with at least 10 rated funds/))).toBeInTheDocument();

    // Six columns, no sideways scroll: the group, its funds, its quartile mix, Q1 share, the
    // measure and the median rank; every number carries its own change.
    const grid = screen.getByTestId("explore-grid");
    expect(within(grid).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "AMC",
      "Funds",
      "Quartile mix",
      "Top quartile",
      "average composite rank",
      "Median position",
    ]);
    // The colours are explained once, above the table.
    const legend = screen.getByTestId("grid-legend");
    expect(legend).toHaveTextContent("Q1 · top");
    expect(legend).toHaveTextContent("Shading: how close a group is to the best composite rank, among groups with 10+ rated funds");
    expect(legend).toHaveTextContent("change since 31 Aug: green is better, red is worse");
    expect(screen.getByText(/Ranks are counted within each category/)).toBeInTheDocument();
    const icici = within(grid).getByText("ICICI Prudential Mutual Fund").closest("tr")!;
    expect(within(icici).getByText("36%")).toBeInTheDocument();
    expect(within(icici).getByText("▼ 2.0")).toHaveClass("text-positive"); // a lower rank is better
    expect(within(icici).getByText("24.0")).toBeInTheDocument(); // an averaged rank keeps its decimal
    expect(within(icici).getByText("▲ 4pp")).toHaveClass("text-positive");
    const axis = within(grid).getByText("Axis Mutual Fund").closest("tr")!;
    expect(within(axis).getByText("▲ 3.0")).toHaveClass("text-negative");
    const tiny = within(grid).getByText("Tiny Mutual Fund").closest("tr")!;
    expect(tiny).toHaveTextContent("few rated");
    expect(within(tiny).getByRole("img", { name: "No rated funds" })).toHaveTextContent("no rated funds"); // not four equal segments
    expect(within(icici).getByText("top 22%")).toBeInTheDocument();
    expect(within(icici).getByText("▼ 3pp")).toHaveClass("text-positive"); // a smaller position is better
    expect(screen.getByTestId("explore-total")).toHaveTextContent("All funds in scope");

    fireEvent.click(within(grid).getByRole("button", { name: "ICICI Prudential Mutual Fund" }));
    expect(actions.openFunds).toHaveBeenCalledWith({ amc: "ICICI Prudential Mutual Fund" });

    fireEvent.change(within(question).getByLabelText("Grouping"), { target: { value: "category" } });
    expect(onQuery).toHaveBeenLastCalledWith(expect.objectContaining({ by: "category" }));
    fireEvent.click(within(question).getByRole("button", { name: "Top-quartile share by house" }));
    expect(onQuery).toHaveBeenLastCalledWith(expect.objectContaining({ by: "amc", measure: "quartile", sort: "q1_share" }));
    fireEvent.click(within(question).getByRole("checkbox", { name: /compared with/ }));
    expect(onQuery).toHaveBeenLastCalledWith(expect.objectContaining({ compare: false }));
    fireEvent.click(screen.getByRole("button", { name: /Show all 47/ }));
    expect(onQuery).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 0 }));
  });

  it("hides the quartile columns when every group is made of whole categories, and says why", async () => {
    mockApi({
      "GET /api/research/pivots": pivotListing,
      "GET /api/research/explore": { ...exploreResponse, by: { key: "category", label: "Category", kind: "dimension" }, quartilesByConstruction: true },
    });
    render(<Pivots actions={makeActions()} location={{ id: null }} onOpen={vi.fn()} onQuery={vi.fn()} />);
    const grid = await screen.findByTestId("explore-grid");
    const headers = within(grid).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).not.toContain("Quartile mix");
    expect(headers).not.toContain("Top quartile");
    expect(screen.getByText(/splits into four roughly equal parts by construction/)).toBeInTheDocument();
    expect(screen.getByTestId("grid-legend")).not.toHaveTextContent("Q1 · top");
  });

  it("keeps the workbook's own layouts behind a fold and opens one", async () => {
    mockApi({ "GET /api/research/pivots": pivotListing, "GET /api/research/explore": exploreResponse });
    const onOpen = vi.fn();
    render(<Pivots actions={makeActions()} location={{ id: null }} onOpen={onOpen} onQuery={vi.fn()} />);
    const fold = await screen.findByTestId("workbook-layouts");
    expect(fold).toHaveTextContent("The workbook's own pivot layouts");
    expect(within(fold).getByText("Pivot 1-Indices-Roll").closest("button")).toHaveTextContent("cached");
    fireEvent.click(within(fold).getByRole("button", { name: /PIVOT-Composite/ }));
    expect(onOpen).toHaveBeenCalledWith("PIVOT-Composite::PivotTable1");
  });

  it("opens a workbook layout with its saved filters plus the global scope", async () => {
    const calls = mockApi({ "GET /api/research/pivots": pivotListing, "GET /api/research/pivot": pivotTable });
    const onPivotQuery = vi.fn();
    const actions = makeActions();
    render(<Pivots actions={actions} location={{ id: "PIVOT-Composite::PivotTable1" }} onOpen={vi.fn()} onQuery={vi.fn()} onPivotQuery={onPivotQuery} />);
    expect(await screen.findByRole("heading", { name: "PIVOT-Composite" })).toBeInTheDocument();
    const url = calls.find((c) => c.url.startsWith("/api/research/pivot?"))!.url;
    const sent = JSON.parse(new URLSearchParams(url.split("?")[1]).get("spec")!) as PivotQuery;
    expect(sent.filters).toEqual({ Universe: ["Yes"], "Sub Plan": ["Regular"] });

    const grid = await screen.findByTestId("pivot-grid");
    expect(within(grid).getByText("Kotak Nifty Bank Index Fund")).toBeInTheDocument();
    expect(within(grid).getByText("Grand total").closest("tr")).toHaveAttribute("data-kind", "total");

    const picker = screen.getByTestId("filter-Scheme Nature");
    fireEvent.click(within(picker).getByText("Scheme Nature"));
    fireEvent.click(within(picker).getByLabelText("Hybrid"));
    expect(onPivotQuery).toHaveBeenLastCalledWith(expect.objectContaining({ filters: { Universe: ["Yes"], "Sub Plan": ["Regular"], "Scheme Nature": ["Hybrid"] } }));

    fireEvent.click(within(grid).getByRole("button", { name: "Axis Value Fund" }));
    expect(actions.openFunds).toHaveBeenCalledWith({ q: "Axis Value Fund" });
  });

  it("builds the workbook's layout as the default query", () => {
    const q = defaultQuery(pivotListing.pivots[0], undefined, {});
    expect(q).toEqual({ filters: { Universe: ["Yes"], "Sub Plan": ["Direct"] }, rows: ["Scheme Name"], cols: [], values: pivotListing.pivots[0].layout.values });
  });
});
