import { useState } from "react";
import { getResearchMovement, researchExportUrl, type Mover } from "@/api/research";
import { Button, EmptyState, ExportMenu, Select } from "@/components";
import { formatCount } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { formatRankDelta } from "./format";
import type { ResearchActions } from "./types";
import { ConfidentialFooter, MoverRow, Narrative, Note, NotConfigured, PageHead, QuartilePill, RCard, Skeleton, StatCard } from "./ui";

export function MovementPage({ actions, footer }: { actions: ResearchActions; footer?: string | null }) {
  const [pair, setPair] = useState<{ from?: string; to?: string }>({});
  const data = useAsync(() => getResearchMovement(pair.from, pair.to), [pair.from, pair.to]);
  if (data.status === "error") return <EmptyState tone="error" title="Could not compute the movement" description={data.error} action={<Button onClick={data.reload}>Retry</Button>} />;
  if (!data.data) return <Skeleton rows={2} />;
  const m = data.data;
  if (!m.configured) return <NotConfigured problems={m.problems} onOpenAdmin={actions.openAdmin} />;
  const versions = m.versions ?? [];
  const fromId = m.from?.id ?? pair.from ?? "";
  const toId = m.to?.id ?? m.version_id ?? "";

  const selects = versions.length > 1 && (
    <>
      <label className="text-xs text-muted">
        From{" "}
        <Select aria-label="From version" value={fromId} onChange={(e) => setPair((p) => ({ ...p, from: e.target.value }))}>
          {versions.map((v) => (
            <option key={v.id} value={v.id}>
              {v.date ?? v.filename} · {v.filename}
            </option>
          ))}
        </Select>
      </label>
      <label className="text-xs text-muted">
        To{" "}
        <Select aria-label="To version" value={toId} onChange={(e) => setPair((p) => ({ ...p, to: e.target.value }))}>
          {versions.map((v) => (
            <option key={v.id} value={v.id}>
              {v.date ?? v.filename} · {v.filename}
            </option>
          ))}
        </Select>
      </label>
    </>
  );

  if (!m.available) {
    return (
      <div>
        <PageHead title="Movement" sub="Rank and quartile changes between two activated versions" actions={selects} />
        <EmptyState title="Nothing to compare yet" description={m.reason ?? "Activate a second version to see who moved."} action={<Button onClick={actions.openUpload}>Upload a version</Button>} />
      </div>
    );
  }
  const list = (rows: Mover[]) =>
    rows.map((r) => (
      <MoverRow
        key={r.key}
        name={r.label}
        context={[r.category, `${r.rankFrom} → ${r.rankTo}`, r.cause === "repair" ? "repaired row" : null].filter(Boolean).join(" · ")}
        right={<QuartilePill q={r.quartileTo} />}
        delta={formatRankDelta(r.delta)}
        onClick={() => actions.openFund(r.key)}
      />
    ));
  const qc = m.quartileChanges!;

  return (
    <div>
      <PageHead
        title="Movement"
        sub={`${m.to!.filename} · ${m.to!.date ?? ""} compared with ${m.from!.date ?? m.from!.filename}${m.same_month ? " (the same as-of date: a re-upload)" : ""}`}
        actions={
          <>
            {selects}
            <ExportMenu
              items={[
                { label: "Movers (csv)", url: researchExportUrl("movement", "csv", { from: fromId, to: toId }) },
                { label: "Movers (xlsx)", url: researchExportUrl("movement", "xlsx", { from: fromId, to: toId }) },
              ]}
            />
            <Button onClick={actions.openVersions}>Open version diff</Button>
          </>
        }
      />
      <div className="mb-[18px] grid gap-[18px] md:grid-cols-4">
        <StatCard label="Funds that moved" value={formatCount(m.moved!)} note={`of ${formatCount(m.rated!)} rated`} />
        <StatCard label="Moved up" value={<span className="text-positive">{formatCount(m.up!)}</span>} note={m.avg_up ? `avg ▲ ${m.avg_up} places` : undefined} />
        <StatCard label="Moved down" value={<span className="text-negative">{formatCount(m.down!)}</span>} note={m.avg_down ? `avg ▼ ${m.avg_down} places` : undefined} />
        <StatCard label="Quartile changes" value={formatCount(qc.total)} note={`${qc.into_q1} into Q1, ${qc.out_of_q1} out of Q1`} />
      </div>
      <Narrative text={m.narrative} className="mb-4" />
      {m.repairs && m.repairs.length > 0 && (
        <Note className="mb-[18px]">
          <b className="text-ink">
            {m.repairs.length === 1 ? "One of these moves is a data repair, not market change." : `${m.repairs.length} of these moves are data repairs, not market change.`}
          </b>{" "}
          {m.repairs.map((r) => `${r.label}${r.note ? ` (${r.note})` : ""}`).join("; ")}. Their movement is a correction.
        </Note>
      )}
      <div className="grid gap-[18px] md:grid-cols-2">
        <RCard title="Moved up" sub="Largest gains in composite rank">
          {m.risers!.length ? list(m.risers!.slice(0, 25)) : <p className="m-0 text-[13px] text-muted">No fund moved up.</p>}
        </RCard>
        <RCard title="Moved down" sub="Largest falls in composite rank">
          {m.fallers!.length ? list(m.fallers!.slice(0, 25)) : <p className="m-0 text-[13px] text-muted">No fund moved down.</p>}
        </RCard>
      </div>
      {(m.entries!.length > 0 || m.exits!.length > 0) && (
        <p className="m-0 mt-4 text-xs text-muted">
          {formatCount(m.entries!.length)} funds are new to the universe and {formatCount(m.exits!.length)} have left it.
        </p>
      )}
      <ConfidentialFooter text={footer} />
    </div>
  );
}
