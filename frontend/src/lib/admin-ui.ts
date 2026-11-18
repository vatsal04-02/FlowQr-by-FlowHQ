export interface TenantRow {
  id: string; name: string; category: string | null; created_at: string; is_active: boolean; suspension_reason: string | null; support_status: string;
  owner_email: string | null; plan: string | null; subscription_status: string | null; locations: number; cards: number; members: number;
  contact_name?: string | null; phone?: string | null; email?: string | null; origin?: "admin" | "self_service"; city?: string | null; active_cards?: number;
  onboarding_status?: "has_account" | "live" | "ready" | "incomplete"; agreement_recorded?: boolean; managed_access?: "none" | "managed" | "revoked" | "other";
  /** what the business said about having a website in onboarding, the state of the website FlowQR built for it (null = none yet), and the address it gave */
  website_interest?: "has_site" | "wants_site" | "not_now" | null; site_status?: "draft" | "published" | "unpublished" | "suspended" | null; website_url?: string | null;
}
/** How far a business is from working, in words a person at the counter understands. */
export const ONBOARDING: Record<string, { label: string; tone: "green" | "blue" | "amber" | "gray" }> = {
  live: { label: "Cards live", tone: "green" }, has_account: { label: "Has its own account", tone: "blue" }, ready: { label: "Ready for cards", tone: "amber" }, incomplete: { label: "Needs a review link", tone: "gray" },
};
export const SUB_TONE: Record<string, "green" | "blue" | "amber" | "red" | "gray"> = { active: "green", trialing: "blue", manual: "green", past_due: "amber", halted: "red", expired: "red", canceled: "gray", pending: "gray" };
