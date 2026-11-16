"use client";
import clsx from "clsx";
import { ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Logo } from "../ui/Brand";
import { MButton } from "./kit";

export const PRODUCT: [string, string, string][] = [
  ["Google Business", "/google-business", "Profile, reviews, replies, posts"],
  ["Review Cards", "/review-cards", "QR + NFC cards and the review page"],
  ["AI Growth Agent", "/ai-growth-agent", "A daily plan you approve"],
];
const LINKS: [string, string][] = [["Industries", "/industries"], ["Pricing", "/pricing"], ["About", "/about"]];

/** DESIGN.md §5.1: floating pill nav. Transparent at the top, a light blurred surface after 40px of scroll. */
export function Nav() {
  const [solid, setSolid] = useState(false);
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const on = () => setSolid(window.scrollY > 40);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  useEffect(() => {
    if (!open && !menu) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); setMenu(false); btn.current?.focus(); } };
    window.addEventListener("keydown", k);
    if (open) document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = ""; };
  }, [open, menu]);
  const link = "inline-flex min-h-11 items-center px-3 t-small text-m-ink2 hover:text-m-ink";
  return (
    <header className="sticky top-4 z-40 px-4">
      <div className={clsx("mx-auto flex max-w-[1080px] items-center justify-between gap-3 rounded-full p-1.5 transition-[background,box-shadow] duration-300",
        solid || open ? "bg-white/80 shadow-[0_1px_2px_rgba(11,15,46,.06),0_8px_24px_rgba(11,15,46,.06)] backdrop-blur-md" : "bg-transparent")}>
        <Logo tagline={false} size={30} className="h-11 px-2.5" />
        <nav aria-label="Site" className="hidden items-center lg:flex">
          <div className="relative" onMouseLeave={() => setMenu(false)}>
            <button type="button" className={link} aria-expanded={menu} aria-controls="product-menu" onClick={() => setMenu((v) => !v)}>
              Product <ChevronDown className={clsx("ml-1 h-3.5 w-3.5 transition-transform", menu && "rotate-180")} strokeWidth={1.5} aria-hidden />
            </button>
            {menu && (
              <div id="product-menu" className="absolute left-0 top-full w-[300px] pt-2">
                <ul className="rounded-[14px] bg-m-surface p-2 shadow-[var(--shadow-float)]">
                  {PRODUCT.map(([t, h, d]) => (
                    <li key={h}><Link href={h} onClick={() => setMenu(false)} className="block rounded-[10px] px-3 py-2.5 hover:bg-m-bg"><span className="block t-small text-m-ink">{t}</span><span className="block text-[12.5px] text-m-muted">{d}</span></Link></li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          {LINKS.map(([t, h]) => <Link key={h} href={h} className={link}>{t}</Link>)}
        </nav>
        <div className="flex items-center gap-1">
          <Link href="/login" className={clsx(link, "hidden sm:inline-flex")}>Log in</Link>
          <MButton href="/register" event="signup_cta_click" className="hidden sm:inline-flex">Sign up</MButton>
          <button ref={btn} type="button" aria-expanded={open} aria-controls="site-menu" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen((v) => !v)}
            className="grid h-11 w-11 place-items-center rounded-full text-m-ink hover:bg-m-ink/[.05] lg:hidden">
            {open ? <X className="h-5 w-5" strokeWidth={1.5} aria-hidden /> : <Menu className="h-5 w-5" strokeWidth={1.5} aria-hidden />}
          </button>
        </div>
      </div>
      {open && (
        <nav id="site-menu" aria-label="Site menu" className="fixed inset-x-0 bottom-0 top-[76px] z-30 overflow-y-auto bg-m-bg px-4 pb-10 lg:hidden">
          <p className="mt-4 t-micro text-m-muted">Product</p>
          <ul className="mt-1 divide-y divide-m-line">
            {[...PRODUCT.map(([t, h]) => [t, h] as [string, string]), ...LINKS, ["Log in", "/login"] as [string, string]].map(([t, h]) => (
              <li key={h}><Link href={h} onClick={() => setOpen(false)} className="flex min-h-14 items-center text-[20px] font-medium tracking-[-.02em] text-m-ink">{t}</Link></li>
            ))}
          </ul>
          <MButton href="/register" event="signup_cta_click" className="mt-6 w-full justify-between" onClick={() => setOpen(false)}>Sign up</MButton>
        </nav>
      )}
    </header>
  );
}
