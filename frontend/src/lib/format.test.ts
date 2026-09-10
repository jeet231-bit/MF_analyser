import { formatNumber } from "./format";

describe("formatNumber", () => {
  it("uses Indian grouping by default", () => {
    expect(formatNumber(1234567.891)).toBe("12,34,567.89");
  });
  it("supports international grouping", () => {
    expect(formatNumber(1234567.891, { grouping: "international" })).toBe("1,234,567.89");
  });
  it("never renders NaN", () => {
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatNumber(null)).toBe("—");
  });
});
