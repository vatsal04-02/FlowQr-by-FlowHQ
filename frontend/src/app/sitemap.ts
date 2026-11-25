import type { MetadataRoute } from "next";
import { MARKETING_ROUTES, NOINDEX_ROUTES, SITE_URL } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return MARKETING_ROUTES.filter((path) => !NOINDEX_ROUTES.includes(path)).map((path) => ({ url: `${SITE_URL}${path}`, changeFrequency: "monthly", priority: path === "/" ? 1 : 0.7 }));
}
