import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useAsync } from "@/lib/useAsync";
import type { LogicModel } from "@/api/workbooks";
import { getModel } from "@/api/model";
import { graph, model, rules, version } from "@/test/fixtures";
import { jsonError, mockApi } from "@/test/mockApi";
import { OverviewPage } from "./OverviewPage";

function Harness({ versionId = version.id }: { versionId?: string }) {
  const state = useAsync(() => getModel(versionId), [versionId]);
  return <OverviewPage displayName="Equity MF Analyser" version={version} model={state} onBusy={() => {}} onVersionChanged={() => {}} />;
}

const base = (m: LogicModel = model) => ({
  [`GET /api/workbooks/${version.id}/model`]: m,
  [`GET /api/workbooks/${version.id}/graph?level=sheet`]: graph,
  [`GET /api/workbooks/${version.id}/rules`]: rules,
});

afterEach(() => vi.restoreAllMocks());

describe("OverviewPage", () => {
  it("renders counts, the flow diagram, roles and grouped rules from the API", async () => {
    mockApi(base());
    render(<Harness />);
    expect(await screen.findByText("Formula templates")).toBeInTheDocument();
    const values = screen.getAllByTestId("stat-value").map((el) => el.textContent);
    expect(values).toEqual(["5", "17", "19", "4", "10"]);
    expect(await screen.findByRole("img", { name: /sheet dependency flow/i })).toBeInTheDocument();
    expect(screen.getByTestId("flow-node-Outputs")).toBeInTheDocument();
    expect(screen.getByLabelText("Role for Series")).toHaveValue("calculation");
    expect(await screen.findByText(/if B2<=120/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lookups 1/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText(/circular reference/)).not.toBeInTheDocument();
  });

  it("saves a role change through the override endpoint and reloads the model", async () => {
    let served = model;
    const calls = mockApi({
      ...base(),
      [`GET /api/workbooks/${version.id}/model`]: () => served,
      [`PATCH /api/workbooks/${version.id}/model/sheets/Series`]: () => {
        served = {
          ...model,
          sheets: model.sheets.map((s) => (s.name === "Series" ? { ...s, role: "output", role_source: "override" } : s)),
        };
        return served.sheets[3];
      },
    });
    render(<Harness />);
    const select = await screen.findByLabelText("Role for Series");
    fireEvent.change(select, { target: { value: "output" } });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.body).toEqual({ role: "output", reason: "set on the overview page" });
    await waitFor(() => expect(screen.getAllByText("you set this").length).toBeGreaterThan(0));
    expect(screen.getByLabelText("Role for Series")).toHaveValue("output");
  });

  it("surfaces cycles as a chip that expands to the explanation", async () => {
    mockApi(
      base({
        ...model,
        cycles: [[1, 2]],
        cycle_descriptions: ["2 blocks on Cyc form a reference cycle [Cyc!A1, Cyc!B1]: A1 reads B1 (hits B1); B1 reads A1 (hits A1)"],
        summary: { ...model.summary, cycles: 1 },
      }),
    );
    render(<Harness />);
    const chip = await screen.findByRole("button", { name: /1 circular reference/ });
    fireEvent.click(chip);
    expect(screen.getByText(/A1 reads B1/)).toBeInTheDocument();
    expect(screen.getByText(/engine will refuse/)).toBeInTheDocument();
  });

  it("offers interpretation when the version has no model yet", async () => {
    const calls = mockApi({
      [`GET /api/workbooks/${version.id}/model`]: jsonError(404, "No logic model for this version yet. POST /interpret first."),
      [`POST /api/workbooks/${version.id}/interpret`]: { version_id: version.id, scope: [], summary: model.summary, sheets: [], cycles: [], cycle_descriptions: [], unresolved: [] },
      [`GET /api/workbooks/${version.id}/graph?level=sheet`]: graph,
      [`GET /api/workbooks/${version.id}/rules`]: rules,
    });
    render(<Harness />);
    const button = await screen.findByRole("button", { name: "Interpret workbook" });
    fireEvent.click(button);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/interpret"))).toBe(true));
  });

  it("shows a designed error state when the model cannot load", async () => {
    mockApi({ [`GET /api/workbooks/${version.id}/model`]: jsonError(500, "boom") });
    render(<Harness />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Could not load the logic model")).toBeInTheDocument();
    expect(within(alert).getByText("boom")).toBeInTheDocument();
  });
});
