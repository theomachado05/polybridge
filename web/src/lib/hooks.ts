"use client";

import { useCallback, useEffect, useState } from "react";

export interface Async<T> { data: T | null; error: string | null; loading: boolean }

export function useAsync<T>(key: string | null, fn: () => Promise<T>): Async<T> {
  const [s, setS] = useState<{ key: string | null; data: T | null; error: string | null }>({ key: null, data: null, error: null });
  useEffect(() => {
    if (key === null) return;
    let alive = true;
    fn().then(
      (data) => alive && setS({ key, data, error: null }),
      (e) => alive && setS({ key, data: null, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (key === null) return { data: null, error: null, loading: false };
  const fresh = s.key === key;
  return { data: fresh ? s.data : null, error: fresh ? s.error : null, loading: !fresh };
}

export function useRetry(): [number, () => void] {
  const [n, setN] = useState(0);
  return [n, useCallback(() => setN((x) => x + 1), [])];
}

export const money = (x: number | null | undefined) =>
  x == null ? "n/a" : x.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: x >= 100 ? 0 : 2 });
export const pct = (x: number | null | undefined, d = 0) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
