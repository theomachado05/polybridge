export const DEFAULT_API_URL = "http://localhost:8000";
export const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8000";

export function apiBase(configured: string | undefined): string {
  const v = (configured ?? "").trim().replace(/\/+$/, "");
  return v || DEFAULT_API_URL;
}

export function proxiedHeaders(incoming: Headers, secret: string | undefined, host: string): Headers {
  const h = new Headers(incoming);
  h.delete("x-agent-secret");
  if (secret) h.set("x-agent-secret", secret);
  if (!h.has("x-forwarded-for") && !h.has("x-forwarded-host") && !h.has("forwarded")) h.set("x-forwarded-host", host || "unknown");
  return h;
}
