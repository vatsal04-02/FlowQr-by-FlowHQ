import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Marketing pages are public; the app, admin, API and customer card/review pages are not for search engines.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/admin", "/dashboard", "/overview", "/gbp/", "/gbp$", "/ai/", "/ai$", "/settings", "/c/", "/q/", "/n/", "/r/", "/onboarding", "/login", "/register"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
