import Link from "next/link";
import type { ReactNode } from "react";

/**
 * A four-column footer (adapted from the supplied "footer-column" block): the brand, a sentence and the main actions on the left; four titled link columns on the right; a rule and the
 * small print under them. It is a layout only: what goes in it is passed in (the marketing footer, components/marketing/FooterCards.tsx, passes FlowQR's own pages, the support address the
 * server reports, and the legal lines). The block's sample social links, phone number, address and "live chat" dot are not used: FlowQR has none of them to show.
 */
export type FooterLink = { text: string; href: string; icon?: ReactNode };
export type FooterColumn = { title: string; links: FooterLink[] };

const LINK = "inline-flex min-h-11 items-center gap-2 text-[14px] text-white/70 transition-colors hover:text-white focus-visible:!outline-white md:min-h-9";

export function FooterColumns({ brand, columns, left, right }: { brand: ReactNode; columns: FooterColumn[]; left: ReactNode; right: ReactNode }) {
  return (
    <footer className="mt-16 w-full rounded-t-[28px] bg-m-navy text-white">
      <div className="mkt-wrap pb-6 pt-14 lg:pt-20">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-3">
          <div>{brand}</div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-9 md:grid-cols-4 lg:col-span-2">
            {columns.map((col) => (
              <div key={col.title}>
                <p className="text-[17px] font-medium tracking-[-.01em] text-white">{col.title}</p>
                <ul className="mt-4 space-y-0.5">
                  {col.links.map((l) => (
                    <li key={l.href}>
                      {l.href.startsWith("mailto:") ? <a href={l.href} className={LINK}>{l.icon}<span className="break-all">{l.text}</span></a> : <Link href={l.href} className={LINK}>{l.icon}{l.text}</Link>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
        <div className="mt-12 flex flex-col gap-2 border-t border-white/15 pt-6 text-[13px] text-white/60 md:flex-row md:items-center md:justify-between">
          <p>{left}</p>
          <p className="max-w-[560px] md:text-right">{right}</p>
        </div>
      </div>
    </footer>
  );
}
