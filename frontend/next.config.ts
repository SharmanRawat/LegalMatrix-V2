import type { NextConfig } from "next";

const API_UPSTREAM = process.env.API_UPSTREAM || "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  experimental: {
    // The rewrite proxy buffers upload bodies; Next 16 caps that at 10MB by
    // default and forwards a TRUNCATED multipart body past the cap, which
    // makes the backend hang waiting for bytes that never arrive (multi-photo
    // uploads are 4-9MB phone JPEGs each and easily exceed 10MB).
    proxyClientMaxBodySize: '64mb',
    // OCR+SLM scans take ~25-60s (more on cold model load); the proxy must
    // keep waiting for the upstream response that long.
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