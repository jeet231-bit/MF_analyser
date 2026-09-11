import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { diffExportUrl, exportPolling, runExportUrl } from "@/api/exports";
import { ExportMenu } from "./ExportMenu";

afterEach(() => vi.restoreAllMocks());

function mockFetch(handler: (url: string) => Response | Promise<Response>) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push(url);
    return handler(url);
  });
  return calls;
}

describe("export urls", () => {
  it("build the run and changelog export endpoints", () => {
    expect(runExportUrl("r1", "csv", { sheet: "Series", window: "A2:G4" })).toBe("/api/runs/r1/export?format=csv&sheet=Series&window=A2%3AG4");
    expect(runExportUrl("r1", "xlsx", { scope: "all", formulas: true })).toBe("/api/runs/r1/export?format=xlsx&scope=all&formulas=true");
    expect(diffExportUrl("a", "b", "xlsx")).toBe("/api/workbooks/a/diff/b/export?format=xlsx");
  });
});

describe("ExportMenu", () => {
  it("downloads a synchronous export and names the file from the response", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const calls = mockFetch(
      () =>
        new Response("a,b\n1,2\n", {
          status: 200,
          headers: { "Content-Type": "text/csv", "Content-Disposition": "attachment; filename*=UTF-8''table-r1.csv" },
        }),
    );
    render(<ExportMenu items={[{ label: "CSV — this window", url: "/api/runs/r1/export?format=csv&sheet=Series" }]} />);
    fireEvent.click(screen.getByRole("button", { name: /Export/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /CSV/ }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(calls).toEqual(["/api/runs/r1/export?format=csv&sheet=Series"]);
    expect(await screen.findByRole("status")).toHaveTextContent("Download started");
  });

  it("polls a background job and then downloads its file", async () => {
    exportPolling.ms = 5;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    let polls = 0;
    const calls = mockFetch((url) => {
      if (url.includes("/runs/")) {
        return new Response(JSON.stringify({ id: "job1", run_id: "r1", format: "xlsx", status: "running", error: null, filename: null, created_at: "", finished_at: null }), { status: 202 });
      }
      polls += 1;
      const status = polls < 2 ? "running" : "ok";
      return new Response(JSON.stringify({ id: "job1", run_id: "r1", format: "xlsx", status, error: null, filename: "all.xlsx", created_at: "", finished_at: null }), { status: 200 });
    });
    render(<ExportMenu items={[{ label: "Excel — all sheets", url: "/api/runs/r1/export?format=xlsx&scope=all" }]} />);
    fireEvent.click(screen.getByRole("button", { name: /Export/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Excel/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("background");
    await waitFor(() => expect(click).toHaveBeenCalled());
    exportPolling.ms = 1000;
    expect(calls.filter((u) => u.includes("/api/exports/job1")).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("status")).toHaveTextContent("Download started");
  });

  it("shows the server's message when an export is refused", async () => {
    mockFetch(() => new Response(JSON.stringify({ detail: "PDF export needs WeasyPrint" }), { status: 501 }));
    render(<ExportMenu items={[{ label: "PDF report", url: "/api/runs/r1/export?format=pdf" }]} />);
    fireEvent.click(screen.getByRole("button", { name: /Export/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /PDF/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("PDF export needs WeasyPrint");
  });
});
