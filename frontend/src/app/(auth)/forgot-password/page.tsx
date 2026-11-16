"use client";
import Link from "next/link";
import { useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { emailRule, useForm } from "@/lib/form";

export default function ForgotPassword() {
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const f = useForm({ email: "" }, { email: emailRule });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.validateAll()) return;
    setBusy(true);
    try { await api("/auth/password-reset/request", { method: "POST", body: { email: f.values.email.trim() } }); setDone(true); }
    catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  return (
    <AuthShell title="Reset your password" subtitle="We'll email you a link to choose a new one." footer={<Link href="/login" className="font-semibold text-brand-700 hover:underline">Back to log in</Link>}>
      {done ? <Alert tone="success" title="Check your inbox">If an account exists for that email, a reset link is on its way. It expires in 30 minutes.</Alert> : (
        <form onSubmit={submit} noValidate className="space-y-4">
          <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
          <Input label="Email" type="email" autoComplete="email" required {...f.bind("email")} />
          <Button type="submit" size="lg" variant="brand" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
    </AuthShell>
  );
}
