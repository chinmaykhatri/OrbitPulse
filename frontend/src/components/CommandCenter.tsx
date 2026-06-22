/** OrbitPulse Command Center — main application page. */
'use client';

import { useState, useCallback } from 'react';
import type { Conjunction } from '@/types/api';
import { useHealth, useConjunctions, useFunnel, useISS } from '@/hooks/usePolling';
import { useWebSocket } from '@/hooks/useWebSocket';

import Header from '@/components/Header';
import TriageFunnel from '@/components/TriageFunnel';
import AlertList from '@/components/AlertList';
import Globe from '@/components/Globe';
import DetailDrawer from '@/components/DetailDrawer';
import SOCRATESPanel from '@/components/SOCRATESPanel';
import PipelineLoading from '@/components/PipelineLoading';

export default function CommandCenter() {
  const health = useHealth();
  const [activeTier, setActiveTier] = useState<string | undefined>(undefined);
  const conjunctions = useConjunctions(activeTier);
  const funnel = useFunnel();
  const iss = useISS();
  const ws = useWebSocket();

  const [selectedConjunction, setSelectedConjunction] = useState<Conjunction | null>(null);

  const handleSelectConjunction = useCallback((conj: Conjunction) => {
    setSelectedConjunction(conj);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setSelectedConjunction(null);
  }, []);

  const handleTierClick = useCallback((tier: string | undefined) => {
    setActiveTier(tier);
  }, []);

  // Show pipeline loading screen until ready
  if (!health.data?.ready) {
    return (
      <div style={{
        width: '100vw',
        height: '100vh',
        background: 'var(--bg-deep)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <PipelineLoading
          stage={health.data?.stage ?? ws.pipelineStatus?.stage ?? null}
          progressPct={health.data?.progress_pct ?? ws.pipelineStatus?.progress_pct ?? null}
          objectCount={health.data?.objects_loaded ?? 0}
        />
      </div>
    );
  }

  return (
    <div className="app-layout">
      {/* Header */}
      <Header
        isReady={health.data.ready}
        isConnected={ws.isConnected}
        objectCount={health.data.objects_loaded}
        conjunctionCount={health.data.conjunctions_found}
      />

      {/* Sidebar */}
      <aside className="app-sidebar">
        {/* Triage Funnel */}
        <TriageFunnel
          stats={funnel.data}
          isLoading={funnel.isLoading}
          onTierClick={handleTierClick}
          activeTier={activeTier}
        />

        {/* Alert List */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          borderTop: '1px solid var(--border-subtle)',
        }}>
          <div style={{
            padding: 'var(--space-3) var(--space-4) var(--space-1)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
            <span style={{
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--text-tertiary)',
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
            }}>
              {activeTier ? `${activeTier} Alerts` : 'All Conjunctions'}
            </span>
            {activeTier && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setActiveTier(undefined)}
                style={{ fontSize: 'var(--text-2xs)' }}
              >
                Clear Filter
              </button>
            )}
          </div>
          <AlertList
            conjunctions={conjunctions.data}
            isLoading={conjunctions.isLoading}
            onSelect={handleSelectConjunction}
            selectedId={selectedConjunction?.id ?? null}
          />
        </div>

        {/* SOCRATES Panel */}
        <div style={{
          borderTop: '1px solid var(--border-subtle)',
          padding: 'var(--space-2)',
        }}>
          <SOCRATESPanel />
        </div>
      </aside>

      {/* Main — Globe + Drawer */}
      <main className="app-main">
        <Globe
          positions={ws.positions}
          issPosition={iss.data}
        />

        {/* Globe overlay controls */}
        <div className="globe-controls">
          <button
            className="globe-control-btn"
            title="Refresh positions"
            onClick={() => ws.sendMessage({ type: 'subscribe', filter: 'all' })}
          >
            ⟳
          </button>
        </div>

        {/* Detail Drawer */}
        <DetailDrawer
          conjunction={selectedConjunction}
          onClose={handleCloseDrawer}
        />
      </main>
    </div>
  );
}
