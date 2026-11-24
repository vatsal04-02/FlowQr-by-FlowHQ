import { Star } from "lucide-react";
import type { ReactNode } from "react";
import { backgroundStyle, COPY, effectiveBrand, landingStyle, type Background } from "@/lib/review-growth";

export interface FrameBusiness { name: string; logo_url: string | null; location?: string | null }
export interface FrameBranding { brand_color: string; background: Background; welcome_message: string | null; footer_message: string | null }

/**
 * The customer-facing shell: a navy header with the business, then a white sheet that carries the page. Used by the real page and by every live preview.
 * The owner's colour still drives the stars' glow, buttons and card edge (a business that never chose one gets FlowQR orange); the page background setting tints the sheet (Plain and Soft stay white).
 */
export function LandingFrame({ business, branding, children, preview, note, poweredBy = "Powered by" }: { business: FrameBusiness; branding: FrameBranding; children: ReactNode; preview?: boolean; note?: ReactNode; poweredBy?: string }) {
  // A live preview sits INSIDE a dashboard page that already has its own main landmark and its own h1: it must not add a second of either (screen readers would announce two main regions and two page titles).
  const Root = preview ? "div" : "main";
  const Title = preview ? "p" : "h1";
  const sheet = branding.background === "plain" || branding.background === "soft" ? { background: "#FFFFFF" } : backgroundStyle(branding.background, effectiveBrand(branding.brand_color));
  return (
    <div style={{ ...landingStyle(effectiveBrand(branding.brand_color)) }} className={`${preview ? "min-h-full" : "min-h-dvh"} bg-[#F5F4F0] sm:py-8`}>
      <Root className="mx-auto flex w-full max-w-[440px] flex-col overflow-hidden sm:min-h-0 sm:rounded-[28px] sm:shadow-[0_30px_60px_-30px_rgba(18,22,63,.55)]" style={{ minHeight: preview ? undefined : "100dvh" }}>
        <header className="px-5 pb-9 pt-[max(1.25rem,env(safe-area-inset-top))] text-white" style={{ background: "radial-gradient(120% 90% at 100% 0%, rgba(234,88,12,.30), transparent 55%), linear-gradient(160deg, #171A45 0%, #2A2E69 100%)" }}>
          <div className="flex items-center gap-3.5">
            {business.logo_url
              ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={business.logo_url} alt="" className="h-12 w-12 shrink-0 rounded-xl bg-white object-cover" />
              : <span aria-hidden className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-white text-[22px] font-extrabold text-[#12163F]">{business.name.charAt(0).toUpperCase()}</span>}
            <div className="min-w-0">
              <Title className="truncate text-[17px] font-extrabold leading-tight tracking-tight text-white">{business.name}</Title>
              {business.location && <p className="truncate text-[13px] text-[#C9CBE8]">{business.location}</p>}
            </div>
          </div>
          {note && <p className="mt-3.5 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-[12px] font-semibold text-white ring-1 ring-white/10">{note}</p>}
        </header>
        <div className="-mt-6 flex-1 rounded-t-[28px] px-5 pb-8 pt-7 shadow-[0_-12px_30px_-18px_rgba(23,26,69,.55)]" style={sheet}>
          {branding.welcome_message && <p className="mb-5 rounded-2xl bg-[#F6F4EF] px-4 py-3 text-[15px] leading-relaxed text-ink-700">{branding.welcome_message}</p>}
          {children}
          <footer className="mt-8 text-center text-xs text-ink-500">
            {branding.footer_message && <p className="mb-2 text-[13px] text-ink-700">{branding.footer_message}</p>}
            <p className="flex items-center justify-center gap-1.5">{poweredBy}<span className="text-[17px] font-extrabold tracking-tight text-[#171A45]">flow<span className="text-[#C2410C]">qr</span></span></p>
            <p className="mt-1 text-[11px] text-ink-400">No incentives, no filtering of reviews</p>
          </footer>
        </div>
      </Root>
    </div>
  );
}

/** Non-interactive sample of the customer's single screen, for the dashboard's live previews. */
export function PreviewForm({ lang = "en", ai = true, topics }: { lang?: "en" | "hi"; ai?: boolean; topics?: { en: string; hi: string }[] }) {
  const c = COPY[lang];
  const sample = (topics?.length ? topics : [{ en: "Friendly staff", hi: "मिलनसार स्टाफ़" }, { en: "Clean clinic", hi: "साफ़-सफ़ाई" }, { en: "No long wait", hi: "कम इंतज़ार" }]).slice(0, 6);
  return (
    <div aria-hidden className="pointer-events-none select-none">
      <h2 className="text-[1.7rem] font-extrabold leading-tight tracking-tight text-ink">{c.h}</h2>
      <div className="mt-4 flex items-center justify-between">{[1, 2, 3, 4, 5].map((n) => <Star key={n} className="h-9 w-9" strokeWidth={1.6} style={n <= 4 ? { fill: "#F5A524", color: "#D9890A", filter: "drop-shadow(0 3px 6px rgba(245,165,36,.5))" } : { fill: "#F4F2EC", color: "#CFCBBF" }} />)}</div>
      <p className="mt-1 text-center text-[17px] font-bold text-[#9A3412]">{c.rateWords[3]}</p>
      <div className="mt-3 flex items-baseline justify-between"><p className="text-[15px] font-bold text-ink">{c.topicsLabel}</p><span className="text-xs text-ink-500">{c.topicsHint}</span></div>
      <div className="mt-2 flex flex-wrap gap-2">
        {sample.map((s, i) => (
          <span key={s.en} className={`inline-flex min-h-10 items-center rounded-full px-3.5 text-sm font-semibold ${i === 0 ? "bg-[#171A45] text-white" : "bg-white text-ink ring-1 ring-[#E4E1D9]"}`}>{lang === "hi" ? s.hi : s.en}</span>
        ))}
      </div>
      <div className="mt-4 rounded-[18px] p-[2px]" style={{ background: "linear-gradient(135deg, #F5A524, var(--brand))" }}>
        <div className="rounded-[16px] bg-white p-3.5"><span className="rounded-full bg-[#FFEFE5] px-2.5 py-1 text-[11px] font-bold text-[#9A3412]">{c.badgeRefined}</span><div className="mt-2 h-14 text-sm leading-relaxed text-ink-400">{c.editorPh}</div></div>
      </div>
      <div className="mt-4 flex min-h-12 items-center justify-center gap-2 rounded-2xl px-5 text-[15px] font-bold text-[var(--on-brand)]" style={{ background: "linear-gradient(135deg, var(--brand), color-mix(in srgb, var(--brand) 78%, #000))" }}>{c.cta}</div>
    </div>
  );
}
