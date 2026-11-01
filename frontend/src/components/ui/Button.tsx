import Link from "next/link";
import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "accent" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-colors duration-200 select-none disabled:opacity-60 disabled:pointer-events-none whitespace-nowrap";
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800 shadow-card",
  // Orange is the FlowQR brand accent; dark text keeps 4.5:1 contrast.
  accent: "bg-flow-500 text-ink hover:bg-flow-400 active:bg-flow-600 shadow-card",
  secondary: "bg-white text-ink border border-ink-200 hover:bg-ink-50 active:bg-ink-100",
  ghost: "text-ink-700 hover:bg-ink-50 active:bg-ink-100",
  danger: "bg-white text-red-700 border border-red-200 hover:bg-red-50 active:bg-red-100",
};
const sizes: Record<Size, string> = {
  md: "min-h-11 px-4 text-[15px]",
  sm: "min-h-11 sm:min-h-9 px-3 text-sm",
  lg: "min-h-12 px-6 text-base",
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
