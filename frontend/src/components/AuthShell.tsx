/**
 * Sign-in and sign-up frame. The layout lives in components/ui/auth-page.tsx (split brand panel + form); this name stays so every auth page (log in, sign up, forgot and reset password,
 * verify email, accept invite) keeps importing `AuthShell` and they all share one look.
 */
export { AuthPage as AuthShell } from "./ui/auth-page";
