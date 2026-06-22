/** SOCRATES validation panel — shows cross-validation against CelesTrak. */
'use client';

import { useState } from 'react';
import type { SOCRATESValidation } from '@/types/api';
import * as api from '@/lib/api';

export default function SOCRATESPanel() {
  const [validation, setValidation] = useState<SOCRATESValidation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleValidate() {
    setIsLoading(true);
    setError(null);
    try {
      const result = await api.getSOCRATES();
      setValidation(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation failed');
    } finally {
      setIsLoading(false);
    }
  }

  const avgDelta = validation?.matches.length
    ? validation.matches.reduce((sum, m) => sum + m.delta_km, 0) / validation.matches.length
    : 0;

  return (
    <div className="panel animate-fade-in">
      <div className="panel-header">
        <span className="panel-title">SOCRATES Validation</span>
        <button className="btn btn-ghost btn-sm" onClick={handleValidate} disabled={isLoading}>
          {isLoading ? 'Fetching…' : 'Validate'}
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

      {!validation && !error && (
        <div style={{
          padding: 'var(--space-4)',
          textAlign: 'center',
          color: 'var(--text-tertiary)',
          fontSize: 'var(--text-sm)',
        }}>
          Cross-validate predictions against CelesTrak SOCRATES
        </div>
      )}

      {validation && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {/* Summary Stats */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: 'var(--space-3)',
          }}>
            <div className="metric">
              <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>
                {validation.matches.length}
              </span>
              <span className="metric-label">Matches</span>
            </div>
            <div className="metric">
              <span className="metric-value" style={{
                fontSize: 'var(--text-lg)',
                color: avgDelta < 1 ? 'var(--tier-dismissed)' : avgDelta < 5 ? 'var(--tier-watchlist)' : 'var(--tier-action)',
              }}>
                {avgDelta.toFixed(2)}
              </span>
              <span className="metric-label">Avg Δ km</span>
            </div>
            <div className="metric">
              <span className="metric-value" style={{ fontSize: 'var(--text-lg)', color: 'var(--text-tertiary)' }}>
                {validation.last_fetched
                  ? new Date(validation.last_fetched).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                  : '—'}
              </span>
              <span className="metric-label">Fetched</span>
            </div>
          </div>

          {/* Match Table */}
          {validation.matches.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>NORAD Pair</th>
                  <th>Our Miss</th>
                  <th>SOCRATES</th>
                  <th>Delta</th>
                </tr>
              </thead>
              <tbody>
                {validation.matches.map((m, idx) => (
                  <tr key={idx}>
                    <td className="mono">{m.norad_ids.join(' × ')}</td>
                    <td className="mono">
                      {m.our_prediction.miss_distance_km != null
                        ? `${(m.our_prediction.miss_distance_km as number).toFixed(2)} km`
                        : '—'}
                    </td>
                    <td className="mono">
                      {(m.socrates_prediction.miss_distance_km as number).toFixed(2)} km
                    </td>
                    <td className="mono" style={{
                      color: m.delta_km < 1 ? 'var(--tier-dismissed)' : 'var(--tier-action)',
                    }}>
                      {m.delta_km.toFixed(2)} km
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
