import { UploadPanel } from "@/modules/overview/UploadPanel";
import { ConfidentialFooter, PageHead, RCard } from "./ui";

const STEPS = [
  ["Read and interpret", "Sheets, formulas, dependencies, rules"],
  ["Recalculate and check against Excel", "Every formula cell reconciled"],
  ["Show what changed", "Data rows, logic edits, structure"],
  ["You activate it", "Or roll back to any earlier version"],
];

export function UploadPage({ onBusy, onDone, footer }: { onBusy: (busy: boolean, label?: string) => void; onDone: (versionId: string) => void; footer?: string | null }) {
  return (
    <div>
      <PageHead title="Upload version" sub="Drop a new master workbook — the system reads its logic, recalculates and shows you what changed" />
      <div className="grid gap-[18px] md:grid-cols-12">
        <div className="md:col-span-7">
          <UploadPanel onBusy={onBusy} onDone={onDone} />
          <p className="m-0 mt-[12px] text-xs text-muted">Close the workbook in Excel first, and upload a saved copy rather than the live file.</p>
        </div>
        <RCard className="md:col-span-5" title="What happens next" sub="Nothing goes live until you approve it">
          <ol className="m-0 list-none p-0">
            {STEPS.map(([title, sub], i) => (
              <li key={title} className="flex items-center gap-[11px] border-b border-hairline py-[10px] last:border-b-0">
                <span className="tabular min-w-[20px] font-heading text-sm font-semibold text-muted">{i + 1}</span>
                <div>
                  <div className="text-[13px] font-semibold text-ink">{title}</div>
                  <div className="text-[11.5px] text-muted">{sub}</div>
                </div>
              </li>
            ))}
          </ol>
        </RCard>
      </div>
      <ConfidentialFooter text={footer} />
    </div>
  );
}
