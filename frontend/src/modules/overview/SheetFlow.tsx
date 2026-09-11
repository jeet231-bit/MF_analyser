import { useMemo } from "react";
import type { GraphResponse } from "@/api/model";
import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import { layoutByDepth } from "./layout";

/** Role → fill/stroke classes. Palette only: no semantic colours for roles. */
const roleStyle: Record<string, { rect: string; text: string }> = {
  input: { rect: "fill-surface stroke-hairline", text: "fill-ink" },
  reference: { rect: "fill-surface-lifted stroke-hairline", text: "fill-ink" },
  transformation: { rect: "fill-accent-soft stroke-accent/40", text: "fill-ink" },
  calculation: { rect: "fill-accent-soft stroke-hairline", text: "fill-ink" },
  output: { rect: "fill-ink stroke-ink", text: "fill-ground" },
  external: { rect: "fill-ground stroke-hairline", text: "fill-muted" },
};

const LEGEND = ["input", "reference", "transformation", "calculation", "output"];

export function SheetFlow({ graph, selected, onSelect }: { graph: GraphResponse; selected?: string | null; onSelect?: (id: string) => void }) {
  const layout = useMemo(() => layoutByDepth(graph.nodes, graph.edges), [graph]);
  if (graph.nodes.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <svg
          role="img"
          aria-label="Sheet dependency flow, left to right"
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width={layout.width}
          height={layout.height}
          className="block max-w-none font-heading"
        >
          <defs>
            <marker id="flow-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 8 4 L 0 8 z" className="fill-muted" />
            </marker>
          </defs>
          {layout.edges.map((e) => (
            <path
              key={`${e.source}->${e.target}`}
              d={e.path}
              fill="none"
              strokeWidth={e.strokeWidth}
              markerEnd="url(#flow-arrow)"
              className={cn(
                "stroke-hairline",
                selected && (e.source === selected || e.target === selected) && "stroke-accent",
              )}
            >
              <title>
                {e.source} → {e.target}: {formatCount(e.weight)} block dependencies
              </title>
            </path>
          ))}
          {layout.nodes.map((n) => {
            const style = roleStyle[n.kind] ?? roleStyle.input;
            const formulas = Number(n.data.formula_cells ?? 0);
            const inputs = Number(n.data.input_cells ?? 0);
            const isSelected = selected === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x}, ${n.y})`}
                onClick={onSelect ? () => onSelect(n.id) : undefined}
                className={onSelect ? "cursor-pointer" : undefined}
                data-testid={`flow-node-${n.id}`}
              >
                <rect
                  width={n.w}
                  height={n.h}
                  rx={10}
                  strokeWidth={isSelected ? 2 : 1}
                  className={cn(style.rect, isSelected && "stroke-accent")}
                />
                <text x={12} y={18} className={cn("text-[12px] font-medium", style.text)}>
                  {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                </text>
                <text x={12} y={34} className={cn("tabular text-[10px]", n.kind === "output" ? "fill-ground/80" : "fill-muted")}>
                  {formulas > 0 ? `${formatCount(formulas)} formulas` : `${formatCount(inputs)} inputs`}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="flex flex-wrap gap-3 text-[11px] text-muted">
        {LEGEND.map((role) => (
          <span key={role} className="inline-flex items-center gap-1">
            <svg width="14" height="10" aria-hidden>
              <rect width="14" height="10" rx="3" className={roleStyle[role].rect} />
            </svg>
            {role}
          </span>
        ))}
        <span className="ml-auto">Arrows point from the sheet that is read to the sheet that reads it.</span>
      </div>
    </div>
  );
}
