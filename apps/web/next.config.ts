import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produce a self-contained build for Docker/production (no node_modules needed)
  output: "standalone",

  // Allow HMR connections from 127.0.0.1 (localhost IPv4)
  allowedDevOrigins: ["127.0.0.1"],

  // Proxy /api requests to the FastAPI backend during development
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:4010/api/:path*",
      },
    ];
  },
};

export default nextConfig;