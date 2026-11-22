import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const tabs = ['Overview', 'Users', 'Chats', 'Documents', 'Agents', 'System Health', 'Errors'];

export default function AnalyticsDashboard({ API = defaultApi }) {
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

  const [activeTab, setActiveTab] = useState('Overview');
  const [data, setData] = useState(emptyAnalytics());
  const [health, setHealth] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const reportFrontendError = (page, err, stackTrace = '') => {
    fetch(`${API}/analytics/error`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        user_id: userId,
        page,
        error: String(err || 'Unknown frontend error').slice(0, 2000),
        stack_trace: String(stackTrace || ''),
        metadata: {
          url: window.location.href,
          user_agent: navigator.userAgent,
        },
      }),
    }).catch(() => {});
  };

  const loadAnalytics = async () => {
    setLoading(true);
    setError('');
    try {
      const [dashboardRes, healthRes] = await Promise.all([
        fetch(`${API}/analytics/dashboard`, { headers }),
        fetch(`${API}/analytics/health`, { headers }),
      ]);
      const dashboardJson = await dashboardRes.json().catch(() => ({}));
      const healthJson = await healthRes.json().catch(() => ({}));
      if (!dashboardRes.ok) throw new Error(dashboardJson.detail || 'Analytics failed');
      if (!healthRes.ok) throw new Error(healthJson.detail || 'Health check failed');
      setData({ ...emptyAnalytics(), ...dashboardJson });
      setHealth(healthJson || {});
      fetch(`${API}/analytics/event`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          feature: 'analytics',
          action: 'center_viewed',
          metadata: { page: 'analytics', tab: activeTab },
        }),
      }).catch(() => {});
    } catch (err) {
      const message = err.message || 'Analytics failed';
      setError(message);
      reportFrontendError('analytics', message, err.stack || '');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalytics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId, activeTab]);

  useEffect(() => {
    const onError = (event) => {
      reportFrontendError(window.location.pathname || 'unknown', event.message, event.error?.stack || '');
    };
    const onUnhandled = (event) => {
      const reason = event.reason;
      reportFrontendError(
        window.location.pathname || 'unknown',
        reason?.message || String(reason || 'Unhandled promise rejection'),
        reason?.stack || ''
      );
    };
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onUnhandled);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onUnhandled);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId, headers]);

  const S = styles(loading);
  const summary = data.summary || {};
  const systemHealth = health && health.backend ? health : (data.system_health || {});

  return (
    <div style={S.page}>
      <style>{`
        @media (max-width: 1120px) {
          .analytics-grid-2,
          .analytics-grid-3,
          .analytics-grid-4 { grid-template-columns: 1fr !important; }
          .analytics-cards { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 680px) {
          .analytics-cards { grid-template-columns: 1fr !important; }
          .analytics-tabs { grid-template-columns: 1fr 1fr !important; }
          .analytics-table { min-width: 680px; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>Analytics & Monitoring Center</h1>
            <div style={S.sub}>Usage, system health, feature adoption, and frontend error tracking.</div>
          </div>
          <button type="button" onClick={loadAnalytics} disabled={loading} style={S.button}>
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>

        <div className="analytics-tabs" style={S.tabs}>
          {tabs.map((tabName) => (
            <button
              key={tabName}
              type="button"
              onClick={() => setActiveTab(tabName)}
              style={{
                ...S.tab,
                ...(activeTab === tabName ? S.activeTab : {}),
              }}
            >
              {tabName}
            </button>
          ))}
        </div>

        {error && (
          <div style={S.errorBox}>
            {error}
          </div>
        )}

        {activeTab === 'Overview' && (
          <Overview data={data} summary={summary} S={S} />
        )}

        {activeTab === 'Users' && (
          <UsersPage data={data} summary={summary} S={S} />
        )}

        {activeTab === 'Chats' && (
          <ChatsPage data={data} summary={summary} S={S} />
        )}

        {activeTab === 'Documents' && (
          <DocumentsPage data={data} summary={summary} S={S} />
        )}

        {activeTab === 'Agents' && (
          <AgentsPage data={data} summary={summary} S={S} />
        )}

        {activeTab === 'System Health' && (
          <SystemHealthPage health={systemHealth} summary={summary} S={S} />
        )}

        {activeTab === 'Errors' && (
          <ErrorsPage data={data} summary={summary} S={S} />
        )}
      </div>
    </div>
  );
}

function Overview({ data, summary, S }) {
  const insights = data.usage_insights || {};
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <Metric label="Total Users" value={summary.total_users || 0} color="#60a5fa" />
        <Metric label="Active Users" value={summary.active_users || 0} color="#34d399" />
        <Metric label="Total Chats" value={summary.total_chats || 0} color="#a78bfa" />
        <Metric label="Documents Uploaded" value={summary.documents_uploaded || summary.documents_indexed || 0} color="#fbbf24" />
        <Metric label="Code Reviews Run" value={summary.code_reviews_run || 0} color="#38bdf8" />
        <Metric label="Vision Requests" value={summary.vision_requests || 0} color="#f472b6" />
        <Metric label="Security Scans" value={summary.security_scans || 0} color="#fb7185" />
        <Metric label="Tracked Errors" value={summary.total_errors || 0} color="#f97316" />
        <Metric label="Run Count" value={summary.run_count || 0} color="#38bdf8" />
        <Metric label="Run Success Rate" value={`${summary.run_success_rate || 0}%`} color="#34d399" />
        <Metric label="Run Failure Rate" value={`${summary.run_failure_rate || 0}%`} color="#fb7185" />
        <Metric label="Run Avg Duration" value={`${summary.run_avg_duration_ms || 0} ms`} color="#fbbf24" />
      </div>

      <div className="analytics-grid-2" style={S.grid2}>
        <Panel title="Daily Usage" S={S}>
          <BarChart rows={data.daily_usage || []} labelKey="day" valueKey="events" color="#38bdf8" />
        </Panel>
        <Panel title="Usage Analytics" S={S}>
          <div style={S.infoGrid}>
            <InfoRow label="Most Used Agent" value={insights.most_used_agent || 'No data yet'} />
            <InfoRow label="Most Asked Topic" value={insights.most_asked_topic || 'No data yet'} />
            <InfoRow label="Most Uploaded File Type" value={insights.most_uploaded_file_type || 'No data yet'} />
            <InfoRow label="Most Active User" value={insights.most_active_user || 'No data yet'} />
          </div>
        </Panel>
      </div>

      <div className="analytics-grid-3" style={S.grid3}>
        <Panel title="Feature Usage" S={S}>
          <RankList rows={data.feature_usage || []} titleKey="feature" meta={(row) => `${row.events} events / ${formatNumber(row.tokens)} tokens`} />
        </Panel>
        <Panel title="Model Usage" S={S}>
          <RankList rows={data.model_usage || []} titleKey="model" meta={(row) => `${row.calls} calls / ${formatNumber(row.tokens)} tokens`} />
        </Panel>
        <Panel title="Top Users" S={S}>
          <RankList rows={data.top_users || []} titleKey="user_id" meta={(row) => `${row.events} events / ${formatNumber(row.tokens)} tokens`} />
        </Panel>
      </div>
    </div>
  );
}

function UsersPage({ data, summary, S }) {
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <Metric label="Total Users" value={summary.total_users || 0} color="#60a5fa" />
        <Metric label="Active Users" value={summary.active_users || 0} color="#34d399" />
        <Metric label="Team Members" value={summary.team_members || 0} color="#fbbf24" />
        <Metric label="Most Active User" value={(data.usage_insights || {}).most_active_user || 'No data'} color="#a78bfa" compact />
      </div>
      <Panel title="Users" S={S}>
        <DataTable
          columns={['User', 'Events', 'Tokens', 'Failures', 'Last Seen']}
          rows={(data.users || []).map((row) => [
            row.user_id,
            formatNumber(row.events),
            formatNumber(row.tokens),
            formatNumber(row.failures),
            formatDate(row.last_seen),
          ])}
          empty="No user activity yet."
        />
      </Panel>
    </div>
  );
}

function ChatsPage({ data, summary, S }) {
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <Metric label="Total Chats" value={summary.total_chats || 0} color="#a78bfa" />
        <Metric label="Tokens Used" value={formatNumber(summary.tokens_used || 0)} color="#38bdf8" />
        <Metric label="Average Latency" value={`${summary.avg_duration_ms || 0} ms`} color="#fbbf24" />
        <Metric label="Most Asked Topic" value={(data.usage_insights || {}).most_asked_topic || 'No data'} color="#34d399" compact />
      </div>
      <div className="analytics-grid-2" style={S.grid2}>
        <Panel title="Daily Chats" S={S}>
          <BarChart rows={data.daily_usage || []} labelKey="day" valueKey="events" color="#a78bfa" />
        </Panel>
        <Panel title="Asked Topics" S={S}>
          <RankList rows={data.topic_usage || []} titleKey="topic" meta={(row) => `${row.count} requests`} />
        </Panel>
      </div>
      <Panel title="Recent Chats" S={S}>
        <DataTable
          columns={['User', 'Action', 'Model', 'Tokens', 'Latency', 'Status', 'Time']}
          rows={(data.recent_chats || []).map((row) => [
            row.user_id,
            row.action,
            row.model || 'unknown',
            formatNumber(row.tokens),
            `${row.duration_ms || 0} ms`,
            row.status,
            formatDate(row.created_at),
          ])}
          empty="No chat activity yet."
        />
      </Panel>
    </div>
  );
}

function DocumentsPage({ data, summary, S }) {
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <Metric label="Documents Uploaded" value={summary.documents_uploaded || summary.documents_indexed || 0} color="#fbbf24" />
        <Metric label="Most Uploaded File Type" value={(data.usage_insights || {}).most_uploaded_file_type || 'No data'} color="#38bdf8" compact />
        <Metric label="Generated Storage" value={formatBytes(summary.generated_storage_bytes || 0)} color="#34d399" />
        <Metric label="Documents Indexed" value={summary.documents_indexed || 0} color="#a78bfa" />
      </div>
      <div className="analytics-grid-2" style={S.grid2}>
        <Panel title="File Types" S={S}>
          <RankList rows={data.document_types || []} titleKey="type" meta={(row) => `${row.count} files`} />
        </Panel>
        <Panel title="Top Documents" S={S}>
          <RankList rows={data.top_documents || []} titleKey="name" meta={(row) => `${row.extension || 'file'} / ${formatBytes(row.size || 0)}`} />
        </Panel>
      </div>
      <Panel title="Documents" S={S}>
        <DataTable
          columns={['Name', 'Type', 'Size', 'Updated']}
          rows={(data.top_documents || []).map((row) => [
            row.name,
            row.extension || 'file',
            formatBytes(row.size || 0),
            formatDate(row.updated_at),
          ])}
          empty="No uploaded documents found."
        />
      </Panel>
    </div>
  );
}

function AgentsPage({ data, summary, S }) {
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <Metric label="Agent Tasks" value={summary.agent_tasks || 0} color="#f472b6" />
        <Metric label="Most Used Agent" value={(data.usage_insights || {}).most_used_agent || 'No data'} color="#60a5fa" compact />
        <Metric label="Code Reviews Run" value={summary.code_reviews_run || 0} color="#38bdf8" />
        <Metric label="Security Scans" value={summary.security_scans || 0} color="#fb7185" />
      </div>
      <div className="analytics-grid-2" style={S.grid2}>
        <Panel title="Agent Usage" S={S}>
          <RankList rows={data.agent_usage || []} titleKey="agent" meta={(row) => `${row.events} events`} />
        </Panel>
        <Panel title="Feature Usage" S={S}>
          <RankList rows={data.feature_usage || []} titleKey="feature" meta={(row) => `${row.events} events / ${formatNumber(row.tokens)} tokens`} />
        </Panel>
      </div>
    </div>
  );
}

function SystemHealthPage({ health, summary, S }) {
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <HealthMetric label="Backend Status" status={health.backend || 'offline'} value={health.backend || 'offline'} />
        <HealthMetric label="Database Status" status={health.database || 'offline'} value={health.database || 'offline'} />
        <HealthMetric label="RAG Status" status={health.rag ? 'online' : 'warning'} value={health.rag ? 'ready' : 'not loaded'} />
        <Metric label="API Failures" value={summary.api_failures || 0} color="#f97316" />
      </div>
      <div className="analytics-grid-3" style={S.grid3}>
        <Panel title="CPU Usage" S={S}>
          <UsageBlock label="CPU" item={health.cpu_usage || {}} />
        </Panel>
        <Panel title="Memory Usage" S={S}>
          <UsageBlock label="Memory" item={health.memory_usage || {}} detail={formatBytes((health.memory_usage || {}).process_bytes || 0)} />
        </Panel>
        <Panel title="Disk Usage" S={S}>
          <UsageBlock label="Disk" item={health.disk_usage || {}} detail={`${formatBytes((health.disk_usage || {}).free_bytes || 0)} free`} />
        </Panel>
      </div>
      <Panel title="System Health" S={S}>
        <div style={S.infoGrid}>
          <InfoRow label="Backend Status" value={health.backend || 'offline'} />
          <InfoRow label="Database Status" value={health.database || 'offline'} />
          <InfoRow label="RAG Status" value={health.rag ? 'ready' : 'not loaded'} />
          <InfoRow label="Analytics DB" value={health.analytics_db || 'unknown'} />
          <InfoRow label="Analytics DB Size" value={formatBytes(health.analytics_db_size || 0)} />
          <InfoRow label="Checked At" value={formatDate(health.checked_at)} />
        </div>
      </Panel>
    </div>
  );
}

function ErrorsPage({ data, summary, S }) {
  return (
    <div style={S.stack}>
      <div className="analytics-cards" style={S.grid4}>
        <Metric label="Tracked Errors" value={summary.total_errors || 0} color="#f97316" />
        <Metric label="API Failures" value={summary.api_failures || 0} color="#fb7185" />
        <Metric label="Average Latency" value={`${summary.avg_duration_ms || 0} ms`} color="#fbbf24" />
        <Metric label="Total Events" value={formatNumber(summary.total_events || 0)} color="#60a5fa" />
      </div>
      <div className="analytics-grid-2" style={S.grid2}>
        <Panel title="Errors By Page" S={S}>
          <RankList rows={data.errors_by_page || []} titleKey="page" meta={(row) => `${row.count} errors`} />
        </Panel>
        <Panel title="API Failures" S={S}>
          <FailureList rows={data.recent_failures || []} />
        </Panel>
      </div>
      <Panel title="Error Logs" S={S}>
        <DataTable
          columns={['Timestamp', 'User', 'Page', 'Error', 'Stack Trace']}
          rows={(data.recent_errors || []).map((row) => [
            formatDate(row.created_at),
            row.user_id,
            row.page || 'unknown',
            row.error,
            row.stack_trace ? row.stack_trace.slice(0, 120) : '',
          ])}
          empty="No frontend errors recorded."
        />
      </Panel>
    </div>
  );
}

function Panel({ title, children, S }) {
  return (
    <section style={S.panel}>
      <div style={S.sectionTitle}>{title}</div>
      {children}
    </section>
  );
}

function Metric({ label, value, color, compact = false }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 14, minWidth: 0 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{
        color,
        fontSize: compact ? 16 : 24,
        fontWeight: 850,
        marginTop: 5,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: compact ? 'nowrap' : 'normal',
      }}>
        {value}
      </div>
    </div>
  );
}

function HealthMetric({ label, status, value }) {
  const color = statusColor(status);
  return (
    <div style={{ background: '#0f172a', border: `1px solid ${color.border}`, borderRadius: 8, padding: 14 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{ color: color.text, fontSize: 20, fontWeight: 850, marginTop: 5, textTransform: 'capitalize' }}>{value}</div>
    </div>
  );
}

function UsageBlock({ label, item, detail }) {
  const percent = Number.isFinite(Number(item.percent)) ? Number(item.percent) : null;
  const color = statusColor(item.status);
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, color: '#cbd5e1', fontSize: 13 }}>
        <span>{label}</span>
        <span style={{ color: color.text, fontWeight: 850 }}>{percent === null ? 'Unavailable' : `${percent}%`}</span>
      </div>
      <div style={{ height: 10, background: '#111827', borderRadius: 8, overflow: 'hidden', border: '1px solid rgba(148,163,184,.12)' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, percent || 0))}%`, background: color.text, borderRadius: 8 }} />
      </div>
      <div style={{ color: '#64748b', fontSize: 11 }}>{detail || item.status || 'online'}</div>
    </div>
  );
}

function BarChart({ rows, labelKey, valueKey, color }) {
  const max = Math.max(1, ...rows.map((row) => Number(row[valueKey] || 0)));
  return (
    <div style={{ display: 'grid', gap: 9 }}>
      {rows.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No usage events yet.</div>
      ) : rows.map((row) => {
        const value = Number(row[valueKey] || 0);
        return (
          <div key={row[labelKey]} style={{ display: 'grid', gridTemplateColumns: '92px 1fr 54px', gap: 9, alignItems: 'center' }}>
            <div style={{ color: '#94a3b8', fontSize: 11 }}>{String(row[labelKey]).slice(-10)}</div>
            <div style={{ height: 10, background: '#111827', borderRadius: 8, overflow: 'hidden', border: '1px solid rgba(148,163,184,.12)' }}>
              <div style={{ height: '100%', width: `${Math.max(4, (value / max) * 100)}%`, background: color, borderRadius: 8 }} />
            </div>
            <div style={{ color: '#cbd5e1', fontSize: 11, textAlign: 'right' }}>{value}</div>
          </div>
        );
      })}
    </div>
  );
}

function RankList({ rows, titleKey, meta }) {
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No data yet.</div>
      ) : rows.map((row, index) => (
        <div key={`${row[titleKey]}-${index}`} style={{ display: 'grid', gridTemplateColumns: '28px 1fr', gap: 8, alignItems: 'center', background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
          <div style={{ color: '#38bdf8', fontWeight: 850, fontSize: 13 }}>{index + 1}</div>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#f8fafc', fontSize: 13, fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row[titleKey] || 'Unknown'}</div>
            <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 3 }}>{meta(row)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function FailureList({ rows }) {
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.length === 0 ? (
        <div style={{ color: '#34d399', fontSize: 13 }}>No API failures recorded.</div>
      ) : rows.map((row, index) => (
        <div key={`${row.created_at}-${index}`} style={{ background: '#111827', border: '1px solid rgba(248,113,113,.2)', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ color: '#fecaca', fontSize: 13, fontWeight: 850 }}>{row.feature} / {row.action}</div>
            <div style={{ color: '#64748b', fontSize: 11 }}>{formatDate(row.created_at)}</div>
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 5 }}>{row.status}</div>
        </div>
      ))}
    </div>
  );
}

function DataTable({ columns, rows, empty }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="analytics-table" style={{ width: '100%', borderCollapse: 'collapse', color: '#cbd5e1', fontSize: 12 }}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} style={{ textAlign: 'left', color: '#94a3b8', fontWeight: 850, padding: '0 10px 9px', borderBottom: '1px solid rgba(148,163,184,.18)' }}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} style={{ padding: '12px 10px', color: '#64748b', borderBottom: '1px solid rgba(148,163,184,.1)' }}>
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={`${rowIndex}-${cellIndex}`} style={{ padding: '10px', borderBottom: '1px solid rgba(148,163,184,.1)', maxWidth: cellIndex === 0 ? 260 : 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {cell || '-'}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10, minWidth: 0 }}>
      <span style={{ color: '#94a3b8', flexShrink: 0 }}>{label}</span>
      <span style={{ color: '#f8fafc', fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  );
}

function emptyAnalytics() {
  return {
    summary: {},
    daily_usage: [],
    model_usage: [],
    top_users: [],
    users: [],
    recent_chats: [],
    top_documents: [],
    document_types: [],
    agent_usage: [],
    topic_usage: [],
    feature_usage: [],
    recent_failures: [],
    recent_errors: [],
    errors_by_page: [],
    usage_insights: {},
    health: {},
    system_health: {},
  };
}

function styles(loading) {
  return {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: '#07111a',
      color: '#e5e7eb',
      padding: 22,
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    },
    shell: {
      maxWidth: 1260,
      margin: '0 auto',
      display: 'grid',
      gap: 16,
    },
    stack: {
      display: 'grid',
      gap: 14,
    },
    header: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 14,
      flexWrap: 'wrap',
    },
    title: {
      margin: 0,
      color: '#f8fafc',
      fontSize: 23,
      fontWeight: 850,
    },
    sub: {
      color: '#94a3b8',
      fontSize: 13,
      marginTop: 4,
    },
    panel: {
      background: '#0f172a',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: 16,
      boxShadow: '0 16px 36px rgba(0,0,0,.24)',
      minWidth: 0,
    },
    grid4: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 12,
    },
    grid3: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
      gap: 14,
    },
    grid2: {
      display: 'grid',
      gridTemplateColumns: '1.2fr .8fr',
      gap: 14,
    },
    infoGrid: {
      display: 'grid',
      gap: 9,
      color: '#cbd5e1',
      fontSize: 12,
    },
    tabs: {
      display: 'grid',
      gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
      gap: 8,
      background: '#0f172a',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: 8,
    },
    tab: {
      border: '1px solid transparent',
      borderRadius: 8,
      background: 'transparent',
      color: '#94a3b8',
      fontSize: 12,
      fontWeight: 800,
      padding: '9px 8px',
      cursor: 'pointer',
      whiteSpace: 'nowrap',
    },
    activeTab: {
      background: 'linear-gradient(135deg, rgba(37,99,235,.28), rgba(20,184,166,.22))',
      color: '#f8fafc',
      border: '1px solid rgba(96,165,250,.28)',
    },
    button: {
      border: 'none',
      borderRadius: 8,
      padding: '10px 13px',
      color: '#fff',
      fontWeight: 850,
      background: 'linear-gradient(135deg,#2563eb,#0f766e)',
      cursor: loading ? 'not-allowed' : 'pointer',
      whiteSpace: 'nowrap',
    },
    sectionTitle: {
      color: '#cbd5e1',
      fontSize: 13,
      fontWeight: 850,
      marginBottom: 10,
    },
    errorBox: {
      color: '#fecaca',
      background: 'rgba(239,68,68,.12)',
      border: '1px solid rgba(248,113,113,.25)',
      borderRadius: 8,
      padding: 10,
      fontSize: 13,
    },
  };
}

function statusColor(status) {
  if (status === 'critical' || status === 'offline' || status === 'error') {
    return { text: '#fb7185', border: 'rgba(251,113,133,.35)' };
  }
  if (status === 'warning' || status === 'unavailable') {
    return { text: '#fbbf24', border: 'rgba(251,191,36,.35)' };
  }
  return { text: '#34d399', border: 'rgba(52,211,153,.35)' };
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

