import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getValidation, type ValidationReport } from "@/api/validation";
import { useAsync } from "@/lib/useAsync";
import { version } from "@/test/fixtures";
import { jsonError, mockApi } from "@/test/mockApi";
import { ValidationPage } from "./ValidationPage";

const report: ValidationReport = {
  id: "rep1",
  version_id: version.id,
  run_id: "run1",
  created_at: "2026-09-11T12:00:00Z",
  status: "passed_with_warnings",
  policy: { significant_digits: 15, max_mismatch_ratio: 0, max_precision_ratio: 0.001 },
  totals: { checked: 1000, matched: 1000, mismatched: 0, skipped_unsupported: 1, skipped_stale: 0 },
  by_sheet: [
    { sheet: "Series", formula_cells: 100, checked: 100, matched: 100, mismatched: 0, skipped_unsupported: 0, skipped_stale: 0 },
    { sheet: "Calc", formula_cells: 11, checked: 10, matched: 10, mismatched: 0, skipped_unsupported: 1, skipped_stale: 0 },
  ],
  mismatches: [],
  mismatches_truncated: false,
  unsupported: [{ function: "XLOOKUP", sheet: "Calc", cell: "B11", cells: 1 }],
  anomalies: [
    {
      id: 1,
      kind: "own_row",
      sheet: "Roll Perf",
      location: "K3181, L3181",
      title: "Roll Perf row 3181: formulas read row 3258 instead of their own row",
      explanation: "This is the signature of a cut-and-pasted row.",
      detail: {},
    },
  ],
  anomaly_counts: { own_row: 1 },
  reasons: ["1 cell(s) use functions the engine does not support and were skipped", "1 structural anomaly warning(s)"],
  seconds: 4.2,
};

function Harness({ status = "interpreted" }: { status?: string }) {
  const state = useAsync(() => getValidation(version.id), [version.id]);
  return <ValidationPage version={{ ...version, status }} report={state} onBusy={() => {}} onVersionChanged={() => {}} />;
}

afterEach(() => vi.restoreAllMocks());

describe("ValidationPage", () => {
  it("renders totals, coverage, skipped functions and grouped anomalies", async () => {
    mockApi({ [`GET /api/workbooks/${version.id}/validation`]: report });
    render(<Harness />);
    expect(await screen.findByText("passed with warnings")).toBeInTheDocument();
    const values = screen.getAllByTestId("stat-value").map((el) => el.textContent);
    expect(values).toEqual(["1,000", "1,000", "0", "1", "1"]);
    expect(screen.getByText("Every checked cell matches Excel")).toBeInTheDocument();
    expect(screen.getByText("XLOOKUP")).toBeInTheDocument();
    expect(screen.getByText(/Rows reading other rows/)).toBeInTheDocument();
    expect(screen.getByText(/cut-and-pasted row/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activate version" })).toBeInTheDocument();
  });

  it("offers to run validation when none exists and posts to /validate", async () => {
    const calls = mockApi({
      [`GET /api/workbooks/${version.id}/validation`]: jsonError(404, "This version has not been validated yet."),
      [`POST /api/workbooks/${version.id}/validate`]: report,
    });
    render(<Harness />);
    fireEvent.click(await screen.findByRole("button", { name: "Run validation" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/validate"))).toBe(true));
  });

  it("requires an override reason to activate a failed validation", async () => {
    const failed: ValidationReport = {
      ...report,
      status: "failed",
      totals: { ...report.totals, mismatched: 1, matched: 999 },
      mismatches: [{ sheet: "Series", cell: "C21", template_id: 3, formula: "=C20+B21", excel: 3271, engine: 3270, delta: -1, classification: "semantics" }],
      reasons: ["1 of 1,000 checked cells differ from Excel beyond precision"],
    };
    const calls = mockApi({
      [`GET /api/workbooks/${version.id}/validation`]: failed,
      [`POST /api/workbooks/${version.id}/activate`]: { ...version, status: "active", activation_override: true },
    });
    render(<Harness />);
    expect(await screen.findByText("Series!C21")).toBeInTheDocument();
    expect(screen.getByText("semantics")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Activate with override" }));
    const activate = screen.getByRole("button", { name: "Activate with this reason" });
    expect(activate).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Override reason"), { target: { value: "known perturbation" } });
    fireEvent.click(activate);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/activate"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/activate"))?.body).toEqual({ override_reason: "known perturbation" });
  });
});
