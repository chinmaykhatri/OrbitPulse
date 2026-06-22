/** Detail drawer — bottom panel showing selected conjunction's full data + actions. */
'use client';

import { useState } from 'react';
import type { Conjunction } from '@/types/api';
import RiskTimeline from './RiskTimeline';
import ManeuverPanel from './ManeuverPanel';
import NegotiationPanel from './NegotiationPanel';
import FragmentationPanel from './FragmentationPanel';
import { useTimeline } from '@/hooks/usePolling';

interface DrawerProps {
  conjunction: Conjunction | null;
  onClose: () => void;
}

type Tab = 'timeline' | 'maneuver' | 'negotiate' | 'fragment';

export default function DetailDrawer({ conjunction, onClose }: DrawerProps) {
  const [activeTab, setActiveTab] = useState<Tab>('timeline');
  const timeline = useTimeline(conjunction?.obj_a_id ?? null);

  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: 'timeline', label: 'Timeline', icon: '📊' },
    { id: 'maneuver', label: 'Maneuver', icon: '🚀' },
    { id: 'negotiate', label: 'Negotiate', icon: '🤝' },
    { id: 'fragment', label: 'Fragment', icon: '💥' },
  ];

  return (
    <div className={`drawer ${conjunction ? 'open' : ''}`} style={{ maxHeight: '55vh' }}>
      <div className="drawer-handle" />

      {conjunction && (
        <div className="drawer-content">
          {/* Header */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-4)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <span className={`tier-badge ${conjunction.tier.toLowerCase()}`}>
                {conjunction.tier}
              </span>
              <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>
                {conjunction.obj_a_name || `NORAD-${conjunction.obj_a_id}`}
                {' × '}
                {conjunction.obj_b_name || `NORAD-${conjunction.obj_b_id}`}
              </h3>
            </div>
            <button
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              style={{ minWidth: 32 }}
            >
              ✕
            </button>
          </div>

          {/* Key Metrics */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            gap: 'var(--space-4)',
            padding: 'var(--space-3)',
            background: 'var(--bg-surface-elevated)',
            borderRadius: 'var(--radius-md)',
            marginBottom: 'var(--space-4)',
          }}>
            <div className="metric">
              <span className="metric-value" style={{
                fontSize: 'var(--text-lg)',
                color: conjunction.miss_distance_km < 1 ? 'var(--tier-action)' : 'var(--text-primary)',
              }}>
                {conjunction.miss_distance_km.toFixed(3)}
              </span>
              <span className="metric-label">Miss (km)</span>
            </div>
            <div className="metric">
              <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>
                {conjunction.relative_velocity_kms.toFixed(1)}
              </span>
              <span className="metric-label">Rel. Vel (km/s)</span>
            </div>
            <div className="metric">
              <span className="metric-value" style={{
                fontSize: 'var(--text-lg)',
                color: conjunction.risk_score > 0.7 ? 'var(--tier-action)' : 'var(--tier-watchlist)',
              }}>
                {(conjunction.risk_score * 100).toFixed(0)}%
              </span>
              <span className="metric-label">Risk Score</span>
            </div>
            <div className="metric">
              <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>
                {formatCountdown(conjunction.tca_time)}
              </span>
              <span className="metric-label">Time to TCA</span>
            </div>
            <div className="metric">
              <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>
                {conjunction.both_maneuverable ? '✓ Both' : '✗ One'}
              </span>
              <span className="metric-label">Maneuverable</span>
            </div>
          </div>

          {/* Tab Navigation */}
          <div style={{
            display: 'flex',
            gap: 'var(--space-1)',
            marginBottom: 'var(--space-4)',
            borderBottom: '1px solid var(--border-subtle)',
            paddingBottom: 'var(--space-1)',
          }}>
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`btn btn-sm ${activeTab === tab.id ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setActiveTab(tab.id)}
                style={{ borderRadius: 'var(--radius-sm)' }}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div style={{ minHeight: 200 }}>
            {activeTab === 'timeline' && (
              <RiskTimeline events={timeline.data} isLoading={timeline.isLoading} />
            )}
            {activeTab === 'maneuver' && (
              <ManeuverPanel conjunctionId={conjunction.id} />
            )}
            {activeTab === 'negotiate' && (
              <NegotiationPanel
                conjunctionId={conjunction.id}
                bothManeuverable={conjunction.both_maneuverable}
              />
            )}
            {activeTab === 'fragment' && (
              <FragmentationPanel
                noradId={conjunction.obj_a_id}
                objectName={conjunction.obj_a_name}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatCountdown(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff < 0) return 'PAST';
  const hours = Math.floor(diff / 3600000);
  const mins = Math.floor((diff % 3600000) / 60000);
  if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  return `${hours}h ${mins}m`;
}
