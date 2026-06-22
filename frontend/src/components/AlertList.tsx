/** Alert card list — displays conjunctions sorted by risk. */
'use client';

import type { Conjunction } from '@/types/api';

interface AlertListProps {
  conjunctions: Conjunction[] | null;
  isLoading: boolean;
  onSelect: (conjunction: Conjunction) => void;
  selectedId: number | null;
}

function formatTCA(iso: string): string {
  const d = new Date(iso);
  const now = Date.now();
  const diffH = (d.getTime() - now) / 3600000;
  if (diffH < 0) return 'PAST';
  if (diffH < 1) return `${Math.round(diffH * 60)}m`;
  if (diffH < 24) return `${Math.round(diffH)}h`;
  return `${Math.round(diffH / 24)}d`;
}

function TierBadge({ tier }: { tier: string }) {
  const cls = tier === 'ACTION' ? 'action' : tier === 'WATCHLIST' ? 'watchlist' : 'dismissed';
  return <span className={`tier-badge ${cls}`}>{tier}</span>;
}

export default function AlertList({ conjunctions, isLoading, onSelect, selectedId }: AlertListProps) {
  if (isLoading || !conjunctions) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 'var(--space-4)' }}>
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="skeleton" style={{ height: 80, borderRadius: 'var(--radius-md)' }} />
        ))}
      </div>
    );
  }

  if (conjunctions.length === 0) {
    return (
      <div style={{
        padding: 'var(--space-8) var(--space-4)',
        textAlign: 'center',
        color: 'var(--text-tertiary)',
        fontSize: 'var(--text-sm)',
      }}>
        No conjunctions detected in the current 72h window.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 'var(--space-3)' }}>
      {conjunctions.map((c) => (
        <div
          key={c.id}
          className={`alert-card tier-${c.tier.toLowerCase()} ${selectedId === c.id ? 'selected' : ''} animate-fade-in`}
          onClick={() => onSelect(c)}
          style={{
            borderColor: selectedId === c.id ? 'var(--primary-500)' : undefined,
            background: selectedId === c.id ? 'var(--bg-surface-elevated)' : undefined,
          }}
        >
          <div className="alert-card-header">
            <span className="alert-card-title truncate" style={{ maxWidth: '65%' }}>
              {c.obj_a_name || `NORAD-${c.obj_a_id}`} × {c.obj_b_name || `NORAD-${c.obj_b_id}`}
            </span>
            <TierBadge tier={c.tier} />
          </div>
          <div className="alert-card-meta">
            <span>Miss: {c.miss_distance_km.toFixed(2)} km</span>
            <span>TCA: T-{formatTCA(c.tca_time)}</span>
            <span>Vel: {c.relative_velocity_kms.toFixed(1)} km/s</span>
            <span>Risk: {(c.risk_score * 100).toFixed(0)}%</span>
          </div>
          {c.prev_miss_distance_km !== null && c.prev_miss_distance_km !== undefined && (
            <div style={{
              marginTop: 'var(--space-1)',
              fontSize: 'var(--text-2xs)',
              fontFamily: 'var(--font-mono)',
              color: c.miss_distance_km < c.prev_miss_distance_km ? 'var(--tier-action)' : 'var(--tier-dismissed)',
            }}>
              {c.miss_distance_km < c.prev_miss_distance_km ? '▲ CONVERGING' : '▼ DIVERGING'}
              {' '}(prev: {c.prev_miss_distance_km.toFixed(2)} km)
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
