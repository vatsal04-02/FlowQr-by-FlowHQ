import { load } from "@cashfreepayments/cashfree-js";
import { api } from "./api";

export const rupees = (paise: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(paise / 100);

export const FEATURE_LABELS: Record<string, string> = {
  review_sync: "Google review sync", ai_replies: "AI reply drafts", gbp_info: "Edit business info, hours & categories",
  gbp_posts: "Google Posts", gbp_media: "Photo management", gbp_performance: "Google performance metrics", insights: "Sentiment & topic insights",
  local_seo: "Local SEO", keyword_tracking: "Keyword tracking", geo_ranking: "Geographic ranking maps", autonomy: "Autonomous SEO maintenance", ai_posts: "AI Google Posts",
  profile_optimizer: "AI Profile Optimizer", growth_agent: "AI Growth Agent", multi_location: "Multi-location management",
};

/** Wording for the history of a subscription (what happened, in plain language). */
export const EVENT_LABELS: Record<string, string> = {
  trial_started: "Free trial started", activated: "Subscription started", renewed: "Renewed", plan_changed: "Plan changed", plan_change_scheduled: "Plan change scheduled for the next renewal",
  cancel_requested: "Cancellation scheduled", canceled: "Cancelled", expired: "Expired", past_due: "A payment failed", payment_failed: "A payment failed", refunded: "A payment was refunded",
  promo_granted: "Free Growth month started (card purchase)", promo_ended: "Free Growth month ended", promo_revoked: "Free Growth month ended early (card refunded)", promo_denied: "No second free month",
  admin_override: "Changed by FlowQR support", status_changed: "Status changed",
  checkout_created: "Payment setup started", checkout_replaced: "An earlier payment setup was replaced", retry_requested: "We asked your bank to try the payment again",
  charge_after_cancel: "A payment arrived after you cancelled (support will refund it)", amount_mismatch: "A payment did not match your plan (support is checking)",
};

interface RazorpayOptions { key: string; name: string; description?: string; subscription_id?: string; order_id?: string; prefill?: { name?: string; email?: string }; theme?: { color: string }; handler: (r: Record<string, string>) => void; modal?: { ondismiss?: () => void } }
declare global { interface Window { Razorpay?: new (o: RazorpayOptions) => { open: () => void; on: (e: string, cb: (r: unknown) => void) => void } } }

/** Loads Razorpay's hosted checkout script on demand (only after the user clicks a pay button). */
export function loadRazorpay(): Promise<NonNullable<Window["Razorpay"]>> {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) return resolve(window.Razorpay);
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.async = true;
    s.onload = () => (window.Razorpay ? resolve(window.Razorpay) : reject(new Error("Razorpay unavailable")));
    s.onerror = () => reject(new Error("Couldn't load the payment window. Check your connection."));
    document.body.appendChild(s);
  });
}

export async function openCheckout(opts: Omit<RazorpayOptions, "handler" | "theme" | "name"> & { onSuccess: (r: Record<string, string>) => void; onDismiss?: () => void }) {
  const Razorpay = await loadRazorpay();
  const { onSuccess, onDismiss, ...rest } = opts;
  new Razorpay({ ...rest, name: "FlowQR by FlowHQ", theme: { color: "#BD3E1B" }, handler: onSuccess, modal: { ondismiss: onDismiss } }).open();
}

/** Opens Cashfree's hosted subscription checkout for a session the SERVER created. Whatever happens there, the app believes only what the server reads back from Cashfree (see the
 *  return page). The SDK is Cashfree's own package, pinned to an exact version; it loads https://sdk.cashfree.com/js/v3/cashfree.js and nothing else. */
export async function openCashfreeCheckout(sessionId: string, environment: string): Promise<void> {
  const cashfree = await load({ mode: environment === "production" ? "production" : "sandbox" });
  if (!cashfree) throw new Error("The payment window could not be loaded. Check your connection and try again.");
  const result = await cashfree.subscriptionsCheckout({ subsSessionId: sessionId, redirectTarget: "_self" });
  if (result?.error) throw new Error(result.error.message || "The payment window reported a problem. Nothing was charged.");
}

export { api };
