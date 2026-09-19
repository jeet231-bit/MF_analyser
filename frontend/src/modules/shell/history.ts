import { useCallback, useEffect, useRef, useState } from "react";
import type { EntityQuery, PivotQuery } from "@/api/research";
import type { AppMode, PageId } from "./navigation";

/** One screen of the app: the page plus whatever it needs to be re-shown exactly. */
export interface AppLocation {
  mode: AppMode;
  page: PageId;
  sheet?: string;
  fund?: string;
  /** The Funds page's filters, sort, pivot and page, kept so Back lands on the same list. */
  funds?: EntityQuery;
  /** The Pivots screen: which pivot is open (null = the list) and its layout. */
  pivot?: { id: string | null; query?: PivotQuery };
}

interface Entry extends AppLocation {
  depth: number;
}

interface HistoryState {
  entry: Entry;
  /** The entries visited in this tab, by depth; lets "Back to …" name the previous screen. */
  stack: Entry[];
}

function isEntry(value: unknown): value is Entry {
  return typeof value === "object" && value !== null && typeof (value as Entry).depth === "number" && typeof (value as Entry).page === "string";
}

/**
 * In-app history on top of the browser's: every screen is a history entry, so the browser's
 * Back button (and the app's own back links) return to the previous screen with its state
 * instead of leaving the console. Filters changed on a screen `replace` its entry.
 */
export function useAppHistory(initial: () => AppLocation) {
  const [state, setState] = useState<HistoryState>(() => {
    const restored = window.history.state;
    if (isEntry(restored)) return { entry: restored, stack: [] };
    const first = { ...initial(), depth: 0 };
    window.history.replaceState(first, "");
    return { entry: first, stack: [first] };
  });
  const latest = useRef(state);
  useEffect(() => {
    latest.current = state;
  }, [state]);

  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      if (isEntry(event.state)) setState((s) => ({ entry: event.state as Entry, stack: s.stack }));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const commit = useCallback((next: HistoryState) => {
    latest.current = next;
    setState(next);
  }, []);

  const navigate = useCallback(
    (next: AppLocation) => {
      const { entry, stack } = latest.current;
      const e: Entry = { ...next, depth: entry.depth + 1 };
      window.history.pushState(e, "");
      commit({ entry: e, stack: [...stack.slice(0, entry.depth + 1), e] });
      window.scrollTo({ top: 0 });
    },
    [commit],
  );

  const replace = useCallback(
    (patch: Partial<AppLocation>) => {
      const { entry, stack } = latest.current;
      const e: Entry = { ...entry, ...patch };
      window.history.replaceState(e, "");
      const next = [...stack];
      next[e.depth] = e;
      commit({ entry: e, stack: next });
    },
    [commit],
  );

  /** Go back one screen; when there is none (a fresh tab), show `fallback` instead. */
  const back = useCallback(
    (fallback: AppLocation) => {
      if (latest.current.entry.depth > 0) window.history.back();
      else navigate(fallback);
    },
    [navigate],
  );

  const { entry, stack } = state;
  const previous: AppLocation | null = entry.depth > 0 ? (stack[entry.depth - 1] ?? null) : null;
  return { location: entry as AppLocation, navigate, replace, back, previous, canGoBack: entry.depth > 0 };
}

const PAGE_NAMES: Partial<Record<PageId, string>> = {
  dashboard: "dashboard",
  insights: "insights",
  funds: "funds",
  fund: "the previous fund",
  categories: "categories",
  pivots: "pivots",
  movement: "movement",
  admin: "admin",
  upload: "upload",
  overview: "overview",
  inputs: "inputs",
  outputs: "outputs",
  versions: "versions",
  validation: "validation",
};

/** A short name for a screen, used in "← Back to …" links. */
export function describeLocation(loc: AppLocation | null): string | null {
  if (!loc) return null;
  if (loc.page === "funds") {
    const q = loc.funds ?? {};
    const parts = [q.amc, q.category, q.plan, q.q ? `“${q.q}”` : undefined].filter(Boolean);
    return parts.length ? `funds · ${parts.join(" · ")}` : "all funds";
  }
  if (loc.page === "pivots" && loc.pivot?.id) return `pivot ${loc.pivot.id.split("::")[0]}`;
  if (loc.page === "sheet" && loc.sheet) return loc.sheet;
  return PAGE_NAMES[loc.page] ?? loc.page;
}
