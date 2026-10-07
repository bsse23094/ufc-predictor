import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next standalone tracing creates symlinks that Windows forbids without developer mode.
  // Docker/Linux builds still emit the required production standalone bundle.
  output: process.platform === "win32" ? undefined : "standalone",
  reactStrictMode: true,
  transpilePackages: ["@ufc-predictor/shared-types", "@ufc-predictor/ui"],
  async rewrites() {
    const apiTarget = process.env.API_BASE_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiTarget}/api/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${apiTarget}/health`,
      },
      {
        source: "/readiness",
        destination: `${apiTarget}/readiness`,
      },
    ];
  },
};

export default nextConfig;
