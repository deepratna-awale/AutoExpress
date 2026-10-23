import type { NextConfig } from "next";

// The production build is a static export that the Flask app serves (see autoexpress/frontend.py).
// During `next dev`, every request Next.js doesn't handle itself is proxied to the Flask server.
const FLASK_URL = process.env.AUTOEXPRESS_BACKEND_URL || "http://127.0.0.1:5000";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  images: { unoptimized: true },
  ...(isDev && {
    async rewrites() {
      return { beforeFiles: [], afterFiles: [], fallback: [{ source: "/:path*", destination: `${FLASK_URL}/:path*` }] };
    },
  }),
};

export default nextConfig;
