import { render, screen } from "@testing-library/react";
import { HealthPage } from "./HealthPage";

const healthy = {
  status: "ok",
  service: "mf-analyser",
  version: "0.1.0",
  environment: "test",
  python: "3.12.14",
  database: "ok",
  time: "2026-09-10T10:00:00Z",
};

describe("HealthPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders backend details when the API responds", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(healthy), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    render(<HealthPage />);
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByTestId("health-python")).toHaveTextContent("3.12.14");
  });

  it("shows a designed error state when the API is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<HealthPage />);
    expect(await screen.findByText("Unreachable")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/could not reach the backend/i);
  });
});
