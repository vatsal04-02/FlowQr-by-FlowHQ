"use client";
import clsx from "clsx";
import { ArrowLeft, Check, CreditCard, LogOut, MapPin, PartyPopper, Star, type LucideIcon } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Poster } from "@/components/marketing/Poster";
import { Button } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Brand";

/** The four set-up steps. `lead` is the line shown on the progress panel while the step is current. */
export const STEPS: { title: string; hint: string; lead: string; icon: LucideIcon }[] = [
  { title: "Your business", hint: "Name, address and contact", lead: "Let's put your business on the map.", icon: MapPin },
  { title: "Collecting reviews", hint: "Your review link or Google", lead: "How should reviews reach you?", icon: Star },
  { title: "Plan and card", hint: "Start your free trial", lead: "Pick a plan and start your free trial.", icon: CreditCard },
  { title: "Launch", hint: "Your first review page", lead: "Nearly there. One last look.", icon: PartyPopper },
];

/**
 * The frame around every set-up step. Wide screens: a navy progress panel on the left (the real FlowQR card peeking out of its corner) and the step on the right.
 * Phones: a slim progress bar above the step. Finished steps are buttons, so a person can go back and change what they entered.
 */
export function WizardShell({ step, email, onSignOut, onGo, children }: { step: number; email?: string; onSignOut: () => void; onGo: (step: number) => void; children: ReactNode }) {
  const cur = STEPS[Math.min(step, STEPS.length - 1)];
  return (
    <div className="mkt wiz relative isolate min-h-dvh overflow-x-clip bg-m-bg">
      {/* warm backdrop: two soft orange glows and a faint dot grid, all decorative */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -left-40 -top-40 h-[560px] w-[560px] rounded-full bg-[radial-gradient(closest-side,rgba(254,106,5,.16),rgba(254,106,5,0))]" />
        <div className="absolute -right-32 top-[30%] h-[520px] w-[520px] rounded-full bg-[radial-gradient(closest-side,rgba(255,178,122,.28),rgba(255,178,122,0))]" />
        <div className="absolute inset-0 opacity-50 [background-image:radial-gradient(rgba(11,15,46,.10)_1px,transparent_1.2px)] [background-size:24px_24px] [mask-image:linear-gradient(to_bottom,#000,transparent_70%)]" />
      </div>

      <header>
        <div className="mx-auto flex h-[68px] max-w-[1120px] items-center justify-between gap-3 px-4 sm:px-6">
          <Logo tagline={false} />
          <div className="flex items-center gap-1">
            {email && <p className="hidden max-w-[240px] truncate text-[13px] text-m-muted sm:block">{email}</p>}
            <button type="button" onClick={onSignOut} className="inline-flex min-h-11 items-center gap-2 rounded-full px-3 text-[14px] font-medium text-m-ink2 hover:bg-m-ink/[.05]">
              <LogOut className="h-4 w-4" aria-hidden />Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1120px] gap-6 px-4 pb-16 pt-2 sm:px-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:gap-10 lg:pt-6">
        {/* phones and tablets */}
        <nav aria-label="Set-up progress" className="lg:hidden">
          <p className="flex items-center justify-between gap-3 text-[13px]">
            <span className="inline-flex items-center gap-2 font-semibold text-m-ink"><span aria-hidden className="grid h-7 w-7 place-items-center rounded-full bg-m-accent text-m-ink"><cur.icon className="h-3.5 w-3.5" strokeWidth={2} /></span>Step {step + 1} of {STEPS.length}</span>
            <span className="text-m-muted">{cur.title}</span>
          </p>
          <ol className="mt-3 grid grid-cols-4 gap-1.5">
            {STEPS.map((s, i) => (
              <li key={s.title} aria-current={i === step ? "step" : undefined} className={clsx("h-1.5 rounded-full transition-colors duration-500", i < step ? "bg-m-navy" : i === step ? "bg-m-accent" : "bg-m-ink/10")}>
                <span className="sr-only">{s.title}{i < step ? ", done" : i === step ? ", current" : ""}</span>
              </li>
            ))}
          </ol>
        </nav>

        {/* wide screens */}
        <aside className="hidden lg:block">
          <div className="sticky top-6 flex min-h-[620px] flex-col overflow-hidden rounded-[28px] bg-m-navy p-8 text-white shadow-[0_28px_64px_-28px_rgba(17,23,63,.55)]">
            <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-[radial-gradient(closest-side,rgba(254,106,5,.45),rgba(254,106,5,0))]" />
            <p className="relative text-[12px] font-semibold uppercase tracking-[.1em] text-white/60">Set up FlowQR</p>
            <h2 key={step} className="fq-rise relative mt-3 text-[27px] font-semibold leading-[1.1] tracking-[-.03em] [text-wrap:balance]">{cur.lead}</h2>
            <nav aria-label="Set-up progress" className="relative mt-8">
              <ol>
                {STEPS.map((s, i) => {
                  const done = i < step, now = i === step;
                  const inner = (
                    <>
                      <span className={clsx("relative z-10 grid h-9 w-9 shrink-0 place-items-center rounded-full text-[13px] font-semibold transition-colors duration-300",
                        done ? "bg-m-accent text-m-ink" : now ? "bg-white text-m-ink ring-4 ring-m-accent/40" : "bg-white/10 text-white/70 ring-1 ring-white/20")}>
                        {done ? <Check className="h-4 w-4" strokeWidth={3} aria-hidden /> : <s.icon className="h-4 w-4" strokeWidth={1.75} aria-hidden />}
                      </span>
                      <span className="pt-1">
                        <span className={clsx("block text-[15px] font-medium leading-tight", now ? "text-white" : done ? "text-white/90 group-hover:underline" : "text-white/60")}>{s.title}{done && <span className="sr-only">, done. Go back to edit</span>}</span>
                        <span className="mt-0.5 block text-[13px] leading-snug text-white/55">{s.hint}</span>
                      </span>
                    </>
                  );
                  return (
                    <li key={s.title} aria-current={now ? "step" : undefined} className="relative pb-6 last:pb-0">
                      {i < STEPS.length - 1 && <span aria-hidden className={clsx("absolute left-[17px] top-10 h-[calc(100%-2.5rem)] w-px", done ? "bg-m-accent" : "bg-white/15")} />}
                      {done
                        ? <button type="button" onClick={() => onGo(i)} className="group flex w-full gap-3.5 rounded-[12px] text-left focus-visible:!outline-white">{inner}</button>
                        : <div className="flex gap-3.5">{inner}</div>}
                    </li>
                  );
                })}
              </ol>
            </nav>
            <p className="relative mt-auto max-w-[150px] pt-8 text-[13px] leading-relaxed text-white/60">About three minutes. You can change everything later.</p>
            {/* the real card, tilted and cropped by the corner of the panel */}
            <div aria-hidden className="pointer-events-none absolute -bottom-16 -right-10 w-[168px] rotate-[9deg] opacity-95" style={{ filter: "drop-shadow(0 18px 24px rgba(0,0,0,.4))" }}><Poster alt="" /></div>
          </div>
        </aside>

        <main className="min-w-0">{children}</main>
      </div>
    </div>
  );
}

/** The card every step sits in. It rises in once per step; motion is switched off for people who ask for less of it (globals.css). */
export function StepCard({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <section className={clsx("wiz-card fq-rise p-5 sm:p-9", wide ? "max-w-[860px]" : "max-w-[720px]")}>{children}</section>;
}

/** The step title: an icon tile, "Step n of 4", the title and one line of help. It takes focus when the step appears, so a keyboard or screen-reader user starts at the top of the new step. */
export function StepHeading({ step, title, children }: { step: number; title: string; children?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  const Icon = STEPS[step]?.icon ?? Star;
  useEffect(() => {
    window.scrollTo({ top: 0 });
    ref.current?.focus({ preventScroll: true });
  }, []);
  return (
    <div className="flex items-start gap-4">
      <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-[16px] bg-m-tint text-m-accentStrong ring-1 ring-m-accent/20"><Icon className="h-6 w-6" strokeWidth={1.75} /></span>
      <div className="min-w-0">
        <p className="text-[12px] font-semibold uppercase tracking-[.1em] text-m-accentStrong">Step {step + 1} of {STEPS.length}</p>
        <h1 ref={ref} tabIndex={-1} style={{ outline: "none" }} className="mt-1 text-[28px] font-semibold leading-[1.1] tracking-[-.035em] text-m-ink sm:text-[34px]">{title}</h1>
        {children && <p className="mt-2.5 text-[15.5px] leading-relaxed text-m-muted">{children}</p>}
      </div>
    </div>
  );
}

/** A titled group inside a step: a small icon and heading, then its fields. Keeps a long form readable as a few short pieces. */
export function Section({ icon: Icon, title, hint, delay = 0, children }: { icon: LucideIcon; title: string; hint?: string; delay?: number; children: ReactNode }) {
  return (
    <section className="fq-rise" style={{ ["--d" as string]: `${delay}ms` }}>
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="grid h-7 w-7 place-items-center rounded-full bg-m-ink/[.06] text-m-ink2"><Icon className="h-3.5 w-3.5" strokeWidth={2} /></span>
        <h2 className="text-[15px] font-semibold text-m-ink">{title}</h2>
        {hint && <p className="ml-auto hidden text-[13px] text-m-muted sm:block">{hint}</p>}
      </div>
      <div className="mt-4 space-y-5">{children}</div>
    </section>
  );
}

/** The row under every step: Back on the left (when there is somewhere to go back to), the main action on the right. On phones the main action comes first and fills the width. */
export function StepActions({ onBack, backDisabled, children }: { onBack?: () => void; backDisabled?: boolean; children: ReactNode }) {
  return (
    <div className="mt-9 flex flex-col-reverse gap-3 border-t border-m-line pt-6 sm:flex-row sm:items-center sm:justify-between">
      {onBack ? <Button type="button" variant="ghost" onClick={onBack} disabled={backDisabled} icon={<ArrowLeft className="h-4 w-4" aria-hidden />}>Back</Button> : <span aria-hidden />}
      {children}
    </div>
  );
}
