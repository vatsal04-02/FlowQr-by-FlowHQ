"use client";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { ClosedNote, RegisterFields, useRegister } from "@/components/auth/RegisterForm";
import { trialTerms } from "@/lib/plans";

export default function RegisterPage() {
  const r = useRegister();
  const { mode, mandateRequired, trialDays } = r;

  const footer = <>Already have an account? <Link href="/login" className="font-semibold text-[#C94C00] underline">Log in</Link></>;
  if (mode === "closed") {
    return (
      <AuthShell title="Registration is closed" subtitle="FlowQR is not taking new accounts right now." footer={footer}>
        <ClosedNote />
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Create your FlowQR account" subtitle={`Takes about two minutes. ${trialTerms(mandateRequired)}`} footer={footer}
      mobileNote={<>{trialDays}-day free trial{trialTerms(mandateRequired) ? <> · {trialTerms(mandateRequired).replace(/\.$/, "")}</> : null}</>}
      points={["Create your account.", "Add your business. If you are on Google, we will find it for you.", mandateRequired ? "Pick a plan and authorise UPI AutoPay or a card. Your first payment is after the free trial." : "Pick a plan and start your free trial."]}>
      <RegisterFields r={r} />
    </AuthShell>
  );
}
