"use client";
import clsx from "clsx";
import { useEffect, useState } from "react";

/** Sticky tab bar for /industries: links to each industry's block and highlights the one in view. */
export function IndustryTabs({ items }: { items: [string, string][] }) {
  const [active, setActive] = useState(items[0][0]);
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: "-45% 0px -50% 0px" });
    items.forEach(([id]) => { const el = document.getElementById(id); if (el) io.observe(el); });
    return () => io.disconnect();
  }, [items]);
  return (
    <nav aria-label="Industries" className="sticky top-[84px] z-20">
      <div className="mkt-wrap">
        <ul className="flex gap-1 overflow-x-auto rounded-full bg-m-surface/90 p-1.5 shadow-[var(--shadow-card)] backdrop-blur-md">
          {items.map(([id, name]) => (
            <li key={id} className="shrink-0"><a href={`#${id}`} aria-current={active === id ? "true" : undefined}
              className={clsx("inline-flex min-h-10 items-center whitespace-nowrap rounded-full px-4 t-small transition-colors", active === id ? "bg-m-navy text-white" : "text-m-ink2 hover:bg-m-bg")}>{name}</a></li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
