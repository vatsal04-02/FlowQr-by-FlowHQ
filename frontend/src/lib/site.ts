/** The public site's address, for canonical URLs, the sitemap and social cards. Set NEXT_PUBLIC_SITE_URL in production. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

export const MARKETING_ROUTES = ["/", "/google-business", "/review-cards", "/ai-growth-agent", "/whatsapp-marketing-ai-agent", "/industries", "/pricing", "/about", "/demo", "/privacy", "/terms", "/refund-policy", "/data-deletion"];

/** Per-page metadata with canonical and hreflang (en-IN now; hi-IN can be added when a Hindi version ships). */
export function pageMeta(path: string, title: string, description: string) {
  return {
    title: path === "/" ? { absolute: title } : title,
    description,
    alternates: { canonical: path, languages: { "en-IN": path } },
    openGraph: { title, description, url: path },
    twitter: { title, description },
  };
}
