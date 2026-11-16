"use client";
import clsx from "clsx";
import { Loader2, MapPin, Search } from "lucide-react";
import { useEffect, useId, useRef, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { controlClass, Field, invalidClass } from "@/components/ui/Form";
import type { Suggestion } from "@/lib/places";

/**
 * A text field that suggests places as you type (ARIA 1.2 combobox, list autocomplete).
 * Keyboard: ArrowDown/ArrowUp move, Enter picks, Escape closes, Tab leaves. A screen reader hears how many suggestions there are.
 * The typed text is always the value: suggestions only help, so the field works exactly like a normal input when none appear.
 */
export function PlaceCombobox({ label, hint, error, required, value, onChange, onBlurValue, suggestions, loading, enabled, onPick, picking, placeholder, name, autoComplete, icon, ...rest }: {
  label: string; hint?: string; error?: string; required?: boolean; value: string; onChange: (v: string) => void; onBlurValue?: () => void;
  suggestions: Suggestion[]; loading: boolean; enabled: boolean; onPick: (s: Suggestion) => void; picking?: boolean; placeholder?: string; name?: string; autoComplete?: string; icon?: ReactNode;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "name" | "placeholder" | "autoComplete">) {
  const listId = useId();
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [active, setActive] = useState(-1);
  const box = useRef<HTMLDivElement>(null);

  const open = enabled && focused && !dismissed && suggestions.length > 0 && value.trim().length >= 3;
  useEffect(() => { setActive(-1); }, [suggestions]);
  useEffect(() => { setDismissed(false); }, [value]);

  function pick(s: Suggestion) { setDismissed(true); setActive(-1); onPick(s); }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!enabled) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!suggestions.length) return;
      e.preventDefault();
      setDismissed(false);
      setActive((i) => (e.key === "ArrowDown" ? (i + 1) % suggestions.length : (i <= 0 ? suggestions.length - 1 : i - 1)));
    } else if (e.key === "Enter" && open && active >= 0) {
      e.preventDefault();
      pick(suggestions[active]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault(); e.stopPropagation();
      setDismissed(true);
    }
  }

  // keep the highlighted row in view when moving with the keyboard
  useEffect(() => {
    if (active >= 0) box.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <Field label={label} hint={hint} error={error} required={required}>
      {({ id, describedBy, invalid }) => (
        <div className="relative">
          <span aria-hidden className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-400">{icon ?? <Search className="h-[18px] w-[18px]" strokeWidth={1.75} />}</span>
          <input id={id} name={name} value={value} placeholder={placeholder} autoComplete={autoComplete ?? "off"} required={required} spellCheck={false}
            role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={listId} aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
            aria-invalid={invalid || undefined} aria-describedby={describedBy}
            onChange={(e) => onChange(e.target.value)} onFocus={() => setFocused(true)} onBlur={() => { setFocused(false); onBlurValue?.(); }} onKeyDown={onKeyDown}
            className={clsx(controlClass, "pl-11 pr-11", invalid && invalidClass)} {...rest} />
          <span aria-hidden className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-ink-400">{(loading || picking) && <Loader2 className="h-[18px] w-[18px] fq-spin" />}</span>
          <p role="status" className="sr-only">
            {picking ? "Filling in the details" : open ? `${suggestions.length} suggestion${suggestions.length === 1 ? "" : "s"} available. Use the up and down arrow keys, then Enter.` : ""}
          </p>
          {open && (
            <div ref={box} className="absolute inset-x-0 top-[calc(100%+6px)] z-30 overflow-hidden rounded-[18px] bg-white shadow-[0_18px_44px_-12px_rgba(11,15,46,.28),0_0_0_1px_rgba(11,15,46,.06)]">
              <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="max-h-[320px] overflow-y-auto py-1.5">
                {suggestions.map((s, i) => (
                  <li key={s.place_id} id={`${listId}-${i}`} data-i={i} role="option" aria-selected={i === active}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => pick(s)} onMouseMove={() => active !== i && setActive(i)}
                    className={clsx("flex min-h-[52px] cursor-pointer items-center gap-3 px-4 py-2", i === active ? "bg-m-tint" : "hover:bg-ink-50")}>
                    <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-m-tint text-m-accentStrong"><MapPin className="h-4 w-4" strokeWidth={1.75} /></span>
                    <span className="min-w-0">
                      <span className="block truncate text-[14.5px] font-medium text-ink">{s.title}</span>
                      {s.subtitle && <span className="block truncate text-[13px] text-ink-500">{s.subtitle}</span>}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="border-t border-ink-100 px-4 py-2 text-right text-[11px] text-ink-400">Powered by Google</p>
            </div>
          )}
        </div>
      )}
    </Field>
  );
}
