"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** The page the "confirm deleting your account" email opens. The link is NOT used just by opening it (mail scanners open links): a person has to press the button. The link works once. */
function Inner() {
  const token = useSearchParams().get("token") ?? "";
  const { refresh } = useAuth();
  const [state, setState] = useState<"ready" | "working" | "ok" | "error">(token ? "ready" : "error");
  const [msg, setMsg] = useState(token ? "" : "This link is missing its token.");

  async function confirm() {
    setState("working");
    try { await api("/account/me/deletion/confirm", { method: "POST", body: { token } }); setState("ok"); await refresh(); }
    catch (e) { setState("error"); setMsg(errorMessage(e)); }
  }

  if (state === "ok") {
    return <div className="space-y-4"><Alert tone="success" title="Deletion confirmed">Your account is scheduled for deletion. You have been signed out everywhere. You can still log in during the grace period and cancel it in Settings, Account. We will email you when it is done.</Alert><LinkButton href="/login" variant="secondary">Back to log in</LinkButton></div>;
  }
  if (state === "error") {
    return <div className="space-y-4"><Alert tone="error" title="This link can't be used">{msg} If you still want to delete your account, log in and request it again from Settings, Account.</Alert><LinkButton href="/login" variant="secondary">Log in</LinkButton></div>;
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-700">You asked to delete your FlowQR account. If you confirm, you will be signed out everywhere and your account will be deleted after the grace period, unless you cancel. No business will be deleted.</p>
      <Button variant="danger" loading={state === "working"} onClick={() => void confirm()}>Yes, delete my account</Button>
      <p className="text-xs text-ink-500">Did not ask for this? Close this page and change your password.</p>
    </div>
  );
}
export default function ConfirmAccountDeletion() { return <AuthShell title="Confirm account deletion"><Suspense><Inner /></Suspense></AuthShell>; }
