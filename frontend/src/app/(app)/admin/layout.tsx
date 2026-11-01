"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Alert } from "@/components/ui/Card";
import { useAuth } from "@/lib/auth";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { me } = useAuth();
  const path = usePathname();
  if (!me?.user.is_platform_admin) return <Alert tone="error" title="Platform admins only">You don't have access to this area.</Alert>;
  return (
    <>
      <div className="mb-6 flex gap-1 border-b border-ink-100" role="tablist" aria-label="Platform admin">
        {[["/admin", "Overview"], ["/admin/cards", "Card inventory"]].map(([href, label]) => (
          <Link key={href} href={href} role="tab" aria-selected={path === href} className={`tap inline-flex items-center border-b-2 px-4 text-sm font-semibold ${path === href ? "border-brand-600 text-brand-700" : "border-transparent text-ink-500 hover:text-ink"}`}>{label}</Link>
        ))}
      </div>
      {children}
    </>
  );
}
