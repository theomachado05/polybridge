import type { NextConfig } from "next";

const backend = (process.env.POLYBRIDGE_BACKEND_ORIGIN || "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  devIndicators: false,
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
