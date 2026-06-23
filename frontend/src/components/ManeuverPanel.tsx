/** Maneuver trade-off matrix — Go/No-Go panel with ranked burns, secondary risks, and approve action. */
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
  const [approvedId, setApprovedId] = useState<number | null>(null);

  async function handlePlanManeuvers() {
    if (!conjunctionId) return;
    setIsLoading(true);
    setError(null);
    setApprovedId(null);
    try {
      const result = await api.planManeuvers(conjunctionId);
      setMatrix(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to plan maneuvers');
    } finally {
      setIsLoading(false);
    }
  }

  function handleApprove(candidateId: number) {
    setApprovedId(candidateId);
  }

  if (!conjunctionId) {
    return (
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Go / No-Go Trade-Off Matrix</span>
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
        <span className="panel-title">Go / No-Go Trade-Off Matrix</span>
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
          {/* AI Recommendation */}
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

          {/* Approved Confirmation */}
          {approvedId && (
            <div style={{
              padding: 'var(--space-3)',
              background: 'hsla(142, 55%, 45%, 0.10)',
              border: '1px solid hsla(142, 55%, 45%, 0.30)',
              borderRadius: 'var(--radius-md)',
              fontSize: 'var(--text-xs)',
              marginBottom: 'var(--space-3)',
              color: 'var(--tier-dismissed)',
              fontWeight: 600,
            }}>
              ✓ Maneuver #{approvedId} approved — burn command would be uplinked to spacecraft
            </div>
          )}

          {/* Candidate Table */}
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Direction</th>
                  <th>Δv (m/s)</th>
                  <th>New Miss</th>
                  <th>Fuel (kg)</th>
                  <th>Life Impact</th>
                  <th>Secondary Risks</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {matrix.candidates.map((c) => {
                  const hasSecondary = c.secondary_conjunctions > 0;
                  const isRejected = c.status === 'REJECTED';
                  const isRecommended = c.status === 'RECOMMENDED';
                  const isApproved = approvedId === c.id;

                  return (
                    <tr key={c.id} style={{
                      opacity: isRejected ? 0.5 : 1,
                      background: isApproved
                        ? 'hsla(142, 55%, 45%, 0.08)'
                        : isRecommended
                          ? 'hsla(210, 100%, 56%, 0.05)'
                          : undefined,
                    }}>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>{c.direction}</td>
                      <td className="mono">{c.delta_v_ms.toFixed(2)}</td>
                      <td className="mono" style={{
                        color: c.new_miss_distance_km > 5 ? 'var(--tier-dismissed)' : 'var(--tier-watchlist)',
                      }}>
                        {c.new_miss_distance_km.toFixed(2)} km
                      </td>
                      <td className="mono">{c.fuel_cost_kg.toFixed(3)}</td>
                      <td className="mono">{c.mission_life_impact.pct_of_remaining.toFixed(1)}%</td>

                      {/* Secondary Risks column */}
                      <td>
                        {hasSecondary ? (
                          <span style={{
                            color: 'var(--tier-action)',
                            fontWeight: 700,
                            fontSize: 'var(--text-xs)',
                          }}>
                            ⚠ {c.secondary_conjunctions}
                          </span>
                        ) : (
                          <span style={{
                            color: 'var(--tier-dismissed)',
                            fontSize: 'var(--text-xs)',
                          }}>
                            ✓ None
                          </span>
                        )}
                      </td>

                      {/* Status */}
                      <td>
                        <span className={`tier-badge ${
                          isApproved ? 'dismissed' :
                          isRecommended ? 'action' :
                          isRejected ? 'watchlist' :
                          'dismissed'
                        }`}
                          style={
                            isApproved
                              ? { background: 'hsla(142, 55%, 45%, 0.15)', color: 'var(--tier-dismissed)', borderColor: 'hsla(142, 55%, 45%, 0.30)' }
                              : isRecommended
                                ? { background: 'var(--primary-ghost)', color: 'var(--primary-400)', borderColor: 'hsla(210, 100%, 56%, 0.30)' }
                                : isRejected
                                  ? { background: 'var(--tier-action-bg)', color: 'var(--tier-action)', borderColor: 'var(--tier-action-border)' }
                                  : {}
                          }
                        >
                          {isApproved ? 'APPROVED' : c.status}
                        </span>
                      </td>

                      {/* Approve Button */}
                      <td>
                        {!isRejected && !isApproved && (
                          <button
                            className="btn btn-sm"
                            onClick={() => handleApprove(c.id)}
                            disabled={approvedId !== null}
                            style={{
                              background: isRecommended ? 'var(--primary-500)' : 'var(--bg-surface-elevated)',
                              color: isRecommended ? '#fff' : 'var(--text-secondary)',
                              border: isRecommended ? 'none' : '1px solid var(--border-default)',
                              padding: '2px 10px',
                              fontSize: 'var(--text-2xs)',
                              cursor: approvedId !== null ? 'not-allowed' : 'pointer',
                              borderRadius: 'var(--radius-sm)',
                              fontWeight: 600,
                            }}
                          >
                            {isRecommended ? '★ Approve' : 'Approve'}
                          </button>
                        )}
                        {isRejected && (
                          <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
                            Rejected
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
