import { useState, useEffect, useRef } from 'react';

const BASE = process.env.REACT_APP_API_BASE || 'http://127.0.0.1:8000';

export default function AgentPanel({ API = BASE }) {
  const [task, setTask] = useState('');
  const [jobId, setJobId] = useState(null);
  const [state, setState] = useState({ status: 'idle', pending: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef(null);

  const headers = () => {
    const token = localStorage.getItem('aria_token');
    return { Authorization: `Bearer ${token}` };
  };

  const call = async (method, path, query = '') => {
    const r = await fetch(`${API}/eva-agent/${path}${query}`, { method, headers: headers() });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  };

  useEffect(() => {
    if (!jobId) return undefined;
    const poll = async () => {
      try {
        const s = await call('GET', `status/${jobId}`);
        setState(s);
        if (s.status === 'done' || String(s.status).startsWith('error')) {
          clearInterval(timer.current);
        }
      } catch (e) {
        setError(`Status failed: ${e.message}`);
        clearInterval(timer.current);
      }
    };
    poll();
    timer.current = setInterval(poll, 2000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line
  }, [jobId]);

  const start = async () => {
    if (!task.trim()) return;
    setError(''); setBusy(true);
    try {
      const r = await call('POST', 'run', `?task=${encodeURIComponent(task)}`);
      setState({ status: 'running', pending: [] });
      setJobId(r.job_id);
    } catch (e) {
      setError(`Start failed: ${e.message}`);
    } finally { setBusy(false); }
  };

  const decide = async (ok) => {
    setBusy(true); setError('');
    try {
      await call('POST', `approve/${jobId}`, `?ok=${ok}`);
    } catch (e) {
      setError(`Approve failed: ${e.message}`);
    } finally { setBusy(false); }
  };

  const waiting = state.status === 'waiting_approval';

  return (
    <div style={{ maxWidth: 760, margin: '24px auto', padding: 16 }}>
      <h2>EVA Coding Agent</h2>
      <p style={{ opacity: 0.7 }}>
        Works on a copy of the project. Read every command before approving.
      </p>

      <textarea
        value={task} onChange={(e) => setTask(e.target.value)}
        rows={4} style={{ width: '100%' }}
        placeholder="e.g. Find where chat history is stored. Do not modify files."
      />
      <button onClick={start} disabled={busy || waiting || state.status === 'running'}>
        Start task
      </button>

      {jobId && <p>Job #{jobId}: <b>{state.status}</b></p>}
      {error && <p style={{ color: 'crimson' }}>{error}</p>}

      {waiting && (
        <div style={{ border: '1px solid #c90', padding: 12, marginTop: 12 }}>
          <b>Agent wants to run:</b>
          {state.pending.map((p, i) => (
            <pre key={i} style={{ whiteSpace: 'pre-wrap' }}>
{`[${p.tool}] ${p.summary || ''}\n${p.action}`}
            </pre>
          ))}
          <button onClick={() => decide(true)} disabled={busy}>Approve</button>{' '}
          <button onClick={() => decide(false)} disabled={busy}>Reject</button>
        </div>
      )}

      {Array.isArray(state.log) && state.log.length > 0 && (
        <pre style={{ whiteSpace: 'pre-wrap', marginTop: 12 }}>{state.log.join('\n')}</pre>
      )}
    </div>
  );
}