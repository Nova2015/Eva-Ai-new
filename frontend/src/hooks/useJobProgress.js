// useWebSocket.js â€” drop in src/hooks/
import { useEffect, useRef, useState } from 'react';

const HF_WS = 'ws://127.0.0.1:8000/ws';

export default function useJobProgress(jobId) {
  const [progress, setProgress] = useState({ step: '', message: '', percent: 0, done: false, error: null });
  const wsRef = useRef(null);

  useEffect(() => {
    if (!jobId) return;

    const ws = new WebSocket(`${HF_WS}/${jobId}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setProgress(data);
    };

    ws.onerror = () => setProgress(p => ({ ...p, error: 'Connection error' }));

    return () => ws.close();
  }, [jobId]);

  return progress;
}


