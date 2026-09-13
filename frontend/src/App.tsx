import { useCallback, useEffect, useMemo, useState } from "react";
import { getConfig } from "@/api/config";
import { getModel } from "@/api/model";
import { getResearchConfig, getResearchSummary, scopeParam } from "@/api/research";
import { listRuns } from "@/api/runs";
import { anomalyTotal, getValidation } from "@/api/validation";
import { listWorkbooks } from "@/api/workbooks";
import { Button, EmptyState, JobChip, ProgressBar } from "@/components";
import { DEFAULT_FORMAT } from "@/lib/format";
import { FormatContext } from "@/lib/FormatContext";
import { useAsync } from "@/lib/useAsync";
import { useAuth } from "@/modules/auth/useAuth";
import { CalculationsPage } from "@/modules/calculations/CalculationsPage";
import { InputsPage } from "@/modules/inputs/InputsPage";
import { OutputsPage } from "@/modules/outputs/OutputsPage";
import { OverviewPage } from "@/modules/overview/OverviewPage";
import { AdminPage } from "@/modules/research/AdminPage";
import { CategoriesPage } from "@/modules/research/CategoriesPage";
import { DashboardPage } from "@/modules/research/DashboardPage";
import { FundDetailPage } from "@/modules/research/FundDetailPage";
import { FundsPage } from "@/modules/research/FundsPage";
import { InsightsPage } from "@/modules/research/InsightsPage";
import { MovementPage } from "@/modules/research/MovementPage";
import { ScopeBar } from "@/modules/research/ScopeBar";
import type { ResearchActions } from "@/modules/research/types";
import { UploadPage } from "@/modules/research/UploadPage";
import { useScope } from "@/modules/research/useScope";
import { greeting, initials, useViewer } from "@/modules/research/useViewer";
import { OverridesBar } from "@/modules/runs/OverridesBar";
import { useRunSession } from "@/modules/runs/useRunSession";
import { AppShell } from "@/modules/shell/AppShell";
import { describeLocation, useAppHistory, type AppLocation } from "@/modules/shell/history";
import { isResearchPage, moduleSheets, readPinned, readView, validationPill, writePinned, writeView, type AppMode, type PageId } from "@/modules/shell/navigation";
import { Rail } from "@/modules/shell/Rail";
import { TopBar } from "@/modules/shell/TopBar";
import { ValidationPage } from "@/modules/validation/ValidationPage";
import { VersionsPage } from "@/modules/versions/VersionsPage";
import { useTheme } from "@/theme";

export default function App() {
  const { theme, toggle } = useTheme();
  const config = useAsync(getConfig, []);
  const versions = useAsync(listWorkbooks, []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const history = useAppHistory(readView);
  const view = history.location;
  const [pinned, setPinnedState] = useState(readPinned);
  const selectedFund = view.fund ?? null;
  const selectedSheet = view.sheet ?? null;
  const [busy, setBusy] = useState<{ active: boolean; label?: string }>({ active: false });
  const [researchTick, setResearchTick] = useState(0);
  const { scope, setScope, applied: scopeApplied } = useScope();
  const viewer = useViewer(config.data?.viewer_name);
  const auth = useAuth();

  const versionList = versions.data ?? [];
  const activeVersion = versionList.find((v) => v.status === "active") ?? null;
  const effectiveId =
    selectedId && versionList.some((v) => v.id === selectedId) ? selectedId : (activeVersion?.id ?? versionList[0]?.id ?? null);
  const version = versionList.find((v) => v.id === effectiveId) ?? null;

  const model = useAsync(
    () => (effectiveId ? getModel(effectiveId) : Promise.reject(new Error("no version"))),
    [effectiveId],
  );
  const validation = useAsync(
    () => (effectiveId ? getValidation(effectiveId) : Promise.reject(new Error("no version"))),
    [effectiveId],
  );
  const runs = useAsync(
    () => (effectiveId ? listRuns(effectiveId) : Promise.reject(new Error("no version"))),
    [effectiveId],
  );
  const summary = useAsync(() => getResearchSummary(undefined, scope), [researchTick, versionList.length, activeVersion?.id, scopeParam(scope)]);
  const researchConfig = useAsync(() => getResearchConfig(), [researchTick, activeVersion?.id]);

  useEffect(() => {
    document.title = config.data?.display_name ? `${config.data.display_name} · MF Analyser` : "MF Analyser";
  }, [config.data?.display_name]);
  useEffect(() => writeView({ mode: view.mode, page: view.page }), [view.mode, view.page]);

  const onBusy = useCallback((active: boolean, label?: string) => setBusy({ active, label }), []);
  const session = useRunSession(effectiveId, onBusy, runs.reload);
  const baselineId = useMemo(
    () => runs.data?.find((r) => r.kind === "full" && r.status === "ok" && Object.keys(r.overrides).length === 0)?.id ?? null,
    [runs.data],
  );
  const runId = session.activeRun?.id ?? baselineId;
  const formatSettings = useMemo(
    () =>
      config.data ? { grouping: config.data.number_grouping, decimals: config.data.number_decimals } : DEFAULT_FORMAT,
    [config.data],
  );
  const displayName = config.data?.display_name ?? null;
  const validationReport = validation.status === "ready" ? validation.data : null;
  const readyModel = model.status === "ready" ? model.data : null;
  const summaryData = summary.status === "ready" ? summary.data : null;
  const footer = summaryData?.configured ? summaryData.footer : null;

  const { navigate, back: goBackTo } = history;
  const go = useCallback(
    (page: PageId, sheet?: string) => {
      const mode: AppMode = isResearchPage(page) ? "research" : "workbook";
      const loc: AppLocation = { mode, page };
      if (sheet !== undefined) loc.sheet = sheet;
      navigate(loc);
    },
    [navigate],
  );
  const setMode = useCallback((mode: AppMode) => navigate({ mode, page: mode === "research" ? "dashboard" : "overview" }), [navigate]);
  const setPinned = useCallback((next: boolean) => {
    writePinned(next);
    setPinnedState(next);
  }, []);

  const refreshAll = useCallback(() => {
    versions.reload();
    validation.reload();
    runs.reload();
    setResearchTick((t) => t + 1);
  }, [versions, validation, runs]);

  const actions: ResearchActions = useMemo(
    () => ({
      openFund: (key) => navigate({ mode: "research", page: "fund", fund: key }),
      openFunds: (query) => navigate({ mode: "research", page: "funds", funds: query && Object.keys(query).length ? query : undefined }),
      goBack: () => goBackTo({ mode: "research", page: "funds" }),
      openCategories: () => go("categories"),
      openMovement: () => go("movement"),
      openInsights: () => go("insights"),
      openAdmin: () => go("admin"),
      openVersions: () => go("versions"),
      openUpload: () => go("upload"),
    }),
    [go, navigate, goBackTo],
  );

  const rail = (
    <Rail
      displayName={displayName}
      mode={view.mode}
      model={readyModel}
      activeItem={view.page}
      activeSheet={selectedSheet}
      onNavigate={go}
      anomalyCount={anomalyTotal(validationReport?.anomaly_counts)}
      summary={summaryData}
      insightCount={researchConfig.data?.configured ? researchConfig.data.insights?.length : undefined}
      openFindings={researchConfig.data?.findings?.filter((f) => f.status === "open").length ?? 0}
      pinned={pinned || view.mode === "workbook"}
      onPin={setPinned}
    />
  );
  const topBar = (
    <TopBar
      mode={view.mode}
      onMode={setMode}
      onSearch={(q) => actions.openFunds({ q })}
      version={view.mode === "research" ? (activeVersion ?? version) : version}
      validationLabel={validationReport ? validationPill[validationReport.status].label : null}
      theme={theme}
      onToggleTheme={toggle}
      viewerInitials={initials(viewer.name)}
      viewerName={viewer.name}
      onOpenProfile={() => go("admin")}
      onSignOut={auth.required ? () => void auth.signOut() : undefined}
    />
  );
  const scopeBar = (
    <ScopeBar
      scope={scope}
      description={summaryData?.configured ? summaryData.scope?.description : undefined}
      options={summaryData?.configured ? summaryData.scope_options : undefined}
      onApply={setScope}
    />
  );

  const versionsPanel = (
    <VersionsPage versions={versionList} selectedId={effectiveId} onBusy={onBusy} onVersionsChanged={refreshAll} />
  );
  const validationPanel = version ? (
    <ValidationPage version={version} report={validation} onBusy={onBusy} onVersionChanged={refreshAll} />
  ) : null;

  let content: React.ReactNode;
  const page = view.page;
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
  } else if (!version || page === "upload") {
    content = (
      <UploadPage
        onBusy={onBusy}
        onDone={(id) => {
          setSelectedId(id);
          refreshAll();
          go("admin");
        }}
        footer={footer}
      />
    );
  } else if (page === "dashboard") {
    content = (
      <DashboardPage
        summary={summary}
        scope={scope}
        scopeBar={scopeBar}
        greeting={greeting(viewer.name)}
        actions={actions}
        reload={() => setResearchTick((t) => t + 1)}
      />
    );
  } else if (page === "insights") {
    content = <InsightsPage actions={actions} runId={summaryData?.run_id ?? null} scope={scope} scopeBar={scopeBar} />;
  } else if (page === "funds") {
    content = <FundsPage actions={actions} query={view.funds} onQuery={(q) => history.replace({ funds: q })} footer={footer} scope={scope} scopeBar={scopeBar} />;
  } else if (page === "fund") {
    content = selectedFund ? (
      <FundDetailPage key={selectedFund} fundKey={selectedFund} actions={actions} footer={footer} backLabel={describeLocation(history.previous)} />
    ) : (
      <FundsPage actions={actions} query={view.funds} onQuery={(q) => history.replace({ funds: q })} footer={footer} scope={scope} scopeBar={scopeBar} />
    );
  } else if (page === "categories") {
    content = <CategoriesPage actions={actions} footer={footer} scope={scope} scopeBar={scopeBar} />;
  } else if (page === "movement") {
    content = <MovementPage actions={actions} footer={footer} scope={scope} scopeBar={scopeBar} />;
  } else if (page === "admin") {
    content = (
      <AdminPage
        summary={summaryData}
        versions={versionList}
        validation={validation}
        versionsPanel={versionsPanel}
        validationPanel={validationPanel}
        footer={footer}
        viewer={viewer}
        actions={actions}
      />
    );
  } else if (page === "versions") {
    content = versionsPanel;
  } else if (page === "validation") {
    content = validationPanel;
  } else if (page === "inputs") {
    content = <InputsPage version={version} session={session} runId={runId} />;
  } else if (page === "outputs") {
    content = <OutputsPage version={version} session={session} runId={runId} />;
  } else if (page === "sheet" && selectedSheet) {
    const role = readyModel?.sheets.find((s) => s.name === selectedSheet)?.role;
    content =
      role === "output" ? (
        <OutputsPage version={version} session={session} runId={runId} />
      ) : readyModel ? (
        <CalculationsPage version={version} model={readyModel} sheets={[selectedSheet]} title={selectedSheet} session={session} runId={runId} />
      ) : (
        <EmptyState title="Loading the logic model" />
      );
  } else if (page === "calculations" || page === "analysis") {
    content = readyModel ? (
      <CalculationsPage
        version={version}
        model={readyModel}
        sheets={moduleSheets(readyModel, page)}
        title={page === "analysis" ? "Analysis" : "Calculations"}
        session={session}
        runId={runId}
      />
    ) : (
      <EmptyState title="Loading the logic model" />
    );
  } else {
    content = (
      <OverviewPage
        displayName={displayName}
        version={version}
        model={model}
        onBusy={onBusy}
        onVersionChanged={refreshAll}
      />
    );
  }

  return (
    <FormatContext.Provider value={formatSettings}>
      <ProgressBar active={busy.active} label={busy.label} />
      <AppShell rail={rail} topBar={topBar} pinned={pinned || view.mode === "workbook"}>
        {session.job && (
          <div className="mb-3">
            <JobChip job={session.job} onDismiss={session.dismissJob} />
          </div>
        )}
        {scopeApplied && view.mode === "workbook" && (
          <p className="mb-3 text-xs text-muted">A research scope is set; workbook pages show every sheet as the master computes it.</p>
        )}
        {content}
      </AppShell>
      {version && view.mode === "workbook" && <OverridesBar session={session} />}
    </FormatContext.Provider>
  );
}
