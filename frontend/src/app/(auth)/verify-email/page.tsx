"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Inner() {
  const token = useSearchParams().get("token") ?? "";
  const { refresh } = useAuth();
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!token) { setState("error"); setMsg("This link is missing its token."); return; }
    api("/auth/verify-email", { method: "POST", body: { token } })
      .then(async () => { setState("ok"); await refresh(); })
      .catch((e) => { setState("error"); setMsg(errorMessage(e)); });
  }, [token, refresh]);
  if (state === "working") return <Spinner label="Verifying your email" />;
  return state === "ok"
    ? <div className="space-y-4"><Alert tone="success" title="Email verified">Thanks! You can now invite your team, connect Google and manage billing.</Alert><LinkButton href="/dashboard">Go to dashboard</LinkButton></div>
    : <div className="space-y-4"><Alert tone="error" title="Couldn't verify your email">{msg} Log in and use &ldquo;Resend verification email&rdquo; to get a new link.</Alert><LinkButton href="/login" variant="secondary">Log in</LinkButton></div>;
}
export default function VerifyEmail() { return <AuthShell title="Verify your email"><Suspense><Inner /></Suspense></AuthShell>; }
