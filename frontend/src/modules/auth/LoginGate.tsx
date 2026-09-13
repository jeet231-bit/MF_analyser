import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { getSession, login, logout, type SessionState } from "@/api/auth";
import { ApiError, UNAUTHENTICATED_EVENT } from "@/api/client";
import { Button } from "@/components/Button";
import { AuthContext } from "./useAuth";

type Phase = { kind: "checking" } | { kind: "locked" } | { kind: "open"; required: boolean } | { kind: "unreachable"; detail: string };

/**
 * Wraps the app: asks the server whether a shared password is required and, when it is and no
 * session exists, shows the sign-in screen instead of the app. A 401 from any later request
 * (an expired session) brings the screen back without a reload.
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });

  const apply = useCallback((state: SessionState) => {
    setPhase(state.required && !state.authenticated ? { kind: "locked" } : { kind: "open", required: state.required });
  }, []);

  useEffect(() => {
    let cancelled = false;
    getSession()
      .then((state) => {
        if (!cancelled) apply(state);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // An older backend without the auth endpoint answers 404: there is no gate.
        if (error instanceof ApiError && error.status === 404) setPhase({ kind: "open", required: false });
        else setPhase({ kind: "unreachable", detail: error instanceof Error ? error.message : String(error) });
      });
    const onExpired = () => setPhase({ kind: "locked" });
    window.addEventListener(UNAUTHENTICATED_EVENT, onExpired);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHENTICATED_EVENT, onExpired);
    };
  }, [apply]);

  const signOut = useCallback(async () => {
    try {
      await logout();
    } finally {
      setPhase({ kind: "locked" });
    }
  }, []);

  if (phase.kind === "checking") {
    return (
      <div className="grid min-h-screen place-items-center bg-ground text-muted" role="status">
        Checking your session…
      </div>
    );
  }
  if (phase.kind === "unreachable") {
    return (
      <div className="grid min-h-screen place-items-center bg-ground px-[16px]">
        <div className="max-w-[420px] rounded-[24px] glass-strong rise p-[28px] text-center">
          <h1 className="font-heading text-[18px] font-bold text-ink">The server is not answering</h1>
          <p className="mt-[8px] text-[13px] text-muted">{phase.detail}</p>
          <p className="mt-[8px] text-[13px] text-muted">Check that the MF Analyser service is running, then reload this page.</p>
          <Button variant="primary" className="mt-[16px]" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </div>
      </div>
    );
  }
  if (phase.kind === "locked") {
    return <LoginPage onSignedIn={() => setPhase({ kind: "open", required: true })} />;
  }
  return <AuthContext.Provider value={{ required: phase.required, signOut }}>{children}</AuthContext.Provider>;
}

/** The sign-in screen: the brand mark, one password field, one error line. */
export function LoginPage({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(password);
      setPassword("");
      onSignedIn();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) setError("That password is not right.");
      else setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center bg-ground px-[16px]">
      <form onSubmit={submit} className="w-full max-w-[380px] rounded-[24px] glass-strong rise p-[28px]" aria-labelledby="login-title">
        <div className="mb-[20px] flex items-center gap-[12px]">
          <span className="grid h-[40px] w-[40px] place-items-center rounded-[14px] bg-accent font-heading text-[15px] font-bold text-white" aria-hidden>
            MF
          </span>
          <div>
            <h1 id="login-title" className="font-heading text-[18px] font-bold leading-tight text-ink">
              MF Analyser
            </h1>
            <p className="text-[12px] text-muted">Internal research console</p>
          </div>
        </div>
        <label htmlFor="login-password" className="mb-[6px] block text-[12px] font-semibold text-ink-2">
          Shared password
        </label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-full border border-hairline bg-ground px-[16px] py-[10px] text-[14px] text-ink outline-none focus:border-accent"
        />
        {error && (
          <p role="alert" className="mt-[10px] text-[12.5px] text-negative">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={!password || busy} className="mt-[16px] w-full justify-center">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="mt-[14px] text-center text-[11.5px] text-muted">Ask the team for the password. Sessions last a working day.</p>
      </form>
    </main>
  );
}
