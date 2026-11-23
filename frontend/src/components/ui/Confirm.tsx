"use client";
import { AlertTriangle } from "lucide-react";
import { createContext, useCallback, useContext, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";

export type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** danger (default) = the red button for deletes and removals; neutral = a normal button for "are you sure" on sends and publishes */
  tone?: "danger" | "neutral";
  /** the person must type this word to enable the button (irreversible things only) */
  typeToConfirm?: string;
};

const Ctx = createContext<((o: ConfirmOptions) => Promise<boolean>) | null>(null);

/**
 * Destructive-action protection. `const confirm = useConfirm(); if (!(await confirm({ title: "Delete photo?", body: "…" }))) return;`
 * Replaces the browser's confirm(): same words on every screen, the safe choice (Cancel) is focused first, Esc cancels, and the danger button says what it does.
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [o, setO] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState("");
  const resolve = useRef<((v: boolean) => void) | null>(null);
  const inputId = useId();

  const ask = useCallback((opts: ConfirmOptions) => new Promise<boolean>((res) => { resolve.current?.(false); resolve.current = res; setTyped(""); setO(opts); }), []);
  const done = useCallback((v: boolean) => { resolve.current?.(v); resolve.current = null; setO(null); }, []);
  const danger = (o?.tone ?? "danger") === "danger";
  const locked = !!o?.typeToConfirm && typed.trim().toLowerCase() !== o.typeToConfirm.toLowerCase();

  return (
    <Ctx.Provider value={ask}>
      {children}
      <Modal open={!!o} onClose={() => done(false)} title={o?.title ?? ""}
        footer={<>
          <Button variant="secondary" onClick={() => done(false)}>{o?.cancelLabel ?? "Cancel"}</Button>
          <Button variant={danger ? "danger" : "primary"} disabled={locked} onClick={() => done(true)} className={danger ? "!bg-neg !text-pure-white dark:!text-pure-ink hover:!opacity-90" : undefined}>{o?.confirmLabel ?? (danger ? "Yes, continue" : "Confirm")}</Button>
        </>}>
        <div className="flex gap-3">
          {danger && <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-neg-tint text-neg"><AlertTriangle className="h-5 w-5" /></span>}
          <div className="min-w-0 flex-1 text-[15px] text-muted">
            {o?.body}
            {o?.typeToConfirm && (
              <label htmlFor={inputId} className="mt-4 block text-sm font-medium text-ink">
                Type <b>{o.typeToConfirm}</b> to continue
                <input id={inputId} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false}
                  className="mt-1.5 min-h-11 w-full rounded-xl bg-surface-2 px-3 text-base text-ink ring-1 ring-line focus:ring-2 focus:ring-accent" />
              </label>
            )}
          </div>
        </div>
      </Modal>
    </Ctx.Provider>
  );
}

export const useConfirm = () => { const c = useContext(Ctx); if (!c) throw new Error("ConfirmProvider missing"); return c; };
