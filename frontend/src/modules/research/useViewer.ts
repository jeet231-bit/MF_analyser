import { useCallback, useState } from "react";

export const VIEWER_KEY = "mfa-viewer";

function read(): string | null {
  try {
    const raw = localStorage.getItem(VIEWER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { name?: unknown };
    return typeof parsed.name === "string" && parsed.name.trim() ? parsed.name.trim() : null;
  } catch {
    return null;
  }
}

/** "morning" / "afternoon" / "evening" from the browser clock. */
export function timeOfDay(date = new Date()): "morning" | "afternoon" | "evening" {
  const h = date.getHours();
  return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
}

/** "Good morning, Jeet" (or a plain "Good morning" when no name is known). */
export function greeting(name: string | null | undefined, date = new Date()): string {
  const base = `Good ${timeOfDay(date)}`;
  return name ? `${base}, ${name}` : base;
}

export function initials(name: string | null | undefined): string {
  if (!name) return "·";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

/**
 * The viewer's first name, interim: a per-browser setting in Admin, falling back to the
 * config's default. When sign-in exists this derives from the signed-in email and the local
 * setting goes away. Every storage access is wrapped.
 */
export function useViewer(defaultName: string | null | undefined) {
  const [local, setLocal] = useState<string | null>(read);
  const name = local ?? (defaultName?.trim() || null);
  const setName = useCallback((next: string) => {
    const trimmed = next.trim();
    try {
      if (trimmed) localStorage.setItem(VIEWER_KEY, JSON.stringify({ name: trimmed }));
      else localStorage.removeItem(VIEWER_KEY);
    } catch {
      /* storage unavailable */
    }
    setLocal(trimmed || null);
  }, []);
  return { name, localName: local, setName };
}
