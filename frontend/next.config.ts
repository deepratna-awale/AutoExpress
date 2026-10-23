import type { NextConfig } from "next";

// The production build is a static export that the Flask app serves (see autoexpress/views.py).
// During `next dev`, API calls are proxied to the Flask server instead.
const FLASK_URL = process.env.AUTOEXPRESS_BACKEND_URL || "http://127.0.0.1:5000";

const FLASK_ROUTES = [
  "/backends",
  "/receive_data",
  "/get-models",
  "/get-samplers",
  "/get-schedulers",
  "/get-loras",
  "/upload",
  "/generate",
  "/interrupt",
  "/toggle",
  "/expression-families",
  "/expression-family",
  "/images/:path*",
  "/image/:path*",
  "/classic",
  "/static/:path*",
];

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  images: { unoptimized: true },
  ...(isDev && {
    async rewrites() {
      return FLASK_ROUTES.map((source) => ({ source, destination: `${FLASK_URL}${source}` }));
    },
  }),
};

export default nextConfig;
