import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const tabs = [
  { id: '', label: 'All Runs' },
  { id: 'running', label: 'Running' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
];

export default function RunCenter({ API = defaultApi }) {
  const storedUser = (() => {
    try {
      return JSON.parse(localStorage.getItem('aria_user') || '{}');
    } catch {
      return {};
    }
  })();
  const userId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const token = localStorage.getItem('aria_token');
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }), [token]);

  const [activeStatus, setActiveStatus] = useState('');
  const [runs, setRuns] = useState([]);
  const [metrics, setMetrics] = useState({ summary: {}, by_type: [] });
  const [selectedRun, setSelectedRun] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadRuns = async (status = activeStatus) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId, limit: '100' });
      if (status) params.set('status', status);
      const res = await fetch(`${API}/runs?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Runs failed');
      setRuns(json.runs || []);
      setMetrics(json.metrics || { summary: {}, by_type: [] });
      if (selectedRun) {
        const updated = (json.runs || []).find((run) => run.id === selectedRun.id);
        if (updated) await loadRunDetail(updated.id);
      }
    } catch (err) {
      setError(err.message || 'Runs failed');
    } finally {
      setLoading(false);
    }
  };

  const loadRunDetail = async (runId) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/runs/${runId}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Run detail failed');
      setSelectedRun(json.run || null);
    } catch (err) {
      setError(err.message || 'Run detail failed');
    } finally {
      setLoading(false);
    }
  };

  const cancelRun = async (runId) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/runs/${runId}/cancel`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, reason: 'Cancelled from Run Center' }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Cancel failed');
      setSelectedRun(json.run || null);
      await loadRuns();
    } catch (err) {
      setError(err.message || 'Cancel failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRuns(activeStatus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId, activeStatus]);

  const S = styles(loading);
  const summary = metrics.summary || {};

  return (
    <div style={S.page}>
      <style>{`
        @media (max-width: 1120px) {
          .run-grid-2,
          .run-grid-4 { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 680px) {
          .run-tabs { grid-template-columns: 1fr 1fr !important; }
          .run-table { min-width: 760px; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>Run Center</h1>
            <div style={S.sub}>Durable workflow tracking for code, RAG, vision, GitHub, agents, and approvals.</div>
          </div>
          <button type="button" onClick={() => loadRuns()} disabled={loading} style={S.primaryButton}>
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>

        {error && <div style={S.error}>{error}</div>}

        <div className="run-grid-4" style={S.grid4}>
          <Metric label="Run Count" value={summary.total_runs || 0} color="#38bdf8" />
          <Metric label="Running" value={summary.running_runs || 0} color="#fbbf24" />
          <Metric label="Success Rate" value={`${summary.success_rate || 0}%`} color="#34d399" />
          <Metric label="Failure Rate" value={`${summary.failure_rate || 0}%`} color="#fb7185" />
        </div>

        <div className="run-tabs" style={S.tabs}>
          {tabs.map((tab) => (
            <button
              key={tab.label}
              type="button"
              onClick={() => setActiveStatus(tab.id)}
              style={{ ...S.tab, ...(activeStatus === tab.id ? S.activeTab : {}) }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="run-grid-2" style={S.grid2}>
          <section style={S.panel}>
            <div style={S.sectionTitle}>{tabs.find((tab) => tab.id === activeStatus)?.label || 'All Runs'}</div>
            <div style={{ overflowX: 'auto' }}>
              <table className="run-table" style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Run</th>
                    <th style={S.th}>Type</th>
                    <th style={S.th}>Status</th>
                    <th style={S.th}>Progress</th>
                    <th style={S.th}>Duration</th>
                    <th style={S.th}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.length === 0 ? (
                    <tr>
                      <td colSpan={6} style={S.emptyCell}>No runs found.</td>
                    </tr>
                  ) : runs.map((run) => (
                    <tr key={run.id} onClick={() => loadRunDetail(run.id)} style={{ cursor: 'pointer', background: selectedRun?.id === run.id ? 'rgba(37,99,235,.12)' : 'transparent' }}>
                      <td style={S.td}>
                        <div style={{ color: 'var(--text)', fontWeight: 850 }}>{run.title}</div>
                        <div style={S.muted}>{run.source}</div>
                      </td>
                      <td style={S.td}>{run.run_type}</td>
                      <td style={S.td}><StatusPill status={run.status} /></td>
                      <td style={S.td}><Progress value={run.progress || 0} /></td>
                      <td style={S.td}>{formatDuration(run.duration_ms || 0)}</td>
                      <td style={S.td}>{formatDate(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={S.panel}>
            <div style={S.sectionTitle}>Run Details</div>
            {!selectedRun ? (
              <div style={S.muted}>Select a run to inspect status, payload, result, and timeline.</div>
            ) : (
              <div style={S.stack}>
                <div style={S.detailHeader}>
                  <div>
                    <div style={{ color: 'var(--text)', fontSize: 17, fontWeight: 900 }}>{selectedRun.title}</div>
                    <div style={S.muted}>{selectedRun.id}</div>
                  </div>
                  <StatusPill status={selectedRun.status} />
                </div>
                <Progress value={selectedRun.progress || 0} tall />
                <div style={S.infoGrid}>
                  <InfoRow label="Source" value={selectedRun.source} />
                  <InfoRow label="Run Type" value={selectedRun.run_type} />
                  <InfoRow label="Duration" value={formatDuration(selectedRun.duration_ms || 0)} />
                  <InfoRow label="Created" value={formatDate(selectedRun.created_at)} />
                </div>
                {['queued', 'running'].includes(selectedRun.status) && (
                  <button type="button" onClick={() => cancelRun(selectedRun.id)} disabled={loading} style={S.dangerButton}>
                    Cancel Run
                  </button>
                )}
                <div>
                  <div style={S.sectionTitle}>Event Timeline</div>
                  <EventTimeline events={selectedRun.events || []} S={S} />
                </div>
                <JsonBlock title="Payload" value={selectedRun.payload} S={S} />
                <JsonBlock title="Result" value={selectedRun.result} S={S} />
                {selectedRun.error && <div style={S.error}>{selectedRun.error}</div>}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function EventTimeline({ events, S }) {
  if (!events.length) return <div style={S.muted}>No events recorded yet.</div>;
  return (
    <div style={S.timeline}>
      {events.map((event) => (
        <div key={event.id} style={S.eventRow}>
          <div style={{ ...S.eventDot, background: statusColor(event.status) }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ color: 'var(--text)', fontWeight: 850 }}>{event.message}</div>
            <div style={S.muted}>{event.event_type} / {event.status} / {formatDate(event.created_at)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, color }) {
  return (
    <div style={{ background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 20, padding: 14, backdropFilter: 'blur(20px)' }}>
      <div style={{ color: 'var(--text3)', fontSize: 11 }}>{label}</div>
      <div style={{ color, fontSize: 24, fontWeight: 900, marginTop: 6 }}>{value}</div>
    </div>
  );
}

function StatusPill({ status }) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      borderRadius: 999,
      padding: '4px 9px',
      color: statusColor(status),
      background: 'var(--surface)',
      border: `1px solid ${statusColor(status)}44`,
      fontSize: 11,
      fontWeight: 900,
      textTransform: 'capitalize',
    }}>
      {status || 'unknown'}
    </span>
  );
}

function Progress({ value, tall = false }) {
  const safe = Math.max(0, Math.min(Number(value || 0), 100));
  return (
    <div style={{ display: 'grid', gap: 5 }}>
      <div style={{ height: tall ? 12 : 8, background: 'var(--surface2)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
        <div style={{ width: `${safe}%`, height: '100%', background: 'linear-gradient(135deg,var(--accent),#14b8a6)' }} />
      </div>
      {tall && <div style={{ color: 'var(--text3)', fontSize: 11 }}>{safe}% complete</div>}
    </div>
  );
}

function JsonBlock({ title, value, S }) {
  return (
    <div>
      <div style={S.sectionTitle}>{title}</div>
      <pre style={S.pre}>{JSON.stringify(value || {}, null, 2)}</pre>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 12, padding: '9px 10px' }}>
      <span style={{ color: 'var(--text3)', fontSize: 12 }}>{label}</span>
      <span style={{ color: 'var(--text)', fontSize: 12, fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value || '-'}</span>
    </div>
  );
}

function styles(loading) {
  return {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: 'var(--bg)',
      color: 'var(--text)',
      padding: 22,
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    },
    shell: { maxWidth: 1320, margin: '0 auto', display: 'grid', gap: 16 },
    stack: { display: 'grid', gap: 14 },
    header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap' },
    title: { margin: 0, color: 'var(--text)', fontSize: 23, fontWeight: 900 },
    sub: { color: 'var(--text3)', fontSize: 13, marginTop: 4 },
    grid4: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 },
    grid2: { display: 'grid', gridTemplateColumns: '1.08fr .92fr', gap: 14, alignItems: 'start' },
    panel: { background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 20, padding: 16, boxShadow: '0 16px 36px rgba(0,0,0,.24), 0 0 28px var(--accent-glow)', backdropFilter: 'blur(20px)', minWidth: 0 },
    tabs: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 20, padding: 8 },
    tab: { border: '1px solid transparent', borderRadius: 12, background: 'transparent', color: 'var(--text3)', fontSize: 12, fontWeight: 850, padding: '9px 8px', cursor: 'pointer' },
    activeTab: { background: 'var(--accent-soft)', color: 'var(--text)', border: '1px solid var(--border2)' },
    primaryButton: { border: 'none', borderRadius: 12, padding: '10px 13px', color: '#fff', fontWeight: 850, background: 'linear-gradient(135deg,var(--accent),#0f766e)', cursor: loading ? 'not-allowed' : 'pointer' },
    dangerButton: { border: '1px solid rgba(248,113,113,.25)', borderRadius: 8, padding: '9px 12px', color: '#fecaca', background: 'rgba(239,68,68,.12)', fontWeight: 850, cursor: loading ? 'not-allowed' : 'pointer' },
    error: { color: '#fecaca', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(248,113,113,.25)', borderRadius: 8, padding: 10, fontSize: 13 },
    sectionTitle: { color: 'var(--text2)', fontSize: 13, fontWeight: 900, marginBottom: 10 },
    muted: { color: 'var(--text3)', fontSize: 12, lineHeight: 1.5 },
    table: { width: '100%', borderCollapse: 'collapse', color: 'var(--text2)', fontSize: 12 },
    th: { textAlign: 'left', color: 'var(--text3)', fontWeight: 900, padding: '0 10px 9px', borderBottom: '1px solid var(--border)' },
    td: { padding: '10px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle' },
    emptyCell: { padding: 12, color: 'var(--text3)', borderBottom: '1px solid var(--border)' },
    detailHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 },
    infoGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 },
    timeline: { display: 'grid', gap: 10 },
    eventRow: { display: 'grid', gridTemplateColumns: '14px 1fr', gap: 10, alignItems: 'start' },
    eventDot: { width: 9, height: 9, borderRadius: 99, marginTop: 5 },
    pre: { margin: 0, maxHeight: 220, overflow: 'auto', background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 12, padding: 10, color: 'var(--text2)', fontSize: 11 },
  };
}

function statusColor(status) {
  if (status === 'completed') return '#34d399';
  if (status === 'failed') return '#fb7185';
  if (status === 'cancelled') return '#f97316';
  if (status === 'running') return '#fbbf24';
  return '#94a3b8';
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatDuration(ms) {
  const value = Number(ms || 0);
  if (value < 1000) return `${value} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} sec`;
  return `${(value / 60_000).toFixed(1)} min`;
}

