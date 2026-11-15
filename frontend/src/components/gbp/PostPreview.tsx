"use client";
import { useEffect, useState } from "react";

const CTA_LABEL: Record<string, string> = { LEARN_MORE: "Learn more", BOOK: "Book", ORDER: "Order online", SHOP: "Shop", SIGN_UP: "Sign up", CALL: "Call now" };

/**
 * A faithful-in-shape preview of a Google Business "update" post: business name, the photo (if the link loads), the text and the button.
 * It shows exactly what the owner typed. Nothing is added. Google may crop very long text in its own apps.
 */
const range = (a?: string | null, b?: string | null) => {
  if (!a || !b) return null;
  const f = (d: string) => new Date(d).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  return `${f(a)} – ${f(b)}`;
};

export function PostPreview({ business, text, photo, cta, when = "Just now", topic = "STANDARD", title, start, end, coupon, terms }: {
  business: string; text: string; photo?: string | null; cta?: string | null; when?: string;
  topic?: "STANDARD" | "OFFER" | "EVENT"; title?: string | null; start?: string | null; end?: string | null; coupon?: string | null; terms?: string | null;
}) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [photo]);
  const showPhoto = !!photo && photo.startsWith("https://") && !broken;
  const initial = (business.trim()[0] ?? "F").toUpperCase();
  return (
    <figure aria-label="Preview of this post on Google" className="keep-light overflow-hidden rounded-2xl border border-ink-100 bg-white">
      <figcaption className="flex items-center gap-2.5 px-4 pb-2 pt-3.5">
        <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-navy text-sm font-bold text-white">{initial}</span>
        <span className="min-w-0 leading-tight"><span className="block truncate text-sm font-semibold text-navy">{business}</span><span className="text-xs text-ink-500">{topic === "OFFER" ? "Offer" : topic === "EVENT" ? "Event" : "Update"} · {when}</span></span>
      </figcaption>
      {showPhoto && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photo!} alt="" referrerPolicy="no-referrer" onError={() => setBroken(true)} className="aspect-[16/10] w-full object-cover" />
      )}
      {!!photo && photo.startsWith("https://") && broken && <p className="mx-4 mb-2 rounded-lg bg-brand-50 px-3 py-2 text-[13px] text-ink-700">The photo link doesn&rsquo;t open as a picture, so Google can&rsquo;t use it.</p>}
      {topic !== "STANDARD" && (
        <div className="px-4 pt-1">
          <p className="text-base font-semibold text-navy">{title?.trim() || (topic === "OFFER" ? "Offer title" : "Event title")}</p>
          <p className="text-xs text-ink-500">{range(start, end) ?? "Start and end date needed"}</p>
        </div>
      )}
      <div className="px-4 pb-4 pt-1">
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-navy">{text.trim() ? text : <span className="text-ink-400">Your post text shows here as you type.</span>}</p>
        {topic === "OFFER" && coupon && <p className="mt-3 rounded-lg border border-dashed border-ink-300 px-3 py-2 text-center text-sm font-semibold tracking-wider text-navy">{coupon}</p>}
        {topic === "OFFER" && terms && <p className="mt-2 text-xs text-ink-500">{terms}</p>}
        {topic !== "OFFER" && cta && CTA_LABEL[cta] && <span className="mt-3 inline-flex min-h-9 items-center rounded-full border border-ink-300 px-4 text-sm font-semibold text-brand-700">{CTA_LABEL[cta]}</span>}
      </div>
    </figure>
  );
}
