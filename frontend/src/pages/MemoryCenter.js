import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

export default function MemoryCenter({ API = defaultApi }) {
  const storedUser = (() => {
    try {
      return JSON.parse(localStorage.getItem('aria_user') || '{}');
    } catch {
      return {};
    }
  })();

  const userId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const [query, setQuery] = useState('');
  const [memoryText, setMemoryText] = useState('');
  const [memoryType, setMemoryType] = useState('project');
  const [importance, setImportance] = useState(3);
  const [data, setData] = useState({ memories: [], recent_chats: [], search_results: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const token = localStorage.getItem('aria_token');

  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
  }), [token]);

  const loadMemories = async (search = query) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      if (search.trim()) params.set('q', search.trim());
      const res = await fetch(`${API}/memory-v2?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Memory load failed');
      setData(json);
    } catch (err) {
      setError(err.message || 'Memory load failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMemories('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId]);

  const addMemory = async () => {
    if (!memoryText.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/memory-v2`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          content: memoryText,
          memory_type: memoryType,
          importance: Number(importance),
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Save memory failed');
      setMemoryText('');
      await loadMemories('');
    } catch (err) {
      setError(err.message || 'Save memory failed');
    } finally {
      setLoading(false);
    }
  };

  const deleteMemory = async (id) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      const res = await fetch(`${API}/memory-v2/${id}?${params.toString()}`, {
        method: 'DELETE',
        headers,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Delete failed');
      await loadMemories(query);
    } catch (err) {
      setError(err.message || 'Delete failed');
    } finally {
      setLoading(false);
    }
  };

  const exportMemory = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      const res = await fetch(`${API}/memory-v2/export?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Export failed');
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eva-memory-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'Export failed');
    } finally {
      setLoading(false);
    }
  };

  const memories = data.memories || [];
  const recent = memories.slice(0, 8);
  const important = memories.filter((m) => Number(m.importance || 1) >= 3).slice(0, 8);
  const projects = memories.filter((m) => m.memory_type === 'project').slice(0, 8);
  const searchResults = data.search_results || [];

  const styles = {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: '#07111f',
      color: '#e5e7eb',
      padding: 22,
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    },
    shell: {
      maxWidth: 1220,
      margin: '0 auto',
      display: 'grid',
      gap: 16,
    },
    header: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 14,
      flexWrap: 'wrap',
    },
    title: {
      fontSize: 22,
      fontWeight: 850,
      color: '#f8fafc',
      margin: 0,
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
      boxShadow: '0 16px 40px rgba(0,0,0,.24)',
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
      minHeight: 86,
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
      fontWeight: 800,
      background: 'linear-gradient(135deg,#2563eb,#0f766e)',
      cursor: loading ? 'not-allowed' : 'pointer',
      whiteSpace: 'nowrap',
    },
    grid3: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
      gap: 14,
    },
    sectionTitle: {
      fontSize: 13,
      color: '#cbd5e1',
      fontWeight: 850,
      marginBottom: 10,
    },
  };

  const MemoryList = ({ items, empty }) => (
    <div style={{ display: 'grid', gap: 8 }}>
      {items.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>{empty}</div>
      ) : items.map((memory) => (
        <div key={memory.id} style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ color: '#93c5fd', fontSize: 11, fontWeight: 850, textTransform: 'uppercase' }}>
              {memory.memory_type || 'memory'} / importance {memory.importance || 1}
            </div>
            {String(memory.id).startsWith('chat-') ? null : (
              <button onClick={() => deleteMemory(memory.id)} disabled={loading} style={{ background: 'transparent', border: 'none', color: '#fca5a5', cursor: 'pointer', fontSize: 12 }}>
                Delete
              </button>
            )}
          </div>
          <div style={{ color: '#e5e7eb', fontSize: 13, lineHeight: 1.45, marginTop: 5, whiteSpace: 'pre-wrap' }}>
            {memory.content}
          </div>
          <div style={{ color: '#64748b', fontSize: 11, marginTop: 6 }}>{memory.created_at}</div>
        </div>
      ))}
    </div>
  );

  return (
    <div style={styles.page}>
      <style>{`
        @media (max-width: 980px) {
          .memory-grid { grid-template-columns: 1fr !important; }
          .memory-controls { grid-template-columns: 1fr !important; }
        }
      `}</style>

      <div style={styles.shell}>
        <div style={styles.header}>
          <div>
            <h1 style={styles.title}>Memory Center</h1>
            <div style={styles.sub}>Long-term memories, project context, preferences, recent chat recall, and export.</div>
          </div>
          <button type="button" onClick={exportMemory} disabled={loading} style={styles.button}>Export Memory</button>
        </div>

        {error && (
          <div style={{ color: '#fecaca', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(248,113,113,.25)', borderRadius: 8, padding: 10, fontSize: 13 }}>
            {error}
          </div>
        )}

        <div className="memory-controls" style={{ display: 'grid', gridTemplateColumns: '1.3fr .7fr', gap: 14 }}>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Search Memory</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') loadMemories(query); }} placeholder="Search previous fixes, deployments, projects, preferences..." style={styles.input} />
              <button type="button" onClick={() => loadMemories(query)} disabled={loading} style={styles.button}>{loading ? 'Loading' : 'Search'}</button>
            </div>
          </div>

          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Memory Stats</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
              <Stat label="Memories" value={memories.length} />
              <Stat label="Important" value={important.length} />
              <Stat label="Chats" value={(data.recent_chats || []).length} />
            </div>
          </div>
        </div>

        <div style={styles.panel}>
          <div style={styles.sectionTitle}>Add Memory</div>
          <div style={{ display: 'grid', gap: 10 }}>
            <textarea value={memoryText} onChange={(e) => setMemoryText(e.target.value)} placeholder="Example: User project is EVA AI. Prefers FastAPI, React, RAG, GitHub PR workflows, Render deploy support." style={styles.textarea} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px 120px', gap: 8 }}>
              <select value={memoryType} onChange={(e) => setMemoryType(e.target.value)} style={styles.input}>
                <option value="project">Project</option>
                <option value="preference">Preference</option>
                <option value="goal">Goal</option>
                <option value="skill">Skill</option>
                <option value="long_term">Long-Term</option>
              </select>
              <input type="number" min="1" max="5" value={importance} onChange={(e) => setImportance(e.target.value)} style={styles.input} />
              <button type="button" onClick={addMemory} disabled={loading || !memoryText.trim()} style={styles.button}>Save</button>
            </div>
          </div>
        </div>

        {query.trim() && (
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Search Results</div>
            <MemoryList items={searchResults} empty="No matching memories yet." />
          </div>
        )}

        <div className="memory-grid" style={styles.grid3}>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Recent Memories</div>
            <MemoryList items={recent} empty="No recent memories yet." />
          </div>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Important Memories</div>
            <MemoryList items={important} empty="No important memories yet." />
          </div>
          <div style={styles.panel}>
            <div style={styles.sectionTitle}>Project Memories</div>
            <MemoryList items={projects} empty="No project memories yet." />
          </div>
        </div>

        <div style={styles.panel}>
          <div style={styles.sectionTitle}>Recent Chat Memory</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {(data.recent_chats || []).length === 0 ? (
              <div style={{ color: '#64748b', fontSize: 13 }}>No chat rows saved in Memory V2 yet.</div>
            ) : (data.recent_chats || []).map((chat) => (
              <div key={chat.id} style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
                <div style={{ color: '#93c5fd', fontSize: 11, fontWeight: 850 }}>{chat.title || 'Chat'} / {chat.created_at}</div>
                <div style={{ color: '#e5e7eb', fontSize: 13, marginTop: 6 }}><strong>User:</strong> {chat.message}</div>
                <div style={{ color: '#cbd5e1', fontSize: 13, marginTop: 4 }}><strong>EVA:</strong> {(chat.response || '').slice(0, 360)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{ color: '#f8fafc', fontWeight: 850, fontSize: 22 }}>{value}</div>
    </div>
  );
}

