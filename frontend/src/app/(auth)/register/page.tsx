"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { trialTerms, usePlans } from "@/lib/plans";
import { useEffect, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { GoogleSignIn, useGoogleError } from "@/components/GoogleAuth";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { emailRule, passwordRule, phoneRule, required, useForm } from "@/lib/form";

export default function RegisterPage() {
  const { refresh } = useAuth();
  const router = useRouter();
  const { cardRequired } = usePlans();
  const [busy, setBusy] = useState(false);
  const f = useForm({ full_name: "", email: "", phone: "", password: "" }, {
    full_name: required("Your name"), email: emailRule, password: passwordRule, phone: phoneRule,
  });

  // Who may register is decided by the backend (REGISTRATION_MODE); this only tells people before they type a password. The server refuses regardless of what this page shows.
  const [mode, setMode] = useState<"open" | "allowlist" | "closed" | null>(null);
  useEffect(() => {
    api<{ mode: "open" | "allowlist" | "closed" }>("/auth/registration").then((r) => setMode(r.mode)).catch(() => setMode("open"));
  }, []);

  const googleError = useGoogleError();
  useEffect(() => { if (googleError) f.fail(googleError); }, [googleError]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const v = f.values;
      await api("/auth/register", { method: "POST", body: { full_name: v.full_name.trim(), email: v.email.trim(), phone: v.phone.trim() || null, password: v.password } });
      if (!(await refresh())) { f.fail("Your account was created, but your browser did not keep the session. Allow cookies for flowqr.site, then log in."); return; }
      router.replace("/onboarding");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  const footer = <>Already have an account? <Link href="/login" className="font-semibold text-[#C94C00] underline">Log in</Link></>;
  if (mode === "closed") {
    return (
      <AuthShell title="Registration is closed" subtitle="FlowQR is not taking new accounts right now." footer={footer}>
        <Alert tone="info">FlowQR is open to approved businesses only at the moment. If you expected access, contact FlowQR support. If you already have an account, log in.</Alert>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Create your FlowQR account" subtitle={`Takes about two minutes. ${trialTerms(cardRequired)}`} footer={footer}>
      {mode === "allowlist" && <div className="mb-4"><Alert tone="info">FlowQR is open to approved businesses only at the moment. Register with the email address you gave us. Other addresses are not accepted yet.</Alert></div>}
      <GoogleSignIn label="Sign up with Google" divider="or sign up with email" />
      <form onSubmit={submit} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Your name" autoComplete="name" required {...f.bind("full_name")} />
        <Input label="Work email" type="email" autoComplete="email" inputMode="email" required {...f.bind("email")} />
        <Input label="Mobile number (optional)" type="tel" autoComplete="tel" inputMode="tel" placeholder="98765 43210" hint="Indian mobile number" {...f.bind("phone")} />
        <Input label="Password" type="password" autoComplete="new-password" required hint="At least 10 characters with upper and lower case letters." {...f.bind("password")} />
        <Button type="submit" size="lg" variant="brand" className="w-full" loading={busy}>Create account</Button>
        <p className="text-center text-xs text-ink-500">By creating an account you agree to use FlowQR honestly: no fake reviews, no review gating.</p>
      </form>
    </AuthShell>
  );
}
