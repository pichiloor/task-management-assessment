import { vi } from "vitest";

type Handler = (request: {
  method: string;
  url: URL;
  body: unknown;
  headers: Headers;
}) => Response | Promise<Response>;

export type Call = { method: string; path: string; body: unknown; auth: string | null };

export function json(body: unknown, status = 200, headers: HeadersInit = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** Replaces global fetch with a router keyed by "METHOD /path" and records
 * every call, so tests assert on what the UI actually sent. */
export function fakeApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = init.method ?? "GET";
    const headers = new Headers(init.headers);
    let body: unknown = init.body;
    if (typeof body === "string") body = JSON.parse(body);
    else if (body instanceof URLSearchParams) body = Object.fromEntries(body);
    calls.push({ method, path: url.pathname, body, auth: headers.get("Authorization") });
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) return json({ detail: "Not Found", code: "not_found" }, 404);
    return handler({ method, url, body, headers });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}
