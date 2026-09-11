import { render, screen } from "@testing-library/react";
import type { OutputsSummary } from "@/api/views";
import { mockApi } from "@/test/mockApi";
import { version } from "@/test/fixtures";
import { baselineRun, outputs, whatIfOutputs, whatIfRun } from "@/test/runFixtures";
import type { RunSession } from "@/modules/runs/useRunSession";
import { OutputsPage } from "./OutputsPage";

afterEach(() => vi.restoreAllMocks());

const idle: RunSession = {
  draft: new Map(),
  setDraft: () => {},
  resetDraft: () => {},
  activeRun: null,
  job: null,
  error: null,
  running: false,
  waiting: null,
  runAnalysis: async () => {},
  runFull: async () => {},
  backToBaseline: () => {},
  dismissJob: () => {},
};

describe("OutputsPage", () => {
  it("leads with metrics as stat tiles, without deltas on the baseline", async () => {
    mockApi({ [`GET /api/workbooks/${version.id}/outputs?run_id=${baselineRun.id}`]: outputs });
    render(<OutputsPage version={version} session={idle} runId={baselineRun.id} />);
    expect(await screen.findByRole("heading", { name: "Outputs", level: 2 })).toBeInTheDocument();
    const values = screen.getAllByTestId("stat-value").map((el) => el.textContent);
    expect(values).toEqual(["3,410", "3,410", "5"]);
    expect(screen.queryAllByTestId("stat-delta")).toHaveLength(0);
    expect(screen.getByText(/Baseline results/)).toBeInTheDocument();
  });

  it("shows deltas against the baseline under a what-if run", async () => {
    mockApi({ [`GET /api/workbooks/${version.id}/outputs?run_id=${whatIfRun.id}`]: whatIfOutputs });
    render(<OutputsPage version={version} session={{ ...idle, activeRun: whatIfRun }} runId={whatIfRun.id} />);
    const deltas = await screen.findAllByTestId("stat-delta");
    expect(deltas.map((d) => d.textContent)).toEqual(["▲ 80.00 vs baseline", "▼ 1.00 vs baseline"]);
    expect(screen.getByText("unchanged")).toBeInTheDocument();
    expect(screen.getByText(/2 output cells changed/)).toBeInTheDocument();
  });

  it("draws a chart only when the sheet is a dated series", async () => {
    const withSeries: OutputsSummary = {
      ...outputs,
      sheets: [
        {
          ...outputs.sheets[0],
          sheet: "Daily",
          metrics: [],
          blocks: [],
          series: {
            x_label: "Date",
            x_type: "date",
            rows: 60,
            columns: [{ label: "Return", points: [["2025-01-01", 0], ["2025-01-02", 0.01], ["2025-01-03", 0.02]] }],
          },
        },
      ],
    };
    mockApi({ [`GET /api/workbooks/${version.id}/outputs?run_id=${baselineRun.id}`]: withSeries });
    render(<OutputsPage version={version} session={idle} runId={baselineRun.id} />);
    expect(await screen.findByText("Return over Date · 60 rows")).toBeInTheDocument();
  });
});
