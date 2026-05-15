/**
 * hooks/useTickerWebSocket.ts
 * ============================
 * Fix #21: Manages the live ticker WebSocket connection with:
 *   - Exponential backoff on disconnect (100ms → up to 30s)
 *   - Max retry ceiling (10 attempts before giving up)
 *   - Degraded-state surfacing — exposes `isDegraded` flag so the UI
 *     can show stale-price warnings instead of silently showing old data
 *   - onclose / onerror handled (not silent no-ops)
 *
 * Usage:
 *   const { prices, isDegraded, connectionStatus } = useTickerWebSocket(url);
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { useStore } from '../store/useStore';

export interface TickerPrices {
  arabica_price?: number;
  robusta_price?: number;
  arabica_change_pct?: number;
  robusta_change_pct?: number;
  updated_at?: string;
}

interface UseTickerWebSocketReturn {
  prices: TickerPrices;
  isDegraded: boolean;
  connectionStatus: 'connected' | 'disconnected' | 'connecting';
  retryCount: number;
}

const BASE_DELAY_MS  = 100;
const MAX_DELAY_MS   = 30_000;
const MAX_RETRIES    = 10;

function jitter(ms: number): number {
  return ms + Math.random() * ms * 0.2;
}

export function useTickerWebSocket(url: string): UseTickerWebSocketReturn {
  const [prices,     setPrices]     = useState<TickerPrices>({});
  const [isDegraded, setIsDegraded] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  const setConnectionStatus = useStore((s) => s.setConnectionStatus);
  const connectionStatus    = useStore((s) => s.connectionStatus);

  const wsRef         = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCountRef = useRef(0);
  const isMountedRef  = useRef(true);

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (wsRef.current) {
      // Remove handlers before closing to avoid triggering reconnect on intentional close
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;

    cleanup();
    setConnectionStatus('connecting');

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMountedRef.current) return;
      retryCountRef.current = 0;
      setRetryCount(0);
      setIsDegraded(false);
      setConnectionStatus('connected');
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!isMountedRef.current) return;
      try {
        const data = JSON.parse(event.data as string) as TickerPrices;
        setPrices(data);
        setIsDegraded(false);
      } catch {
        // Malformed frame — ignore but don't crash
      }
    };

    ws.onerror = (event: Event) => {
      // onerror is always followed by onclose — log here, reconnect in onclose
      console.warn('[useTickerWebSocket] WebSocket error', event);
    };

    ws.onclose = (event: CloseEvent) => {
      if (!isMountedRef.current) return;
      setConnectionStatus('disconnected');

      const attempt = retryCountRef.current;

      if (attempt >= MAX_RETRIES) {
        // Gave up — surface degraded state to UI
        console.error(
          `[useTickerWebSocket] Max retries (${MAX_RETRIES}) reached. Prices may be stale.`,
        );
        setIsDegraded(true);
        return;
      }

      // Exponential backoff with full jitter
      const delay = jitter(Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS));
      console.info(
        `[useTickerWebSocket] Disconnected (code=${event.code}). ` +
        `Retry ${attempt + 1}/${MAX_RETRIES} in ${(delay / 1000).toFixed(1)}s...`,
      );

      retryCountRef.current = attempt + 1;
      setRetryCount(attempt + 1);
      setIsDegraded(attempt > 2); // surface degraded after 3 failed attempts

      retryTimerRef.current = setTimeout(connect, delay);
    };
  }, [url, cleanup, setConnectionStatus]);

  useEffect(() => {
    isMountedRef.current = true;
    connect();

    return () => {
      isMountedRef.current = false;
      cleanup();
    };
  }, [connect, cleanup]);

  return { prices, isDegraded, connectionStatus, retryCount };
}
