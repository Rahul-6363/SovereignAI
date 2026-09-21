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
  // `next build` and `next dev` share `.next` by default, and running one
  // while the other is up corrupts it — the build dies at "Collecting page
  // data" with a misleading `Cannot find module for page: /_document`.
  // Setting NEXT_DIST_DIR lets a production build be verified without
  // stopping the dev server someone is using.
  distDir: process.env.NEXT_DIST_DIR || ".next",
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
