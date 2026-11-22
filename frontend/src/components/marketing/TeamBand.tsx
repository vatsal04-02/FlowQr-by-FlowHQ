import { ArrowRight, Check, QrCode } from "lucide-react";
import Link from "next/link";
import { en } from "@/content/marketing/en";
import { GoogleG, SectionHead, WhatsAppLogo } from "./kit";
import { Rise } from "./motion";
import { ScrollWords } from "./scroll";

/**
 * "Meet your marketing team": the three agents side by side, one job each, so the page says what FlowQR is (a team) before it explains any one agent. Each card links to where that agent is
 * explained. The WhatsApp agent carries a "Coming soon" chip because it is built but not open to customers yet (see content/marketing/en.ts, `whatsapp`). Copy lives in en.home.squad.
 */
const c = en.home.squad;

function Icon({ i }: { i: number }) {
  if (i === 0) return <GoogleG size={26} />;
  if (i === 2) return <WhatsAppLogo size={26} />;
  return <QrCode className="h-6 w-6 text-m-navy" strokeWidth={1.5} aria-hidden />;
}

export function TeamBand() {
  return (
    <section aria-labelledby="team-h" className="py-10 md:py-16">
      <div className="mkt-wrap">
        <Rise><SectionHead id="team-h" title={c.title} sub={<ScrollWords text={c.sub} />} /></Rise>
        <ul className="mt-9 grid gap-4 md:mt-12 md:grid-cols-3">
          {c.agents.map((a, i) => (
            <Rise as="li" key={a.name} delay={0.08 + i * 0.07} y={16} blur={false} className="h-full">
              <Link href={a.href} className="group flex h-full flex-col rounded-[20px] bg-m-surface p-5 shadow md:p-6-[var(--shadow-card)] transition-shadow duration-300 hover:shadow-[var(--shadow-float)]">
                <span className="flex items-start justify-between gap-3">
                  <span className="grid h-12 w-12 place-items-center rounded-full bg-m-bg" aria-hidden><Icon i={i} /></span>
                  {a.tag && <span className="inline-flex h-6 items-center rounded-full bg-m-ink/[.06] px-2.5 text-[12px] font-semibold text-m-ink2">{a.tag}</span>}
                </span>
                <h3 className="mt-4 text-[21px] md:mt-5 md:text-[22px] font-medium leading-tight tracking-[-.02em] text-m-ink">{a.name}</h3>
                <p className="mb-5 mt-2 text-[15px] leading-relaxed text-m-ink2">{a.job}</p>
                <span className="mt-auto flex items-center gap-2 border-t border-m-line pt-4 text-[14px] text-m-ink">
                  <span aria-hidden className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[#157347]"><Check className="h-3 w-3 text-white" strokeWidth={3} /></span>{a.approve}
                </span>
                <span className="mt-4 inline-flex items-center gap-1.5 text-[14px] font-medium text-m-accentStrong">
                  {a.cta}<ArrowRight aria-hidden className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={1.75} />
                </span>
              </Link>
            </Rise>
          ))}
        </ul>
      </div>
    </section>
  );
}
