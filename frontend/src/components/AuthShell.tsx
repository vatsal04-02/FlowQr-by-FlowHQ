import type { ReactNode } from "react";
import { Logo } from "./ui/Brand";
import { GoogleDots } from "./ui/Card";
import { CheckCircle2 } from "lucide-react";

export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_minmax(420px,520px)]">
      <aside className="relative hidden overflow-hidden bg-brand-900 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="relative z-10 inline-flex items-center gap-2 font-display text-lg font-semibold"><Logo className="[&_span]:!text-white" /></div>
        <div className="relative z-10 max-w-md">
          <GoogleDots className="mb-5 scale-125 origin-left" />
          <h2 className="!text-white text-3xl font-semibold leading-tight">More honest reviews, handled in minutes.</h2>
          <ul className="mt-6 space-y-3 text-brand-100">
            {["Unique QR/NFC cards for every location", "AI that polishes your customers' own words", "Reply drafts you approve before anything goes live"].map((t) => (
              <li key={t} className="flex items-start gap-2.5"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-g-green" aria-hidden />{t}</li>
            ))}
          </ul>
        </div>
        <p className="relative z-10 text-xs text-brand-200">FlowQR is a product of FlowHQ and is not affiliated with or endorsed by Google.</p>
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand-700/60" aria-hidden />
        <div className="pointer-events-none absolute -bottom-20 right-10 h-56 w-56 rounded-full bg-flow-500/20" aria-hidden />
      </aside>
      <main className="flex flex-col justify-center px-5 py-10 sm:px-10">
        <div className="mx-auto w-full max-w-md">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h1 className="text-2xl font-semibold sm:text-3xl">{title}</h1>
          {subtitle && <p className="mt-2 text-ink-500">{subtitle}</p>}
          <div className="mt-7">{children}</div>
          {footer && <div className="mt-6 text-center text-sm text-ink-500">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
