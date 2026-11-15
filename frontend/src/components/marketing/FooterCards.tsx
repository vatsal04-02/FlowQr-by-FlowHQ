"use client";
import Link from "next/link";
import { Logo } from "../ui/Brand";
import { useFetch } from "@/lib/use-api";
import { MButton } from "./kit";
import { Rise } from "./motion";

/** DESIGN.md §5.11: tint brand card, white link card, navy card. The support email comes from the server (never invented). */
export function FooterCards() {
  const { data } = useFetch<{ support_email: string | null }>("/legal/info");
  return (
    <footer className="pb-10 pt-6">
      <div className="mkt-wrap">
        <div className="grid gap-3 md:grid-cols-[1.3fr_1fr_1fr]">
          <div className="flex min-h-[200px] flex-col justify-between rounded-[20px] bg-m-tint p-7 md:min-h-[260px]">
            <div>
              <Logo size={44} />
              <p className="mt-4 max-w-[260px] t-small text-m-ink2">Your local AI marketing team.</p>
            </div>
            <div className="mt-8 space-y-1 text-[13px] text-m-muted">
              {data?.support_email && <p><a className="hover:text-m-ink" href={`mailto:${data.support_email}`}>{data.support_email}</a></p>}
              <p>© {new Date().getFullYear()} FlowHQ</p>
            </div>
          </div>
          <nav aria-label="Product" className="rounded-[20px] bg-m-surface p-7">
            <p className="t-small text-m-muted">Product</p>
            <ul className="mt-4 space-y-1">
              {[["Google Business", "/google-business"], ["Review Cards", "/review-cards"], ["AI Growth Agent", "/ai-growth-agent"], ["Industries", "/industries"], ["Pricing", "/pricing"]].map(([t, h]) => (
                <li key={h}><Link href={h} className="inline-flex min-h-11 items-center text-[22px] md:min-h-9 font-medium tracking-[-.03em] text-m-ink hover:text-m-accentStrong">{t}</Link></li>
              ))}
            </ul>
          </nav>
          <div className="flex min-h-[220px] flex-col justify-between rounded-[20px] bg-m-navy p-7 text-white md:min-h-[260px]">
            <div>
              <p className="t-small text-white/60">For custom systems</p>
              <Rise><p className="mt-4 text-[26px] font-medium leading-[1.05] tracking-[-.035em]">FlowHQ builds automation <span className="text-white/60">for your team</span></p></Rise>
            </div>
            <MButton href="/about#services" variant="dark" icon="arrow" className="mt-8 self-start">Speak with us</MButton>
          </div>
        </div>
        <div className="mt-6 flex flex-col gap-3 text-[13px] text-m-muted md:flex-row md:items-center md:justify-between">
          <p className="flex flex-wrap gap-x-4 gap-y-1">
            {[["Privacy", "/privacy"], ["Terms", "/terms"], ["Refunds", "/refund-policy"], ["Delete your data", "/data-deletion"]].map(([t, h]) => <Link key={h} href={h} className="inline-flex min-h-11 items-center hover:text-m-ink md:min-h-8">{t}</Link>)}
          </p>
          <p className="max-w-[560px]">Google and Google Business Profile are trademarks of Google LLC. FlowQR is not affiliated with Google.</p>
        </div>
        <p className="mt-4 text-[12px] leading-relaxed text-m-muted">Pictures: <a className="underline" href="https://commons.wikimedia.org/w/index.php?curid=15511964">Commercial Street, Bangalore</a> by Jay Bergesen, CC BY 2.0; <a className="underline" href="https://commons.wikimedia.org/w/index.php?curid=29631722">Street shop for sweets, Rajasthan</a> by Felipe Skroski, CC BY 2.0; <a className="underline" href="https://commons.wikimedia.org/wiki/File:A_store_inside_Moazzam_Jahi_Market_in_Hyderabad.jpg">A store inside Moazzam Jahi Market, Hyderabad</a> by Mouryan, CC BY-SA 4.0; <a className="underline" href="https://commons.wikimedia.org/w/index.php?curid=16489092">Beauty salon, Deccan Odyssey</a> by Simon Pielow, CC BY-SA 2.0; <a className="underline" href="https://commons.wikimedia.org/w/index.php?curid=150240815">Kebab &amp; Curry Indian Restaurant</a> by Chongkian, CC BY-SA 4.0. All via Wikimedia Commons.</p>
      </div>
    </footer>
  );
}
