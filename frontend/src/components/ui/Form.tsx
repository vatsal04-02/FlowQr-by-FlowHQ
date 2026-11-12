"use client";
import clsx from "clsx";
import { AlertCircle } from "lucide-react";
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const control =
  "w-full min-h-11 rounded-lg border bg-white px-3 py-2 text-base text-ink placeholder:text-ink-400 transition-colors sm:min-h-9 sm:text-sm " +
  "border-ink-300 hover:border-ink-500 focus-visible:border-brand-600 disabled:bg-ink-50 disabled:text-ink-400";
const invalid = "border-red-500 hover:border-red-500";

interface FieldShell { label: string; hint?: string; error?: string; required?: boolean; children: (p: { id: string; describedBy?: string; invalid: boolean }) => ReactNode; className?: string }

export function Field({ label, hint, error, required, children, className }: FieldShell) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-[13px] font-medium text-ink-700">
        {label}{required && <span className="text-red-600" aria-hidden> *</span>}
      </label>
      {children({ id, describedBy: [hintId, errId].filter(Boolean).join(" ") || undefined, invalid: !!error })}
      {hint && !error && <p id={hintId} className="mt-1.5 text-sm text-ink-500">{hint}</p>}
      {error && (
        <p id={errId} role="alert" className="mt-1.5 flex items-start gap-1.5 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />{error}
        </p>
      )}
    </div>
  );
}

type BaseProps = { label: string; hint?: string; error?: string; wrapperClassName?: string };

export const Input = forwardRef<HTMLInputElement, BaseProps & InputHTMLAttributes<HTMLInputElement>>(
  function Input({ label, hint, error, wrapperClassName, className, required, ...rest }, ref) {
    return (
      <Field label={label} hint={hint} error={error} required={required} className={wrapperClassName}>
        {({ id, describedBy, invalid: inv }) => (
          <input ref={ref} id={id} required={required} aria-invalid={inv || undefined} aria-describedby={describedBy}
            className={clsx(control, inv && invalid, className)} {...rest} />
        )}
      </Field>
    );
  });

export const Textarea = forwardRef<HTMLTextAreaElement, BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ label, hint, error, wrapperClassName, className, required, ...rest }, ref) {
    return (
      <Field label={label} hint={hint} error={error} required={required} className={wrapperClassName}>
        {({ id, describedBy, invalid: inv }) => (
          <textarea ref={ref} id={id} required={required} aria-invalid={inv || undefined} aria-describedby={describedBy}
            className={clsx(control, "min-h-[120px] resize-y leading-relaxed", inv && invalid, className)} {...rest} />
        )}
      </Field>
    );
  });

export function Select({ label, hint, error, wrapperClassName, className, required, children, ...rest }: BaseProps & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <Field label={label} hint={hint} error={error} required={required} className={wrapperClassName}>
      {({ id, describedBy, invalid: inv }) => (
        <select id={id} required={required} aria-invalid={inv || undefined} aria-describedby={describedBy}
          className={clsx(control, "appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 20 20%22 fill=%22%2364748B%22><path d=%22M5.5 7.5 10 12l4.5-4.5%22 stroke=%22%2364748B%22 stroke-width=%222%22 fill=%22none%22/></svg>')] bg-[length:20px] bg-[right_12px_center] bg-no-repeat pr-10", inv && invalid, className)} {...rest}>
          {children}
        </select>
      )}
    </Field>
  );
}

/** Compact select for filter bars (visible label via aria-label). */
export function FilterSelect({ label, className, children, ...rest }: { label: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select aria-label={label} className={clsx(control, "py-1.5 !text-sm sm:w-auto", className)} {...rest}>{children}</select>
  );
}

/** Focusable error summary placed at the top of a form; each item links to its field. */
export function ErrorSummary({ errors, serverError, summaryRef }: { errors: Record<string, string>; serverError?: string | null; summaryRef?: React.RefObject<HTMLDivElement | null> }) {
  const items = Object.entries(errors).filter(([, v]) => v);
  if (!items.length && !serverError) return null;
  return (
    <div ref={summaryRef} tabIndex={-1} role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3.5 text-sm text-red-800 outline-none focus-visible:ring-2 focus-visible:ring-red-500">
      <p className="font-semibold">{serverError ? "We couldn't save that" : "Please fix the following"}</p>
      {serverError && <p className="mt-1">{serverError}</p>}
      {items.length > 0 && <ul className="mt-1 list-disc pl-5">{items.map(([k, v]) => <li key={k}>{v}</li>)}</ul>}
    </div>
  );
}
