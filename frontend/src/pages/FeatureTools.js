import { useState, useEffect, useCallback } from 'react';
import { X, Video, Globe, Play, Bell, Trash2, Loader, Plus } from 'lucide-react';

async function fetchWithTimeout(url, options = {}, ms = 12000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(tid);
    return res;
  } catch (err) {
    clearTimeout(tid);
    if (err.name === 'AbortError') throw new Error('Request timed out.');
    throw err;
  }
}

function getHeaders() {
  const token = localStorage.getItem('aria_token') || '';
  return {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

const LANGS = ['python']; // HF /code-run-test executes Python only

// Code execution runs on the HF service (Python sandbox), not Render.
const HF_CODE_API = process.env.REACT_APP_RAG_API_BASE || 'http://127.0.0.1:7860';

// â”€â”€ Code Sandbox Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function SandboxTab() {
  const [code, setCode] = useState('print("Hello from EVA Sandbox!")');
  const [language, setLanguage] = useState('python');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const run = async () => {
    setRunning(true);
    setError('');
    setResult(null);
    try {
      const res = await fetchWithTimeout(`${HF_CODE_API}/code-run-test`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ code, language }),
      }, 20000);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Execution failed');
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <select value={language} onChange={e => setLanguage(e.target.value)} style={S.select}>
          {LANGS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        <button onClick={run} disabled={running} style={S.runBtn}>
          {running ? <Loader size={13} className="eva-ft-spin" /> : <Play size={13} />}
          {running ? 'Running...' : 'Run'}
        </button>
      </div>
      <textarea
        value={code}
        onChange={e => setCode(e.target.value)}
        rows={8}
        style={S.codeArea}
        spellCheck={false}
        placeholder="Write code here..."
      />
      {error && <div style={S.errorBox}>{error}</div>}
      {result && (
        <div style={S.resultBox}>
          {result.stdout && <pre style={S.pre}>{result.stdout}</pre>}
          {result.stderr && <pre style={{ ...S.pre, color: '#f87171' }}>{result.stderr}</pre>}
          {!result.stdout && !result.stderr && (
            <span style={{ color: 'var(--text3)', fontSize: 12 }}>No output</span>
          )}
          <div style={{ color: 'var(--text3)', fontSize: 11, marginTop: 6 }}>Return code: {result.returncode}</div>
        </div>
      )}
    </div>
  );
}

// â”€â”€ YouTube Monitor Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function YouTubeTab({ API }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [monitors, setMonitors] = useState([]);
  const [error, setError] = useState('');

  const loadMonitors = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${API}/youtube/alerts`, { headers: getHeaders() }, 10000);
      const data = await res.json().catch(() => ({}));
      setMonitors(data.alerts || []);
    } catch { /* non-critical */ }
  }, [API]);

  useEffect(() => { loadMonitors(); }, [loadMonitors]);

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError('');
    try {
      const res = await fetchWithTimeout(`${API}/youtube/search`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ query, max_results: 6 }),
      }, 15000);
      const data = await res.json().catch(() => ({}));
      if (data.error) { setError(data.error); setResults([]); }
      else setResults(data.results || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setSearching(false);
    }
  };

  const addMonitor = async (item) => {
    try {
      await fetchWithTimeout(`${API}/youtube/monitor`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ channel_name: item.channel, label: item.channel }),
      }, 10000);
      alert(`Now monitoring: ${item.channel}`);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && search()}
          placeholder="Search YouTube..."
          style={S.input}
        />
        <button onClick={search} disabled={searching} style={S.runBtn}>
          {searching ? <Loader size={13} className="eva-ft-spin" /> : <Video size={13} />}
          Search
        </button>
      </div>
      {error && <div style={S.errorBox}>{error}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 260, overflowY: 'auto' }}>
        {results.map((r, i) => (
          <div key={i} style={S.ytCard}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: 'var(--text)', fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.title}</div>
              <div style={{ color: 'var(--text3)', fontSize: 10 }}>{r.channel}</div>
            </div>
            <button onClick={() => addMonitor(r)} style={S.iconBtn} title="Monitor this channel"><Bell size={12} /></button>
            <a href={r.url} target="_blank" rel="noreferrer" style={{ ...S.iconBtn, textDecoration: 'none', display: 'flex' }}><Play size={12} /></a>
          </div>
        ))}
      </div>
      {monitors.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,.06)', paddingTop: 8 }}>
          <div style={{ color: 'var(--text3)', fontSize: 10, marginBottom: 6 }}>NEW VIDEO ALERTS</div>
          {monitors.map((m, i) => (
            <div key={i} style={{ fontSize: 11, color: '#22c55e', padding: '3px 0' }}>ðŸ”” {m.title}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// â”€â”€ Website Monitor Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function WebsiteTab({ API }) {
  const [url, setUrl] = useState('');
  const [monitors, setMonitors] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [changes, setChanges] = useState([]);

  const loadMonitors = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${API}/monitor/list`, { headers: getHeaders() }, 10000);
      const data = await res.json().catch(() => ({}));
      setMonitors(data.monitors || []);
    } catch { /* non-critical */ }
  }, [API]);

  useEffect(() => { loadMonitors(); }, [loadMonitors]);

  const addSite = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetchWithTimeout(`${API}/monitor/add`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ url: url.trim() }),
      }, 15000);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Failed to add monitor');
      setUrl('');
      await loadMonitors();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const checkNow = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetchWithTimeout(`${API}/monitor/check`, { headers: getHeaders() }, 20000);
      const data = await res.json().catch(() => ({}));
      setChanges(data.changes || []);
      await loadMonitors();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const removeSite = async (id) => {
    try {
      await fetchWithTimeout(`${API}/monitor/${id}`, { method: 'DELETE', headers: getHeaders() }, 10000);
      setMonitors(prev => prev.filter(m => m.id !== id));
    } catch (e) { setError(e.message); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addSite()}
          placeholder="https://example.com"
          style={S.input}
        />
        <button onClick={addSite} disabled={loading} style={S.runBtn}>
          <Plus size={13} /> Add
        </button>
      </div>
      <button onClick={checkNow} disabled={loading || monitors.length === 0} style={{ ...S.runBtn, alignSelf: 'flex-start' }}>
        {loading ? <Loader size={13} className="eva-ft-spin" /> : <Globe size={13} />} Check now
      </button>
      {error && <div style={S.errorBox}>{error}</div>}
      {changes.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,.06)', paddingTop: 8 }}>
          <div style={{ color: '#22c55e', fontSize: 11, marginBottom: 4 }}>ðŸ”” {changes.length} change(s) detected</div>
          {changes.map((c, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text)', padding: '3px 0' }}>{c.label}: {c.word_diff > 0 ? '+' : ''}{c.word_diff} words</div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflowY: 'auto' }}>
        {monitors.map(m => (
          <div key={m.id} style={S.ytCard}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: 'var(--text)', fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.label}</div>
              <div style={{ color: 'var(--text3)', fontSize: 10 }}>{m.changes?.length || 0} changes recorded</div>
            </div>
            <button onClick={() => removeSite(m.id)} style={S.iconBtn} title="Remove"><Trash2 size={12} /></button>
          </div>
        ))}
        {monitors.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 12, textAlign: 'center', padding: 16 }}>No websites monitored yet.</div>}
      </div>
    </div>
  );
}

// â”€â”€ Main Component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// The Tools Center. Its own three tools plus any `extraTabs` the caller passes
// â€” each { id, label, icon, render } â€” so surfaces that already exist elsewhere
// (the Directory, the Skill Library) appear here as tabs rendered INSIDE this
// modal rather than as competing modal layers. The caller owns those
// components; this file neither imports nor re-implements them.
export default function FeatureTools({ open, onClose, initialTab = 'sandbox', API, extraTabs = [] }) {
  const [tab, setTab] = useState(initialTab);

  if (!open) return null;

  const tabs = [
    { id: 'sandbox', label: 'Code Sandbox', icon: <Play size={13} /> },
    { id: 'youtube',  label: 'YouTube Monitor', icon: <Video size={13} /> },
    { id: 'website',  label: 'Website Detector', icon: <Globe size={13} /> },
    ...extraTabs.map(({ id, label, icon }) => ({ id, label, icon })),
  ];
  const extraById = Object.fromEntries(extraTabs.map((t) => [t.id, t]));
  // A tab may ask for more room. The Directory is a sidebar + search + detail
  // layout built for ~880px; at the compact width its three columns are cramped.
  // The container adapts instead of each panel re-implementing its own sizing.
  const wide = Boolean(extraById[tab]?.wide);

  return (
    <>
      <button type="button" onClick={onClose} style={S.backdrop} aria-label="Close" />
      <div style={wide ? { ...S.modal, ...S.modalWide } : S.modal}>
        <div style={S.header}>
          <span style={{ color: 'var(--text)', fontSize: 14, fontWeight: 800 }}>EVA Tools</span>
          <button type="button" onClick={onClose} style={S.closeBtn}><X size={16} /></button>
        </div>
        <div style={S.tabRow}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{ ...S.tabBtn, ...(tab === t.id ? S.tabBtnActive : {}) }}>
              {t.icon} {t.label}
            </button>
          ))}
        </div>
        <div style={S.body}>
          {tab === 'sandbox' && <SandboxTab />}
          {tab === 'youtube' && <YouTubeTab API={API} />}
          {tab === 'website' && <WebsiteTab API={API} />}
          {extraById[tab] ? extraById[tab].render() : null}
        </div>
      </div>
      <style>{`
        @keyframes eva-ft-spin { to { transform: rotate(360deg); } }
        .eva-ft-spin { animation: eva-ft-spin .8s linear infinite; }
      `}</style>
    </>
  );
}

// â”€â”€ Styles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const S = {
  backdrop: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 1100, border: 'none', cursor: 'default' },
  // Both widths are viewport-capped first (96vw), so the modal can never exceed
  // the screen and no horizontal overflow is introduced on small screens; the
  // pixel cap only applies once there is room for it.
  modalWide: { width: 'min(96vw, 880px)' },
  modal: { position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', width: 'min(96vw, 600px)', maxHeight: '85vh', background: 'var(--surface)', backdropFilter: 'blur(24px)', border: '1px solid rgba(124,58,237,.2)', borderRadius: 16, zIndex: 1101, display: 'flex', flexDirection: 'column', boxShadow: '0 32px 80px rgba(0,0,0,.8)', overflow: 'hidden' },
  header: { display: 'flex', alignItems: 'center', padding: '14px 18px', borderBottom: '1px solid rgba(255,255,255,.06)', flexShrink: 0 },
  closeBtn: { marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', display: 'flex' },
  tabRow: { display: 'flex', gap: 4, padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,.05)', flexShrink: 0, flexWrap: 'wrap' },
  tabBtn: { display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,.08)', background: 'transparent', color: 'var(--text2)', fontSize: 11, fontWeight: 600, cursor: 'pointer' },
  tabBtnActive: { background: 'color-mix(in srgb, var(--accent) 20%, transparent)', border: '1px solid rgba(124,58,237,.4)', color: 'var(--accent)' },
  body: { flex: 1, minHeight: 0, overflowY: 'auto', padding: 16 },
  select: { background: 'var(--surface2)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 8, padding: '7px 10px', color: 'var(--text)', fontSize: 12 },
  input: { flex: 1, background: 'var(--surface2)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 8, padding: '7px 10px', color: 'var(--text)', fontSize: 12, outline: 'none' },
  runBtn: { display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: 'none', background: 'linear-gradient(135deg,#7c3aed,#a855f7)', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' },
  codeArea: { background: 'var(--bg)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 8, padding: 12, color: 'var(--text2)', fontSize: 12, fontFamily: 'monospace', resize: 'vertical', outline: 'none' },
  resultBox: { background: 'var(--bg)', border: '1px solid rgba(255,255,255,.06)', borderRadius: 8, padding: 10, maxHeight: 160, overflowY: 'auto' },
  pre: { margin: 0, fontSize: 12, color: 'var(--text2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' },
  errorBox: { background: 'rgba(248,113,113,.1)', border: '1px solid rgba(248,113,113,.2)', borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#f87171' },
  ytCard: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', background: 'var(--surface2)', border: '1px solid rgba(255,255,255,.05)', borderRadius: 8 },
  iconBtn: { background: 'none', border: '1px solid rgba(255,255,255,.08)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer', padding: 5, alignItems: 'center', justifyContent: 'center' },
};

