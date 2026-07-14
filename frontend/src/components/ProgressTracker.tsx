import React, { useEffect, useState, useRef, useCallback } from 'react';
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import type { ProgressMessage } from '../types';

const getWsBase = (): string => {
  if (import.meta.env.VITE_WS_BASE) {
    return import.meta.env.VITE_WS_BASE;
  }
  const apiBase = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';
  // Strip trailing /api or api
  const base = apiBase.replace(/\/api\/?$/, '');
  
  if (base.startsWith('https://')) {
    return base.replace('https://', 'wss://');
  }
  if (base.startsWith('http://')) {
    return base.replace('http://', 'ws://');
  }
  // Fallback to window origin if relative
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
};

const WS_BASE = getWsBase();

interface ProgressTrackerProps {
  runId: string;
  onScoringComplete: () => void;
}

export const ProgressTracker: React.FC<ProgressTrackerProps> = ({ runId, onScoringComplete }) => {
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<'idle' | 'running' | 'success' | 'failed'>('idle');
  const [logs, setLogs] = useState<string[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const stableOnScoringComplete = useCallback(onScoringComplete, [onScoringComplete]);

  useEffect(() => {
    if (!runId) return;
    const ws = new WebSocket(`${WS_BASE}/api/runs/${runId}/progress`);
    wsRef.current = ws;
    setStatus('running');
    setLogs(['[SYSTEM] Connected to evaluations pipeline.', '[SYSTEM] Listening for scoring updates…']);

    ws.onmessage = (event) => {
      try {
        const msg: ProgressMessage = JSON.parse(event.data);
        if (msg.type === 'status') {
          if (msg.status === 'processing_scoring') {
            setStatus('running');
            setLogs((p) => [...p, `[STATUS] ${msg.message}`]);
          } else if (msg.status === 'completed') {
            setStatus('success');
            setProgress(1);
            setLogs((p) => [...p, `[STATUS] ${msg.message}`, '[SYSTEM] Stage 2 scoring complete. Shortlist ready.']);
            stableOnScoringComplete();
          } else if (msg.status === 'failed') {
            setStatus('failed');
            setLogs((p) => [...p, `[ERROR] ${msg.message}`]);
            stableOnScoringComplete();
          }
        } else if (msg.type === 'progress') {
          if (msg.progress !== undefined) setProgress(msg.progress);
          if (msg.message) setLogs((p) => [...p, `[LOG] ${msg.message}`]);
        }
      } catch (e) {
        console.error('Error parsing WS message:', e);
      }
    };

    ws.onclose = () => setLogs((p) => [...p, '[SYSTEM] Connection closed.']);
    ws.onerror = () => setLogs((p) => [...p, '[ERROR] Connection encountered an issue.']);
    return () => wsRef.current?.close();
  }, [runId, stableOnScoringComplete]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  if (status === 'idle') return null;

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>Stage 2 Live Pipeline</span>
        {status === 'running' && (
          <span className="pill pill-amber" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Loader2 size={10} className="spin" /> Evaluating
          </span>
        )}
        {status === 'success' && (
          <span className="pill pill-green" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <CheckCircle2 size={10} /> Complete
          </span>
        )}
        {status === 'failed' && (
          <span className="pill pill-red" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <XCircle size={10} /> Failed
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: 'var(--text-muted)', marginBottom: 5 }}>
        <span>Mireye API Fetch Progress</span>
        <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{(progress * 100).toFixed(0)}%</span>
      </div>
      <div style={{ height: 4, background: 'var(--surface-3)', borderRadius: 99, overflow: 'hidden', marginBottom: 12 }}>
        <div style={{ height: '100%', width: `${progress * 100}%`, background: 'var(--accent)', borderRadius: 99, transition: 'width .4s ease' }} />
      </div>

      {/* Log output */}
      <div style={{
        background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
        padding: '8px 12px', maxHeight: 120, overflowY: 'auto', fontFamily: "'SF Mono','Fira Code','Menlo',monospace",
        fontSize: 10.5, lineHeight: 1.8
      }}>
        {logs.map((log, idx) => {
          let cls = 'log-line';
          if (log.startsWith('[SYSTEM]')) cls += ' sys';
          else if (log.startsWith('[STATUS]')) cls += ' ok';
          else if (log.startsWith('[ERROR]')) cls += ' err';
          return <div key={`${idx}-${log.slice(0, 20)}`} className={cls}>{log}</div>;
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
};
