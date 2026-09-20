/**
 * Meshcore — web config.
 *
 * All browser calls are same-origin `/api/...`; this rewrite proxies them to
 * the FastAPI backend (localhost:8000 in dev, `api:8000` inside docker-compose
 * via the API_BASE_URL env var).
 */
/** @type {import('next').NextConfig} */
const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
