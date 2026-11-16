"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { GoogleSignIn, useGoogleError } from "@/components/GoogleAuth";
import { Button } from "@/components/ui/Button";
import { ErrorSummary, Input, PasswordInput } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { emailRule, required, useForm } from "@/lib/form";

export default function LoginPage() {
  const { me, loading, refresh } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const f = useForm({ email: "", password: "" }, { email: emailRule, password: required("Password") });

  const googleError = useGoogleError();

  useEffect(() => { if (!loading && me) router.replace("/overview"); }, [loading, me, router]);
  useEffect(() => { if (googleError) f.fail(googleError); }, [googleError]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      await api("/auth/login", { method: "POST", body: { email: f.values.email.trim(), password: f.values.password } });
      // Only move on once the browser really holds a session. If it refused the cookie (blocked third-party/site data), say so instead of bouncing back to this page silently.
      if (!(await refresh())) { f.fail("You were signed in, but your browser did not keep the session. Allow cookies for flowqr.site and try again."); return; }
      router.replace("/overview");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <AuthShell title="Welcome back" subtitle="Log in to manage your reviews and cards."
      pitch={{ title: "Pick up where you left off.", body: "Reviews to answer, posts to approve and cards to track, all in one place." }}
      footer={<>New to FlowQR? <Link href="/register" className="font-semibold text-[#C94C00] underline">Create an account</Link></>}>
      <GoogleSignIn divider="or use email" />
      <form onSubmit={submit} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Email" type="email" autoComplete="email" inputMode="email" required {...f.bind("email")} />
        <PasswordInput label="Password" autoComplete="current-password" required {...f.bind("password")} />
        <div className="flex justify-end"><Link href="/forgot-password" className="inline-flex min-h-11 items-center text-sm font-semibold text-[#C94C00] underline">Forgot password?</Link></div>
        <Button type="submit" size="lg" variant="brand" className="w-full" loading={busy}>Log in</Button>
      </form>
    </AuthShell>
  );
}
