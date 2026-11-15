"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { GoogleButton, OrDivider, useGoogleError } from "@/components/GoogleAuth";
import { Button } from "@/components/ui/Button";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { emailRule, passwordRule, phoneRule, required, useForm } from "@/lib/form";

export default function RegisterPage() {
  const { refresh } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const f = useForm({ full_name: "", email: "", phone: "", password: "" }, {
    full_name: required("Your name"), email: emailRule, password: passwordRule, phone: phoneRule,
  });

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
      await refresh();
      router.replace("/onboarding");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <AuthShell title="Create your FlowQR account" subtitle="Takes about two minutes. No card needed."
      footer={<>Already have an account? <Link href="/login" className="font-semibold text-[#C94C00] underline">Log in</Link></>}>
      <GoogleButton label="Sign up with Google" />
      <OrDivider>or sign up with email</OrDivider>
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
