/** WebSocket hook — connects to /ws/live with auto-reconnect and typed messages. */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { WSMessage } from '@/types/api';

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

interface UseWebSocketReturn {
  lastMessage: WSMessage | null;
  positions: number[][];
  pipelineStatus: { stage: string; progress_pct: number } | null;
  isConnected: boolean;
  sendMessage: (msg: Record<string, unknown>) => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const reconnectAttempt = useRef(0);

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [positions, setPositions] = useState<number[][]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<{
    stage: string;
    progress_pct: number;
  } | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`${WS_BASE}/ws/live`);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttempt.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        setLastMessage(msg);

        if (msg.type === 'positions') {
          setPositions(msg.data);
        } else if (msg.type === 'pipeline_status') {
          setPipelineStatus(msg.data);
        } else if (msg.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong' }));
        }
      } catch (err) {
        console.error('WebSocket message parse error:', err);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
      const delay = Math.min(1000 * 2 ** reconnectAttempt.current, 30000);
      reconnectAttempt.current += 1;
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { lastMessage, positions, pipelineStatus, isConnected, sendMessage };
}
