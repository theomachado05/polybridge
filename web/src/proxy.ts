import { NextResponse, type NextRequest } from "next/server";
import { proxiedHeaders } from "@/lib/tunnel";

export function proxy(request: NextRequest) {
  const headers = proxiedHeaders(request.headers, process.env.AGENT_TOOL_SECRET, request.headers.get("host") ?? "");
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/:path*" };
