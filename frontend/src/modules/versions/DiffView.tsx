import { LOGIC_LABELS, STRUCTURAL_LABELS, type DiffReport, type LogicChange } from "@/api/versions";
import { Card, EmptyState, Pill, StatTile, type PillTone } from "@/components";
import { formatCount } from "@/lib/format";

const logicTone: Record<string, PillTone> = {
  template_added: "accent",
  template_removed: "negative",
  template_changed: "warning",
  rule_added: "accent",
  rule_removed: "negative",
  name_added: "accent",
  name_removed: "negative",
  name_changed: "warning",
};

const structuralTone: Record<string, PillTone> = {
  anomaly_new: "negative",
  anomaly_resolved: "positive",
  sheet_removed: "negative",
  sheet_added: "accent",
  sheet_renamed: "warning",
  role_changed: "warning",
  blocks_merged: "neutral",
  blocks_split: "neutral",
};

/** A DiffReport as a readable changelog: logic first, then data, then structural. */
export function DiffView({ report, baseLabel, targetLabel }: { report: DiffReport; baseLabel: string; targetLabel: string }) {
  const s = report.summary;
  return (
    <div className="space-y-4">
      <div>
        <p className="font-heading text-base font-semibold text-ink">{report.headline}</p>
        <p className="text-xs text-muted">
          {baseLabel} → {targetLabel}
        </p>
      </div>
      <section className="grid grid-cols-2 gap-2 md:grid-cols-4" aria-label="Diff summary">
        <StatTile label="Logic changes" value={formatCount(s.logic_changes)} hint={`${formatCount(s.logic_cells)} cells`} />
        <StatTile label="Data changes" value={formatCount(s.data_changes)} hint="counts, not itemised" />
        <StatTile label="Structural changes" value={formatCount(s.structural_changes)} />
        <StatTile
          label="Outputs affected"
          value={`${formatCount(s.outputs_affected_by_logic)} / ${formatCount(s.outputs_total)}`}
          hint={`by logic · ${formatCount(s.outputs_affected_by_data)} by data`}
        />
      </section>

      <Card title="Logic changes">
        {report.logic.length === 0 ? (
          <EmptyState title="No logic changes" description="Every formula pattern, rule and named range is the same in both versions." />
        ) : (
          <ul className="divide-y divide-hairline">
            {report.logic.map((c) => (
              <LogicEntry key={c.id} change={c} />
            ))}
          </ul>
        )}
      </Card>

      <Card title="Data changes">
        {report.data.length === 0 ? (
          <EmptyState title="No data changes" description="No rows were added or removed and no input values changed." />
        ) : (
          <ul className="space-y-1 text-sm">
            {report.data.map((d) => (
              <li key={d.id} className="flex items-baseline gap-2">
                <Pill tone="neutral" dot={false}>
                  {d.kind.replace("_", " ")}
                </Pill>
                <span className="text-ink">{d.description}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Structural changes">
        {report.structural.length === 0 ? (
          <EmptyState title="No structural changes" description="Same sheets, same roles, same block layout, no anomaly changes." />
        ) : (
          <ul className="space-y-1 text-sm">
            {report.structural.map((c) => (
              <li key={c.id} className="flex items-baseline gap-2">
                <Pill tone={structuralTone[c.kind] ?? "neutral"} dot={false}>
                  {STRUCTURAL_LABELS[c.kind]}
                </Pill>
                <span className="text-ink">{c.description}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function LogicEntry({ change }: { change: LogicChange }) {
  const oldFormula = change.detail.old_formula as string | undefined;
  const newFormula = change.detail.new_formula as string | undefined;
  return (
    <li className="py-2">
      <details>
        <summary className="cursor-pointer select-none">
          <span className="inline-flex flex-wrap items-baseline gap-2">
            <Pill tone={logicTone[change.kind] ?? "neutral"} dot={false}>
              {LOGIC_LABELS[change.kind]}
            </Pill>
            <span className="font-heading text-sm font-medium text-ink">{change.title}</span>
            {change.affected_output_count > 0 && (
              <span className="tabular text-xs text-muted">{change.affected_output_count} output(s) affected</span>
            )}
          </span>
        </summary>
        <div className="mt-1 space-y-1 pl-1 text-sm">
          <p className="text-ink">{change.description}</p>
          {(oldFormula || newFormula) && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
              {oldFormula && (
                <>
                  <dt className="text-muted">before</dt>
                  <dd className="tabular break-all text-ink">{oldFormula}</dd>
                </>
              )}
              {newFormula && (
                <>
                  <dt className="text-muted">after</dt>
                  <dd className="tabular break-all text-ink">{newFormula}</dd>
                </>
              )}
            </dl>
          )}
          {change.affected_outputs.length > 0 && (
            <div>
              <p className="text-xs text-muted">Affected outputs</p>
              <ul className="tabular text-xs text-ink">
                {change.affected_outputs.map((o) => (
                  <li key={o.block_id}>
                    {o.sheet}!{o.range}
                    {o.label ? ` · ${o.label}` : ""} · {formatCount(o.cells)} cells
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </details>
    </li>
  );
}
