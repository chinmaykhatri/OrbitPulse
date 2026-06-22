/** Polling hooks for API data with SWR-style refresh. */
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { HealthStatus, Conjunction, FunnelStats, ISSPosition, TimelineEvent } from '@/types/api';
import * as api from '@/lib/api';

interface UsePollingReturn<T> {
  data: T | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => void;
}

function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 10000,
): UsePollingReturn<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const mountedRef = useRef(true);

  const fetchData = useCallback(async () => {
    try {
      const result = await fetcher();
      if (mountedRef.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, [fetcher]);

  useEffect(() => {
    mountedRef.current = true;
    fetchData();
    const interval = setInterval(fetchData, intervalMs);
    return () => {
      mountedRef.current = false;
      clearInterval(interval);
    };
  }, [fetchData, intervalMs]);

  return { data, error, isLoading, refresh: fetchData };
}

export function useHealth() {
  return usePolling<HealthStatus>(api.getHealth, 5000);
}

export function useConjunctions(tier?: string) {
  const fetcher = useCallback(() => api.getConjunctions(tier), [tier]);
  return usePolling<Conjunction[]>(fetcher, 15000);
}

export function useFunnel() {
  return usePolling<FunnelStats>(api.getFunnel, 15000);
}

export function useISS() {
  return usePolling<ISSPosition>(api.getISS, 5000);
}

export function useTimeline(noradId: number | null) {
  const fetcher = useCallback(() => {
    if (noradId === null) return Promise.resolve([]);
    return api.getTimeline(noradId);
  }, [noradId]);
  return usePolling<TimelineEvent[]>(fetcher, 30000);
}
