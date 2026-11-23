"use client";
import clsx from "clsx";
import { CalendarClock, Check, Hash, Layers } from "lucide-react";
import type { ReactNode } from "react";
import { rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";

const COLOURS = ["#171A45", "#C2410C", "#FB923C", "#0F766E", "#4338CA", "#D97706"];

/** A short burst of confetti behind the ticket. Pure CSS (see .fq-confetti), positions are fixed arithmetic so the markup is the same on every render, and it is not drawn at all when the person asks for reduced motion. */
function Confetti() {
  return (
    <div aria-hidden className="fq-confetti pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {Array.from({ length: 44 }, (_, i) => (
        <i key={i} style={{ left: `${(i * 37) % 100}%`, background: COLOURS[i % COLOURS.length], animationDelay: `${(i % 11) * 0.12}s`, animationDuration: `${2.6 + (i % 7) * 0.35}s`, transform: `rotate(${(i * 53) % 360}deg)`, width: i % 3 ? 8 : 6, height: i % 3 ? 14 : 10 }} />
      ))}
    </div>
  );
}

function Row({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 py-3">
      <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-set-paper text-set-soft">{icon}</span>
      <div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-[.06em] text-set-muted">{label}</p><p className="mt-0.5 break-words text-[15px] font-bold text-set-ink">{children}</p></div>
    </div>
  );
}

/** The receipt shown once the server has confirmed a prepaid payment. Every figure is what the server returned for this order; nothing is filled in. */
export function PaymentTicket({ plan, months, amountPaise, endsAt, orderId, className }: { plan: string; months: number; amountPaise: number; endsAt: string | null; orderId: string; className?: string }) {
  return (
    <>
      <Confetti />
      <section aria-label="Payment receipt" className={clsx("relative z-10 mx-auto w-full max-w-sm rounded-[24px] border border-set-line bg-set-surface shadow-[0_12px_32px_rgb(20_22_58/.10)] fq-enter", className)}>
        <div className="flex flex-col items-center px-6 pb-6 pt-8 text-center">
          <span className="grid h-16 w-16 place-items-center rounded-full bg-set-ok-bg text-set-ok"><span className="grid h-11 w-11 place-items-center rounded-full bg-set-ok-dot text-white"><Check className="h-6 w-6" strokeWidth={3} aria-hidden /></span></span>
          <h2 className="mt-4 text-[22px] font-extrabold tracking-[-0.01em] text-set-ink">Payment received</h2>
          <p className="mt-1 text-sm text-set-muted">Your {plan} plan is active.</p>
          <p className="num mt-4 text-[36px] font-extrabold leading-none tracking-[-0.02em] text-set-ink">{rupees(amountPaise)}</p>
        </div>
        <div aria-hidden className="relative">
          <div className="mx-6 border-t-2 border-dashed border-set-line-strong/70" />
          <span className="absolute -left-3 -top-3 h-6 w-6 rounded-full border border-set-line bg-set-paper [clip-path:inset(0_0_0_50%)]" />
          <span className="absolute -right-3 -top-3 h-6 w-6 rounded-full border border-set-line bg-set-paper [clip-path:inset(0_50%_0_0)]" />
        </div>
        <dl className="divide-y divide-set-line px-6 py-2">
          <Row icon={<Layers className="h-4 w-4" />} label="Plan">{plan} · {months} month{months === 1 ? "" : "s"}</Row>
          {endsAt && <Row icon={<CalendarClock className="h-4 w-4" />} label="Runs until">{fmtDate(endsAt)}</Row>}
          <Row icon={<Hash className="h-4 w-4" />} label="Reference"><span className="font-mono text-[13px] font-semibold">{orderId}</span></Row>
        </dl>
        <p className="border-t-2 border-dashed border-set-line-strong/70 px-6 py-4 text-center text-[13px] leading-5 text-set-muted">One payment. Nothing renews by itself, and nothing more is charged unless you buy again.</p>
      </section>
    </>
  );
}
