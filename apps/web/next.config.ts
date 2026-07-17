import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next standalone tracing creates symlinks that Windows forbids without developer mode.
  // Docker/Linux builds still emit the required production standalone bundle.
  output: process.platform === "win32" ? undefined : "standalone",
  reactStrictMode: true,
  transpilePackages: ["@ufc-predictor/shared-types", "@ufc-predictor/ui"],
};

export default nextConfig;
