import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "./ui/Brand";
import { Poster } from "./marketing/Poster";
import { TrialHeadline, TrialPitch } from "./marketing/TrialHeadline";

/**
 * Sign-in and sign-up frame. Left: the brand panel (orange tint) with a short pitch and the real card, centred as one block so the panel
 * never reads as empty. Right: the form on white, wide enough to breathe. Pages can pass their own `pitch`; the default is the free trial.
 */
export function AuthShell({ title, subtitle, children, footer, pitch, points, mobileNote }: {
  title: string; subtitle?: string; children: ReactNode; footer?: ReactNode;
  pitch?: { title: ReactNode; body: string };
  /** A short numbered list under the pitch (what happens next). */ points?: ReactNode[];
  /** One line shown above the title on phones, where the brand panel is hidden. */ mobileNote?: ReactNode;
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
              {pitch ? pitch.body : <TrialPitch />}
            </p>
            {points && points.length > 0 && (
              <ol className="mt-7 max-w-[34ch] space-y-3.5">
                {points.map((p, i) => (
                  <li key={i} className="flex items-start gap-3 text-[15px] leading-snug text-m-ink">
                    <span aria-hidden className="mt-px grid h-6 w-6 shrink-0 place-items-center rounded-full bg-m-accent text-[12px] font-semibold text-m-ink">{i + 1}</span>
                    <span>{p}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="w-[260px] max-w-full" style={{ filter: "drop-shadow(0 22px 26px rgba(0,0,0,.18))" }}><Poster /></div>
        </div>
        <p className="max-w-md text-[13px] text-m-muted">FlowQR is a product of FlowHQ and is not affiliated with or endorsed by Google.</p>
      </aside>
      <main className="flex flex-col justify-center bg-white px-5 py-10 sm:px-10 lg:px-16">
        <div className="mx-auto w-full max-w-[420px]">
          <Link href="/" className="-ml-2 mb-4 inline-flex min-h-11 items-center gap-1.5 rounded-full px-2 text-[14px] font-medium text-m-muted hover:text-m-ink"><ArrowLeft className="h-4 w-4" aria-hidden />Back to website</Link>
          <div className="mb-8 lg:hidden"><Logo tagline={false} /></div>
          {mobileNote && <p className="mb-4 inline-flex rounded-full bg-m-tint px-3.5 py-1.5 text-[13px] font-medium text-m-ink lg:hidden">{mobileNote}</p>}
          <h1 className="text-[28px] font-semibold leading-tight tracking-[-.02em] text-m-ink">{title}</h1>
          {subtitle && <p className="mt-2 text-[15px] text-m-muted">{subtitle}</p>}
          <div className="mt-7">{children}</div>
          {footer && <div className="mt-7 text-center text-[15px] text-m-muted">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
