"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Inner() {
  const token = useSearchParams().get("token") ?? "";
  const { me, loading, refresh } = useAuth();
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (loading) return <Spinner />;
  if (!me) return (
    <div className="space-y-3">
      <Alert tone="info">Log in (or create an account) with the email address that received this invitation, then come back to this link.</Alert>
      <div className="flex gap-2"><LinkButton href="/login">Log in</LinkButton><LinkButton href="/register" variant="secondary">Create account</LinkButton></div>
    </div>
  );
  async function accept() {
    setBusy(true); setErr(null);
    try { await api("/invitations/accept", { method: "POST", body: { token } }); await refresh(); router.replace("/overview"); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-4">
      <p className="text-ink-700">You're signed in as <b>{me.user.email}</b>.</p>
      {err && <Alert tone="error">{err}</Alert>}
      <Button size="lg" variant="brand" className="w-full" loading={busy} onClick={() => void accept()}>Accept invitation</Button>
      <p className="text-center text-sm"><Link href="/overview" className="text-brand-700 hover:underline">Not now</Link></p>
    </div>
  );
}
export default function AcceptInvite() {
  return <AuthShell title="Join your team on FlowQR"><Suspense><Inner /></Suspense></AuthShell>;
}
