import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { FlowCard } from "./CardArt";
import { Logo } from "./ui/Brand";

const POINTS = ["A permanent QR/NFC link for every card and location", "AI that tidies your customers' own words, never invents them", "Reply drafts that only publish after you approve them"];

export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(440px,540px)]">
      <aside className="hidden bg-ink p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <Logo dark />
        <div>
          <p className="eyebrow !text-gold-400">FlowQR by FlowHQ</p>
          <h2 className="mt-3 max-w-md text-[2rem] font-bold leading-[1.12] tracking-[-.025em]">Collect reviews at the counter. Manage your reputation in one place.</h2>
          <ul className="mt-6 max-w-md space-y-2.5 text-[15px] text-ink-200">
            {POINTS.map((t) => <li key={t} className="flex items-start gap-3"><Check className="mt-1 h-4 w-4 shrink-0 text-gold-400" strokeWidth={2.6} aria-hidden />{t}</li>)}
          </ul>
          <div className="mt-8 w-[210px] -rotate-2" style={{ filter: "drop-shadow(0 22px 26px rgba(0,0,0,.5))" }}><FlowCard code="FQR-0001" /></div>
        </div>
        <p className="max-w-md text-xs text-ink-200">FlowQR is a product of FlowHQ and is not affiliated with or endorsed by Google.</p>
      </aside>
      <main className="flex flex-col justify-center bg-white px-5 py-10 sm:px-10">
        <div className="mx-auto w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h1 className="text-2xl font-bold">{title}</h1>
          {subtitle && <p className="mt-1.5 text-sm text-ink-500">{subtitle}</p>}
          <div className="mt-6">{children}</div>
          {footer && <div className="mt-6 text-center text-sm text-ink-500">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
