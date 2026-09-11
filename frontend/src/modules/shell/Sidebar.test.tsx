import { render, screen } from "@testing-library/react";
import { model, version } from "@/test/fixtures";
import { buildNavigation, ENGINE_NOTE } from "./navigation";
import { Sidebar } from "./Sidebar";

describe("navigation", () => {
  it("derives module entries from sheet roles and keeps them disabled", () => {
    const nav = buildNavigation(model);
    expect(nav.map((n) => n.label)).toEqual(["Overview", "Inputs", "Calculations", "Outputs", "Versions", "Validation"]);
    expect(nav.find((n) => n.id === "inputs")?.sheets).toEqual(["Inputs", "Lookup"]);
    expect(nav.filter((n) => n.enabled).map((n) => n.id)).toEqual(["overview"]);
    expect(buildNavigation(null).map((n) => n.label)).toEqual(["Overview", "Versions", "Validation"]);
  });
});

describe("Sidebar", () => {
  it("renders the workbook name, version badge, disabled modules and a neutral validation pill", () => {
    render(
      <Sidebar
        displayName="Equity MF Analyser"
        versions={[version]}
        selectedVersionId={version.id}
        onSelectVersion={() => {}}
        model={model}
        activeItem="overview"
        theme="light"
        onToggleTheme={() => {}}
      />,
    );
    expect(screen.getByText("Equity MF Analyser")).toBeInTheDocument();
    expect(screen.getByLabelText("Version")).toHaveValue(version.id);
    expect(screen.getByText("interpreted")).toBeInTheDocument();
    const outputs = screen.getByRole("button", { name: /Outputs/ });
    expect(outputs).toBeDisabled();
    expect(outputs).toHaveTextContent(ENGINE_NOTE);
    expect(screen.getByRole("button", { name: /Overview/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("not yet validated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dark theme" })).toBeInTheDocument();
  });
});
