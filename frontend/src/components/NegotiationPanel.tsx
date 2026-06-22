/** Negotiation protocol panel — displays game-theoretic rounds and contract. */
'use client';

import { useState } from 'react';
import type { NegotiationContract } from '@/types/api';
import * as api from '@/lib/api';

interface NegotiationPanelProps {
  conjunctionId: number | null;
  bothManeuverable: boolean;
}

export default function NegotiationPanel({ conjunctionId, bothManeuverable }: NegotiationPanelProps) {
  const [contract, setContract] = useState<NegotiationContract | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleNegotiate() {
    if (!conjunctionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await api.negotiate(conjunctionId);
      setContract(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Negotiation failed');
    } finally {
      setIsLoading(false);
    }
  }

  if (!conjunctionId || !bothManeuverable) {
    return (
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Negotiation Protocol</span>
        </div>
        <div style={{
          padding: 'var(--space-4)',
          textAlign: 'center',
          color: 'var(--text-tertiary)',
          fontSize: 'var(--text-sm)',
        }}>
          {!conjunctionId
            ? 'Select a conjunction to negotiate'
            : 'Only both-maneuverable conjunctions can be negotiated'}
        </div>
      </div>
    );
  }

  return (
    <div className="panel animate-fade-in">
      <div className="panel-header">
        <span className="panel-title">Negotiation Protocol</span>
        <button
          className="btn btn-primary btn-sm"
          onClick={handleNegotiate}
          disabled={isLoading}
        >
          {isLoading ? 'Negotiating…' : 'Run Negotiation'}
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

      {contract && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {/* Negotiation Rounds */}
          {contract.rounds.map((round) => (
            <div key={round.round} style={{
              padding: 'var(--space-3)',
              background: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
            }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                marginBottom: 'var(--space-2)',
              }}>
                <span style={{
                  width: 20,
                  height: 20,
                  borderRadius: 'var(--radius-full)',
                  background: 'var(--primary-ghost)',
                  border: '1px solid hsla(210, 100%, 56%, 0.30)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 'var(--text-2xs)',
                  fontWeight: 700,
                  color: 'var(--primary-400)',
                }}>
                  {round.round}
                </span>
                <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600 }}>
                  {round.proposer}
                </span>
              </div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                <div><strong>Proposal:</strong> {round.proposal}</div>
                <div style={{ marginTop: 'var(--space-1)' }}><strong>Response:</strong> {round.response}</div>
                <div style={{ marginTop: 'var(--space-1)', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
                  {round.reasoning}
                </div>
              </div>
            </div>
          ))}

          {/* Contract Outcome */}
          <div style={{
            padding: 'var(--space-3)',
            background: 'var(--primary-ghost)',
            border: '1px solid hsla(210, 100%, 56%, 0.20)',
            borderRadius: 'var(--radius-md)',
          }}>
            <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--primary-400)', marginBottom: 'var(--space-2)' }}>
              CONTRACT SIGNED
            </div>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              <div>{contract.outcome.summary}</div>
              <div style={{ marginTop: 'var(--space-2)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
                Hash: {contract.outcome.contract_hash}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
