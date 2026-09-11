import { graph } from "@/test/fixtures";
import { layoutByDepth, NODE_W } from "./layout";

describe("layoutByDepth", () => {
  it("places deeper sheets further right and keeps columns vertically centred", () => {
    const layout = layoutByDepth(graph.nodes, graph.edges);
    const x = Object.fromEntries(layout.nodes.map((n) => [n.id, n.x]));
    expect(x.Inputs).toBe(x.Lookup);
    expect(x.Calc).toBeGreaterThan(x.Inputs);
    expect(x.Outputs).toBeGreaterThan(x.Calc);
    expect(x.Calc - x.Inputs).toBeGreaterThanOrEqual(NODE_W);
    const outputs = layout.nodes.find((n) => n.id === "Outputs")!;
    const inputs = layout.nodes.find((n) => n.id === "Inputs")!;
    expect(outputs.y).toBeGreaterThan(inputs.y); // single node is centred below the top of a 2-node column
    expect(layout.width).toBeGreaterThan(3 * NODE_W);
  });

  it("orders nodes within a column by role then name and draws every edge", () => {
    const layout = layoutByDepth(graph.nodes, graph.edges);
    const depth1 = layout.nodes.filter((n) => n.depth === 1).sort((a, b) => a.y - b.y).map((n) => n.id);
    expect(depth1).toEqual(["Series", "Calc"]); // calculation before output
    expect(layout.edges).toHaveLength(graph.edges.length);
    expect(layout.edges[0].path).toMatch(/^M \d+(\.\d+)? \d+(\.\d+)? C /);
    const widths = layout.edges.map((e) => e.strokeWidth);
    expect(Math.max(...widths)).toBeGreaterThan(Math.min(...widths));
  });

  it("handles an empty graph", () => {
    const layout = layoutByDepth([], []);
    expect(layout.nodes).toEqual([]);
    expect(layout.edges).toEqual([]);
  });
});
