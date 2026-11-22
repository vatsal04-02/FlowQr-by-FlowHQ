/**
 * Marketing analytics events (PRD §5): calculator_calculate, faq_open, card_enquiry_submit.
 * Pushed to window.dataLayer if an analytics tag is installed; otherwise nothing is sent anywhere.
 */
type Win = Window & { dataLayer?: Record<string, unknown>[] };

export function track(event: string, props: Record<string, unknown> = {}) {
  if (typeof window === "undefined") return;
  (window as Win).dataLayer?.push({ event, ...props });
}
