/** Fragmentation simulation panel — triggers NASA breakup model and shows debris cloud. */
'use client';

import { useState } from 'react';
import type { FragmentationResponse } from '@/types/api';
import * as api from '@/lib/api';

interface FragPanelProps {
  noradId: number | null;
  objectName: string | null;
}

export default function FragmentationPanel({ noradId, objectName }: FragPanelProps) {
  const [result, setResult] = useState<FragmentationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fragmentCount, setFragmentCount] = useState(50);

  async function handleSimulate() {
    if (!noradId) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.triggerFragmentation(noradId, fragmentCount);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Simulation failed');
    } finally {
      setIsLoading(false);
    }
  }

  if (!noradId) {
    return (
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Fragmentation Simulator</span>
        </div>
        <div style={{
          padding: 'var(--space-4)',
          textAlign: 'center',
          color: 'var(--text-tertiary)',
          fontSize: 'var(--text-sm)',
        }}>
          Select an object to simulate breakup event
        </div>
      </div>
    );
  }

  return (
    <div className="panel animate-fade-in">
      <div className="panel-header">
        <span className="panel-title">Fragmentation Simulator</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
          Target: <strong style={{ color: 'var(--text-primary)' }}>{objectName || `NORAD-${noradId}`}</strong>
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
        <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
          Fragments:
        </label>
        <input
          type="range"
          min={10}
          max={200}
          value={fragmentCount}
          onChange={(e) => setFragmentCount(parseInt(e.target.value))}
          style={{ flex: 1, accentColor: 'hsl(0, 85%, 60%)' }}
        />
        <span className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-primary)', minWidth: 30 }}>
          {fragmentCount}
        </span>
        <button
          className="btn btn-danger btn-sm"
          onClick={handleSimulate}
          disabled={isLoading}
        >
          {isLoading ? 'Simulating…' : '💥 Simulate'}
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
        }}>
          {error}
        </div>
      )}

      {result && (
        <div className="animate-scale-in" style={{
          padding: 'var(--space-3)',
          background: 'var(--tier-action-bg)',
          border: '1px solid var(--tier-action-border)',
          borderRadius: 'var(--radius-md)',
          fontSize: 'var(--text-xs)',
          lineHeight: 1.6,
        }}>
          <div style={{ fontWeight: 600, color: 'var(--tier-action)', marginBottom: 'var(--space-1)' }}>
            ⚠ BREAKUP EVENT SIMULATED
          </div>
          <div style={{ color: 'var(--text-secondary)' }}>
            <div>{result.fragments_generated} fragments generated from NORAD-{result.parent_norad_id}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', marginTop: 'var(--space-1)' }}>
              NASA Standard Breakup Model · Log-normal velocity distribution · Expires in 60 min
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
