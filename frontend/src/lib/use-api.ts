"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";

/** Fetch-on-mount/param-change hook with loading + error state and manual reload. */
export function useFetch<T>(path: string | null, params?: Record<string, string | number | undefined | null>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const key = JSON.stringify([path, params]);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (path === null) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await api<T>(path, { params });
      if (mine === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (mine === seq.current) setError(errorMessage(e));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => { void load(); }, [load]);
  return { data, error, loading, reload: load, setData };
}
