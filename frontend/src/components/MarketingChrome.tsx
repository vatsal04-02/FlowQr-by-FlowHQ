import Link from "next/link";
import { Logo } from "./ui/Brand";
import { LinkButton } from "./ui/Button";

export function MarketingHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-ink-100 bg-white/90 backdrop-blur">
      <div className="container-page flex items-center justify-between py-3">
        <Logo />
        <nav className="flex items-center gap-1 sm:gap-2" aria-label="Site">
          <Link href="/#how" className="tap hidden items-center rounded-xl px-3 text-sm font-semibold text-ink-700 hover:bg-ink-50 sm:inline-flex">How it works</Link>
          <Link href="/#features" className="tap hidden items-center rounded-xl px-3 text-sm font-semibold text-ink-700 hover:bg-ink-50 sm:inline-flex">Features</Link>
          <Link href="/pricing" className="tap inline-flex items-center rounded-xl px-3 text-sm font-semibold text-ink-700 hover:bg-ink-50">Pricing</Link>
          <Link href="/login" className="tap inline-flex items-center rounded-xl px-3 text-sm font-semibold text-ink-700 hover:bg-ink-50">Log in</Link>
          <LinkButton href="/register" size="sm">Start free trial</LinkButton>
        </nav>
      </div>
    </header>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-ink-100 py-8">
      <div className="container-page flex flex-col gap-3 text-sm text-ink-500 sm:flex-row sm:items-center sm:justify-between">
        <p>© {new Date().getFullYear()} FlowHQ. FlowQR is a FlowHQ product.</p>
        <p className="max-w-xl">FlowQR is not affiliated with, endorsed by or sponsored by Google. Google and Google Business Profile are trademarks of Google LLC.</p>
      </div>
    </footer>
  );
}
