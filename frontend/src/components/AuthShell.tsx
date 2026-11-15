import type { ReactNode } from "react";
import { Logo } from "./ui/Brand";
import { Poster } from "./marketing/Poster";
import { TrialHeadline } from "./marketing/TrialHeadline";

/**
 * Sign-in and sign-up frame. Left: the brand panel (orange tint) with a short pitch and the real card, centred as one block so the panel
 * never reads as empty. Right: the form on white, wide enough to breathe. Pages can pass their own `pitch`; the default is the free trial.
 */
export function AuthShell({ title, subtitle, children, footer, pitch }: {
  title: string; subtitle?: string; children: ReactNode; footer?: ReactNode;
  pitch?: { title: ReactNode; body: string };
}) {
  return (
    <div className="mkt grid min-h-dvh lg:grid-cols-[minmax(0,1.1fr)_minmax(460px,.9fr)]">
      <aside className="hidden bg-m-tint px-12 py-10 lg:flex lg:flex-col xl:px-20">
        <Logo tagline={false} />
        <div className="my-auto grid max-w-[760px] items-center gap-12 py-12 xl:grid-cols-[1fr_auto]">
          <div>
            <h2 className="text-[clamp(32px,3.2vw,48px)] font-semibold leading-[1.05] tracking-[-.03em] text-m-ink [text-wrap:balance]">
              {pitch?.title ?? <TrialHeadline />}
            </h2>
            <p className="mt-5 max-w-[34ch] text-[17px] leading-relaxed text-m-ink">
              {pitch?.body ?? "No card needed. Connect your Google profile, put a FlowQR card on your counter, and approve everything before it goes live."}
            </p>
          </div>
          <div className="w-[260px] max-w-full" style={{ filter: "drop-shadow(0 22px 26px rgba(0,0,0,.18))" }}><Poster /></div>
        </div>
        <p className="max-w-md text-[13px] text-m-muted">FlowQR is a product of FlowHQ and is not affiliated with or endorsed by Google.</p>
      </aside>
      <main className="flex flex-col justify-center bg-white px-5 py-10 sm:px-10 lg:px-16">
        <div className="mx-auto w-full max-w-[420px]">
          <div className="mb-8 lg:hidden"><Logo tagline={false} /></div>
          <h1 className="text-[28px] font-semibold leading-tight tracking-[-.02em] text-m-ink">{title}</h1>
          {subtitle && <p className="mt-2 text-[15px] text-m-muted">{subtitle}</p>}
          <div className="mt-7">{children}</div>
          {footer && <div className="mt-7 text-center text-[15px] text-m-muted">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
