import { useCallback, useState } from "react";

export const WATCHLIST_KEY = "mfa-watchlist";

export interface WatchItem {
  key: string;
  label: string;
  sub?: string | null;
}

function read(): WatchItem[] {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is WatchItem => typeof x === "object" && x !== null && typeof (x as WatchItem).key === "string");
  } catch {
    return [];
  }
}

function write(items: WatchItem[]): void {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(items));
  } catch {
    /* storage unavailable: the list lives for this page only */
  }
}

/**
 * Funds pinned by this viewer, kept in the browser (per viewer, per browser) until the platform
 * has accounts. Every read and write is wrapped, so a blocked storage never breaks a page.
 */
export function useWatchlist() {
  const [items, setItems] = useState<WatchItem[]>(read);

  const has = useCallback((key: string) => items.some((i) => i.key === key), [items]);
  const toggle = useCallback((item: WatchItem) => {
    setItems((prev) => {
      const next = prev.some((i) => i.key === item.key) ? prev.filter((i) => i.key !== item.key) : [...prev, item];
      write(next);
      return next;
    });
  }, []);
  const remove = useCallback((key: string) => {
    setItems((prev) => {
      const next = prev.filter((i) => i.key !== key);
      write(next);
      return next;
    });
  }, []);

  return { items, has, toggle, remove };
}
