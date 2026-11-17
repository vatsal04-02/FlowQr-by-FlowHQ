import clsx from "clsx";
import Link from "next/link";

/**
 * The FlowQR mark: three QR squares and one opening outward ("your business, flowing out to new customers").
 * Four solid shapes on a 100-unit grid, so it stays sharp down to a 16px favicon. Navy #11173F, orange #FE6A05.
 *  - mark (default): navy squares, orange leaf, no tile
 *  - onDark: white squares, orange leaf (for navy grounds)
 *  - tile "orange" | "navy" | "light": the app icons
 *  - onAccent: white squares and a near-black leaf, no tile, for the dashboard's orange brand circle
 */
const NAVY = "#11173F", ORANGE = "#FE6A05";
const SQ = 45, R = 12, GAP = 10;
const LEAF = `M${SQ + GAP + 6} ${SQ + GAP}H100A45 45 0 0 1 ${SQ + GAP} 100V${SQ + GAP + 6}Q${SQ + GAP} ${SQ + GAP} ${SQ + GAP + 6} ${SQ + GAP}Z`;

function Shapes({ squares, leaf }: { squares: string; leaf: string }) {
  return (
    <>
      <rect x="0" y="0" width={SQ} height={SQ} rx={R} fill={squares} />
      <rect x={SQ + GAP} y="0" width={SQ} height={SQ} rx={R} fill={squares} />
      <rect x="0" y={SQ + GAP} width={SQ} height={SQ} rx={R} fill={squares} />
      <path d={LEAF} fill={leaf} />
    </>
  );
}

export function LogoMark({ size = 32, variant = "mark", className }: { size?: number; variant?: "mark" | "onDark" | "orange" | "navy" | "light" | "onAccent" | "auto"; className?: string }) {
  if (variant === "onAccent") {
    return (
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="FlowQR" className={clsx("shrink-0", className)}>
        <Shapes squares="#FFFFFF" leaf="#131014" />
      </svg>
    );
  }
  if (variant === "auto") {   // squares follow the app theme (--logo-ink), the leaf stays orange
    return (
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="FlowQR" className={clsx("shrink-0", className)}>
        <Shapes squares="var(--logo-ink, #11173F)" leaf={ORANGE} />
      </svg>
    );
  }
  if (variant === "mark" || variant === "onDark") {
    return (
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="FlowQR" className={clsx("shrink-0", className)}>
        <Shapes squares={variant === "onDark" ? "#FFFFFF" : NAVY} leaf={ORANGE} />
      </svg>
    );
  }
  const bg = variant === "orange" ? ORANGE : variant === "navy" ? NAVY : "#F4F2EE";
  const squares = variant === "light" ? NAVY : "#FFFFFF";
  const leaf = variant === "orange" ? NAVY : ORANGE;
  return (
    <svg width={size} height={size} viewBox="0 0 160 160" role="img" aria-label="FlowQR" className={clsx("shrink-0", className)}>
      <rect width="160" height="160" rx="40" fill={bg} stroke={variant === "light" ? "#E4E1DA" : "none"} />
      <g transform="translate(37 37) scale(.86)"><Shapes squares={squares} leaf={leaf} /></g>
    </svg>
  );
}

/**
 * The lockup: the mark + "flowqr" ("qr" in orange) in the logo's own face, with "by FlowHQ" under "flow" (as in the brand sheet). `auto` follows the app theme (navy on light, white on dark);
 * `dark` is for fixed navy grounds; `markOnly` is the mark alone (a phone's top bar, a collapsed rail).
 */
export function Logo({ href = "/", className, tagline = true, dark = false, auto = false, markOnly = false, size = 30, label = "FlowQR by FlowHQ home" }: { href?: string; className?: string; tagline?: boolean; dark?: boolean; auto?: boolean; markOnly?: boolean; size?: number; label?: string }) {
  const ink = dark ? "#FFFFFF" : auto ? "var(--logo-ink, #11173F)" : "#11173F";
  return (
    <Link href={href} className={clsx("inline-flex items-center gap-[.32em] rounded-lg", className)} style={{ fontSize: size }} aria-label={label}>
      <LogoMark size={size} variant={dark ? "onDark" : auto ? "auto" : "mark"} />
      {!markOnly && (
        <span aria-hidden className="leading-none">
          <span className="block font-brand font-bold lowercase tracking-[-.035em]" style={{ fontSize: size * 0.92, color: ink, lineHeight: 0.95 }}>flow<span style={{ color: ORANGE }}>qr</span></span>
          {tagline && <span className="mt-[.12em] block font-brand font-semibold" style={{ fontSize: Math.max(10, size * 0.3), color: dark ? "rgba(255,255,255,.62)" : "#6B6F82" }}>by FlowHQ</span>}
        </span>
      )}
    </Link>
  );
}
