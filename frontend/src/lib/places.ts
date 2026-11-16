"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

/** One suggestion row. `place_id` is Google's; nothing else about the place is known until it is picked. */
export interface Suggestion { place_id: string; title: string; subtitle: string; types?: string[] }
/** The picked place, already shaped for our forms by the server (see backend/app/services/places_suggest.py). */
export interface PlaceDetails {
  place_id: string; name: string; formatted_address: string; address_line: string; area: string | null; city: string | null; state: string | null;
  postal_code: string | null; phone: string | null; website: string | null; category: string | null; review_url: string | null;
}
export interface PinInfo { postal_code: string; city: string | null; state: string | null; areas: string[] }

const newSession = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`);

/**
 * Suggestions as the person types. 300 ms after the last keystroke, from 3 characters, one request in flight (older ones are cancelled).
 * The session token lives from the first keystroke until a place is picked, which is how Google bills typing plus one pick as one session.
 * `available` is false when the server has no Google key or the limits are reached: the field then behaves like a plain input.
 */
export function usePlaceSuggest(query: string, kind: "business" | "address", active: boolean) {
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(true);
  const session = useRef(newSession());
  const seq = useRef(0);

  useEffect(() => {
    const q = query.trim();
    if (!active || !available || q.length < 3) { setItems([]); setLoading(false); return; }
    const mine = ++seq.current;
    const ctl = new AbortController();
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const r = await api<{ enabled: boolean; suggestions: Suggestion[] }>("/places/autocomplete", { params: { q, kind, session: session.current }, signal: ctl.signal });
        if (mine !== seq.current) return;
        if (!r.enabled) setAvailable(false);
        setItems(r.suggestions);
      } catch (e) {
        if (ctl.signal.aborted || mine !== seq.current) return;
        setItems([]);
        if (e instanceof ApiError && (e.status === 429 || e.status === 401)) setAvailable(false);
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, 300);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [query, kind, active, available]);

  /** Fetches the picked place and starts a fresh session for the next search. */
  const pick = useCallback(async (s: Suggestion): Promise<PlaceDetails | null> => {
    const token = session.current;
    session.current = newSession();
    setItems([]);
    try { return await api<PlaceDetails>("/places/details", { params: { place_id: s.place_id, session: token } }); } catch { return null; }
  }, []);

  return { items, loading, available, pick, clear: () => setItems([]) };
}

/** City and state for a six-digit PIN (India Post's public directory, through our server). Resolves to null when unknown or unreachable. */
export async function lookupPin(pin: string, signal?: AbortSignal): Promise<PinInfo | null> {
  if (!/^[1-9]\d{5}$/.test(pin)) return null;
  try { return await api<PinInfo>(`/places/pincode/${pin}`, { signal }); } catch { return null; }
}

/** The business the owner picked from Google in step 1, kept across steps (and a page refresh) so the location step can pre-fill itself. */
const KEY = "flowqr.onboarding";
export interface WizardMemory { place: PlaceDetails | null; method: "link" | "google" }
export function loadMemory(): WizardMemory {
  try { const v = JSON.parse(sessionStorage.getItem(KEY) || "null"); if (v && typeof v === "object") return { place: v.place ?? null, method: v.method === "google" ? "google" : "link" }; } catch { /* private mode or bad JSON */ }
  return { place: null, method: "link" };
}
export function saveMemory(m: WizardMemory) { try { sessionStorage.setItem(KEY, JSON.stringify(m)); } catch { /* private mode */ } }
export function clearMemory() { try { sessionStorage.removeItem(KEY); } catch { /* private mode */ } }
