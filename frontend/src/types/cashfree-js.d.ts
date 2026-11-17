// @cashfreepayments/cashfree-js 1.0.7 ships no type declarations. This is the part of its documented API that FlowQR uses
// (https://www.cashfree.com/docs/payments/subscription/hosted-checkout): load the SDK, then open the hosted subscription checkout for a session the server created.
declare module "@cashfreepayments/cashfree-js" {
  export interface CashfreeSdk {
    /** Payment Gateway hosted checkout for a ONE-TIME order the server created (https://www.cashfree.com/docs/payments/online/checkout/redirect). */
    checkout(options: { paymentSessionId: string; redirectTarget?: "_self" | "_blank" | "_top" | "_modal" }): Promise<{ error?: { message?: string } } | undefined>;
    subscriptionsCheckout(options: { subsSessionId: string; redirectTarget?: "_self" | "_blank" | "_top" | "_modal" }): Promise<{ error?: { message?: string } } | undefined>;
  }
  export function load(options: { mode: "sandbox" | "production" }): Promise<CashfreeSdk | null>;
}
