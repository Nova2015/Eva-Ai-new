import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const tabs = ['Dashboard', 'Tasks', 'History', 'Scheduler', 'Marketplace', 'Reports'];

const agentOptions = [
  { value: 'repo', label: 'Repo Agent' },
  { value: 'deployment', label: 'Deployment Agent' },
  { value: 'security', label: 'Security Agent' },
  { value: 'memory', label: 'Memory Agent' },
  { value: 'report', label: 'Report Agent' },
];

export default function AgentCenter({ API = defaultApi }) {
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

  const [activeTab, setActiveTab] = useState('Dashboard');
  const [dashboard, setDashboard] = useState({ agents: [], counts: {}, recent_tasks: [], schedules: [] });
  const [tasks, setTasks] = useState([]);
  const [history, setHistory] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [marketplace, setMarketplace] = useState([]);
  const [report, setReport] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [taskForm, setTaskForm] = useState({
    agent_type: 'repo',
    title: 'Review project',
    instruction: 'Review EVA AI project and suggest fixes.',
    payload: '',
    priority: 3,
  });
  const [scheduleForm, setScheduleForm] = useState({
    name: 'Backend health check',
    agent_type: 'deployment',
    cron_label: 'Every hour',
    instruction: 'Check backend health and detect deployment failures.',
  });

  const loadAgentOS = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      const [dashRes, tasksRes, historyRes, schedulesRes, marketRes] = await Promise.all([
        fetch(`${API}/agent-os/dashboard?${params.toString()}`, { headers }),
        fetch(`${API}/agent-os/tasks?${params.toString()}`, { headers }),
        fetch(`${API}/agent-os/history?${params.toString()}`, { headers }),
        fetch(`${API}/agent-os/schedules?${params.toString()}`, { headers }),
        fetch(`${API}/agent-os/marketplace`, { headers }),
      ]);

      const dash = await dashRes.json().catch(() => ({}));
      const taskData = await tasksRes.json().catch(() => ({}));
      const historyData = await historyRes.json().catch(() => ({}));
      const scheduleData = await schedulesRes.json().catch(() => ({}));
      const marketData = await marketRes.json().catch(() => ({}));

      if (!dashRes.ok) throw new Error(dash.detail || 'Agent dashboard failed');
      setDashboard(dash);
      setTasks(taskData.tasks || []);
      setHistory(historyData.history || []);
      setSchedules(scheduleData.schedules || []);
      setMarketplace(marketData.agents || []);
    } catch (err) {
      setError(err.message || 'Agent OS unavailable');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAgentOS();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId]);

  const parsePayload = (text) => {
    if (!text.trim()) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { note: text };
    }
  };

  const runTask = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/agent-os/tasks`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          agent_type: taskForm.agent_type,
          title: taskForm.title,
          instruction: taskForm.instruction,
          payload: parsePayload(taskForm.payload),
          priority: Number(taskForm.priority),
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Task failed');
      await loadAgentOS();
      setActiveTab('Tasks');
    } catch (err) {
      setError(err.message || 'Task failed');
    } finally {
      setLoading(false);
    }
  };

  const createSchedule = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/agent-os/schedules`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, ...scheduleForm }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Schedule failed');
      await loadAgentOS();
      setActiveTab('Scheduler');
    } catch (err) {
      setError(err.message || 'Schedule failed');
    } finally {
      setLoading(false);
    }
  };

  const generateReport = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      const res = await fetch(`${API}/agent-os/report?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Report failed');
      setReport(json.report || '');
      setActiveTab('Reports');
    } catch (err) {
      setError(err.message || 'Report failed');
    } finally {
      setLoading(false);
    }
  };

  const downloadReport = async (format) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId, format });
      const res = await fetch(`${API}/agent-os/report/download?${params.toString()}`, { headers });
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eva-agent-report.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'Download failed');
    } finally {
      setLoading(false);
    }
  };

  const styles = {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: '#08111e',
      color: '#e5e7eb',
      padding: 22,
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    },
    shell: {
      maxWidth: 1240,
      margin: '0 auto',
      display: 'grid',
      gap: 16,
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
      marginTop: 4,
      color: '#94a3b8',
      fontSize: 13,
    },
    tabs: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap',
    },
    tab: {
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: '9px 12px',
      background: '#0f172a',
      color: '#94a3b8',
      cursor: 'pointer',
      fontWeight: 750,
      fontSize: 12,
    },
    activeTab: {
      background: 'linear-gradient(135deg,#2563eb,#0f766e)',
      color: '#fff',
      borderColor: 'transparent',
    },
    panel: {
      background: '#0f172a',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: 16,
      boxShadow: '0 16px 36px rgba(0,0,0,.24)',
    },
    grid4: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 12,
    },
    grid2: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 14,
    },
    input: {
      width: '100%',
      borderRadius: 8,
      border: '1px solid rgba(148,163,184,.24)',
      background: '#020617',
      color: '#e5e7eb',
      padding: '10px 12px',
      boxSizing: 'border-box',
      outline: 'none',
      fontSize: 13,
      fontFamily: 'inherit',
    },
    textarea: {
      width: '100%',
      minHeight: 92,
      resize: 'vertical',
      borderRadius: 8,
      border: '1px solid rgba(148,163,184,.24)',
      background: '#020617',
      color: '#e5e7eb',
      padding: 12,
      boxSizing: 'border-box',
      outline: 'none',
      lineHeight: 1.45,
      fontSize: 13,
      fontFamily: 'inherit',
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
  };

  const renderTab = () => {
    if (activeTab === 'Dashboard') {
      return (
        <div style={{ display: 'grid', gap: 14 }}>
          <div className="agent-grid" style={styles.grid4}>
            <Stat label="Running Agents" value={dashboard.running_agents || 0} />
            <Stat label="Running Tasks" value={dashboard.counts?.running || 0} />
            <Stat label="Completed" value={dashboard.counts?.completed || 0} />
            <Stat label="Scheduled Jobs" value={dashboard.counts?.scheduled || 0} />
          </div>
          <div className="agent-grid" style={styles.grid2}>
            <div style={styles.panel}>
              <div style={styles.sectionTitle}>Agent Dashboard</div>
              <div style={{ display: 'grid', gap: 8 }}>
                {(dashboard.agents || []).map((agent) => (
                  <AgentRow key={agent.id} agent={agent} />
                ))}
              </div>
            </div>
            <div style={styles.panel}>
              <div style={styles.sectionTitle}>Scheduled Jobs</div>
              <ScheduleList schedules={schedules.slice(0, 6)} />
            </div>
          </div>
        </div>
      );
    }

    if (activeTab === 'Tasks') {
      return (
        <div className="agent-grid" style={styles.grid2}>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Create Agent Task</div>
            <div style={{ display: 'grid', gap: 10 }}>
              <select value={taskForm.agent_type} onChange={(e) => setTaskForm({ ...taskForm, agent_type: e.target.value })} style={styles.input}>
                {agentOptions.map((agent) => <option key={agent.value} value={agent.value}>{agent.label}</option>)}
              </select>
              <input value={taskForm.title} onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} placeholder="Task title" style={styles.input} />
              <textarea value={taskForm.instruction} onChange={(e) => setTaskForm({ ...taskForm, instruction: e.target.value })} placeholder="Task instruction" style={styles.textarea} />
              <textarea value={taskForm.payload} onChange={(e) => setTaskForm({ ...taskForm, payload: e.target.value })} placeholder='Optional JSON payload, for example {"urls":["http://localhost:8002/health"]}' style={{ ...styles.textarea, minHeight: 70 }} />
              <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 8 }}>
                <input type="number" min="1" max="5" value={taskForm.priority} onChange={(e) => setTaskForm({ ...taskForm, priority: e.target.value })} style={styles.input} />
                <button type="button" onClick={runTask} disabled={loading || !taskForm.instruction.trim()} style={styles.button}>{loading ? 'Running' : 'Run Agent Task'}</button>
              </div>
            </div>
          </div>
          <TaskList tasks={tasks} />
        </div>
      );
    }

    if (activeTab === 'History') {
      return <HistoryList history={history} />;
    }

    if (activeTab === 'Scheduler') {
      return (
        <div className="agent-grid" style={styles.grid2}>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Create Schedule</div>
            <div style={{ display: 'grid', gap: 10 }}>
              <input value={scheduleForm.name} onChange={(e) => setScheduleForm({ ...scheduleForm, name: e.target.value })} placeholder="Schedule name" style={styles.input} />
              <select value={scheduleForm.agent_type} onChange={(e) => setScheduleForm({ ...scheduleForm, agent_type: e.target.value })} style={styles.input}>
                {agentOptions.map((agent) => <option key={agent.value} value={agent.value}>{agent.label}</option>)}
              </select>
              <input value={scheduleForm.cron_label} onChange={(e) => setScheduleForm({ ...scheduleForm, cron_label: e.target.value })} placeholder="Every hour" style={styles.input} />
              <textarea value={scheduleForm.instruction} onChange={(e) => setScheduleForm({ ...scheduleForm, instruction: e.target.value })} placeholder="Schedule instruction" style={styles.textarea} />
              <button type="button" onClick={createSchedule} disabled={loading || !scheduleForm.name.trim()} style={styles.button}>Save Schedule</button>
            </div>
          </div>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Agent Scheduler</div>
            <ScheduleList schedules={schedules} />
          </div>
        </div>
      );
    }

    if (activeTab === 'Marketplace') {
      return (
        <div className="agent-grid" style={styles.grid4}>
          {marketplace.map((agent) => (
            <div key={agent.id} style={styles.panel}>
              <div style={{ color: '#f8fafc', fontWeight: 850, marginBottom: 5 }}>{agent.name}</div>
              <div style={{ color: '#38bdf8', fontSize: 11, fontWeight: 850, textTransform: 'uppercase' }}>{agent.category}</div>
              <div style={{ color: '#94a3b8', fontSize: 13, lineHeight: 1.45, marginTop: 10 }}>{agent.description}</div>
              <div style={{ marginTop: 12 }}><StatusPill status={agent.status} /></div>
            </div>
          ))}
        </div>
      );
    }

    return (
      <div className="agent-grid" style={styles.grid2}>
        <div style={styles.panel}>
          <div style={styles.sectionTitle}>Project Report Generator</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" onClick={generateReport} disabled={loading} style={styles.button}>Generate Report</button>
            <button type="button" onClick={() => downloadReport('md')} disabled={loading} style={styles.button}>Markdown</button>
            <button type="button" onClick={() => downloadReport('docx')} disabled={loading} style={styles.button}>DOCX</button>
            <button type="button" onClick={() => downloadReport('pdf')} disabled={loading} style={styles.button}>PDF</button>
          </div>
        </div>
        <div style={styles.panel}>
          <div style={styles.sectionTitle}>Report Preview</div>
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#cbd5e1', fontSize: 12, lineHeight: 1.45, maxHeight: 460, overflow: 'auto' }}>
            {report || 'No report generated yet.'}
          </pre>
        </div>
      </div>
    );
  };

  return (
    <div style={styles.page}>
      <style>{`
        @media (max-width: 1100px) {
          .agent-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
      <div style={styles.shell}>
        <div style={styles.header}>
          <div>
            <h1 style={styles.title}>Agent Center</h1>
            <div style={styles.sub}>EVA Agent OS for repository, deployment, security, memory, scheduler, and reporting work.</div>
          </div>
          <button type="button" onClick={loadAgentOS} disabled={loading} style={styles.button}>{loading ? 'Refreshing' : 'Refresh'}</button>
        </div>

        {error && (
          <div style={{ color: '#fecaca', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(248,113,113,.25)', borderRadius: 8, padding: 10, fontSize: 13 }}>
            {error}
          </div>
        )}

        <div style={styles.tabs}>
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              style={{ ...styles.tab, ...(activeTab === tab ? styles.activeTab : {}) }}
            >
              {tab}
            </button>
          ))}
        </div>

        {renderTab()}
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const colors = {
    ready: ['rgba(16,185,129,.14)', '#34d399'],
    running: ['rgba(59,130,246,.15)', '#60a5fa'],
    completed: ['rgba(16,185,129,.14)', '#34d399'],
    installed: ['rgba(16,185,129,.14)', '#34d399'],
    warning: ['rgba(245,158,11,.15)', '#fbbf24'],
    failed: ['rgba(239,68,68,.15)', '#fca5a5'],
  };
  const c = colors[status] || colors.ready;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', borderRadius: 999, padding: '4px 9px', background: c[0], color: c[1], fontSize: 11, fontWeight: 850, textTransform: 'uppercase' }}>
      {status || 'ready'}
    </span>
  );
}

function Stat({ label, value }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 14 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{ color: '#f8fafc', fontSize: 24, fontWeight: 850, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function AgentRow({ agent }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center', gap: 10, background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
      <div>
        <div style={{ color: '#f8fafc', fontSize: 13, fontWeight: 850 }}>{agent.name}</div>
        <div style={{ color: '#64748b', fontSize: 11, marginTop: 3 }}>{agent.last_task || 'Ready for tasks'}</div>
      </div>
      <StatusPill status={agent.status} />
    </div>
  );
}

function ScheduleList({ schedules }) {
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {schedules.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No schedules yet.</div>
      ) : schedules.map((schedule) => (
        <div key={schedule.id} style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ color: '#f8fafc', fontWeight: 850, fontSize: 13 }}>{schedule.name}</div>
            <StatusPill status={schedule.enabled ? 'ready' : 'warning'} />
          </div>
          <div style={{ color: '#38bdf8', fontSize: 11, fontWeight: 850, marginTop: 5 }}>{schedule.cron_label} / {schedule.agent_type}</div>
          <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 5 }}>{schedule.instruction}</div>
        </div>
      ))}
    </div>
  );
}

function TaskList({ tasks }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 16 }}>
      <div style={{ color: '#cbd5e1', fontSize: 13, fontWeight: 850, marginBottom: 10 }}>Agent Tasks</div>
      <div style={{ display: 'grid', gap: 8 }}>
        {tasks.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>No Agent OS tasks yet.</div>
        ) : tasks.map((task) => (
          <div key={task.id} style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <div>
                <div style={{ color: '#f8fafc', fontWeight: 850, fontSize: 13 }}>{task.title}</div>
                <div style={{ color: '#38bdf8', fontSize: 11, fontWeight: 850, marginTop: 4 }}>{task.agent_type} / priority {task.priority}</div>
              </div>
              <StatusPill status={task.status} />
            </div>
            <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 7 }}>{task.instruction}</div>
            {task.result && (
              <pre style={{ margin: '8px 0 0', color: '#cbd5e1', whiteSpace: 'pre-wrap', fontSize: 11, maxHeight: 180, overflow: 'auto' }}>
                {task.result}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function HistoryList({ history }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 16 }}>
      <div style={{ color: '#cbd5e1', fontSize: 13, fontWeight: 850, marginBottom: 10 }}>Agent History</div>
      <div style={{ display: 'grid', gap: 8 }}>
        {history.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>No history yet.</div>
        ) : history.map((item) => (
          <div key={item.id} style={{ display: 'grid', gridTemplateColumns: '160px 120px 1fr', gap: 10, alignItems: 'center', background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
            <div style={{ color: '#64748b', fontSize: 11 }}>{item.created_at}</div>
            <div style={{ color: '#38bdf8', fontSize: 11, fontWeight: 850, textTransform: 'uppercase' }}>{item.agent_type} / {item.event}</div>
            <div style={{ color: '#cbd5e1', fontSize: 12 }}>{item.details}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

