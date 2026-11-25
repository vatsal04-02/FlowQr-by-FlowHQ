/**
 * Which plan feature each page needs (owner decision 2026-11-25: a business sees only what its plan includes). The server already refuses everything a plan lacks (402); this keeps the
 * menus, the phone "More" sheet, search and a pasted link in step with it, so nobody is shown a page they cannot use. The names are the plan features of backend/app/services/plans.py
 * (tests/nav-plans.test.mjs fails if one is misspelt or a plan loses a page it should keep). A page that is not listed here is part of every plan.
 */
export const PAGE_FEATURE: Record<string, string> = {
  "/gbp/studio": "gbp_posts",
  "/gbp/posts": "gbp_posts",
  "/gbp/photos": "gbp_media",
  "/seo/rankings": "keyword_tracking",
  "/seo/performance": "gbp_performance",
  "/ai/today": "growth_agent",
  "/ai/automations": "growth_agent",
  "/ai/studio": "gbp_posts",
  "/ai/operator": "autonomy",
  "/ai/tasks": "growth_agent",
  "/ai/approvals": "growth_agent",
  "/ai/changes": "autonomy",
  "/ai/activity": "growth_agent",
};

/** The features of the signed-in business's plan, or null while they are not known yet (then nothing is hidden, so the menu never flashes empty). */
export type PlanFeatures = ReadonlySet<string> | null | undefined;

export const allows = (features: PlanFeatures, href: string): boolean => !features || !PAGE_FEATURE[href] || features.has(PAGE_FEATURE[href]);

/** The feature a located page needs: the most specific of its tab, page and destination that is listed. */
export function featureFor(...hrefs: (string | undefined | null)[]): string | null {
  for (const h of hrefs) if (h && PAGE_FEATURE[h]) return PAGE_FEATURE[h];
  return null;
}
