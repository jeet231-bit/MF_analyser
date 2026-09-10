import { useCallback, useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "@/api/health";
import { ApiError } from "@/api/client";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { formatTimestamp } from "@/lib/format";

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: HealthResponse }
  | { kind: "error"; message: string };

function describeError(err: unknown): string {
  if (err instanceof ApiError) return `Backend answered ${err.status}. Is the API running on port 8000?`;
  if (err instanceof TypeError) return "Could not reach the backend. Start it with `npm run dev` and retry.";
  return err instanceof Error ? err.message : "Unknown error";
}

export function HealthPage() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ kind: "error", message: describeError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  return (
    <Card
      title="Backend connection"
      action={
        <button
          type="button"
          onClick={reload}
          className="rounded-sm px-2 py-1 font-heading text-xs font-medium text-accent hover:bg-accent-soft"
        >
          Refresh
        </button>
      }
    >
      {state.kind === "loading" && (
        <p className="text-sm text-muted" role="status">
          Checking the API…
        </p>
      )}
      {state.kind === "error" && (
        <div className="space-y-1" role="alert">
          <Pill tone="negative">Unreachable</Pill>
          <p className="text-sm text-muted">{state.message}</p>
        </div>
      )}
      {state.kind === "ready" && <HealthDetails data={state.data} />}
    </Card>
  );
}

function HealthDetails({ data }: { data: HealthResponse }) {
  const rows: Array<[string, string]> = [
    ["Service", data.service],
    ["Version", data.version],
    ["Environment", data.environment],
    ["Python", data.python],
    ["Database", data.database],
    ["Checked", formatTimestamp(data.time)],
  ];
  return (
    <div className="space-y-2">
      <Pill tone={data.status === "ok" ? "positive" : "warning"}>
        {data.status === "ok" ? "Healthy" : "Degraded"}
      </Pill>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="tabular text-ink" data-testid={`health-${label.toLowerCase()}`}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
