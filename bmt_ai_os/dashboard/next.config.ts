import type { NextConfig } from "next";
import path from "path";

const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}/api/:path*`,
      },
      {
        source: "/v1/:path*",
        destination: `${API_ORIGIN}/v1/:path*`,
      },
      {
        source: "/healthz",
        destination: `${API_ORIGIN}/healthz`,
      },
      {
        source: "/metrics",
        destination: `${API_ORIGIN}/metrics`,
      },
    ];
  },
};

export default nextConfig;
