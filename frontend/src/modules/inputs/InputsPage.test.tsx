import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockApi } from "@/test/mockApi";
import { version } from "@/test/fixtures";
import { baselineRun, inputs, seriesGrid, whatIfRun } from "@/test/runFixtures";
import { OverridesBar } from "@/modules/runs/OverridesBar";
import { useRunSession } from "@/modules/runs/useRunSession";
import { InputsPage } from "./InputsPage";

afterEach(() => vi.restoreAllMocks());

function Harness() {
  const session = useRunSession(version.id, () => {});
  return (
    <>
      <InputsPage version={version} session={session} runId={session.activeRun?.id ?? baselineRun.id} />
      <OverridesBar session={session} />
    </>
  );
}

describe("InputsPage", () => {
  it("shows labelled parameter controls grouped by section and pages tables through the grid", async () => {
    mockApi({
      [`GET /api/workbooks/${version.id}/inputs`]: inputs,
      [`GET /api/runs/${baselineRun.id}/grid`]: seriesGrid,
    });
    render(<Harness />);
    expect(await screen.findByText("Assumptions")).toBeInTheDocument();
    expect(screen.getByLabelText("Threshold")).toHaveValue("0.75");
    expect(screen.getByLabelText("Units")).toHaveValue("120");
    expect(screen.getByLabelText("Start date")).toHaveValue("2026-01-31");
    expect(screen.getByLabelText("Active")).toHaveValue("true");
    expect(screen.queryByRole("region", { name: "Overrides" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Series/ }));
    expect(await screen.findByText("Sales", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("Cumulative")).toBeInTheDocument();
    expect(screen.getByLabelText("Series!B2")).toHaveValue("97");
  });

  it("accumulates edits into the draft bar and runs them", async () => {
    const calls = mockApi({
      [`GET /api/workbooks/${version.id}/inputs`]: inputs,
      [`GET /api/workbooks/${version.id}/inputs?run_id=${whatIfRun.id}`]: inputs,
      [`POST /api/workbooks/${version.id}/runs`]: whatIfRun,
    });
    render(<Harness />);
    const units = await screen.findByLabelText("Units");
    fireEvent.change(units, { target: { value: "200" } });
    fireEvent.blur(units);
    const bar = await screen.findByRole("region", { name: "Overrides" });
    expect(bar).toHaveTextContent("1 change");
    expect(screen.getByText("pending")).toBeInTheDocument();

    fireEvent.change(units, { target: { value: "abc" } });
    fireEvent.blur(units);
    expect(units).toHaveAttribute("aria-invalid", "true");
    expect(bar).toHaveTextContent("1 change"); // invalid text never reaches the draft

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect((calls.find((c) => c.method === "POST")?.body as { overrides: unknown }).overrides).toEqual({ "Inputs!B3": 200 });
    expect(await screen.findByText("what-if run")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to baseline" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Overrides" })).not.toBeInTheDocument());
  });

  it("shows a designed error state", async () => {
    mockApi({});
    render(<Harness />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no logic model yet");
  });
});
