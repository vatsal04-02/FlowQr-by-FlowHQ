"use client";
import clsx from "clsx";
import { useEffect, useState } from "react";

/** The person's picture, or their initials. The picture is the Google account photo (a link on Google's image host, saved at Google sign-in); the initials show for everyone without one, while it loads,
 * and if it fails to load, so the circle is never empty or broken. It is decoration (the name is in the account menu), so it is hidden from screen readers. `referrerPolicy="no-referrer"` keeps the
 * app's address out of the request to Google's image host. */
export function Avatar({ src, initials, className, textClass = "text-[13px]" }: { src?: string | null; initials: string; className?: string; textClass?: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  const photo = !!src && !failed;
  return (
    <span aria-hidden className={clsx("relative grid shrink-0 place-items-center overflow-hidden rounded-full bg-ink-solid font-semibold text-ink-on", textClass, className)}>
      {initials}
      {photo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" referrerPolicy="no-referrer" decoding="async" draggable={false} onError={() => setFailed(true)} className="absolute inset-0 h-full w-full object-cover" />
      )}
    </span>
  );
}
