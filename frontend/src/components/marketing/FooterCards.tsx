"use client";
import Link from "next/link";
import { Logo } from "../ui/Brand";
import { useFetch } from "@/lib/use-api";
import { MButton } from "./kit";
import { TrialNote } from "./TrialNote";

/** The site footer: one full-width navy band. Brand and a demo button, three link columns, then the legal line. The support email comes from the server (never invented). */
const COLUMNS: { title: string; links: [string, string][] }[] = [
  { title: "Product", links: [["Google Business", "/google-business"], ["Review Cards", "/review-cards"], ["AI Growth Agent", "/ai-growth-agent"]] },
  { title: "Company", links: [["Industries", "/industries"], ["Pricing", "/pricing"], ["About", "/about"], ["FlowHQ services", "/about#services"]] },
  { title: "Legal", links: [["Privacy", "/privacy"], ["Terms", "/terms"], ["Refunds", "/refund-policy"], ["Delete your data", "/data-deletion"]] },
];
const LINK = "inline-flex min-h-9 items-center text-[15px] text-white/75 transition-colors hover:text-white focus-visible:!outline-white";

export function FooterCards() {
  const { data } = useFetch<{ support_email: string | null }>("/legal/info");
  return (
    <footer className="mt-8 bg-m-navy text-white">
      <div className="mkt-wrap py-12 md:py-16">
        <div className="grid gap-10 lg:grid-cols-[1.2fr_2fr] lg:gap-16">
          <div>
            <Logo dark size={40} />
            <p className="mt-5 max-w-[320px] text-[15px] leading-relaxed text-white/75">Google reviews and review cards for local businesses.</p>
            <div className="mt-6 flex flex-wrap items-center gap-2.5"><MButton href="/register" event="signup_cta_click">Sign up</MButton><Link href="/login" className="inline-flex min-h-11 items-center rounded-full border border-white/40 px-5 text-[14px] font-medium text-white transition-colors hover:bg-white/10 focus-visible:!outline-white">Log in</Link></div>
            <TrialNote className="mt-3 text-[13px] text-white/60" />
            {data?.support_email && <p className="mt-5 text-[14px]"><a className="text-white/75 underline-offset-4 hover:text-white hover:underline focus-visible:!outline-white" href={`mailto:${data.support_email}`}>{data.support_email}</a></p>}
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-3">
            {COLUMNS.map((col) => (
              <div key={col.title}>
                <p className="text-[12px] font-semibold uppercase tracking-[.08em] text-white/50">{col.title}</p>
                <ul className="mt-3 space-y-0.5">
                  {col.links.map(([t, h]) => <li key={h}><Link href={h} className={LINK}>{t}</Link></li>)}
                </ul>
              </div>
            ))}
          </nav>
        </div>
        <div className="mt-12 flex flex-col gap-2 border-t border-white/15 pt-6 text-[13px] text-white/60 md:flex-row md:items-center md:justify-between">
          <p>&copy; {new Date().getFullYear()} FlowHQ. All rights reserved.</p>
          <p className="max-w-[560px] md:text-right">Google and Google Business Profile are trademarks of Google LLC. FlowQR is not affiliated with Google.</p>
        </div>
      </div>
    </footer>
  );
}
