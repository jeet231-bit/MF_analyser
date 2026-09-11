import { render, screen } from "@testing-library/react";
import { DataTable, type Column } from "./DataTable";
import { StatTile } from "./StatTile";

describe("StatTile", () => {
  it("renders the value and a directional delta", () => {
    render(<StatTile label="Score" value="0.84" delta={{ value: -0.02, direction: "down", label: "vs baseline" }} />);
    expect(screen.getByText("Score")).toBeInTheDocument();
    expect(screen.getByTestId("stat-value")).toHaveTextContent("0.84");
    expect(screen.getByTestId("stat-delta")).toHaveTextContent("▼ 0.02 vs baseline");
    expect(screen.getByTestId("stat-delta").className).toContain("text-negative");
  });
});

describe("DataTable", () => {
  const rows = [
    { id: "a", name: "Alpha", amount: 1234567.891 },
    { id: "b", name: "Beta", amount: null },
  ];
  const columns: Column<(typeof rows)[number]>[] = [
    { key: "name", header: "Name" },
    { key: "amount", header: "Amount", numeric: true, decimals: 2 },
  ];

  it("formats numeric columns with Indian grouping and right alignment", () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    const cell = screen.getByText("12,34,567.89");
    expect(cell.className).toContain("text-right");
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("supports international grouping and an empty message", () => {
    render(<DataTable columns={columns} rows={[rows[0]]} rowKey={(r) => r.id} grouping="international" />);
    expect(screen.getByText("1,234,567.89")).toBeInTheDocument();
    render(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} emptyMessage="Empty here" />);
    expect(screen.getByText("Empty here")).toBeInTheDocument();
  });
});
