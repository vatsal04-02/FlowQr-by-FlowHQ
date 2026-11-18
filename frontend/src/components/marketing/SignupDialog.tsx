"use client";
import Link from "next/link";
import { ClosedNote, RegisterFields, useRegister } from "@/components/auth/RegisterForm";
import { Modal } from "@/components/ui/Modal";
import { trialTerms } from "@/lib/plans";

/**
 * Sign up in a window over the page (the pricing page's plan buttons open it). It is the same form as /register (components/auth/RegisterForm.tsx): same checks, same 18+ confirmation, same
 * server call, and the same place afterwards (onboarding). The form is only mounted while the window is open. The buttons that open it are real links to /register, so a new tab, a
 * copied link or a browser without scripts all still reach the full page.
 */
function Body() {
  const r = useRegister();
  const sub = `${r.trialDays}-day free trial. ${trialTerms(r.mandateRequired)}`.trim();
  return (
    <>
      <p className="-mt-2 mb-4 text-[14px] text-ink-600">{r.mode === "closed" ? "FlowQR is not taking new accounts right now." : sub}</p>
      {r.mode === "closed" ? <ClosedNote /> : <RegisterFields r={r} />}
      <p className="mt-5 text-center text-[14px] text-ink-600">Already have an account? <Link href="/login" className="font-semibold text-[#C94C00] underline">Log in</Link></p>
    </>
  );
}

export function SignupDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <Modal open={open} onClose={onClose} title="Start your free trial">{open && <Body />}</Modal>;
}
