"use client";
import { Check, Copy, Send } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";

/**
 * Send a campaign's review page to a customer. On a phone this opens the phone's own share sheet (WhatsApp, SMS, email: whatever the person has); where the browser has no
 * share sheet, or the person cancels into nothing, a small sheet shows the link with a Copy button. No messaging integration is used or needed.
 */
export function SendLink({ url, name, label = "Send link", variant = "secondary", size = "sm", className }: { url: string; name: string; label?: string; variant?: "secondary" | "primary" | "brand"; size?: "sm" | "md"; className?: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = `Thank you for visiting ${name}. It would help us a lot if you left a short Google review:`;
  async function go() {
    const nav = navigator as Navigator & { share?: (d: ShareData) => Promise<void> };
    if (nav.share) {
      try { await nav.share({ title: name, text, url }); return; }
      catch (e) { if ((e as DOMException)?.name === "AbortError") return; }  // the person closed the share sheet: nothing more to do
    }
    setOpen(true);
  }
  async function copy() {
    try { await navigator.clipboard.writeText(url); } catch { const i = document.getElementById("send-link-url") as HTMLInputElement | null; i?.select(); document.execCommand?.("copy"); }
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  }
  return (
    <>
      <Button variant={variant} size={size} className={className} icon={<Send className="h-4 w-4" aria-hidden />} onClick={() => void go()}>{label}</Button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Send review link">
        <label htmlFor="send-link-url" className="text-[13px] text-muted">Link to your review page</label>
        <div className="mt-1 flex gap-2">
          <input id="send-link-url" readOnly value={url} onFocus={(e) => e.currentTarget.select()} className="min-h-11 min-w-0 flex-1 rounded-[12px] bg-surface-2 px-3 text-[14px]" />
          <Button onClick={() => void copy()} icon={copied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}>{copied ? "Copied" : "Copy"}</Button>
        </div>
        <a href={`https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex min-h-11 items-center text-[14px] font-medium underline underline-offset-2">Open in WhatsApp</a>
      </Sheet>
    </>
  );
}
