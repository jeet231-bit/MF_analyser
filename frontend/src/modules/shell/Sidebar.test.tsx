import { fireEvent, render, screen } from "@testing-library/react";
import { model, version } from "@/test/fixtures";
import { buildNavigation } from "./navigation";
import { Sidebar } from "./Sidebar";

describe("navigation", () => {
  it("derives module entries from sheet roles; every module is a live page", () => {
    const nav = buildNavigation(model, 3);
    expect(nav.map((n) => n.label)).toEqual(["Overview", "Inputs", "Calculations", "Outputs", "Versions", "Validation"]);
    expect(nav.find((n) => n.id === "inputs")?.sheets).toEqual(["Inputs", "Lookup"]);
    expect(nav.filter((n) => n.enabled).map((n) => n.id)).toEqual(["overview", "inputs", "calculations", "outputs", "versions", "validation"]);
    expect(nav.find((n) => n.id === "validation")?.badge).toBe(3);
    expect(buildNavigation(null).map((n) => n.label)).toEqual(["Overview", "Versions", "Validation"]);
    expect(buildNavigation(null, 0).find((n) => n.id === "validation")?.badge).toBeUndefined();
  });
});

function renderSidebar(overrides: Partial<React.ComponentProps<typeof Sidebar>> = {}) {
  const onNavigate = vi.fn();
  render(
    <Sidebar
      displayName="Equity MF Analyser"
      versions={[version]}
      selectedVersionId={version.id}
      onSelectVersion={() => {}}
      model={model}
      activeItem="overview"
      onNavigate={onNavigate}
      validationStatus={null}
      anomalyCount={0}
      theme="light"
      onToggleTheme={() => {}}
      {...overrides}
    />,
  );
  return onNavigate;
}

describe("Sidebar", () => {
  it("renders the workbook name, version badge, module entries and a neutral validation pill", () => {
    renderSidebar();
    expect(screen.getByText("Equity MF Analyser")).toBeInTheDocument();
    expect(screen.getByLabelText("Version")).toHaveValue(version.id);
    expect(screen.getByText("interpreted")).toBeInTheDocument();
    const outputs = screen.getByRole("button", { name: /Outputs/ });
    expect(outputs).toBeEnabled();
    expect(outputs).toHaveTextContent("2");
    expect(screen.getByRole("button", { name: /Overview/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("not yet validated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dark theme" })).toBeInTheDocument();
  });

  it("enables Validation with an anomaly badge and reflects the validation status", () => {
    const onNavigate = renderSidebar({ validationStatus: "passed_with_warnings", anomalyCount: 2 });
    const validation = screen.getByRole("button", { name: /Validation/ });
    expect(validation).toBeEnabled();
    expect(screen.getByLabelText("2 anomalies")).toHaveTextContent("2");
    fireEvent.click(validation);
    expect(onNavigate).toHaveBeenCalledWith("validation");
    expect(screen.getByText("passed with warnings")).toBeInTheDocument();
  });
});
