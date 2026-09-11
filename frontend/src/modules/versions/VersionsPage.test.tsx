import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { DiffReport } from "@/api/versions";
import type { WorkbookVersion } from "@/api/workbooks";
import { version } from "@/test/fixtures";
import { mockApi } from "@/test/mockApi";
import { VersionsPage } from "./VersionsPage";

const active: WorkbookVersion = { ...version, id: "v-active", filename: "master-aug.xlsx", status: "active", validation_status: "passed", uploaded_at: "2026-08-31T09:00:00Z", activated_at: "2026-08-31T10:00:00Z" };
const pending: WorkbookVersion = {
  ...version,
  id: "v-new",
  filename: "master-sep.xlsx",
  status: "pending_review",
  validation_status: "passed_with_warnings",
  uploaded_at: "2026-09-11T09:00:00Z",
  diff_base_id: "v-active",
  diff_headline: "1 logic change affecting 2 of 5 outputs",
};
const failed: WorkbookVersion = { ...version, id: "v-bad", filename: "master-bad.xlsx", status: "validated", validation_status: "failed", uploaded_at: "2026-09-01T09:00:00Z" };

const report: DiffReport = {
  base_version_id: "v-active",
  target_version_id: "v-new",
  created_at: "2026-09-11T09:05:00Z",
  headline: "1 logic change affecting 2 of 5 outputs; 1 data change reaching 3 of 5 outputs",
  summary: { logic_changes: 1, data_changes: 1, structural_changes: 1, outputs_total: 5, outputs_affected_by_logic: 2, outputs_affected_by_data: 3, logic_cells: 20 },
  logic: [
    {
      id: 1,
      kind: "template_changed",
      sheet: "Series",
      location: "D2:D21",
      cells: 20,
      title: "Series D2:D21: formula changed",
      description: "threshold B2 <= 120 → 130",
      detail: { old_formula: '=IF(B2<=120,"Low",IF(B2<=200,"Mid","High"))', new_formula: '=IF(B2<=130,"Low",IF(B2<=200,"Mid","High"))' },
      affected_outputs: [{ block_id: 9, sheet: "Outputs", range: "B3", label: "High months", cells: 1 }],
      affected_output_count: 1,
    },
  ],
  data: [{ id: 2, kind: "rows_added", sheet: "Series", count: 5, description: "Series: 5 row(s) added (25 formula cells extend existing patterns)", detail: {} }],
  structural: [{ id: 3, kind: "anomaly_resolved", sheet: "Roll Perf", description: "Resolved own row anomaly: Roll Perf row 3181", detail: { kind: "own_row" } }],
  sheet_map: { Series: "Series" },
};

afterEach(() => vi.restoreAllMocks());

describe("VersionsPage", () => {
  it("lists versions with status and validation chips and shows the changelog vs the active version", async () => {
    mockApi({ "GET /api/workbooks/v-active/diff/v-new": report });
    render(<VersionsPage versions={[pending, active, failed]} selectedId="v-new" onBusy={() => {}} onVersionsChanged={() => {}} />);
    expect(screen.getAllByText("master-sep.xlsx").length).toBeGreaterThan(0);
    expect(screen.getByText("pending review")).toBeInTheDocument();
    expect(screen.getAllByText("passed with warnings").length).toBeGreaterThan(0);
    expect(await screen.findByText(report.headline)).toBeInTheDocument();
    expect(screen.getByText("threshold B2 <= 120 → 130")).toBeInTheDocument();
    expect(screen.getByText(/Series: 5 row\(s\) added/)).toBeInTheDocument();
    expect(screen.getByText("Anomaly resolved")).toBeInTheDocument();
    expect(screen.getByText(/Outputs!B3 · High months/)).toBeInTheDocument();
    expect(screen.getByLabelText("Base version")).toHaveValue("v-active");
    expect(screen.getByLabelText("Target version")).toHaveValue("v-new");
  });

  it("activates a pending version and demands a reason for a failed one", async () => {
    const calls = mockApi({
      "GET /api/workbooks/v-active/diff/v-new": report,
      "POST /api/workbooks/v-new/activate": { ...pending, status: "active" },
      "POST /api/workbooks/v-bad/activate": { ...failed, status: "active", activation_override: true },
    });
    const onChanged = vi.fn();
    render(<VersionsPage versions={[pending, active, failed]} selectedId="v-new" onBusy={() => {}} onVersionsChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "Activate master-sep.xlsx" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/v-new/activate"))).toBe(true));
    expect(onChanged).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Activate master-bad.xlsx" }));
    const dialog = screen.getByLabelText("Override reason").closest("div")!;
    const confirm = within(dialog.parentElement!).getByRole("button", { name: "Activate with this reason" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Override reason"), { target: { value: "accepting known mismatch" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/v-bad/activate"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/v-bad/activate"))?.body).toEqual({ override_reason: "accepting known mismatch" });
  });
});
