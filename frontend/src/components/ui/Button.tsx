import Link from "next/link";
import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

// Pills only (DESIGN.md §5). primary/ink = black (white in dark mode): the main action. secondary = grey well. brand = the orange call to
// action, at most one per view; its fill is accent-ink (#BD3E1B, white text 5.4:1), and in dark mode a light orange with dark text.
// inverse = on dark bands. Hover lifts 1px; press settles back.
type Variant = "primary" | "ink" | "secondary" | "ghost" | "danger" | "inverse" | "brand";
type Size = "md" | "sm" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-[12px] font-semibold transition-[transform,background-color,color,box-shadow] duration-150 select-none disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap hover:-translate-y-px active:translate-y-0";
const solid = "bg-ink-solid text-ink-on hover:opacity-90";
const variants: Record<Variant, string> = {
  primary: solid,
  ink: solid,
  secondary: "bg-surface-2 text-ink hover:bg-surface-3",
  ghost: "font-medium text-ink-700 hover:bg-surface-2 hover:translate-y-0",
  danger: "bg-neg-tint text-neg hover:bg-red-100",
  inverse: "bg-white text-ink hover:bg-ink-50",
  brand: "bg-accent-ink text-on-accent hover:bg-accent-lo",
};
// 44px touch targets on small screens; a little denser on pointer devices.
const sizes: Record<Size, string> = {
  md: "min-h-11 px-5 text-sm",
  sm: "min-h-11 px-4 text-[13px] sm:min-h-9",
  lg: "min-h-12 px-6 text-[15px]",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md", extra?: string) {
  return clsx(base, variants[variant], sizes[size], extra);
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant; size?: Size; loading?: boolean; icon?: ReactNode;
}

export function Button({ variant = "primary", size = "md", loading, icon, className, children, disabled, type = "button", ...rest }: Props) {
  return (
    <button type={type} className={buttonClass(variant, size, className)} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 fq-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function LinkButton({ href, variant = "primary", size = "md", className, children, icon, ...rest }: {
  href: string; variant?: Variant; size?: Size; className?: string; children: ReactNode; icon?: ReactNode; target?: string; rel?: string; onClick?: () => void; tabIndex?: number; id?: string;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)} {...rest}>
      {icon}{children}
    </Link>
  );
}

/**
 * The public card page (/c, /q, /n) is outside the dashboard redesign (PRD §2) and keeps its original buttons: rectangular, the orange
 * #FE6A05 with navy text as the main action. Frozen here so the dashboard primitives can change freely.
 */
const legacy = {
  base: "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors duration-150 select-none disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap active:translate-y-px",
  primary: "bg-[#FE6A05] font-semibold text-[#11173F] hover:bg-[#EC5F00] active:bg-[#E05A00]",
  ink: "bg-[#11173F] text-[#FFFFFF] hover:bg-[#3B3A38]",
  secondary: "bg-[#FFFFFF] text-[#11173F] border border-[#D8D5CE] hover:bg-[#F4F2EE] hover:border-[#8C8880] active:bg-[#E8E5DF]",
  lg: "min-h-12 px-5 text-[15px] sm:min-h-11",
} as const;
export function publicButtonClass(variant: "primary" | "ink" | "secondary", extra?: string) {
  return clsx(legacy.base, legacy[variant], legacy.lg, extra);
}
