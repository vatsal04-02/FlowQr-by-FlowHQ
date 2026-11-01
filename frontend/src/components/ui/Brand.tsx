import clsx from "clsx";
import Link from "next/link";

/** FlowQR mark: orange rounded tile with a stylised QR-flow glyph. Original artwork, not Google's. */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="FlowQR" className="shrink-0">
      <rect width="32" height="32" rx="9" fill="#F26B1D" />
      <rect x="7" y="7" width="7" height="7" rx="1.8" fill="#fff" />
      <rect x="18" y="7" width="7" height="7" rx="1.8" fill="#fff" opacity=".75" />
      <rect x="7" y="18" width="7" height="7" rx="1.8" fill="#fff" opacity=".75" />
      <path d="M18.5 21.5h2.2a2.3 2.3 0 0 0 2.3-2.3V18" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" fill="none" />
      <circle cx="23.5" cy="23.5" r="1.7" fill="#fff" />
    </svg>
  );
}

export function Logo({ href = "/", className, tagline = true }: { href?: string; className?: string; tagline?: boolean }) {
  return (
    <Link href={href} className={clsx("inline-flex items-center gap-2.5 rounded-lg", className)} aria-label="FlowQR by FlowHQ home">
      <LogoMark />
      <span className="leading-tight">
        <span className="block font-display text-[17px] font-semibold text-ink">Flow<span className="text-flow-600">QR</span></span>
        {tagline && <span className="block text-[11px] font-medium text-ink-500">by FlowHQ</span>}
      </span>
    </Link>
  );
}
