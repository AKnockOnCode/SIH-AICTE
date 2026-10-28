import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Query } from "../api/client";
import { useSession } from "./session";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * GET an API path. Refetches when the path/query, the demo role or the session data version
 * changes. Keeps the previous data visible while a refetch is in flight.
 */
export function useApi<T>(path: string | null, query?: Query): ApiState<T> {
  const { version, userId } = useSession();
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);
  const key = path ? `${path}|${JSON.stringify(query ?? {})}` : "";
  const lastKey = useRef("");

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return undefined;
    }
    const ctrl = new AbortController();
    if (lastKey.current !== `${key}|${userId}`) {
      // A different resource or role: do not show stale data from the previous one.
      setData(undefined);
      lastKey.current = `${key}|${userId}`;
    }
    setLoading(true);
    setError(undefined);
    api.get<T>(path, query, ctrl.signal)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e instanceof ApiError ? e : new ApiError(0, "client_error", String(e)));
        setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version, userId, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function useDebounced<T>(value: T, delayMs: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), delayMs);
    return () => window.clearTimeout(t);
  }, [value, delayMs]);
  return v;
}

/** Run a mutating API call with busy/error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const run = useCallback(async <R,>(fn: () => Promise<R>): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "client_error", String(e)));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}

export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | AgniDrishti`;
  }, [title]);
}
