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

export function LogoMark({ size = 32, variant = "mark", className }: { size?: number; variant?: "mark" | "onDark" | "orange" | "navy" | "light" | "onAccent"; className?: string }) {
  if (variant === "onAccent") {
    return (
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="FlowQR" className={clsx("shrink-0", className)}>
        <Shapes squares="#FFFFFF" leaf="#131014" />
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

/** The lockup: mark + "flowqr" ("qr" in orange), with "by FlowHQ" under it at 160px wide and above. */
export function Logo({ href = "/", className, tagline = true, dark = false, size = 30 }: { href?: string; className?: string; tagline?: boolean; dark?: boolean; size?: number }) {
  return (
    <Link href={href} className={clsx("inline-flex items-center gap-2.5 rounded-lg", className)} aria-label="FlowQR by FlowHQ home">
      <LogoMark size={size} variant={dark ? "onDark" : "mark"} />
      <span className="leading-none">
        <span className={clsx("block font-bold lowercase tracking-[-.04em]", dark ? "text-white" : "text-[#11173F]")} style={{ fontSize: size * 0.8 }}>flow<span className="text-[#FE6A05]">qr</span></span>
        {tagline && <span className={clsx("mt-1 block text-[11px] font-medium", dark ? "text-white/60" : "text-[#6B6F82]")}>by FlowHQ</span>}
      </span>
    </Link>
  );
}
