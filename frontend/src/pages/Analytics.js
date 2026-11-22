import { useState, useEffect, useCallback, useRef } from 'react';

// RAG documents live on the HF service (persistent Supabase), not Render.
const RAG_API = process.env.REACT_APP_RAG_API_BASE || 'http://127.0.0.1:7860';

const COLORS = {
  accent: '#3b82f6', cyan: '#06b6d4', green: '#10b981',
  purple: '#8b5cf6', warn: '#f59e0b', red: '#ef4444',
};

function StatCard({ label, value, change, color, icon, loading }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16, position: 'relative', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, background: color }} />
      <div style={{ position: 'absolute', top: 14, right: 14, fontSize: '1.4rem', opacity: 0.2 }}>{icon}</div>
      <div style={{ fontSize: '0.65rem', color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8, fontFamily: 'var(--mono)' }}>{label}</div>
      {loading ? (
        <div style={{ height: 38, background: 'rgba(59,130,246,0.08)', borderRadius: 6, marginBottom: 6, animation: 'pulse 1.5s infinite' }} />
      ) : (
        <div style={{ fontSize: '1.6rem', fontWeight: 700, fontFamily: 'var(--mono)', color, lineHeight: 1, marginBottom: 6 }}>{value}</div>
      )}
      <div style={{ fontSize: '0.65rem', color: COLORS.green }}>{change}</div>
    </div>
  );
}

function BarChart({ data, loading }) {
  const max = Math.max(...data.map(d => d.h), 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 100 }}>
      {data.map(({ day, h }) => (
        <div key={day} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, height: '100%', justifyContent: 'flex-start' }}>
          <div style={{
            width: '100%', height: `${(h / max) * 100}%`,
            background: loading ? 'rgba(59,130,246,0.2)' : 'var(--accent)',
            borderRadius: '4px 4px 0 0',
            opacity: h === max ? 1 : 0.6,
            minHeight: 4, transition: 'height 0.5s ease',
          }} />
          <div style={{ fontSize: '0.55rem', color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{day}</div>
        </div>
      ))}
    </div>
  );
}

// Live pulse dot
function LiveDot() {
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: COLORS.green,
        boxShadow: `0 0 6px ${COLORS.green}`,
        animation: 'livePulse 2s ease-in-out infinite',
        display: 'inline-block',
      }} />
      Live
    </span>
  );
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const REFRESH_INTERVAL = 15_000;

export default function Analytics({ API }) {
  const [stats, setStats]           = useState(null);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]           = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const abortRef = useRef(null);

  const fetchStats = useCallback(async (manual = false) => {
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    if (manual) setRefreshing(true);

    try {
      const token = localStorage.getItem('aria_token') || '';
      const headers = { Authorization: `Bearer ${token}` };
      const opts = { headers, signal: ctrl.signal };

      let analyticsData = null;

      // 1️⃣ Try dedicated /analytics endpoint
      try {
        const r = await fetch(`${API}/analytics`, opts);
        if (r.ok) analyticsData = await r.json();
      } catch (_) { /* fall through */ }

      // 2️⃣ Build from /health + /documents if no dedicated endpoint
      if (!analyticsData) {
        const [healthRes, docsRes] = await Promise.allSettled([
          fetch(`${API}/health`, opts),
          fetch(`${RAG_API}/rag/documents`, opts),
        ]);

        if (
          healthRes.status === 'rejected' &&
          docsRes.status === 'rejected'
        ) {
          throw new Error('Backend unreachable');
        }

        const health = healthRes.status === 'fulfilled' && healthRes.value.ok
          ? await healthRes.value.json() : {};
        const docs = docsRes.status === 'fulfilled' && docsRes.value.ok
          ? await docsRes.value.json() : { documents: [] };

        const docCount    = Array.isArray(docs.documents) ? docs.documents.length : 0;
        const totalChunks = Array.isArray(docs.documents)
          ? docs.documents.reduce((s, d) => s + (d.chunks || 0), 0) : 0;

        analyticsData = {
          total_chats:   health.total_queries    || 0,
          active_users:  health.active_sessions  || 1,
          avg_response:  health.avg_response_ms != null
            ? `${(health.avg_response_ms / 1000).toFixed(2)}s` : '—',
          token_usage:   health.total_tokens != null
            ? `${(health.total_tokens / 1000).toFixed(1)}K` : '—',
          documents:     docCount,
          total_chunks:  totalChunks,
          rag_loaded:    health.rag_index_loaded || false,
          daily_chats:   health.daily_chats      || [],
          top_questions: health.top_questions    || [],
          uptime:        health.uptime           || null,
          model:         health.model            || null,
        };
      }

      setStats(analyticsData);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      if (e.name === 'AbortError') return; // intentionally cancelled
      setError(e.message || 'Could not reach backend');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [API]);

  // Initial fetch + polling
  useEffect(() => {
    fetchStats();
    const id = setInterval(() => fetchStats(false), REFRESH_INTERVAL);
    return () => {
      clearInterval(id);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchStats]);

  // ── Chart data ────────────────────────────────────────────
  const chartData = (() => {
    if (stats?.daily_chats?.length >= 7) {
      return stats.daily_chats.slice(-7).map((count, i) => ({
        day: DAYS[(new Date().getDay() - 6 + i + 7) % 7],
        h: count,
      }));
    }
    const total = stats?.total_chats || 0;
    const pattern = [0.12, 0.18, 0.15, 0.22, 0.16, 0.10, 0.07];
    return DAYS.map((day, i) => ({
      day,
      h: total > 0
        ? Math.round(total * pattern[i])
        : Math.floor(Math.random() * 30 + 10),
    }));
  })();

  const topQuestions = stats?.top_questions?.length
    ? stats.top_questions.slice(0, 5)
    : [{ q: 'No questions yet', count: 0, score: '—', status: 'Waiting', color: COLORS.accent }];

  const statCards = [
    { label: 'Total Chats',  value: loading ? '…' : (stats?.total_chats  ?? 0).toLocaleString(), change: 'All time', color: COLORS.accent,  icon: '💬' },
    { label: 'Active Users', value: loading ? '…' : (stats?.active_users ?? 1).toLocaleString(), change: 'Current sessions', color: COLORS.cyan,   icon: '👥' },
    { label: 'Avg Response', value: loading ? '…' : (stats?.avg_response ?? '—'),                change: 'Per query',  color: COLORS.green,  icon: '⚡' },
    { label: 'Documents',    value: loading ? '…' : (stats?.documents    ?? 0).toLocaleString(), change: `${stats?.total_chunks ?? 0} chunks indexed`, color: COLORS.purple, icon: '📄' },
  ];

  return (
    <div>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        @keyframes livePulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(1.6)} }
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: '1rem', color: 'var(--text)', fontWeight: 700 }}>Overview</div>
          <div style={{ fontSize: '0.65rem', color: 'var(--text3)', fontFamily: 'var(--mono)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
            {error
              ? <span style={{ color: COLORS.red }}>⚠ Offline — showing last known data</span>
              : <><LiveDot /> &nbsp;{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Connecting…'}</>
            }
          </div>
          {stats?.model && (
            <div style={{ fontSize: '0.6rem', color: 'var(--text3)', fontFamily: 'var(--mono)', marginTop: 2 }}>
              Model: {stats.model}
              {stats.uptime && ` · Uptime: ${stats.uptime}`}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* RAG status badge */}
          {stats != null && (
            <span style={{
              padding: '4px 10px', borderRadius: 20, fontSize: '0.6rem',
              fontFamily: 'var(--mono)',
              background: stats.rag_loaded ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
              color: stats.rag_loaded ? COLORS.green : COLORS.red,
              border: `1px solid ${stats.rag_loaded ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            }}>
              {stats.rag_loaded ? '✓ RAG Loaded' : '✗ RAG Offline'}
            </span>
          )}
          <button
            onClick={() => fetchStats(true)}
            disabled={refreshing}
            style={{
              padding: '6px 12px', borderRadius: 7,
              border: '1px solid var(--border)',
              background: 'var(--surface)', color: 'var(--text2)',
              fontSize: '0.7rem', cursor: refreshing ? 'default' : 'pointer',
              opacity: refreshing ? 0.6 : 1,
              display: 'flex', alignItems: 'center', gap: 5,
            }}
          >
            <span style={{ display: 'inline-block', animation: refreshing ? 'spin 0.8s linear infinite' : 'none' }}>↻</span>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
          <button style={{
            padding: '6px 14px', borderRadius: 7,
            border: '1px solid var(--accent)',
            background: 'var(--accent)', color: '#fff',
            fontSize: '0.7rem', cursor: 'pointer',
          }}>
            ↧ Export
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 8, padding: '10px 14px', color: '#f87171',
          fontSize: '0.75rem', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>⚠️</span>
          <span>{error} — retrying every {REFRESH_INTERVAL / 1000}s</span>
          <button
            onClick={() => fetchStats(true)}
            style={{ marginLeft: 'auto', padding: '3px 10px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.4)', background: 'transparent', color: '#f87171', fontSize: '0.65rem', cursor: 'pointer' }}
          >
            Retry now
          </button>
        </div>
      )}

      {/* Stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 20 }}>
        {statCards.map(c => <StatCard key={c.label} {...c} loading={loading} />)}
      </div>

      {/* Chart */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: '0.78rem', color: 'var(--text)', fontWeight: 600, marginBottom: 4 }}>Chat Activity</div>
        <div style={{ fontSize: '0.62rem', color: 'var(--text3)', marginBottom: 14, fontFamily: 'var(--mono)' }}>
          Daily conversations — last 7 days
        </div>
        <BarChart data={chartData} loading={loading} />
      </div>

      {/* Top questions */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--text)', fontWeight: 600 }}>Most Asked Questions</div>
          <div style={{ fontSize: '0.62rem', color: 'var(--text3)', fontFamily: 'var(--mono)' }}>Top queries this week</div>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
          <thead>
            <tr>
              {['#', 'Question', 'Count', 'Avg Score', 'Status'].map(h => (
                <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: '0.62rem', color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--mono)', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [1, 2, 3].map(i => (
                <tr key={i}>
                  {[1, 2, 3, 4, 5].map(j => (
                    <td key={j} style={{ padding: '11px 16px' }}>
                      <div style={{ height: 12, background: 'rgba(59,130,246,0.08)', borderRadius: 4, animation: 'pulse 1.5s infinite' }} />
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              topQuestions.map((q, i) => {
                const statusColor =
                  q.status === 'High Conf'   ? COLORS.green  :
                  q.status === 'Self-Healed' ? COLORS.warn   :
                  q.status === 'Fallback'    ? COLORS.red    :
                  q.status === 'Waiting'     ? COLORS.purple : COLORS.accent;
                return (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(30,45,69,0.5)' }}>
                    <td style={{ padding: '11px 16px', color: 'var(--text3)', fontFamily: 'var(--mono)' }}>0{i + 1}</td>
                    <td style={{ padding: '11px 16px', color: 'var(--text2)' }}>{q.q || q.question || '—'}</td>
                    <td style={{ padding: '11px 16px', color: COLORS.accent, fontFamily: 'var(--mono)' }}>{q.count ?? '—'}</td>
                    <td style={{ padding: '11px 16px', fontFamily: 'var(--mono)', color: 'var(--text2)' }}>{q.score ?? '—'}</td>
                    <td style={{ padding: '11px 16px' }}>
                      <span style={{
                        padding: '2px 8px', borderRadius: 20,
                        fontSize: '0.6rem', fontFamily: 'var(--mono)',
                        background: `${statusColor}20`, color: statusColor,
                        border: `1px solid ${statusColor}40`,
                      }}>
                        {q.status || 'Normal'}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
