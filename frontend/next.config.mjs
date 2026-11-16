import { LEGACY_ROUTES } from "./src/lib/legacy-routes.mjs";

/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  // Safe subset of a CSP (no script-src yet: Next.js inline scripts would need nonces). Blocks plugins, base-tag hijack, framing and off-site form posts.
  { key: "Content-Security-Policy", value: "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self' https://*.cashfree.com" },  // Cashfree's hosted subscription checkout posts a form to <sandbox|api>.cashfree.com (and may redirect within it); found in the Cashfree Sandbox, where 'self' alone blocked it
  { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  // Same-origin API: the browser only talks to this origin, so session cookies stay first-party
  // (SameSite=Lax) and no CORS is needed. Secrets never reach the browser.
  // With NEXT_PUBLIC_API_URL set (production on Vercel) the browser talks to the API host directly and nothing is proxied; without it (development, the Docker demo) /api is proxied here.
  async rewrites() {
    return process.env.NEXT_PUBLIC_API_URL ? [] : [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // PRD §8: the pre-redesign URLs move permanently (308) to the four sections; Next keeps the query string.
  async redirects() {
    return LEGACY_ROUTES.map(([source, destination]) => ({ source, destination, permanent: true }));
  },
};

export default nextConfig;
