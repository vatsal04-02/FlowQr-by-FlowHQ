"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";

/**
 * Fetch-on-mount/param-change hook with loading + error state and manual reload.
 *
 * `opts.scope` is for data that belongs to one business (the signed-in user can switch between several, and the server answers for whichever is selected): it is part of the cache key, so
 * a change of scope fetches again, and while the new answer is on its way the previous scope's data, error and "loaded" state are NOT shown (`data` is null, `loading` is true). Without a
 * scope the hook behaves exactly as before: old data stays visible while a changed param reloads.
 */
export function useFetch<T>(path: string | null, params?: Record<string, string | number | undefined | null>, opts?: { scope?: string | null }) {
  const scope = opts?.scope;
  const [data, setData] = useState<T | null>(null);
  const [dataScope, setDataScope] = useState<string | null | undefined>(scope);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const key = JSON.stringify([path, params, scope]);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (path === null) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await api<T>(path, { params });
      if (mine === seq.current) { setData(d); setDataScope(scope); setError(null); }
    } catch (e) {
      if (mine === seq.current) { setError(errorMessage(e)); setDataScope(scope); }
    } finally {
      if (mine === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => { void load(); }, [load]);
  // The render in which the scope has just changed still holds the previous scope's state (the effect has not run yet): treat it as "loading, nothing known".
  const foreign = scope !== undefined && dataScope !== scope;
  return { data: foreign ? null : data, error: foreign ? null : error, loading: foreign ? path !== null : loading, reload: load, setData };
}
