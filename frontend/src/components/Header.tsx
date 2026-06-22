/** Command center header — brand, status indicators, live clock. */
'use client';

import { useState, useEffect } from 'react';

interface HeaderProps {
  isReady: boolean;
  isConnected: boolean;
  objectCount: number;
  conjunctionCount: number;
}

export default function Header({ isReady, isConnected, objectCount, conjunctionCount }: HeaderProps) {
  const [clock, setClock] = useState('');

  useEffect(() => {
    const tick = () => {
      setClock(new Date().toISOString().replace('T', '  ').slice(0, 21) + ' UTC');
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="app-header">
      <div className="header-brand">
        <div className="header-logo">OP</div>
        <div>
          <div className="header-title">OrbitPulse</div>
          <div className="header-subtitle">Autonomous Space Traffic Decision Engine</div>
        </div>
      </div>

      <div className="header-status">
        <div className="status-indicator">
          <span className={`status-dot ${isReady ? 'online' : 'degraded'}`} />
          <span>{isReady ? 'OPERATIONAL' : 'INITIALIZING'}</span>
        </div>

        <div className="status-indicator">
          <span className={`status-dot ${isConnected ? 'online' : 'offline'}`} />
          <span>WS {isConnected ? 'LIVE' : 'DISC'}</span>
        </div>

        <div className="status-indicator">
          <span>{objectCount.toLocaleString()} OBJ</span>
        </div>

        <div className="status-indicator">
          <span>{conjunctionCount} CONJ</span>
        </div>

        <div className="status-indicator" style={{ color: 'var(--text-tertiary)' }}>
          <span>{clock}</span>
        </div>
      </div>
    </header>
  );
}
