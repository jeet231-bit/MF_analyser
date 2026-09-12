import { useCallback, useState } from "react";
import type { Scope } from "@/api/research";
import { EMPTY_SCOPE, isScopeEmpty } from "@/api/research";

export const SCOPE_KEY = "mfa-scope";

function read(): Scope {
  try {
    const raw = localStorage.getItem(SCOPE_KEY);
    if (!raw) return EMPTY_SCOPE;
    const parsed = JSON.parse(raw) as Partial<Scope>;
    return {
      dims: typeof parsed.dims === "object" && parsed.dims ? parsed.dims : {},
      quartile: Array.isArray(parsed.quartile) ? parsed.quartile.filter((q) => Number.isInteger(q)) : [],
      bands: typeof parsed.bands === "object" && parsed.bands ? parsed.bands : {},
      rated: parsed.rated === "only" || parsed.rated === "unrated" ? parsed.rated : "all",
      q: typeof parsed.q === "string" && parsed.q ? parsed.q : undefined,
    };
  } catch {
    return EMPTY_SCOPE;
  }
}

function write(scope: Scope): void {
  try {
    if (isScopeEmpty(scope)) localStorage.removeItem(SCOPE_KEY);
    else localStorage.setItem(SCOPE_KEY, JSON.stringify(scope));
  } catch {
    /* storage unavailable: the scope lives for this page only */
  }
}

/** The global scope: one filter every research view, sentence and export honours. Per browser. */
export function useScope() {
  const [scope, setScopeState] = useState<Scope>(read);
  const setScope = useCallback((next: Scope) => {
    write(next);
    setScopeState(next);
  }, []);
  const reset = useCallback(() => setScope(EMPTY_SCOPE), [setScope]);
  return { scope, setScope, reset, applied: !isScopeEmpty(scope) };
}
