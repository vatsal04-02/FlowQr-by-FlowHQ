"use client";
import clsx from "clsx";
import { CheckCircle2, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Toast = { id: number; tone: "success" | "error"; message: string };
const Ctx = createContext<{ push: (message: string, tone?: Toast["tone"]) => void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Toast["tone"] = "success") => {
    const id = Date.now() + Math.random();
    setItems((t) => [...t, { id, tone, message }]);
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), tone === "error" ? 6000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} role="status" className={clsx("fq-enter pointer-events-auto flex max-w-md items-center gap-2 rounded-xl px-4 py-3 text-sm font-medium text-white shadow-pop", t.tone === "success" ? "bg-ink" : "bg-red-700")}>
            {t.tone === "success" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-g-green" aria-hidden /> : <XCircle className="h-4 w-4 shrink-0" aria-hidden />}{t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
export const useToast = () => { const c = useContext(Ctx); if (!c) throw new Error("ToastProvider missing"); return c.push; };
