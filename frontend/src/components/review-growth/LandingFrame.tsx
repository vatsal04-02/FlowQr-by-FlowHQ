import { Star } from "lucide-react";
import type { ReactNode } from "react";
import { LogoMark } from "@/components/ui/Brand";
import { backgroundStyle, COPY, landingStyle, type Background } from "@/lib/review-growth";

export interface FrameBusiness { name: string; logo_url: string | null; location?: string | null }
export interface FrameBranding { brand_color: string; background: Background; welcome_message: string | null; footer_message: string | null }

/** The customer-facing shell: business identity, brand colour, background and footer. Used by the real page and by every live preview. */
export function LandingFrame({ business, branding, children, preview }: { business: FrameBusiness; branding: FrameBranding; children: ReactNode; preview?: boolean }) {
  return (
    <div style={{ ...landingStyle(branding.brand_color), ...backgroundStyle(branding.background, branding.brand_color) }} className={preview ? "min-h-full" : "min-h-dvh"}>
      <main className="mx-auto w-full max-w-md px-5 pb-10 pt-[max(1.75rem,env(safe-area-inset-top))]">
        <header className="flex items-center gap-3.5">
          {business.logo_url
            ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={business.logo_url} alt="" className="h-14 w-14 shrink-0 rounded-2xl border border-black/5 bg-white object-cover shadow-panel" />
            : <span aria-hidden className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-[var(--brand)] text-2xl font-semibold text-[var(--on-brand)] shadow-panel">{business.name.charAt(0).toUpperCase()}</span>}
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold leading-tight tracking-tight text-ink">{business.name}</h1>
            {business.location && <p className="truncate text-sm text-ink-500">{business.location}</p>}
          </div>
        </header>
        {branding.welcome_message && <p className="mt-5 rounded-2xl bg-white/80 px-4 py-3 text-[15px] leading-relaxed text-ink-700 shadow-panel ring-1 ring-black/5">{branding.welcome_message}</p>}
        <div className="mt-6">{children}</div>
        <footer className="mt-10 border-t border-black/5 pt-5 text-center text-xs text-ink-500">
          {branding.footer_message && <p className="mb-2 text-[13px] text-ink-700">{branding.footer_message}</p>}
          <p className="flex items-center justify-center gap-2"><LogoMark size={16} />Powered by FlowQR · no incentives, no filtering of reviews</p>
        </footer>
      </main>
    </div>
  );
}

/** Non-interactive sample of the customer's single screen, for the dashboard's live previews. */
export function PreviewForm({ lang = "en", ai = true, topics }: { lang?: "en" | "hi"; ai?: boolean; topics?: { en: string; hi: string }[] }) {
  const c = COPY[lang];
  const sample = (topics?.length ? topics : [{ en: "Staff", hi: "स्टाफ़" }, { en: "Cleanliness", hi: "सफ़ाई" }, { en: "Waiting time", hi: "इंतज़ार का समय" }]).slice(0, 6);
  return (
    <div aria-hidden className="pointer-events-none select-none">
      <h2 className="text-[1.7rem] font-semibold leading-tight tracking-tight text-ink">{c.h}</h2>
      <p className="mt-1.5 text-[15px] text-ink-500">{c.sub}</p>
      <p className="mt-4 text-sm font-semibold text-ink-700">{c.rateLabel}</p>
      <div className="mt-1 flex items-center gap-1">{[1, 2, 3, 4, 5].map((n) => <Star key={n} className="h-8 w-8" strokeWidth={1.75} style={n <= 4 ? { fill: "var(--brand)", color: "var(--brand)" } : { color: "#C9C7C1" }} />)}</div>
      <p className="mt-4 text-sm font-semibold text-ink-700">{c.topicsLabel}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {sample.map((s, i) => (
          <span key={s.en} className={`inline-flex min-h-10 items-center rounded-full px-3.5 text-sm font-medium ring-1 ${i === 0 ? "bg-[var(--brand)] text-[var(--on-brand)] ring-transparent" : "bg-white text-ink-700 ring-ink-300"}`}>{lang === "hi" ? s.hi : s.en}</span>))}
      </div>
      <div className="mt-4 rounded-2xl bg-white p-3.5 shadow-panel ring-1 ring-black/5">
        <div className="h-16 text-sm leading-relaxed text-ink-400">{c.editorPh}</div>
      </div>
      <div className="mt-4 flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[var(--brand)] px-5 text-[15px] font-semibold text-[var(--on-brand)] shadow-panel">{c.cta}</div>
    </div>
  );
}