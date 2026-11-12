import clsx from "clsx";

/**
 * A real screenshot of the FlowQR app, framed. The pictures in /public/product are captured from the app running on
 * seeded demo data (see docs/ART_DIRECTION_AND_UI_AUDIT.md), so the caption always says so.
 */
export function Shot({ src, alt, path, className, priority, crop }: { src: string; alt: string; path: string; className?: string; priority?: boolean; crop?: string }) {
  return (
    <figure className={clsx("m-0", className)}>
      <div className="overflow-hidden rounded-panel border border-ink-200 bg-white shadow-float">
        <div className="flex items-center gap-2 border-b border-ink-100 bg-ink-50 px-3 py-1.5"><span aria-hidden className="flex gap-1"><i className="h-2 w-2 rounded-full bg-ink-200" /><i className="h-2 w-2 rounded-full bg-ink-200" /><i className="h-2 w-2 rounded-full bg-ink-200" /></span><span className="truncate font-mono text-[11px] text-ink-500">app.flowqr.co.in{path}</span></div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={alt} width={1920} height={1200} loading={priority ? "eager" : "lazy"} decoding="async" className={clsx("block w-full", crop ? clsx("object-cover object-top", crop) : "h-auto")} />
      </div>
      <figcaption className="mt-2 text-xs text-ink-500">Illustrative example · demo data, not a real business</figcaption>
    </figure>
  );
}
