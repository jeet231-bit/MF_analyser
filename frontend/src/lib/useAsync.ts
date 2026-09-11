import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";

export type AsyncState<T> =
  | { status: "loading"; data?: T }
  | { status: "ready"; data: T }
  | { status: "error"; error: string; notFound: boolean; data?: T };

export function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof TypeError) return "Could not reach the backend. Start it with `npm run dev` and retry.";
  return err instanceof Error ? err.message : "Unknown error";
}

type Settled<T> =
  | { key: string; status: "ready"; data: T }
  | { key: string; status: "error"; error: string; notFound: boolean; data?: T };

/**
 * Run an async loader, tracking loading / ready / error. `deps` re-run the loader; `reload()`
 * re-runs it on demand. "Loading" is derived (the settled result belongs to an older key), so
 * no state is set synchronously inside the effect; stale results from superseded calls are ignored.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> & { reload: () => void } {
  const [tick, setTick] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const key = JSON.stringify(deps) + "#" + tick;
  const latest = useRef("");

  useEffect(() => {
    const mine = key;
    latest.current = mine; // effects run in order, so a resolved older call sees a newer key and is dropped
    loader().then(
      (data) => {
        if (latest.current === mine) setSettled({ key: mine, status: "ready", data });
      },
      (err: unknown) => {
        if (latest.current === mine) {
          setSettled((prev) => ({
            key: mine,
            status: "error",
            error: describeError(err),
            notFound: err instanceof ApiError && err.status === 404,
            data: prev?.data,
          }));
        }
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  if (settled && settled.key === key) {
    return settled.status === "ready"
      ? { status: "ready", data: settled.data, reload }
      : { status: "error", error: settled.error, notFound: settled.notFound, data: settled.data, reload };
  }
  return { status: "loading", data: settled?.data, reload };
}
