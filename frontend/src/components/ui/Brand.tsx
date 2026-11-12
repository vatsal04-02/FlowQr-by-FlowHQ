import clsx from "clsx";
import Link from "next/link";
import { useId } from "react";

/** FlowQR mark: the original FlowHQ orange tile with the QR-flow glyph. Original artwork, not Google's. */
export function LogoMark({ size = 32 }: { size?: number }) {
  // Unique id per instance: the logo renders in both the (display:none) desktop sidebar and the mobile header,
  // and a gradient defined inside a hidden SVG does not resolve for a duplicate id elsewhere on the page.
  const gid = `fq-logo-${useId().replace(/:/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="FlowQR" className="shrink-0">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FF8A3D" /><stop offset="1" stopColor="#E85A0C" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${gid})`} />
      <rect x="7" y="7" width="7" height="7" rx="1.8" fill="#fff" />
      <rect x="18" y="7" width="7" height="7" rx="1.8" fill="#fff" opacity=".75" />
      <rect x="7" y="18" width="7" height="7" rx="1.8" fill="#fff" opacity=".75" />
      <path d="M18.5 21.5h2.2a2.3 2.3 0 0 0 2.3-2.3V18" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" fill="none" />
      <circle cx="23.5" cy="23.5" r="1.7" fill="#fff" />
    </svg>
  );
}

export function Logo({ href = "/", className, tagline = true, dark = false }: { href?: string; className?: string; tagline?: boolean; dark?: boolean }) {
  return (
    <Link href={href} className={clsx("inline-flex items-center gap-2.5 rounded-lg", className)} aria-label="FlowQR by FlowHQ home">
      <LogoMark />
      <span className="leading-tight">
        <span className={clsx("block text-[17px] font-bold tracking-tight", dark ? "text-white" : "text-ink")}>Flow<span className={dark ? "text-flow-400" : "text-flow-700"}>QR</span></span>
        {tagline && <span className={clsx("block text-xs font-medium", dark ? "text-ink-200" : "text-ink-500")}>by FlowHQ</span>}
      </span>
    </Link>
  );
}
