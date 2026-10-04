// Tunnel mode (`make share`): the browser talks to the Next.js server only ("/api/*"), which proxies to the backend on
// 127.0.0.1:8000 (next.config.ts rewrites) after src/proxy.ts attaches X-Agent-Secret server side. The secret is read
// from the server's process.env at request time and is never part of the browser bundle. See docs/share.md.

/** Where the browser sends API calls by default (`make dev`): the backend directly. */
export const DEFAULT_API_URL = "http://localhost:8000";
/** Where the Next.js server proxies "/api/*" to (override with POLYBRIDGE_BACKEND_ORIGIN). */
export const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8000";

/** The browser's API base: NEXT_PUBLIC_API_URL ("/api" in tunnel mode) without a trailing slash, else the default. */
export function apiBase(configured: string | undefined): string {
  const v = (configured ?? "").trim().replace(/\/+$/, "");
  return v || DEFAULT_API_URL;
}

/** Request headers for a proxied "/api/*" call: any browser-sent X-Agent-Secret is dropped and the server's own
 * secret set; a forwarding header is always present so the backend treats the call as remote (writes need the
 * secret) even when the proxy and the browser are both on localhost. */
export function proxiedHeaders(incoming: Headers, secret: string | undefined, host: string): Headers {
  const h = new Headers(incoming);
  h.delete("x-agent-secret");
  if (secret) h.set("x-agent-secret", secret);
  if (!h.has("x-forwarded-for") && !h.has("x-forwarded-host") && !h.has("forwarded")) h.set("x-forwarded-host", host || "unknown");
  return h;
}
