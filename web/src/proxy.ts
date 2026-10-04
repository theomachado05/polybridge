// Server side only (Next.js Proxy, Node runtime): attaches X-Agent-Secret to the "/api/*" requests that next.config.ts
// rewrites to the backend. AGENT_TOOL_SECRET comes from the server's environment (`make share` passes it from the
// repo-root .env); it is not NEXT_PUBLIC_ and never reaches the browser.
import { NextResponse, type NextRequest } from "next/server";
import { proxiedHeaders } from "@/lib/tunnel";

export function proxy(request: NextRequest) {
  const headers = proxiedHeaders(request.headers, process.env.AGENT_TOOL_SECRET, request.headers.get("host") ?? "");
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/:path*" };
