/** 72h Risk Timeline — bar chart colored by triage tier. */
'use client';

import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer } from 'recharts';
import type { TimelineEvent } from '@/types/api';

interface TimelineProps {
  events: TimelineEvent[] | null;
  isLoading: boolean;
}

const TIER_COLORS: Record<string, string> = {
  ACTION: 'hsl(0, 85%, 60%)',
  WATCHLIST: 'hsl(38, 92%, 55%)',
  DISMISSED: 'hsl(142, 55%, 45%)',
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{
    payload: TimelineEvent;
  }>;
}

function CustomTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const event = payload[0].payload;
  return (
    <div style={{
      background: 'var(--bg-surface-elevated)',
      border: '1px solid var(--border-default)',
      borderRadius: 'var(--radius-md)',
      padding: 'var(--space-3)',
      fontSize: 'var(--text-xs)',
      fontFamily: 'var(--font-mono)',
      minWidth: 180,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 'var(--space-1)', color: TIER_COLORS[event.tier] }}>
        {event.tier}
      </div>
      <div style={{ color: 'var(--text-secondary)' }}>
        <div>Object: {event.obj_b_name}</div>
        <div>Miss: {event.miss_distance_km.toFixed(2)} km</div>
        <div>Vel: {event.relative_velocity_kms.toFixed(1)} km/s</div>
        <div>Risk: {(event.risk_score * 100).toFixed(0)}%</div>
        <div>TCA: {new Date(event.tca_time).toLocaleString()}</div>
      </div>
    </div>
  );
}

export default function RiskTimeline({ events, isLoading }: TimelineProps) {
  if (isLoading) {
    return (
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">72h Risk Timeline</span>
        </div>
        <div className="skeleton" style={{ height: 160 }} />
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">72h Risk Timeline</span>
        </div>
        <div style={{
          height: 160,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-tertiary)',
          fontSize: 'var(--text-sm)',
        }}>
          Select a satellite to view its risk timeline
        </div>
      </div>
    );
  }

  return (
    <div className="panel animate-fade-in">
      <div className="panel-header">
        <span className="panel-title">72h Risk Timeline</span>
        <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
          {events.length} event{events.length !== 1 ? 's' : ''}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={events} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <XAxis
            dataKey="tca_time"
            tickFormatter={formatTime}
            tick={{ fontSize: 10, fill: 'hsla(0, 0%, 100%, 0.4)' }}
            axisLine={{ stroke: 'hsla(210, 20%, 40%, 0.15)' }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fontSize: 10, fill: 'hsla(0, 0%, 100%, 0.4)' }}
            axisLine={false}
            tickLine={false}
            width={30}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'hsla(210, 20%, 40%, 0.1)' }} />
          <Bar dataKey="risk_score" radius={[3, 3, 0, 0]}>
            {events.map((event, idx) => (
              <Cell key={idx} fill={TIER_COLORS[event.tier] || TIER_COLORS.DISMISSED} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
