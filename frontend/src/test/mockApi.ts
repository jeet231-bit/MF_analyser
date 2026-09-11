import { vi } from "vitest";

type Handler = (init?: RequestInit) => unknown;
type Routes = Record<string, unknown | Handler>;

/**
 * Route fetch by "METHOD /api/path" (query string ignored unless the key includes it).
 * Unmatched routes return 404 so tests fail loudly instead of hanging.
 */
export function mockApi(routes: Routes) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, url, body });
    const path = url.split("?")[0];
    const key = Object.keys(routes).find((k) => k === `${method} ${url}` || k === `${method} ${path}`);
    if (key === undefined) {
      return new Response(JSON.stringify({ detail: `no mock for ${method} ${url}` }), { status: 404 });
    }
    const value = routes[key];
    const payload = typeof value === "function" ? (value as Handler)(init) : value;
    if (payload instanceof Response) return payload;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

export function jsonError(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } });
}
