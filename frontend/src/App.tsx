import { useEffect, useState } from "react";
import { getConfig } from "@/api/config";
import { getModel } from "@/api/model";
import { listWorkbooks } from "@/api/workbooks";
import { Button, EmptyState, ProgressBar } from "@/components";
import { useAsync } from "@/lib/useAsync";
import { OverviewPage } from "@/modules/overview/OverviewPage";
import { UploadPanel } from "@/modules/overview/UploadPanel";
import { AppShell } from "@/modules/shell/AppShell";
import { Sidebar } from "@/modules/shell/Sidebar";
import { useTheme } from "@/theme";

export default function App() {
  const { theme, toggle } = useTheme();
  const config = useAsync(getConfig, []);
  const versions = useAsync(listWorkbooks, []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState<{ active: boolean; label?: string }>({ active: false });

  const versionList = versions.data ?? [];
  const effectiveId = selectedId && versionList.some((v) => v.id === selectedId) ? selectedId : (versionList[0]?.id ?? null);
  const version = versionList.find((v) => v.id === effectiveId) ?? null;

  const model = useAsync(
    () => (effectiveId ? getModel(effectiveId) : Promise.reject(new Error("no version"))),
    [effectiveId],
  );

  useEffect(() => {
    document.title = config.data?.display_name ? `${config.data.display_name} · MF Analyser` : "MF Analyser";
  }, [config.data?.display_name]);

  const onBusy = (active: boolean, label?: string) => setBusy({ active, label });
  const displayName = config.data?.display_name ?? null;

  const sidebar = (
    <div className="flex h-full flex-col">
      <Sidebar
        displayName={displayName}
        versions={versionList}
        selectedVersionId={effectiveId}
        onSelectVersion={setSelectedId}
        model={model.status === "ready" ? model.data : null}
        activeItem="overview"
        theme={theme}
        onToggleTheme={toggle}
      />
      {versionList.length > 0 && (
        <div className="border-t border-hairline px-3 py-2">
          <UploadPanel
            compact
            onBusy={onBusy}
            onDone={(id) => {
              setSelectedId(id);
              versions.reload();
            }}
          />
        </div>
      )}
    </div>
  );

  let content: React.ReactNode;
  if (versions.status === "error") {
    content = (
      <EmptyState
        tone="error"
        title="Could not reach the backend"
        description={versions.error}
        action={<Button onClick={versions.reload}>Retry</Button>}
      />
    );
  } else if (versions.status === "loading" && !versions.data) {
    content = (
      <div aria-busy="true" className="space-y-2">
        <div className="h-8 w-64 animate-pulse rounded-md bg-surface" />
        <div className="h-40 animate-pulse rounded-md border border-hairline bg-surface" />
      </div>
    );
  } else if (!version) {
    content = (
      <UploadPanel
        onBusy={onBusy}
        onDone={(id) => {
          setSelectedId(id);
          versions.reload();
        }}
      />
    );
  } else {
    content = (
      <OverviewPage
        displayName={displayName}
        version={version}
        model={model}
        onBusy={onBusy}
        onVersionChanged={versions.reload}
      />
    );
  }

  return (
    <>
      <ProgressBar active={busy.active} label={busy.label} />
      <AppShell sidebar={sidebar}>{content}</AppShell>
    </>
  );
}
