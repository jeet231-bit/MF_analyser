import { useState } from "react";
import { getResearchCategories, researchExportUrl } from "@/api/research";
import { Button, EmptyState, ExportMenu, Select } from "@/components";
import { formatCount } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import type { ResearchActions } from "./types";
import { ConfidentialFooter, LinkButton, Narrative, NotConfigured, PageHead, QuartileBar, Skeleton } from "./ui";

export function CategoriesPage({ actions, footer }: { actions: ResearchActions; footer?: string | null }) {
  const [measure, setMeasure] = useState<string | undefined>(undefined);
  const data = useAsync(() => getResearchCategories(measure), [measure]);
  if (data.status === "error") return <EmptyState tone="error" title="Could not load the categories" description={data.error} action={<Button onClick={data.reload}>Retry</Button>} />;
  if (!data.data) return <Skeleton rows={2} />;
  const body = data.data;
  if (!body.configured) return <NotConfigured problems={body.problems} onOpenAdmin={actions.openAdmin} />;
  const chosen = body.measures.find((m) => m.key === body.measure);

  return (
    <div>
      <PageHead
        title="Categories"
        sub={`${formatCount(body.rows.length)} categories · quartile spread and averages${body.statsOnly ? ` · ${body.statsOnly} keys in the averages table have no fund behind them and are not shown` : ""}`}
        actions={
          <>
            <Select aria-label="Average measure" value={body.measure ?? ""} onChange={(e) => setMeasure(e.target.value || undefined)}>
              {body.measures.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </Select>
            <ExportMenu
              items={[
                { label: "Categories (csv)", url: researchExportUrl("categories", "csv", { measure: body.measure ?? undefined }) },
                { label: "Categories (xlsx)", url: researchExportUrl("categories", "xlsx", { measure: body.measure ?? undefined }) },
              ]}
            />
          </>
        }
      />
      <Narrative text={body.narrative} className="mb-4" />
      <div className="grid gap-[18px] md:grid-cols-12">
        {body.rows.map((c) => (
          <article key={c.key} className="min-w-0 rounded-xl border border-hairline bg-surface px-5 py-[19px] md:col-span-3" aria-label={c.key}>
            <h3 className="m-0 font-heading text-[13.5px] font-semibold text-ink">{c.key}</h3>
            <p className="m-0 mt-0.5 text-xs text-muted">
              {formatCount(c.rated)} of {formatCount(c.count)} funds rated
            </p>
            <div className="mb-3 mt-3">
              <div className="text-[11.5px] font-medium text-muted">{chosen?.label ?? "Average"} average</div>
              <div className="tabular font-heading text-[23px] font-semibold tracking-[-0.02em] text-ink">{c.valueLabel || "—"}</div>
            </div>
            {c.unranked ? (
              <div className="mb-3 rounded-sm border border-hairline bg-surface-lifted px-[11px] py-[9px] text-[11.5px] text-muted">
                Fewer than {body.unrankedBelow} ranked funds — left unranked by the workbook rule
              </div>
            ) : (
              <QuartileBar counts={c.quartiles} height={22} className="mb-3" />
            )}
            <LinkButton onClick={() => actions.openFunds({ category: c.key })}>Open category →</LinkButton>
          </article>
        ))}
      </div>
      <ConfidentialFooter text={footer} />
    </div>
  );
}
