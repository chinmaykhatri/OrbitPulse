/** API client — typed fetch wrappers for every OrbitPulse endpoint. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const DEMO_KEY = process.env.NEXT_PUBLIC_DEMO_KEY || 'orbitpulse-demo-2026';

import type {
  HealthStatus,
  Conjunction,
  ConjunctionDetail,
  FunnelStats,
  TimelineEvent,
  ISSPosition,
  TradeOffMatrix,
  NegotiationContract,
  SOCRATESValidation,
  FragmentationResponse,
} from '@/types/api';

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-Key': DEMO_KEY,
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// Health
export const getHealth = () => fetchJSON<HealthStatus>('/api/health');

// Objects
export const getISS = () => fetchJSON<ISSPosition>('/api/iss');
export const getPositions = (limit = 5000) =>
  fetchJSON<{ positions: number[][]; count: number }>(`/api/positions?limit=${limit}`);

// Conjunctions
export const getConjunctions = (tier?: string, limit = 50) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (tier) params.set('tier', tier);
  return fetchJSON<Conjunction[]>(`/api/conjunctions?${params}`);
};
export const getConjunction = (id: number) =>
  fetchJSON<ConjunctionDetail>(`/api/conjunctions/${id}`);
export const getFunnel = () => fetchJSON<FunnelStats>('/api/funnel');
export const getTimeline = (noradId: number) =>
  fetchJSON<TimelineEvent[]>(`/api/timeline/${noradId}`);

// Maneuvers
export const planManeuvers = (conjunctionId: number) =>
  fetchJSON<TradeOffMatrix>(`/api/maneuvers/${conjunctionId}`, { method: 'POST' });
export const negotiate = (conjunctionId: number) =>
  fetchJSON<NegotiationContract>(`/api/negotiate/${conjunctionId}`, { method: 'POST' });

// Simulation
export const triggerFragmentation = (noradId: number, count?: number) =>
  fetchJSON<FragmentationResponse>(`/api/simulate/fragment/${noradId}`, {
    method: 'POST',
    body: JSON.stringify({ fragment_count: count }),
  });

// Validation
export const getSOCRATES = () => fetchJSON<SOCRATESValidation>('/api/socrates');
export const getPipelineStatus = () =>
  fetchJSON<{ pipeline: { stage: string; progress_pct: number } | null; catalog_size: number; is_propagated: boolean }>(
    '/api/pipeline/status'
  );

// Data Sources
export interface DataSourceInfo {
  source: string;
  objects: number;
  latest_epoch: string | null;
  oldest_epoch: string | null;
}
export const getDataSources = () =>
  fetchJSON<{
    sources: DataSourceInfo[];
    total_objects: number;
    primary: string;
    supplemental: string;
  }>('/api/sources');
