import { fireEvent, render, screen } from "@testing-library/react";
import { model, version } from "@/test/fixtures";
import { summary } from "@/test/researchFixtures";
import { buildNavigation, buildResearchNav, buildWorkbookNav, readView, VIEW_KEY, writeView } from "./navigation";
import { Sidebar } from "./Sidebar";

describe("navigation", () => {
  it("derives module entries from sheet roles; every module is a live page", () => {
    const nav = buildNavigation(model, 3);
    expect(nav.map((n) => n.label)).toEqual(["Overview", "Inputs", "Calculations", "Outputs", "Versions", "Validation"]);
    expect(nav.find((n) => n.id === "inputs")?.sheets).toEqual(["Inputs", "Lookup"]);
    expect(nav.find((n) => n.id === "validation")?.badge).toBe(3);
    expect(buildNavigation(null).map((n) => n.label)).toEqual(["Overview", "Versions", "Validation"]);
  });

  it("builds the research rail with live counts and the workbook rail with sheets grouped by role", () => {
    const research = buildResearchNav(summary, 12);
    expect(research.map((n) => n.id)).toEqual(["dashboard", "insights", "funds", "categories", "movement"]);
    expect(research.find((n) => n.id === "funds")?.count).toBe(3232);
    expect(research.find((n) => n.id === "categories")?.count).toBe(200);
    expect(research.find((n) => n.id === "movement")?.count).toBe(86);
    expect(research.find((n) => n.id === "insights")?.count).toBe(12);
    expect(buildResearchNav(null).every((n) => n.count === undefined)).toBe(true);

    const groups = buildWorkbookNav(model, 2);
    expect(groups.map((g) => g.label)).toEqual([null, "Outputs", "Calculations", "Inputs", "Model"]);
    expect(groups[1].items.map((i) => i.id)).toEqual(["sheet:Calc", "sheet:Outputs"]);
    expect(groups[3].items).toEqual([{ id: "inputs", label: "Weights & dates", enabled: true, sheets: ["Inputs", "Lookup"] }]);
    expect(groups[4].items.find((i) => i.id === "validation")?.badge).toBe(2);
  });

  it("persists the view per browser and falls back safely", () => {
    localStorage.removeItem(VIEW_KEY);
    expect(readView()).toEqual({ mode: "research", page: "dashboard" });
    writeView({ mode: "workbook", page: "outputs" });
    expect(readView()).toEqual({ mode: "workbook", page: "outputs" });
    writeView({ mode: "research", page: "fund" }); // a fund page needs a fund: reopen on the dashboard
    expect(readView()).toEqual({ mode: "research", page: "dashboard" });
    localStorage.setItem(VIEW_KEY, "{not json");
    expect(readView()).toEqual({ mode: "research", page: "dashboard" });
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => writeView({ mode: "research", page: "funds" })).not.toThrow();
    spy.mockRestore();
  });
});

function renderSidebar(overrides: Partial<React.ComponentProps<typeof Sidebar>> = {}) {
  const onNavigate = vi.fn();
  const onMode = vi.fn();
  render(
    <Sidebar
      displayName="Equity MF Analyser"
      mode="research"
      onMode={onMode}
      versions={[{ ...version, status: "active" }]}
      selectedVersionId={version.id}
      onSelectVersion={() => {}}
      model={model}
      activeItem="dashboard"
      onNavigate={onNavigate}
      validationStatus="passed_with_warnings"
      anomalyCount={0}
      summary={summary}
      insightCount={12}
      theme="light"
      onToggleTheme={() => {}}
      {...overrides}
    />,
  );
  return { onNavigate, onMode };
}

describe("Sidebar (the rail)", () => {
  it("shows the brand, the active version chip, the research entries with counts and the foot", () => {
    const { onNavigate } = renderSidebar();
    expect(screen.getByText("Equity MF Analyser")).toBeInTheDocument();
    expect(screen.getByTestId("version-chip")).toHaveTextContent("master.xlsx");
    expect(screen.getByTestId("version-chip")).toHaveTextContent("active · passed with warnings");
    expect(screen.getByRole("button", { name: /Dashboard/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Funds/ })).toHaveTextContent("3,232");
    expect(screen.getByRole("button", { name: /Movement/ })).toHaveTextContent("86");
    fireEvent.click(screen.getByRole("button", { name: /Categories/ }));
    expect(onNavigate).toHaveBeenCalledWith("categories");
    expect(screen.getByRole("button", { name: /Upload version/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dark theme" })).toBeInTheDocument();
    expect(screen.queryByLabelText("needs attention")).not.toBeInTheDocument();
  });

  it("switches modes and lists workbook sheets grouped by role, routing a sheet to its page", () => {
    const { onNavigate, onMode } = renderSidebar({ mode: "workbook", activeItem: "sheet", activeSheet: "Series", anomalyCount: 2, openFindings: 1 });
    const group = screen.getByRole("group", { name: "View" });
    expect(group.querySelector('[aria-pressed="true"]')).toHaveTextContent("Workbook");
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(onMode).toHaveBeenCalledWith("research");
    expect(screen.getAllByText("Outputs")).toHaveLength(2); // the group label and the sheet of that name
    expect(screen.getByRole("button", { name: /Series/ })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: /^Calc$/ }));
    expect(onNavigate).toHaveBeenCalledWith("sheet", "Calc");
    fireEvent.click(screen.getByRole("button", { name: /Weights & dates/ }));
    expect(onNavigate).toHaveBeenCalledWith("inputs");
    expect(screen.getByLabelText("2 anomalies")).toHaveTextContent("2");
    expect(screen.getByLabelText("needs attention")).toBeInTheDocument();
  });
});
