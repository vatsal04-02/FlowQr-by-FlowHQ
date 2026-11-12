"use client";
import { useEffect, useState } from "react";
import { buttonClass } from "@/components/ui/Button";

// What the backend callback puts in /login?google_error=... (or /settings?google_error=...).
const MESSAGES: Record<string, string> = {
  access_denied: "Google sign-in was cancelled. You can try again or use your email and password.",
  invalid_state: "Your Google sign-in session expired or was opened in a different browser. Please try again.",
  invalid_nonce: "Your Google sign-in session expired. Please try again.",
  invalid_token: "We couldn't verify your Google sign-in. Please try again.",
  exchange_failed: "We couldn't complete Google sign-in. Please try again in a moment.",
  not_configured: "Google sign-in isn't available on this server yet. Please use your email and password.",
  email_not_verified: "Google hasn't verified that email address, so we can't use it to sign you in.",
  account_unverified: "An account with this email already exists but its email hasn't been verified. Log in with your password (or open the verification email we sent), then connect Google from Settings.",
  already_linked: "A different Google account is already connected to this FlowQR account.",
  account_disabled: "This account is disabled. Contact FlowQR support.",
  session_mismatch: "You were signed in as a different user. Please try connecting Google again.",
};

/** Reads and clears ?google_error= once, returning a human message (or null). */
export function useGoogleError(): string | null {
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    const url = new URL(window.location.href);
    const code = url.searchParams.get("google_error");
    if (!code) return;
    setMessage(MESSAGES[code] ?? "Google sign-in didn't complete. Please try again.");
    url.searchParams.delete("google_error");
    window.history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
  }, []);
  return message;
}

function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" className="h-5 w-5" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

/** Full-page navigation (not fetch): the server sets the OAuth cookie and redirects to Google. */
export function GoogleButton({ label = "Continue with Google" }: { label?: string }) {
  const [going, setGoing] = useState(false);
  return (
    <a href="/api/v1/auth/google/start" onClick={() => setGoing(true)} aria-busy={going || undefined}
      className={buttonClass("secondary", "lg", "w-full")}>
      <GoogleG />{going ? "Opening Google…" : label}
    </a>
  );
}

export function OrDivider({ children = "or use email" }: { children?: string }) {
  return (
    <div className="my-5 flex items-center gap-3 text-xs font-medium text-ink-500" role="separator" aria-label={children}>
      <span className="h-px flex-1 bg-ink-200" /><span>{children}</span><span className="h-px flex-1 bg-ink-200" />
    </div>
  );
}
