/**
 * Where the browser finds the API.
 *
 *  - Production (Vercel): NEXT_PUBLIC_API_URL=https://api.flowqr.site. The site (flowqr.site) and the API (api.flowqr.site) are different hosts of the SAME SITE, so the session cookie
 *    (Domain=.flowqr.site, Secure, HttpOnly) is sent with credentialed requests, and the API allows the site's origin explicitly (CORS_ORIGINS).
 *  - Development and the Docker demo: leave it empty. The browser then calls /api/v1 on its own origin and Next.js proxies it (next.config.mjs), exactly as before.
 *
 * It is compiled into the bundle at build time and contains no secret. A trailing slash is removed.
 */
export const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
export const API_V1 = `${API_ORIGIN}/api/v1`;
