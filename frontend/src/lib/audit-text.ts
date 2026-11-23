/**
 * The audit log in words. The server records machine names ("reply.approve", "staff.role_change"); an owner reads "You approved a reply".
 * The table below holds the common action names the backend writes today (backend/app/**: grep for audit(); the rest fall back, below).
 * Pure functions, unit-tested. An action not in the table falls back to its machine name made readable ("rank.grid_scan" becomes "Rank grid scan"), never to raw JSON:
 * the raw record stays one click away under "Details".
 */
const VERBS: Record<string, string> = {
  "auth.login": "signed in", "auth.logout": "signed out", "auth.register": "created the account", "auth.password_changed": "changed their password", "auth.password_reset": "reset their password",
  "auth.email_verified": "verified their email", "auth.google_linked": "linked a Google sign-in",
  "tenant.create": "created the business", "tenant.update": "updated the business profile",
  "location.create": "added a location", "location.update": "updated a location", "location.deactivate": "deactivated a location",
  "staff.invite": "invited a team member", "staff.accept": "accepted an invitation", "staff.remove": "removed a team member", "staff.role_change": "changed a team member's role", "staff.locations_change": "changed a team member's locations",
  "reply.approve": "approved a reply", "reply.publish_attempt": "tried to publish a reply", "reply.auto_template": "changed the automatic reply wording",
  "post.draft_create": "wrote a post draft", "post.ai_draft": "had the AI draft a post", "post.approve": "approved a post", "post.cancel": "cancelled a post",
  "gbp.post_create": "published a Google post", "gbp.post_update": "edited a Google post", "gbp.post_delete": "deleted a Google post",
  "gbp.media_add": "added a Google photo", "gbp.media_delete": "deleted a Google photo", "gbp.update_info": "updated the Google profile details",
  "google.connect_started": "started connecting Google", "google.connect": "connected Google", "google.disconnect": "disconnected Google", "google.select_locations": "chose which Google locations to sync",
  "card.assign": "assigned a card", "card.activate": "activated a card", "card.deactivate": "deactivated a card", "card.pause": "paused a card", "card.lost": "reported a card lost", "card.retire": "retired a card", "card.repoint": "pointed a card at another location",
  "billing.change_plan": "changed the plan", "billing.cancel": "cancelled the plan", "billing.checkout_created": "started a checkout", "billing.prepaid_activated": "activated a prepaid plan", "billing.card_order_created": "ordered cards",
  "account.export": "exported the account data", "account.deletion_requested": "asked to delete the business", "account.deletion_cancelled": "cancelled the deletion of the business",
  "consent.granted": "gave consent", "consent.revoked": "withdrew consent",
  "report.csv": "downloaded a report (CSV)", "report.pdf": "downloaded a report (PDF)", "qr.bulk_export": "exported QR codes",
  "rank.keyword_add": "added a search word to track", "rank.keyword_remove": "stopped tracking a search word",
};

const sentence = (s: string) => { const t = s.replace(/[._]+/g, " ").trim(); return t ? t[0].toUpperCase() + t.slice(1) : s; };

/** "You approved a reply" / "priya@x.com approved a reply" / "FlowQR approved a reply" (actions with no person). `me` is the viewer's own email. */
export function describeAudit(action: string, by: string | null, me?: string | null): string {
  const verb = VERBS[action];
  const who = by ? (me && by.toLowerCase() === me.toLowerCase() ? "You" : by) : "FlowQR";
  if (verb) return `${who} ${verb}`;
  const s = sentence(action);
  return by ? `${who}: ${s.toLowerCase()}` : s;
}

/** "21 Nov, 8:37 pm" in the viewer's own time. */
export function whenText(iso: string, locale = "en-IN"): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = d.toLocaleDateString(locale, { day: "numeric", month: "short" });
  const time = d.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit", hour12: true }).replace(/\s?([AP]M)/i, (_, x: string) => ` ${x.toLowerCase()}`);
  return `${day}, ${time}`;
}
