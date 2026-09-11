import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { createRun, getRun, type CellValue, type RunOut } from "@/api/runs";
import { describeError } from "@/lib/useAsync";

export interface DraftEntry {
  value: CellValue;
  type: string;
  label: string | null;
  sheet: string;
  address: string;
}

export interface RunSession {
  /** Edits not yet run, keyed "Sheet!A1". */
  draft: Map<string, DraftEntry>;
  setDraft: (ref: string, entry: DraftEntry | null) => void;
  resetDraft: () => void;
  /** The what-if run whose values every view shows; null means the baseline. */
  activeRun: RunOut | null;
  /** Background full run in flight (or its terminal state until dismissed). */
  job: RunOut | null;
  error: string | null;
  running: boolean;
  /** Set while the backend reports another run in progress and this one waits its turn. */
  waiting: string | null;
  runAnalysis: () => Promise<void>;
  runFull: () => Promise<void>;
  backToBaseline: () => void;
  dismissJob: () => void;
}

const POLL_MS = 1000;
/** How long to keep retrying when the backend says another run is in progress. */
export const busyRetry = { maxAttempts: 40, fallbackDelayMs: 3000 };

function busyDelay(err: unknown): number | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const body = err.body as { detail?: { busy?: boolean; retry_after_s?: number } } | undefined;
  if (!body?.detail?.busy) return null;
  return (body.detail.retry_after_s ?? busyRetry.fallbackDelayMs / 1000) * 1000;
}

/**
 * Overrides draft and the active what-if run for one workbook version. Incremental what-ifs run
 * synchronously (the caller shows the quiet progress bar via `onBusy`); full runs are background
 * jobs polled until they settle.
 */
export function useRunSession(
  versionId: string | null,
  onBusy: (active: boolean, label?: string) => void,
  onSettled?: () => void,
): RunSession {
  const [draft, setDraftState] = useState<Map<string, DraftEntry>>(new Map());
  const [activeRun, setActiveRun] = useState<RunOut | null>(null);
  const [job, setJob] = useState<RunOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [waiting, setWaiting] = useState<string | null>(null);
  const versionRef = useRef(versionId);

  useEffect(() => {
    if (versionRef.current !== versionId) {
      versionRef.current = versionId;
      setDraftState(new Map());
      setActiveRun(null);
      setJob(null);
      setError(null);
    }
  }, [versionId]);

  const setDraft = useCallback((ref: string, entry: DraftEntry | null) => {
    setDraftState((prev) => {
      const next = new Map(prev);
      if (entry === null) next.delete(ref);
      else next.set(ref, entry);
      return next;
    });
  }, []);

  const resetDraft = useCallback(() => setDraftState(new Map()), []);

  const runAnalysis = useCallback(async () => {
    if (!versionId || draft.size === 0) return;
    const overrides: Record<string, CellValue> = {};
    for (const [ref, entry] of draft) overrides[ref] = entry.value;
    if (activeRun) for (const [ref, value] of Object.entries(activeRun.overrides)) overrides[ref] ??= value;
    setRunning(true);
    setError(null);
    onBusy(true, `Running analysis with ${Object.keys(overrides).length} override(s)`);
    try {
      let run: RunOut | null = null;
      for (let attempt = 1; run === null; attempt += 1) {
        try {
          run = await createRun(versionId, overrides, { mode: "auto" });
        } catch (err) {
          const delay = busyDelay(err);
          if (delay === null || attempt >= busyRetry.maxAttempts) throw err;
          setWaiting(`Another run is in progress; retrying in ${Math.round(delay / 1000)} s (attempt ${attempt})`);
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
      setWaiting(null);
      setActiveRun(run);
      setDraftState(new Map());
      onSettled?.();
    } catch (err) {
      setWaiting(null);
      setError(describeError(err));
    } finally {
      setRunning(false);
      onBusy(false);
    }
  }, [versionId, draft, activeRun, onBusy, onSettled]);

  const runFull = useCallback(async () => {
    if (!versionId) return;
    setError(null);
    try {
      const started = await createRun(versionId, {}, { mode: "full", background: true });
      setJob(started);
    } catch (err) {
      setError(describeError(err));
    }
  }, [versionId]);

  // Poll a background job until it settles.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const id = job.id;
    const timer = setInterval(async () => {
      try {
        const latest = await getRun(id);
        if (latest.status !== "running") {
          clearInterval(timer);
          setJob(latest);
          if (latest.status === "ok") {
            setActiveRun(null);
            onSettled?.();
          }
        }
      } catch (err) {
        clearInterval(timer);
        setError(describeError(err));
        setJob(null);
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [job, onSettled]);

  const backToBaseline = useCallback(() => {
    setActiveRun(null);
    setDraftState(new Map());
  }, []);

  const dismissJob = useCallback(() => setJob(null), []);

  return {
    draft,
    setDraft,
    resetDraft,
    activeRun,
    job,
    error,
    running,
    waiting,
    runAnalysis,
    runFull,
    backToBaseline,
    dismissJob,
  };
}
