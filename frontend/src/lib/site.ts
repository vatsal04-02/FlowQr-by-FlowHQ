/** The public site's address, for canonical URLs, the sitemap and social cards. Set NEXT_PUBLIC_SITE_URL in production. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

export const MARKETING_ROUTES = ["/", "/google-business", "/review-cards", "/ai-growth-agent", "/whatsapp-marketing-ai-agent", "/industries", "/pricing", "/about", "/privacy", "/privacy-hi", "/terms", "/cookie-policy", "/refund-policy", "/data-deletion"];
/** Pages that are public but carry `robots: noindex` (refund-policy until a lawyer confirms the text). They stay out of the sitemap: Search Console warns about a listed page that says "do not index". Remove from this list when the page is indexed. */
export const NOINDEX_ROUTES = ["/refund-policy"];

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
