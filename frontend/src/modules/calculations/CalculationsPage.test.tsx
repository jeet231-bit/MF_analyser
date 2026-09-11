import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "@/test/mockApi";
import { model, version } from "@/test/fixtures";
import { baselineRun, lineage, seriesGrid } from "@/test/runFixtures";
import { useRunSession } from "@/modules/runs/useRunSession";
import { CalculationsPage } from "./CalculationsPage";

afterEach(() => vi.restoreAllMocks());

function Harness({ runId = baselineRun.id }: { runId?: string | null }) {
  const session = useRunSession(version.id, () => {});
  return <CalculationsPage version={version} model={model} sheets={["Series"]} title="Calculations" session={session} runId={runId} />;
}

describe("CalculationsPage", () => {
  it("mirrors the sheet and opens the lineage panel from a computed cell", async () => {
    const calls = mockApi({
      [`GET /api/runs/${baselineRun.id}/grid`]: seriesGrid,
      [`GET /api/workbooks/${version.id}/lineage/Series!D4`]: { ...lineage, cell: "D4" },
    });
    render(<Harness />);
    expect(await screen.findByText("Cumulative")).toBeInTheDocument();
    expect(screen.getByText(/rows 2–4 of 21/)).toBeInTheDocument();
    // A baseline delta shows next to the changed value.
    expect(screen.getByText("+12")).toBeInTheDocument();

    const cells = screen.getAllByTitle("D4 · formula");
    fireEvent.click(cells[0]);
    const panel = await screen.findByRole("dialog", { name: "Series!D4" });
    await waitFor(() => expect(panel).toHaveTextContent('=IF(B6<=120,"Low",IF(B6<=200,"Mid","High"))'));
    expect(panel).toHaveTextContent("125 <= 200 is TRUE");
    expect(panel).toHaveTextContent("Business rule");
    expect(calls.some((c) => c.url.includes("/lineage/Series!D4"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Explain Series!B6" }));
    expect(await screen.findByRole("dialog", { name: "Series!B6" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Back to Series!D4/ }));
    expect(await screen.findByRole("dialog", { name: "Series!D4" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("pages the window", async () => {
    const calls = mockApi({ [`GET /api/runs/${baselineRun.id}/grid`]: seriesGrid });
    render(<Harness />);
    await screen.findByText("Cumulative");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(calls.at(-1)?.url).toContain("r1=5");
    expect(calls.at(-1)?.url).toContain("r2=7");
  });

  it("explains that a baseline run is needed first", () => {
    mockApi({});
    render(<Harness runId={null} />);
    expect(screen.getByText("No baseline run yet")).toBeInTheDocument();
  });
});
