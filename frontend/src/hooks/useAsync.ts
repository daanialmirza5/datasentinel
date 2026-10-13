import { useCallback, useEffect, useState } from 'react';

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  key: string;
  data?: T;
  error?: Error;
}

/**
 * Runs an async loader whenever its dependencies change. Loading is derived (the latest settled
 * request does not match the current dependencies), stale responses are discarded, and the last
 * successful data stays visible while a reload is in flight.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: readonly unknown[], enabled = true): AsyncState<T> {
  const [tick, setTick] = useState(0);
  const [settled, setSettled] = useState<Settled<T>>();
  const [lastData, setLastData] = useState<T>();
  const key = JSON.stringify([...deps, tick]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    loader().then(
      (data) => {
        if (cancelled) return;
        setSettled({ key, data });
        setLastData(data);
      },
      (err: unknown) => {
        if (!cancelled) setSettled({ key, error: err instanceof Error ? err : new Error(String(err)) });
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the serialised key captures the caller's dependencies
  }, [key, enabled]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const current = settled?.key === key ? settled : undefined;
  return {
    data: current ? current.data ?? (current.error ? undefined : lastData) : lastData,
    error: current?.error,
    loading: enabled && !current,
    reload,
  };
}
