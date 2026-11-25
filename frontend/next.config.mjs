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
  // The FULL policy, in REPORT-ONLY mode: the browser checks every page against it and logs what it WOULD have blocked (DevTools console: "[Report Only] ...") but blocks nothing, so it cannot break a page.
  // It exists to find out, on real traffic, what an enforced policy must allow. script-src still needs 'unsafe-inline' (Next.js hydration scripts) until nonces are added, which is why the enforced header above
  // stays the safe subset. When the console is clean on the pages that matter (sign-in, home, billing with a test payment, WhatsApp connect), move these directives into the enforced header.
  { key: "Content-Security-Policy-Report-Only", value: reportOnlyCsp() },
];

function reportOnlyCsp() {
  const api = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
  const self = ["'self'"];
  return [
    "default-src 'self'",
    `script-src ${[...self, "'unsafe-inline'", "https://checkout.razorpay.com", "https://sdk.cashfree.com", "https://*.cashfree.com", "https://connect.facebook.net"].join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    `connect-src ${[...self, api, "https://*.cashfree.com", "https://api.razorpay.com", "https://lumberjack.razorpay.com", "https://*.facebook.com"].filter(Boolean).join(" ")}`,
    "frame-src https://api.razorpay.com https://*.cashfree.com https://*.facebook.com",
    "media-src 'self' blob:",
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "base-uri 'self'", "object-src 'none'", "frame-ancestors 'none'", "form-action 'self' https://*.cashfree.com",
  ].join("; ");
}

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  // Same-origin API: the browser only talks to this origin, so session cookies stay first-party
  // (SameSite=Lax) and no CORS is needed. Secrets never reach the browser.
  // With NEXT_PUBLIC_API_URL set (production on Vercel) the browser talks to the API host directly and nothing is proxied; without it (development, the Docker demo) /api is proxied here.
  async rewrites() {
    // Business websites hosted by FlowQR (SITES_PROVIDER=app): served by the API, sandboxed by its Content-Security-Policy.
    const siteApi = process.env.NEXT_PUBLIC_API_URL || BACKEND_URL;
    const sites = [{ source: "/site/:slug", destination: `${siteApi}/api/v1/public-site/:slug` }, { source: "/site/:slug/:path*", destination: `${siteApi}/api/v1/public-site/:slug/:path*` }];
    return [...sites, ...(process.env.NEXT_PUBLIC_API_URL ? [] : [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }])];
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
