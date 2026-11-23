"use client";
import { Mail } from "lucide-react";
import Link from "next/link";
import { FooterColumns, type FooterColumn } from "@/components/ui/footer-column";
import { Logo } from "../ui/Brand";
import { useFetch } from "@/lib/use-api";
import { MButton } from "./kit";
import { TrialNote } from "./TrialNote";

/**
 * The site footer, in the four-column layout of components/ui/footer-column.tsx: brand and the two sign-up actions on the left; Product, Company, Legal and Contact on the right.
 * Nothing is invented: the links are the site's own pages, and the support email comes from the server (the Contact column shows it only when one is configured; the demo link is always there).
 */
const PRODUCT: FooterColumn = { title: "Product", links: [{ text: "Google Business", href: "/google-business" }, { text: "Review Cards", href: "/review-cards" }, { text: "AI Growth Agent", href: "/ai-growth-agent" }, { text: "WhatsApp Marketing AI Agent", href: "/whatsapp-marketing-ai-agent" }, { text: "Pricing", href: "/pricing" }] };
const COMPANY: FooterColumn = { title: "Company", links: [{ text: "Industries", href: "/industries" }, { text: "About", href: "/about" }, { text: "FlowHQ services", href: "/about#services" }] };
const LEGAL: FooterColumn = { title: "Legal", links: [{ text: "Privacy", href: "/privacy" }, { text: "Terms", href: "/terms" }, { text: "Cookies", href: "/cookie-policy" }, { text: "Refunds", href: "/refund-policy" }, { text: "Delete your data", href: "/data-deletion" }] };

export function FooterCards() {
  const { data } = useFetch<{ support_email: string | null }>("/legal/info");
  const email = data?.support_email;
  const contact: FooterColumn = {
    title: "Contact",
    links: [
      ...(email ? [{ text: email, href: `mailto:${email}`, icon: <Mail aria-hidden className="h-4 w-4 shrink-0 text-m-accent" strokeWidth={1.75} /> }] : []),
    ],
  };
  return (
    <FooterColumns
      columns={[PRODUCT, COMPANY, LEGAL, contact]}
      brand={
        <>
          <Logo dark size={40} />
          <p className="mt-5 max-w-[320px] text-[15px] leading-relaxed text-white/75">An AI marketing team for local businesses: Google, reviews and WhatsApp.</p>
          <div className="mt-6 flex flex-wrap items-center gap-2.5">
            <MButton href="/register" event="signup_cta_click">Sign up</MButton>
            <Link href="/login" className="inline-flex min-h-11 items-center rounded-full border border-white/40 px-5 text-[14px] font-medium text-white transition-colors hover:bg-white/10 focus-visible:!outline-white">Log in</Link>
          </div>
          <TrialNote className="mt-3 text-[13px] text-white/60" />
        </>
      }
      left={<>&copy; {new Date().getFullYear()} FlowHQ. All rights reserved.</>}
      right="Google and Google Business Profile are trademarks of Google LLC. FlowQR is not affiliated with Google."
    />
  );
}
