import type { NextConfig } from "next";

// Tunnel mode (`make share`, docs/share.md): the browser calls "/api/*" on this server, rewritten here to the backend
// (src/proxy.ts adds X-Agent-Secret on the way). Harmless in the default mode, where the browser calls :8000 directly.
const backend = (process.env.POLYBRIDGE_BACKEND_ORIGIN || "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  devIndicators: false,
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
