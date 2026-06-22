/** Triage funnel — 3-tier conjunction count visualization. */
'use client';

import type { FunnelStats } from '@/types/api';

interface FunnelProps {
  stats: FunnelStats | null;
  isLoading: boolean;
  onTierClick: (tier: string | undefined) => void;
  activeTier: string | undefined;
}

export default function TriageFunnel({ stats, isLoading, onTierClick, activeTier }: FunnelProps) {
  if (isLoading || !stats) {
    return (
      <div className="panel animate-fade-in">
        <div className="panel-header">
          <span className="panel-title">Triage Funnel</span>
        </div>
        <div className="funnel">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 36, marginBottom: 8 }} />
          ))}
        </div>
      </div>
    );
  }

  const total = stats.total_screened || 1;
  const rows = [
    {
      label: 'Screened',
      count: stats.total_screened,
      pct: 100,
      className: 'screened',
      tier: undefined as string | undefined,
    },
    {
      label: 'Watchlist',
      count: stats.watchlist,
      pct: Math.max(5, (stats.watchlist / total) * 100),
      className: 'watchlist',
      tier: 'WATCHLIST',
    },
    {
      label: 'Action',
      count: stats.action_required,
      pct: Math.max(5, (stats.action_required / total) * 100),
      className: 'action',
      tier: 'ACTION',
    },
  ];

  return (
    <div className="panel animate-fade-in">
      <div className="panel-header">
        <span className="panel-title">Triage Funnel</span>
        {stats.last_updated && (
          <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
            {new Date(stats.last_updated).toLocaleTimeString()}
          </span>
        )}
      </div>
      <div className="funnel">
        {rows.map((row) => (
          <div
            key={row.label}
            className="funnel-row"
            onClick={() => onTierClick(activeTier === row.tier ? undefined : row.tier)}
            style={{ cursor: 'pointer', opacity: activeTier && activeTier !== row.tier ? 0.5 : 1 }}
          >
            <span className="funnel-label">{row.label}</span>
            <div className="funnel-bar">
              <div
                className={`funnel-fill ${row.className}`}
                style={{ width: `${row.pct}%` }}
              />
            </div>
            <span className="funnel-count" style={{
              color: row.className === 'action' ? 'var(--tier-action)' :
                     row.className === 'watchlist' ? 'var(--tier-watchlist)' :
                     'var(--text-primary)',
            }}>
              {row.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
