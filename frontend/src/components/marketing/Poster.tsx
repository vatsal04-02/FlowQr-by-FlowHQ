import clsx from "clsx";

/**
 * The real FlowQR review poster artwork (89 x 126 mm print file), cut to its card shape. The QR on the artwork is a sample,
 * so every use is captioned as illustrative. Each real card carries its own generated QR.
 */
const DEFAULT_ALT = "The FlowQR review poster: Review us on Google with five stars, a QR code in the middle, Tap to Review and Scan to Review on either side, an AI Review Assistant note, a Write a Review button, and the FlowQR by FlowHQ footer.";

export function Poster({ className, style, muted, alt = DEFAULT_ALT }: { className?: string; style?: React.CSSProperties; muted?: boolean; alt?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/product/poster.webp" width={993} height={1446} loading="eager" decoding="async" style={style}
      alt={alt}
      className={clsx("block h-auto w-full select-none", muted && "opacity-60 grayscale", className)} />
  );
}

/** Numbered marker used on annotated product images. Decorative; the list it points to carries the text. */
export function Pin({ n, className }: { n: number; className?: string }) {
  return <span aria-hidden className={clsx("absolute z-10 grid h-6 w-6 place-items-center rounded-full bg-ink text-xs font-bold text-white ring-[3px] ring-white", className)}>{n}</span>;
}
