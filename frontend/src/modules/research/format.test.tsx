import { act, render, renderHook, screen } from "@testing-library/react";
import { measures } from "@/test/researchFixtures";
import { formatInrCrore, formatMeasure, formatRankDelta, tableMeasures } from "./format";
import { Narrative, QuartileBar, QuartilePill } from "./ui";
import { useWatchlist, WATCHLIST_KEY } from "./useWatchlist";

const settings = { grouping: "indian" as const, decimals: 2 };

describe("research formatting", () => {
  it("renders Indian currency for amounts in crore", () => {
    expect(formatInrCrore(3911885)).toBe("₹39.1 lakh crore");
    expect(formatInrCrore(122954)).toBe("₹1.2 lakh crore");
    expect(formatInrCrore(86785)).toBe("₹86,785 crore");
    expect(formatInrCrore(45.26)).toBe("₹45.3 crore");
  });

  it("formats a measure by its config: ranks as integers, percent units, currency, the workbook's --", () => {
    const by = Object.fromEntries(measures.map((m) => [m.key, m]));
    expect(formatMeasure(3, by.rank, settings)).toBe("3");
    expect(formatMeasure(18.4, by.roll1y, settings)).toBe("18.40%");
    expect(formatMeasure(122954, by.corpus, settings)).toBe("₹1.2 lakh crore");
    expect(formatMeasure(null, by.rank, settings, "--")).toBe("--");
    expect(formatMeasure(null, by.rank, settings)).toBe("—");
    expect(formatRankDelta(4)).toEqual({ text: "▲ 4", direction: "up" });
    expect(formatRankDelta(-16)).toEqual({ text: "▼ 16", direction: "down" });
    expect(formatRankDelta(null).text).toBe("—");
  });

  it("picks table columns: primaries, up to four returns, two secondary scores", () => {
    expect(tableMeasures(measures).map((m) => m.key)).toEqual(["score", "rank", "quartile", "roll1y", "roll3y", "bull", "bear"]);
  });
});

describe("research ui", () => {
  it("labels the quartile bar for screen readers and colours pills by quartile", () => {
    render(<QuartileBar counts={{ "1": 812, "2": 814, "3": 811, "4": 812 }} />);
    expect(screen.getByRole("img", { name: "Quartile distribution: Q1 812 funds, Q2 814 funds, Q3 811 funds, Q4 812 funds" })).toBeInTheDocument();
    const { container } = render(
      <>
        <QuartilePill q={1} />
        <QuartilePill q={null} />
      </>,
    );
    expect(container.querySelector(".bg-q1")).toHaveTextContent("Q1");
    expect(screen.getByText("--")).toHaveClass("bg-hairline");
  });

  it("sets the numbers in a narrative in ink", () => {
    const { container } = render(<Narrative text="86 funds changed rank since 31 Jul: ₹39.1 lakh crore sits in 731 funds." />);
    const bold = Array.from(container.querySelectorAll("b")).map((b) => b.textContent);
    expect(bold).toEqual(["86", "31", "₹39.1 lakh crore", "731"]);
    expect(render(<Narrative text={null} />).container).toBeEmptyDOMElement();
  });
});

describe("useWatchlist", () => {
  beforeEach(() => localStorage.removeItem(WATCHLIST_KEY));

  it("pins and unpins funds and persists them per browser", () => {
    const { result } = renderHook(() => useWatchlist());
    act(() => result.current.toggle({ key: "A", label: "Fund A" }));
    expect(result.current.has("A")).toBe(true);
    expect(JSON.parse(localStorage.getItem(WATCHLIST_KEY)!)).toEqual([{ key: "A", label: "Fund A" }]);
    act(() => result.current.toggle({ key: "A", label: "Fund A" }));
    expect(result.current.items).toEqual([]);
  });

  it("survives storage that throws or holds garbage", () => {
    localStorage.setItem(WATCHLIST_KEY, "{nope");
    const { result } = renderHook(() => useWatchlist());
    expect(result.current.items).toEqual([]);
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => result.current.toggle({ key: "B", label: "Fund B" }));
    expect(result.current.has("B")).toBe(true);
    spy.mockRestore();
  });
});
