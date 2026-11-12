import Link from "next/link";
import { Logo } from "../ui/Brand";
import { LinkButton } from "../ui/Button";

const link = "tap relative inline-flex items-center whitespace-nowrap rounded-lg px-2.5 text-sm font-medium text-ink-700 transition-colors hover:bg-ink-100/70 hover:text-ink sm:min-h-9";

export function MarketingHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-ink-100 bg-white">
      <div className="container-page flex items-center justify-between py-2.5">
        <Logo />
        <nav className="flex items-center gap-0.5 sm:gap-1" aria-label="Site">
          <Link href="/#how" className={`${link} hidden lg:inline-flex`}>How it works</Link>
          <Link href="/#product" className={`${link} hidden lg:inline-flex`}>The card</Link>
          <Link href="/pricing" className={`${link} hidden min-[440px]:inline-flex`}>Pricing</Link>
          <Link href="/#trust" className={`${link} hidden md:inline-flex`}>Trust</Link>
          <Link href="/#faq" className={`${link} hidden md:inline-flex`}>FAQ</Link>
          <Link href="/login" className={link}>Log in</Link>
          <LinkButton href="/register" size="sm">Start free trial</LinkButton>
        </nav>
      </div>
    </header>
  );
}

export function MarketingFooter() {
  const col = "space-y-1.5 text-sm";
  const a = "text-ink-700 hover:text-ink hover:underline";
  return (
    <footer className="border-t border-ink-100 bg-white py-10">
      <div className="container-page grid gap-8 sm:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div><Logo /><p className="mt-3 max-w-xs text-[13px] text-ink-500">Physical review cards and the software to manage what comes back. A FlowHQ product.</p></div>
        <nav aria-label="Product"><p className="eyebrow mb-2">Product</p><ul className={col}>
          <li><Link className={a} href="/#how">How it works</Link></li><li><Link className={a} href="/#reviews">Reviews</Link></li><li><Link className={a} href="/#cards">Cards</Link></li><li><Link className={a} href="/#analytics">Analytics</Link></li></ul></nav>
        <nav aria-label="Company"><p className="eyebrow mb-2">Learn</p><ul className={col}>
          <li><Link className={a} href="/pricing">Pricing</Link></li><li><Link className={a} href="/#trust">Compliance and trust</Link></li><li><Link className={a} href="/#faq">FAQ</Link></li></ul></nav>
        <nav aria-label="Account"><p className="eyebrow mb-2">Account</p><ul className={col}>
          <li><Link className={a} href="/login">Log in</Link></li><li><Link className={a} href="/register">Start free trial</Link></li></ul></nav>
      </div>
      <div className="container-page mt-8 flex flex-col gap-2 border-t border-ink-100 pt-5 text-xs text-ink-500 sm:flex-row sm:items-start sm:justify-between">
        <p>© {new Date().getFullYear()} FlowHQ. FlowQR is a FlowHQ product. <Link className="underline hover:text-ink" href="/privacy">Privacy</Link> · <Link className="underline hover:text-ink" href="/terms">Terms</Link> · <Link className="underline hover:text-ink" href="/data-deletion">Delete your data</Link></p>
        <p className="max-w-xl">FlowQR is not affiliated with, endorsed by or sponsored by Google. Google and Google Business Profile are trademarks of Google LLC.</p>
      </div>
    </footer>
  );
}
