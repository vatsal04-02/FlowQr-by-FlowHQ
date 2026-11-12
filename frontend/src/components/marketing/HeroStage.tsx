import clsx from "clsx";
import { Sparkles } from "lucide-react";
import { Stars } from "@/components/ui/Card";
import { Poster } from "./Poster";

/** Numbered marker that ties each object to its caption below the stage. */
function Step({ n, className }: { n: number; className?: string }) {
  return <span aria-hidden className={clsx("absolute z-20 grid h-6 w-6 place-items-center rounded-full bg-ink text-xs font-bold text-white ring-4 ring-white", className)}>{n}</span>;
}

/** The customer's side: what opens after a tap or scan. A static replica of the real public review page. */
function Phone() {
  return (
    <div className="relative w-[206px] rounded-[32px] bg-ink p-[7px] shadow-float">
      <div className="relative overflow-hidden rounded-[26px] bg-ink-50">
        <span className="absolute left-1/2 top-2 z-10 h-[13px] w-[54px] -translate-x-1/2 rounded-full bg-ink" />
        <div className="space-y-2.5 px-3.5 pb-4 pt-8 text-ink">
          <div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-ink text-xs font-bold text-white">D</span><div className="min-w-0 leading-tight"><p className="truncate text-[11px] font-semibold">Demo Clinic</p><p className="truncate text-[9px] text-ink-500">Main branch</p></div></div>
          <p className="text-[15px] font-bold leading-tight tracking-tight">Share your experience</p>
          <div>
            <p className="mb-1 text-[9px] font-medium text-ink-700">Your experience</p>
            <p className="rounded-md border border-ink-300 bg-white p-2 text-[10px] leading-snug">booked online, seen on time. staff explained the exercises clearly</p>
          </div>
          <span className="flex h-7 items-center justify-center gap-1 rounded-md bg-brand-600 text-[10px] font-semibold text-white"><Sparkles className="h-3 w-3" aria-hidden />Improve my wording</span>
          <div className="rounded-md border border-ink-200 bg-white p-2">
            <p className="mb-1 flex items-center gap-1 text-[9px] font-semibold text-ink-700"><Sparkles className="h-2.5 w-2.5" aria-hidden />AI-assisted · edit freely</p>
            <p className="text-[10px] leading-snug">I booked online and was seen on time. The staff explained the exercises clearly.</p>
          </div>
          <div className="grid grid-cols-[auto_1fr] gap-1.5 whitespace-nowrap text-[9.5px] font-semibold"><span className="flex h-7 items-center justify-center rounded-md border border-ink-200 bg-white px-2.5">Copy</span><span className="flex h-7 items-center justify-center rounded-md bg-ink text-white">Continue to Google</span></div>
        </div>
      </div>
    </div>
  );
}

/** The owner's side: a fragment of the reviews workspace. */
function DashFragment() {
  const rows: [number, string, string, string][] = [
    [5, "Booked online and was seen on time. Staff explained everything.", "Draft ready", "text-brand-800"],
    [3, "Treatment was fine but I waited past my slot.", "Needs reply", "text-amber-900"],
    [5, "Helpful team, good communication throughout.", "Replied", "text-green-800"],
  ];
  const bars = [4, 6, 5, 8, 7, 9, 6, 10, 8, 12, 9, 13];
  return (
    <div className="w-[272px] overflow-hidden rounded-lg border border-ink-100 bg-white shadow-float">
      <div className="flex items-center justify-between border-b border-ink-100 px-3 py-2"><p className="text-[11px] font-semibold">Reviews</p><span className="text-[10px] text-ink-500">10 to reply · 3 drafts</span></div>
      <ul>
        {rows.map(([r, t, s, c], i) => (
          <li key={i} className="border-b border-ink-100 px-3 py-2 last:border-b-0">
            <div className="flex items-center justify-between"><Stars rating={r} size={9} /><span className={clsx("flex items-center gap-1 text-[9px] font-medium", c)}><span className="h-1 w-1 rounded-full bg-current" />{s}</span></div>
            <p className="mt-1 line-clamp-1 text-[10px] text-ink-700">{t}</p>
          </li>
        ))}
      </ul>
      <div className="border-t border-ink-100 bg-ink-50/60 px-3 py-2"><p className="mb-1 text-[9px] font-medium text-ink-500">New reviews per day</p>
        <div className="flex h-7 items-end gap-[3px]" aria-hidden>{bars.map((b, i) => <span key={i} className="flex-1 rounded-[1px] bg-gold-600" style={{ height: `${b * 7}%` }} />)}</div></div>
    </div>
  );
}

/**
 * Hero visual: the real poster, the phone it opens, and the dashboard it feeds, on a block of FlowHQ orange (the poster's own colour).
 * Built on a fixed 640 x 560 canvas that scales with the viewport. Everything inside is an illustrative example.
 */
export function HeroStage() {
  return (
    <figure className="m-0">
      <div className="relative mx-auto h-[280px] w-full max-w-[640px] min-[480px]:h-[386px] sm:h-[515px] lg:h-[420px] xl:h-[526px]" role="img" aria-label="The FlowQR review poster on a counter, the review page it opens on a customer's phone, and the business dashboard where reviews arrive. Illustrative example.">
        <div className="absolute left-0 top-0 h-[560px] w-[640px] origin-top-left scale-[.5] min-[480px]:scale-[.69] sm:scale-[.92] lg:scale-[.75] xl:scale-[.94]">
          <div className="absolute bottom-0 right-0 top-6 w-[470px] rounded-[14px] bg-flow-500" />
          <div className="absolute left-0 top-10 w-[300px] -rotate-[3deg]" style={{ filter: "drop-shadow(0 26px 28px rgba(23,23,25,.38))" }}><Poster /><Step n={1} className="-left-3 -top-3" /></div>
          <div className="absolute right-6 top-14"><DashFragment /><Step n={3} className="-left-3 -top-3" /></div>
          <div className="absolute bottom-[-6px] right-10" style={{ transform: "rotate(1.5deg)" }}><Phone /><Step n={2} className="-left-3 top-8" /></div>
        </div>
      </div>
      <ol className="mx-auto mt-3 grid max-w-[640px] grid-cols-3 gap-3 text-[13px] sm:mt-4" aria-label="How the pieces connect">
        {[["Tap or scan", "the poster at the counter"], ["Customer writes", "in their own words"], ["You manage", "reviews and replies"]].map(([a, b], i) => (
          <li key={a} className="flex gap-2"><span aria-hidden className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-ink text-[11px] font-bold text-white">{i + 1}</span><span><b className="block font-semibold">{a}</b><span className="text-ink-500">{b}</span></span></li>
        ))}
      </ol>
      <figcaption className="mx-auto mt-3 max-w-[640px] text-xs text-ink-500">Illustrative example. The QR on the artwork, the business name and the review text are samples.</figcaption>
    </figure>
  );
}
