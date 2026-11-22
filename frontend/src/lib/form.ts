"use client";
import { useCallback, useRef, useState } from "react";

type Rules<T> = { [K in keyof T]?: (value: T[K], all: T) => string | undefined };

/** Small form helper: validate on blur (inline), validate all on submit, focus error summary on failure. */
export function useForm<T extends Record<string, unknown>>(initial: T, rules: Rules<T> = {}) {
  const [values, setValues] = useState<T>(initial);
  const [errors, setErrors] = useState<Partial<Record<keyof T, string>>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const summaryRef = useRef<HTMLDivElement | null>(null);
  // The latest values and rules, readable from an event handler without being a dependency of it.
  const latest = useRef({ values, rules });
  latest.current = { values, rules };

  const set = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => (e[key] ? { ...e, [key]: undefined } : e));
  }, []);

  const blur = useCallback(<K extends keyof T>(key: K) => {
    const { values: cur, rules: current } = latest.current;
    const rule = current[key];
    if (!rule) return;
    // Validate here, NOT inside a state updater: an updater must be pure, and calling setErrors from inside setValues (as this did) can send React into
    // "Maximum update depth exceeded" (error #185) while a form is being filled, e.g. the New campaign dialog. Only set state when the message really changed.
    const msg = rule(cur[key], cur);
    setErrors((e) => (e[key] === msg ? e : { ...e, [key]: msg }));
  }, []);

  const validateAll = useCallback((): boolean => {
    const next: Partial<Record<keyof T, string>> = {};
    for (const key of Object.keys(rules) as (keyof T)[]) {
      const msg = rules[key]?.(values[key], values);
      if (msg) next[key] = msg;
    }
    setErrors(next);
    const ok = Object.keys(next).length === 0;
    if (!ok) setTimeout(() => summaryRef.current?.focus(), 0);
    return ok;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);

  const fail = useCallback((message: string) => {
    setServerError(message);
    setTimeout(() => summaryRef.current?.focus(), 0);
  }, []);

  const bind = <K extends keyof T>(key: K) => ({
    value: (values[key] ?? "") as string,
    error: errors[key],
    onChange: (e: { target: { value: string } }) => set(key, e.target.value as T[K]),
    onBlur: () => blur(key),
  });

  return { values, errors: errors as Record<string, string>, set, bind, validateAll, serverError, setServerError, fail, summaryRef, setValues };
}

export const required = (label: string) => (v: unknown) => (String(v ?? "").trim() ? undefined : `${label} is required`);
export const emailRule = (v: unknown) => {
  const s = String(v ?? "").trim();
  if (!s) return "Email is required";
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s) ? undefined : "Enter a valid email address";
};
export const passwordRule = (v: unknown) => {
  const s = String(v ?? "");
  if (s.length < 10) return "Use at least 10 characters";
  if (s === s.toLowerCase() || s === s.toUpperCase() || /^\d+$/.test(s)) return "Mix upper and lower case letters";
  return undefined;
};
export const phoneRule = (v: unknown) => {
  const s = String(v ?? "").trim();
  if (!s) return undefined;
  const d = s.replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "").replace(/^0(?=\d{10}$)/, "");
  return /^[6-9]\d{9}$/.test(d) ? undefined : "Enter a 10-digit Indian mobile number";
};
export const googleUrlRule = (v: unknown) => {
  const s = String(v ?? "").trim();
  if (!s) return undefined;
  try {
    const u = new URL(s);
    const ok = u.protocol === "https:" && /(^|\.)(google\.com|google\.co\.in|g\.page|goo\.gl|g\.co|page\.link)$/.test(u.hostname);
    return ok ? undefined : "Use your Google review link (e.g. https://g.page/r/…/review)";
  } catch { return "Enter a full https:// link"; }
};
