/** Maneuver trade-off matrix — shows candidate burns with fuel/miss trade-off. */
'use client';

import { useState } from 'react';
import type { TradeOffMatrix } from '@/types/api';
import * as api from '@/lib/api';

interface ManeuverPanelProps {
  conjunctionId: number | null;
}

export default function ManeuverPanel({ conjunctionId }: ManeuverPanelProps) {
  const [matrix, setMatrix] = useState<TradeOffMatrix | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePlanManeuvers() {
    if (!conjunctionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await api.planManeuvers(conjunctionId);
      setMatrix(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to plan maneuvers');
    } finally {
      setIsLoading(false);
    }
  }

  if (!conjunctionId) {
    return (
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Maneuver Planner</span>
        </div>
        <div style={{
          padding: 'var(--space-4)',
          textAlign: 'center',
          color: 'var(--text-tertiary)',
          fontSize: 'var(--text-sm)',
        }}>
          Select an ACTION conjunction to plan maneuvers
        </div>
      </div>
    );
  }

  return (
    <div className="panel animate-fade-in">
      <div className="panel-header">
        <span className="panel-title">Maneuver Planner</span>
        <button
          className="btn btn-primary btn-sm"
          onClick={handlePlanManeuvers}
          disabled={isLoading}
        >
          {isLoading ? 'Computing…' : 'Plan Maneuvers'}
        </button>
      </div>

      {error && (
        <div style={{
          padding: 'var(--space-3)',
          background: 'var(--tier-action-bg)',
          border: '1px solid var(--tier-action-border)',
          borderRadius: 'var(--radius-md)',
          fontSize: 'var(--text-xs)',
          color: 'var(--tier-action)',
          marginBottom: 'var(--space-3)',
        }}>
          {error}
        </div>
      )}

      {matrix && (
        <>
          {/* Recommendation */}
          {matrix.recommendation && (
            <div style={{
              padding: 'var(--space-3)',
              background: 'var(--primary-ghost)',
              border: '1px solid hsla(210, 100%, 56%, 0.20)',
              borderRadius: 'var(--radius-md)',
              fontSize: 'var(--text-xs)',
              marginBottom: 'var(--space-3)',
              lineHeight: 1.6,
            }}>
              <div style={{ fontWeight: 600, color: 'var(--primary-400)', marginBottom: 'var(--space-1)' }}>
                AI RECOMMENDATION ({matrix.recommendation.source.toUpperCase()})
              </div>
              <div style={{ color: 'var(--text-secondary)' }}>
                {matrix.recommendation.reasoning}
              </div>
            </div>
          )}

          {/* Candidate Table */}
          <table className="data-table">
            <thead>
              <tr>
                <th>Direction</th>
                <th>Δv (m/s)</th>
                <th>New Miss</th>
                <th>Fuel (kg)</th>
                <th>Life Impact</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {matrix.candidates.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{c.direction}</td>
                  <td className="mono">{c.delta_v_ms.toFixed(2)}</td>
                  <td className="mono" style={{
                    color: c.new_miss_distance_km > 5 ? 'var(--tier-dismissed)' : 'var(--tier-watchlist)',
                  }}>
                    {c.new_miss_distance_km.toFixed(2)} km
                  </td>
                  <td className="mono">{c.fuel_cost_kg.toFixed(3)}</td>
                  <td className="mono">{c.mission_life_impact.pct_of_remaining.toFixed(1)}%</td>
                  <td>
                    <span className={`tier-badge ${c.status === 'RECOMMENDED' ? 'action' : 'dismissed'}`}
                      style={c.status === 'RECOMMENDED' ? { background: 'var(--primary-ghost)', color: 'var(--primary-400)', borderColor: 'hsla(210, 100%, 56%, 0.30)' } : {}}
                    >
                      {c.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
