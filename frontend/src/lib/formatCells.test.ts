import { formatCell, formatDelta, isoDateToSerial, serialToIsoDate } from "./format";

describe("cell formatting", () => {
  it("renders by column format with Indian grouping", () => {
    expect(formatCell(1234567.891, "number")).toBe("12,34,567.89");
    expect(formatCell(1234567, "integer")).toBe("12,34,567");
    expect(formatCell(0.1234, "percent")).toBe("12.34%");
    expect(formatCell(3410, "general")).toBe("3,410");
    expect(formatCell(0.5, "general")).toBe("0.50");
    expect(formatCell("--", "number")).toBe("--");
    expect(formatCell(true, "general")).toBe("TRUE");
    expect(formatCell(null, "number")).toBe("");
    expect(formatCell(46053, "date")).toMatch(/31 Jan 2026/);
    expect(formatCell(46053, "general", undefined, "date")).toMatch(/31 Jan 2026/);
  });

  it("round-trips Excel serial dates", () => {
    expect(serialToIsoDate(46053)).toBe("2026-01-31");
    expect(isoDateToSerial("2026-01-31")).toBe(46053);
    expect(serialToIsoDate(1)).toBe("1900-01-01");
  });

  it("signs deltas and derives their direction", () => {
    expect(formatDelta(80)).toEqual({ text: "+80", direction: "up" });
    expect(formatDelta(-1.5)).toEqual({ text: "−1.50", direction: "down" });
    expect(formatDelta(0)).toEqual({ text: "0", direction: "flat" });
  });
});
