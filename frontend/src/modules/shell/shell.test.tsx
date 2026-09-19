import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { model, version } from "@/test/fixtures";
import { summary } from "@/test/researchFixtures";
import { buildNavigation, buildResearchNav, buildWorkbookNav, RAIL_KEY, readPinned, readView, VIEW_KEY, writePinned, writeView } from "./navigation";
import { AppShell } from "./AppShell";
import { describeLocation, useAppHistory } from "./history";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";

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
    expect(research.map((n) => n.id)).toEqual(["dashboard", "insights", "funds", "categories", "pivots", "movement"]);
    expect(buildResearchNav(summary, 12, 17).find((n) => n.id === "pivots")?.count).toBe(17);
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

  it("persists the view and the rail pin per browser and falls back safely", () => {
    localStorage.removeItem(VIEW_KEY);
    localStorage.removeItem(RAIL_KEY);
    expect(readView()).toEqual({ mode: "research", page: "dashboard" });
    writeView({ mode: "workbook", page: "outputs" });
    expect(readView()).toEqual({ mode: "workbook", page: "outputs" });
    writeView({ mode: "research", page: "fund" }); // a fund page needs a fund: reopen on the dashboard
    expect(readView()).toEqual({ mode: "research", page: "dashboard" });
    localStorage.setItem(VIEW_KEY, "{not json");
    expect(readView()).toEqual({ mode: "research", page: "dashboard" });
    expect(readPinned()).toBe(false);
    writePinned(true);
    expect(readPinned()).toBe(true);
    writePinned(false);
    expect(readPinned()).toBe(false);
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => writeView({ mode: "research", page: "funds" })).not.toThrow();
    expect(() => writePinned(true)).not.toThrow();
    spy.mockRestore();
  });
});

function renderRail(overrides: Partial<React.ComponentProps<typeof Rail>> = {}) {
  const onNavigate = vi.fn();
  const onPin = vi.fn();
  render(
    <Rail
      displayName="Equity MF Analyser"
      mode="research"
      model={model}
      activeItem="dashboard"
      onNavigate={onNavigate}
      anomalyCount={0}
      summary={summary}
      insightCount={12}
      pinned={false}
      onPin={onPin}
      {...overrides}
    />,
  );
  return { onNavigate, onPin };
}

describe("Rail (icons that expand on hover, pinnable)", () => {
  it("lists the research screens as icon buttons with counts, the foot, and a pin toggle", () => {
    const { onNavigate, onPin } = renderRail();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).not.toHaveAttribute("data-pinned");
    expect(screen.getByRole("button", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Funds" })).toHaveTextContent("3,232");
    expect(screen.getByRole("button", { name: "Movement" })).toHaveTextContent("86");
    fireEvent.click(screen.getByRole("button", { name: "Categories" }));
    expect(onNavigate).toHaveBeenCalledWith("categories");
    expect(screen.getByRole("button", { name: "Upload version" })).toBeInTheDocument();
    const pin = screen.getByRole("button", { name: "Keep menu open" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(pin);
    expect(onPin).toHaveBeenCalledWith(true);
    expect(screen.queryByLabelText("needs attention")).not.toBeInTheDocument();
  });

  it("stays open when pinned and lists workbook sheets grouped by role, routing a sheet to its page", () => {
    const { onNavigate } = renderRail({ mode: "workbook", activeItem: "sheet", activeSheet: "Series", anomalyCount: 2, openFindings: 1, pinned: true });
    expect(screen.getByRole("navigation", { name: "Main" })).toHaveAttribute("data-pinned");
    expect(screen.getByRole("button", { name: "Collapse menu" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByText("Outputs")).toHaveLength(2); // the group label and the sheet of that name
    expect(screen.getByRole("button", { name: "Series" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Calc" }));
    expect(onNavigate).toHaveBeenCalledWith("sheet", "Calc");
    fireEvent.click(screen.getByRole("button", { name: "Weights & dates" }));
    expect(onNavigate).toHaveBeenCalledWith("inputs");
    expect(screen.getByRole("button", { name: "Validation" })).toHaveTextContent("2");
    expect(screen.getByLabelText("needs attention")).toBeInTheDocument();
  });
});

describe("TopBar", () => {
  it("switches modes, searches, shows the version pill, toggles the theme and opens the profile", () => {
    const onMode = vi.fn();
    const onSearch = vi.fn();
    const onToggleTheme = vi.fn();
    const onOpenProfile = vi.fn();
    render(
      <TopBar
        mode="research"
        onMode={onMode}
        onSearch={onSearch}
        version={{ ...version, status: "active" }}
        validationLabel="passed with warnings"
        theme="light"
        onToggleTheme={onToggleTheme}
        viewerInitials="J"
        viewerName="Jeet"
        onOpenProfile={onOpenProfile}
      />,
    );
    const group = screen.getByRole("group", { name: "View" });
    expect(group.querySelector('[aria-pressed="true"]')).toHaveTextContent("Research");
    fireEvent.click(screen.getByRole("button", { name: "Workbook" }));
    expect(onMode).toHaveBeenCalledWith("workbook");
    const input = screen.getByRole("searchbox", { name: "Search a fund, category or AMC" });
    fireEvent.change(input, { target: { value: "kotak" } });
    fireEvent.submit(input.closest("form")!);
    expect(onSearch).toHaveBeenCalledWith("kotak");
    expect(screen.getByTestId("version-pill")).toHaveTextContent("master.xlsx");
    expect(screen.getByTestId("version-pill")).toHaveTextContent("active · passed with warnings");
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(onToggleTheme).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Jeet: open settings" }));
    expect(onOpenProfile).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Jeet: open settings" })).toHaveTextContent("J");
  });
});

describe("AppShell", () => {
  it("pushes the page aside when the rail is pinned, overlays it otherwise", () => {
    const { rerender } = render(
      <AppShell rail={<nav />} topBar={<header />} pinned={false}>
        <p>page</p>
      </AppShell>,
    );
    expect(screen.getByTestId("shell-column").className).toContain("pl-[var(--rail-w)]");
    rerender(
      <AppShell rail={<nav />} topBar={<header />} pinned>
        <p>page</p>
      </AppShell>,
    );
    expect(screen.getByTestId("shell-column").className).toContain("--rail-open");
  });
});

describe("useAppHistory (Back stays inside the app and restores the screen)", () => {
  it("pushes screens, replaces filters in place, and pops back to the previous screen with them", async () => {
    window.history.replaceState(null, "");
    const { result } = renderHook(() => useAppHistory(() => ({ mode: "research", page: "dashboard" })));
    expect(result.current.location.page).toBe("dashboard");
    expect(result.current.canGoBack).toBe(false);

    act(() => result.current.navigate({ mode: "research", page: "funds", funds: { groupBy: "amc" } }));
    act(() => result.current.replace({ funds: { amc: "Axis" } }));
    expect(result.current.location.funds).toEqual({ amc: "Axis" });
    act(() => result.current.navigate({ mode: "research", page: "fund", fund: "Axis Value - Dir" }));
    expect(result.current.location.fund).toBe("Axis Value - Dir");
    expect(describeLocation(result.current.previous)).toBe("funds · Axis");
    expect(result.current.canGoBack).toBe(true);

    act(() => result.current.back({ mode: "research", page: "funds" }));
    await waitFor(() => expect(result.current.location.page).toBe("funds"));
    expect(result.current.location.funds).toEqual({ amc: "Axis" }); // the filter survived the round trip
    expect(describeLocation(result.current.previous)).toBe("dashboard");
  });

  it("falls back to a given screen when there is nothing to go back to", () => {
    window.history.replaceState(null, "");
    const { result } = renderHook(() => useAppHistory(() => ({ mode: "research", page: "dashboard" })));
    act(() => result.current.back({ mode: "research", page: "funds" }));
    expect(result.current.location.page).toBe("funds");
  });

  it("names screens for the back link", () => {
    expect(describeLocation(null)).toBeNull();
    expect(describeLocation({ mode: "research", page: "funds" })).toBe("all funds");
    expect(describeLocation({ mode: "research", page: "funds", funds: { category: "Direct-Thematic", q: "kotak" } })).toBe("funds · Direct-Thematic · “kotak”");
    expect(describeLocation({ mode: "workbook", page: "sheet", sheet: "Report" })).toBe("Report");
    expect(describeLocation({ mode: "research", page: "fund", fund: "x" })).toBe("the previous fund");
  });
});
