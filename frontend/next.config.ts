import type { NextConfig } from "next";

const API_UPSTREAM = process.env.API_UPSTREAM || "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  experimental: {
    // Next's rewrite proxy kills upstream responses after 30s by default;
    // AI scans take ~30-40s per image-set, so lift the cap to 5 minutes.
    proxyTimeout: 300000,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_UPSTREAM}/api/:path*`,
      },
    ]
  },
};

export default nextConfig;