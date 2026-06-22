/** Pipeline loading screen — shown while backend initializes. */
'use client';

interface PipelineLoadingProps {
  stage: string | null;
  progressPct: number | null;
  objectCount: number;
}

const STAGE_LABELS: Record<string, string> = {
  ingestion: 'Ingesting CelesTrak catalog...',
  propagation: 'Propagating orbital trajectories...',
  detection: 'Screening for conjunctions...',
  demo_seed: 'Seeding demo data...',
};

export default function PipelineLoading({ stage, progressPct, objectCount }: PipelineLoadingProps) {
  const label = stage ? STAGE_LABELS[stage] || stage : 'Initializing pipeline...';
  const pct = progressPct ?? 0;

  return (
    <div className="pipeline-progress">
      <div>
        <div className="header-logo" style={{
          width: 64,
          height: 64,
          fontSize: 'var(--text-2xl)',
          margin: '0 auto var(--space-4)',
        }}>
          OP
        </div>
        <div className="pipeline-progress-title">
          OrbitPulse
        </div>
        <div style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--text-tertiary)',
          textAlign: 'center',
          marginTop: 'var(--space-2)',
        }}>
          Autonomous Space Traffic Decision Engine
        </div>
      </div>

      <div style={{ width: '100%', maxWidth: 400 }}>
        <div className="pipeline-progress-bar">
          <div
            className="pipeline-progress-fill"
            style={{ width: `${Math.max(pct, 2)}%` }}
          />
        </div>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: 'var(--space-2)',
        }}>
          <span className="pipeline-progress-stage">{label}</span>
          <span className="pipeline-progress-stage">{pct.toFixed(0)}%</span>
        </div>
      </div>

      <div style={{
        display: 'flex',
        gap: 'var(--space-8)',
        marginTop: 'var(--space-4)',
      }}>
        <div className="metric" style={{ textAlign: 'center' }}>
          <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>
            {objectCount > 0 ? objectCount.toLocaleString() : '—'}
          </span>
          <span className="metric-label">Objects Loaded</span>
        </div>
        <div className="metric" style={{ textAlign: 'center' }}>
          <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>72h</span>
          <span className="metric-label">Prediction Window</span>
        </div>
        <div className="metric" style={{ textAlign: 'center' }}>
          <span className="metric-value" style={{ fontSize: 'var(--text-lg)' }}>SGP4</span>
          <span className="metric-label">Propagator</span>
        </div>
      </div>

      <div style={{
        fontSize: 'var(--text-2xs)',
        color: 'var(--text-tertiary)',
        textAlign: 'center',
        maxWidth: 400,
        lineHeight: 1.6,
      }}>
        First startup may take 60–120 seconds while propagating orbits.
        Subsequent runs use cached positions.
      </div>
    </div>
  );
}
