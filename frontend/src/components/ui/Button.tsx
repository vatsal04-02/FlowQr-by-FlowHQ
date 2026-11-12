import Link from "next/link";
import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

// primary = the one cobalt action per view. ink = a decisive outward action (publish, create account).
// inverse = for graphite bands. Every button has a press state. Rectangular (8px), never a capsule.
type Variant = "primary" | "ink" | "secondary" | "ghost" | "danger" | "inverse";
type Size = "md" | "sm" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors duration-150 select-none disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap active:translate-y-px";
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800",
  ink: "bg-ink text-white hover:bg-ink-700 active:bg-ink-800",
  secondary: "bg-white text-ink border border-ink-200 hover:bg-ink-50 hover:border-ink-300 active:bg-ink-100",
  ghost: "text-ink-700 hover:bg-ink-100/70 active:bg-ink-100",
  danger: "bg-white text-red-700 border border-red-200 hover:bg-red-50 active:bg-red-100",
  inverse: "bg-white text-ink hover:bg-ink-100 active:bg-ink-200",
};
// 44px touch targets on small screens; denser on pointer devices.
const sizes: Record<Size, string> = {
  md: "min-h-11 px-4 text-sm sm:min-h-9",
  sm: "min-h-11 px-3 text-[13px] sm:min-h-8",
  lg: "min-h-12 px-5 text-[15px] sm:min-h-11",
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
  href: string; variant?: Variant; size?: Size; className?: string; children: ReactNode; icon?: ReactNode; target?: string; rel?: string;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)} {...rest}>
      {icon}{children}
    </Link>
  );
}
