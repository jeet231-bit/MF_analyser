import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { EMPTY_SCOPE, isScopeEmpty, scopeParam, type Scope } from "@/api/research";
import { summary } from "@/test/researchFixtures";
import { ScopeBar } from "./ScopeBar";
import { SCOPE_KEY, useScope } from "./useScope";
import { greeting, initials, timeOfDay, useViewer, VIEWER_KEY } from "./useViewer";

afterEach(() => {
  localStorage.removeItem(SCOPE_KEY);
  localStorage.removeItem(VIEWER_KEY);
});

describe("scope", () => {
  it("serialises only what is selected and knows when nothing is", () => {
    expect(isScopeEmpty(EMPTY_SCOPE)).toBe(true);
    expect(scopeParam(EMPTY_SCOPE)).toBeUndefined();
    const s: Scope = { dims: { plan: "Direct", amc: "" }, quartile: [1], bands: { corpus: "b4", expense: "" }, rated: "only", q: "" };
    expect(JSON.parse(scopeParam(s)!)).toEqual({ dims: { plan: "Direct" }, quartile: [1], bands: { corpus: "b4" }, rated: "only" });
  });

  it("persists per browser and survives garbage or blocked storage", () => {
    localStorage.setItem(SCOPE_KEY, "{nope");
    const { result } = renderHook(() => useScope());
    expect(result.current.applied).toBe(false);
    act(() => result.current.setScope({ ...EMPTY_SCOPE, dims: { plan: "Direct" } }));
    expect(result.current.applied).toBe(true);
    expect(JSON.parse(localStorage.getItem(SCOPE_KEY)!).dims.plan).toBe("Direct");
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => result.current.setScope({ ...EMPTY_SCOPE, rated: "only" }));
    expect(result.current.scope.rated).toBe("only");
    spy.mockRestore();
    act(() => result.current.reset());
    expect(result.current.applied).toBe(false);
  });

  it("renders the description collapsed, expands to the filter grid, applies and resets", () => {
    const onApply = vi.fn();
    render(<ScopeBar scope={EMPTY_SCOPE} description={summary.scope!.description} options={summary.scope_options} onApply={onApply} />);
    expect(screen.getByTestId("scope-description")).toHaveTextContent("All funds · every category · every AMC · both plans");
    expect(screen.queryByRole("button", { name: "Apply scope" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Scope/ }));
    const bar = screen.getByRole("region", { name: "Scope" });
    fireEvent.change(within(bar).getByLabelText("Plan"), { target: { value: "Direct" } });
    fireEvent.change(within(bar).getByLabelText("Quartile"), { target: { value: "1,2" } });
    fireEvent.change(within(bar).getByLabelText("Corpus band"), { target: { value: "b4" } });
    fireEvent.change(within(bar).getByLabelText("Rating status"), { target: { value: "only" } });
    expect(within(bar).getByText(/Scope applies to every view/)).toBeInTheDocument();
    fireEvent.click(within(bar).getByRole("button", { name: "Apply scope" }));
    expect(onApply).toHaveBeenCalledWith({ dims: { plan: "Direct" }, quartile: [1, 2], bands: { corpus: "b4" }, rated: "only" });
    expect(within(bar).queryByRole("button", { name: "Apply scope" })).not.toBeInTheDocument(); // applying collapses the grid
    fireEvent.click(screen.getByRole("button", { name: /Scope/ }));
    fireEvent.click(within(bar).getByRole("button", { name: "Reset" }));
    expect(onApply).toHaveBeenLastCalledWith(EMPTY_SCOPE);
  });
});

describe("viewer", () => {
  it("greets by the browser clock and falls back to a plain greeting without a name", () => {
    expect(timeOfDay(new Date(2026, 8, 12, 9))).toBe("morning");
    expect(timeOfDay(new Date(2026, 8, 12, 14))).toBe("afternoon");
    expect(timeOfDay(new Date(2026, 8, 12, 19))).toBe("evening");
    expect(greeting("Jeet", new Date(2026, 8, 12, 9))).toBe("Good morning, Jeet");
    expect(greeting(null, new Date(2026, 8, 12, 19))).toBe("Good evening");
    expect(initials("Jeet Karkar")).toBe("JK");
    expect(initials(null)).toBe("·");
  });

  it("prefers the per-browser name over the config default, and survives blocked storage", () => {
    const { result } = renderHook(() => useViewer("Jeet"));
    expect(result.current.name).toBe("Jeet");
    expect(result.current.localName).toBeNull();
    act(() => result.current.setName("  Darsh "));
    expect(result.current.name).toBe("Darsh");
    expect(JSON.parse(localStorage.getItem(VIEWER_KEY)!)).toEqual({ name: "Darsh" });
    act(() => result.current.setName(""));
    expect(result.current.name).toBe("Jeet");
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => result.current.setName("Priya"));
    expect(result.current.name).toBe("Priya");
    spy.mockRestore();
  });
});
