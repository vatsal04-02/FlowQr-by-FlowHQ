"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { passwordRule, useForm } from "@/lib/form";

function Inner() {
  const token = useSearchParams().get("token") ?? "";
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const f = useForm({ password: "" }, { password: passwordRule });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.validateAll()) return;
    setBusy(true);
    try { await api("/auth/password-reset/confirm", { method: "POST", body: { token, new_password: f.values.password } }); setDone(true); }
    catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  if (!token) return <Alert tone="error" title="Missing reset link">Open the link from your email, or request a new one.</Alert>;
  return done ? (
    <Alert tone="success" title="Password updated" action={<Link href="/login" className="font-semibold underline">Log in</Link>}>You've been signed out everywhere for safety.</Alert>
  ) : (
    <form onSubmit={submit} noValidate className="space-y-4">
      <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
      <Input label="New password" type="password" autoComplete="new-password" required hint="At least 10 characters, upper and lower case." {...f.bind("password")} />
      <Button type="submit" size="lg" className="w-full" loading={busy}>Set new password</Button>
    </form>
  );
}
export default function ResetPassword() {
  return <AuthShell title="Choose a new password"><Suspense><Inner /></Suspense></AuthShell>;
}
