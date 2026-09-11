import { useState } from "react";
import { diffExportUrl } from "@/api/exports";
import { getDiff } from "@/api/versions";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button, Card, DataTable, EmptyState, ExportMenu, Pill, Select, type Column, type PillTone } from "@/components";
import { formatBytes, formatTimestamp } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { validationPill } from "@/modules/shell/navigation";
import { ActivateControl } from "./ActivateControl";
import { DiffView } from "./DiffView";

const statusTone: Record<string, PillTone> = {
  uploaded: "neutral",
  interpreted: "accent",
  validated: "positive",
  active: "positive",
  pending_review: "warning",
};

export interface VersionsPageProps {
  versions: WorkbookVersion[];
  selectedId: string | null;
  onBusy: (busy: boolean, label?: string) => void;
  onVersionsChanged: () => void;
}

export function VersionsPage({ versions, selectedId, onBusy, onVersionsChanged }: VersionsPageProps) {
  const active = versions.find((v) => v.status === "active") ?? null;
  const [baseId, setBaseId] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const base = baseId ?? active?.id ?? null;
  const target =
    targetId ?? (selectedId && selectedId !== base ? selectedId : (versions.find((v) => v.id !== base)?.id ?? null));

  const diff = useAsync(
    () => (base && target && base !== target ? getDiff(base, target) : Promise.reject(new Error("pick two versions"))),
    [base, target],
  );

  const name = (id: string | null) => {
    const v = versions.find((x) => x.id === id);
    return v ? `${v.filename} (${formatTimestamp(v.uploaded_at)})` : "—";
  };

  const columns: Column<WorkbookVersion>[] = [
    {
      key: "filename",
      header: "Version",
      render: (v) => (
        <div>
          <div className="font-medium text-ink">{v.filename}</div>
          <div className="text-xs text-muted">
            {formatTimestamp(v.uploaded_at)} · {formatBytes(v.size_bytes)}
          </div>
        </div>
      ),
    },
    { key: "status", header: "Status", render: (v) => <Pill tone={statusTone[v.status] ?? "neutral"}>{v.status.replace("_", " ")}</Pill> },
    {
      key: "validation",
      header: "Validation",
      render: (v) =>
        v.validation_status ? (
          <Pill tone={validationPill[v.validation_status].tone}>{validationPill[v.validation_status].label}</Pill>
        ) : (
          <Pill tone="neutral">not validated</Pill>
        ),
    },
    { key: "diff", header: "Vs active at upload", render: (v) => <span className="text-xs text-muted">{v.diff_headline ?? "—"}</span> },
    {
      key: "actions",
      header: "",
      render: (v) => (
        <div className="flex flex-wrap items-center gap-1">
          <ActivateControl version={v} activeId={active?.id ?? null} activeUploadedAt={active?.uploaded_at ?? null} onBusy={onBusy} onDone={onVersionsChanged} />
          <Button size="sm" variant="ghost" onClick={() => setTargetId(v.id)} disabled={v.id === base} aria-label={`Compare ${v.filename}`}>
            Compare
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-ink">Versions</h1>
        <p className="mt-0.5 text-sm text-muted">
          Every upload is an immutable version. Activation goes through the validation gate; rollback is re-activating an older version.
        </p>
      </header>

      <Card title="All versions">
        {versions.length === 0 ? (
          <EmptyState title="No versions yet" description="Upload a copy of the master workbook to create the first version." />
        ) : (
          <DataTable columns={columns} rows={versions} rowKey={(v) => v.id} dense />
        )}
      </Card>

      <Card
        title="Changes between versions"
        action={
          <div className="flex items-center gap-1 text-xs">
            <Select aria-label="Base version" value={base ?? ""} onChange={(e) => setBaseId(e.target.value)}>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.filename}
                  {v.status === "active" ? " (active)" : ""}
                </option>
              ))}
            </Select>
            <span className="text-muted">→</span>
            <Select aria-label="Target version" value={target ?? ""} onChange={(e) => setTargetId(e.target.value)}>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.filename}
                  {v.status === "pending_review" ? " (pending review)" : ""}
                </option>
              ))}
            </Select>
            {base && target && base !== target && (
              <ExportMenu
                items={[
                  { label: "CSV changelog", hint: "One row per change", url: diffExportUrl(base, target, "csv") },
                  { label: "Excel changelog", hint: "Cover sheet + changes", url: diffExportUrl(base, target, "xlsx") },
                ]}
              />
            )}
          </div>
        }
      >
        {(!base || !target || base === target) && (
          <EmptyState title="Pick two different versions" description="The changelog reads from the base version to the target version." />
        )}
        {base && target && base !== target && diff.status === "loading" && !diff.data && (
          <div aria-busy="true" className="h-40 animate-pulse rounded-md bg-surface-lifted" />
        )}
        {base && target && base !== target && diff.status === "error" && (
          <EmptyState tone="error" title="Could not compute the diff" description={diff.error} action={<Button onClick={diff.reload}>Retry</Button>} />
        )}
        {base && target && base !== target && diff.data && <DiffView report={diff.data} baseLabel={name(base)} targetLabel={name(target)} />}
      </Card>
    </div>
  );
}
