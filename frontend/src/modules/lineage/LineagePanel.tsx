import { useState } from "react";
import { getLineage, type LineageNode, type LineageRange } from "@/api/lineage";
import { Button, EmptyState, Pill, SidePanel } from "@/components";
import { cn } from "@/lib/cn";
import { formatCell } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";

export interface LineageTarget {
  sheet: string;
  cell: string;
}

/**
 * "Explain this number": the formula at a cell, what the formula decided, its business rule, and the
 * values it consumed. Any consumed formula cell can be opened in place; a trail leads back.
 */
export function LineagePanel({
  versionId,
  runId,
  target,
  onClose,
}: {
  versionId: string;
  runId: string | null;
  target: LineageTarget | null;
  onClose: () => void;
}) {
  const [trail, setTrail] = useState<LineageTarget[]>([]);
  const current = trail.length > 0 ? trail[trail.length - 1] : target;
  const node = useAsync(
    () => (current ? getLineage(versionId, current.sheet, current.cell, { runId, depth: 1 }) : Promise.reject(new Error("none"))),
    [versionId, runId, current?.sheet, current?.cell],
  );

  const close = () => {
    setTrail([]);
    onClose();
  };
  const open = (sheet: string, cell: string) => setTrail((t) => [...t, { sheet, cell }]);
  const back = () => setTrail((t) => t.slice(0, -1));

  return (
    <SidePanel open={target !== null} onClose={close} title={current ? `${current.sheet}!${current.cell}` : "Lineage"} width="32rem">
      {trail.length > 0 && (
        <button type="button" onClick={back} className="mb-2 text-xs text-accent hover:underline">
          ← Back to {trail.length > 1 ? `${trail[trail.length - 2].sheet}!${trail[trail.length - 2].cell}` : target ? `${target.sheet}!${target.cell}` : "start"}
        </button>
      )}
      {node.status === "error" ? (
        <EmptyState tone="error" title="Could not explain this cell" description={node.error} action={<Button onClick={node.reload}>Retry</Button>} />
      ) : node.status === "loading" && !node.data ? (
        <div aria-busy="true" className="space-y-2">
          <div className="h-5 w-48 animate-pulse rounded-sm bg-surface-lifted" />
          <div className="h-16 animate-pulse rounded-sm bg-surface-lifted" />
        </div>
      ) : node.data ? (
        <NodeView node={node.data} onOpen={open} />
      ) : null}
    </SidePanel>
  );
}

function NodeView({ node, onOpen }: { node: LineageNode; onOpen: (sheet: string, cell: string) => void }) {
  const settings = useFormat();
  const value = formatCell(node.value ?? null, "general", settings, node.type);
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs text-muted">Value</div>
        <div className={cn("tabular font-heading text-2xl font-semibold", node.type === "error" ? "text-negative" : "text-ink")}>
          {value || <span className="text-muted">empty</span>}
        </div>
        <Pill className="mt-1" tone={node.kind === "formula" ? "accent" : "neutral"}>
          {node.kind === "formula" ? "computed" : node.kind === "input" ? "input" : node.kind === "external" ? "external input" : "static"}
        </Pill>
      </div>
      {node.formula && (
        <div>
          <div className="text-xs text-muted">Formula</div>
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded-sm border border-hairline bg-surface-lifted p-2 text-xs text-ink">
            {node.formula}
          </pre>
        </div>
      )}
      {node.explanation && node.explanation.length > 0 && (
        <div>
          <div className="text-xs text-muted">What the formula decided</div>
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-xs text-ink">
            {node.explanation.map((line, i) => (
              <li key={i} className={cn(i === node.explanation!.length - 1 && "font-medium")}>
                {line}
              </li>
            ))}
          </ol>
        </div>
      )}
      {node.rule && (
        <div>
          <div className="text-xs text-muted">Business rule</div>
          <div className="mt-1 text-xs text-ink">{node.rule}</div>
        </div>
      )}
      {node.reads && node.reads.length > 0 && (
        <div>
          <div className="text-xs text-muted">Consumed values</div>
          <ul className="mt-1 divide-y divide-hairline rounded-sm border border-hairline">
            {node.reads.map((r) => (
              <ReadRow key={`${r.sheet}!${r.range}`} read={r} onOpen={onOpen} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ReadRow({ read, onOpen }: { read: LineageRange; onOpen: (sheet: string, cell: string) => void }) {
  const settings = useFormat();
  const [expanded, setExpanded] = useState(false);
  const cells = read.cells ?? [];
  const single = read.count === 1 && cells.length === 1;
  const singleCell = single ? cells[0] : null;
  return (
    <li className="px-2 py-1 text-xs">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-ink">
          {read.sheet}!{read.range}
          {!single && <span className="ml-1 text-muted">{read.count} cells</span>}
        </span>
        {single ? (
          <button
            type="button"
            onClick={() => onOpen(read.sheet, singleCell!.address)}
            className="tabular text-accent hover:underline"
            aria-label={`Explain ${read.sheet}!${singleCell!.address}`}
          >
            {formatCell(singleCell!.value ?? null, "general", settings, singleCell!.type) || "empty"} →
          </button>
        ) : (
          <button type="button" onClick={() => setExpanded((e) => !e)} className="text-accent hover:underline">
            {expanded ? "Hide" : "Show"} values
          </button>
        )}
      </div>
      {!single && expanded && (
        <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 sm:grid-cols-3">
          {cells.map((c) => (
            <li key={c.address} className="flex justify-between gap-2">
              <button type="button" onClick={() => onOpen(read.sheet, c.address)} className="text-muted hover:text-accent">
                {c.address}
              </button>
              <span className="tabular text-ink">{formatCell(c.value ?? null, "general", settings, c.type) || "empty"}</span>
            </li>
          ))}
          {read.truncated && <li className="col-span-full text-muted">… {read.count - cells.length} more</li>}
        </ul>
      )}
    </li>
  );
}
