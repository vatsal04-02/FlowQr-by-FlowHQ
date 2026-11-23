"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";

/** Target of the "Stop these emails" link in notification emails. Needs no sign-in; asks first so a mail scanner opening the link changes nothing. */
function Inner() {
  const token = useSearchParams().get("t") ?? "";
  const [state, setState] = useState<"ask" | "working" | "done" | "error">(token ? "ask" : "error");
  const [msg, setMsg] = useState(token ? "" : "This link is missing its code.");
  async function confirm() {
    setState("working");
    try { await api(`/notifications/unsubscribe?t=${encodeURIComponent(token)}`, { method: "POST" }); setState("done"); }
    catch (e) { setMsg(errorMessage(e)); setState("error"); }
  }
  if (state === "done") return <div className="space-y-4"><Alert tone="success" title="You're unsubscribed">We won&rsquo;t send you these emails any more. You can still see everything in the bell inside FlowQR, and turn emails back on in Settings &rsaquo; Notifications.</Alert><LinkButton href="/login" variant="secondary">Log in</LinkButton></div>;
  if (state === "error") return <Alert tone="error" title="Couldn't unsubscribe">{msg} Log in and switch the emails off in Settings &rsaquo; Notifications instead.</Alert>;
  return <div className="space-y-4"><p className="text-[14px] text-ink-600">Stop FlowQR&rsquo;s notification emails for this business? Account emails such as password resets and payment problems are not affected.</p><Button onClick={confirm} loading={state === "working"}>Unsubscribe</Button></div>;
}
export default function Unsubscribe() { return <AuthShell title="Unsubscribe"><Suspense><Inner /></Suspense></AuthShell>; }
