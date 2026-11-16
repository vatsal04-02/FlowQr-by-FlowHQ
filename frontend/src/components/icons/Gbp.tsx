/**
 * Google Business Profile mark for the GBP section: a blue storefront with a scalloped awning and a white G. Full colour on purpose (the product's own mark),
 * so it ignores the nav's text colour and stroke weight; it takes the same props as a lucide icon so the nav can render it in the same slot.
 */
export function GbpIcon({ className }: { className?: string; strokeWidth?: number; "aria-hidden"?: boolean | "true" | "false" }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <rect x="3.5" y="8" width="17" height="13.5" rx="1.6" fill="#4285F4" />
      <path d="M2 8.5 3.6 3h16.8L22 8.5a2.5 2.5 0 0 1-5 0 2.5 2.5 0 0 1-5 0 2.5 2.5 0 0 1-5 0 2.5 2.5 0 0 1-5 0Z" fill="#1967D2" />
      <path d="M18.2 14.1a3 3 0 1 0 .3 1.5h-2.8" fill="none" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
