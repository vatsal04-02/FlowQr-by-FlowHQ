"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { api, errorMessage } from "@/lib/api";

/** "Resend the verification email", with the answer shown next to the button. The server refuses billing actions until the address is verified (403 email_not_verified); this is the way out. */
export function ResendVerification({ onCheck }: { onCheck?: () => void | Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function resend() {
    setBusy(true); setNote(null);
    try {
      const r = await api<{ email_sent: boolean; detail: string }>("/auth/resend-verification", { method: "POST" });
      setNote(r.email_sent ? "Verification email sent. Open the link in it, then come back here." : r.detail);
    } catch (e) { setNote(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="secondary" loading={busy} onClick={() => void resend()}>Resend verification email</Button>
      {onCheck && <Button size="sm" variant="ghost" onClick={() => void onCheck()}>I have verified it</Button>}
      {note && <span className="text-[13px]" role="status">{note}</span>}
    </span>
  );
}
