import { api } from "./api";

export const rupees = (paise: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(paise / 100);

export const FEATURE_LABELS: Record<string, string> = {
  review_sync: "Google review sync", ai_replies: "AI reply drafts", gbp_info: "Edit business info, hours & categories",
  gbp_posts: "Google Posts", gbp_media: "Photo management", gbp_performance: "Google performance metrics", insights: "Sentiment & topic insights",
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
  new Razorpay({ ...rest, name: "FlowQR by FlowHQ", theme: { color: "#1A5FD0" }, handler: onSuccess, modal: { ondismiss: onDismiss } }).open();
}

export { api };
