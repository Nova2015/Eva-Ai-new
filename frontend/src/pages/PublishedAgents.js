import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const emptyPublish = {
  agent_id: '',
  visibility: 'private',
  title: '',
  description: '',
  category: 'Productivity',
  tags: '',
  allow_cloning: true,
};

export default function PublishedAgents({ API = defaultApi }) {
  const storedUser = safeUser();
  const userId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const organizationId = storedUser.organization_id || 'default-org';
  const role = (storedUser.role || 'user').toLowerCase();
  const isAdmin = ['admin', 'administrator', 'superadmin', 'owner'].includes(role);
  const token = localStorage.getItem('aria_token');
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }), [token]);

  const [activeTab, setActiveTab] = useState('Published');
  const [agents, setAgents] = useState([]);
  const [published, setPublished] = useState([]);
  const [moderation, setModeration] = useState([]);
  const [summary, setSummary] = useState({});
  const [form, setForm] = useState(emptyPublish);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState('');

  const loadData = async () => {
    setLoading(true);
    setNotice('');
    try {
      const params = new URLSearchParams({ user_id: userId, organization_id: organizationId });
      const [agentsRes, publishedRes, summaryRes, moderationRes] = await Promise.all([
        fetch(`${API}/ai-studio/agents?${new URLSearchParams({ user_id: userId })}`, { headers }),
        fetch(`${API}/marketplace/published?${params.toString()}`, { headers }),
        fetch(`${API}/marketplace/summary?${params.toString()}`, { headers }),
        fetch(`${API}/marketplace/admin/moderation?status=all`, { headers }),
      ]);
      const agentsJson = await agentsRes.json().catch(() => ({}));
      const publishedJson = await publishedRes.json().catch(() => ({}));
      const summaryJson = await summaryRes.json().catch(() => ({}));
      const moderationJson = await moderationRes.json().catch(() => ({}));
      if (!agentsRes.ok) throw new Error(agentsJson.detail || 'AI Studio agents failed');
      if (!publishedRes.ok) throw new Error(publishedJson.detail || 'Published agents failed');
      if (!summaryRes.ok) throw new Error(summaryJson.detail || 'Summary failed');
      setAgents(agentsJson.agents || []);
      setPublished(publishedJson.agents || []);
      setSummary(summaryJson.summary || {});
      setModeration(moderationJson.items || []);
      if (!form.agent_id && (agentsJson.agents || []).length) {
        const first = agentsJson.agents[0];
        setForm((current) => ({
          ...current,
          agent_id: first.id,
          title: current.title || first.name,
          description: current.description || first.description || '',
        }));
      }
    } catch (err) {
      setNotice(err.message || 'Published Agents unavailable');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId, organizationId]);

  const selectAgent = (agentId) => {
    const agent = agents.find((item) => item.id === agentId);
    setForm({
      ...form,
      agent_id: agentId,
      title: agent?.name || form.title,
      description: agent?.description || form.description,
    });
  };

  const publishAgent = async () => {
    if (!form.agent_id) {
      setNotice('Create an AI Studio agent first, then publish it here.');
      return;
    }
    setLoading(true);
    setNotice('');
    try {
      const res = await fetch(`${API}/marketplace/agents/${form.agent_id}/publish`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          organization_id: organizationId,
          visibility: form.visibility,
          title: form.title,
          description: form.description,
          category: form.category,
          tags: tagList(form.tags),
          allow_cloning: form.allow_cloning,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Publish failed');
      await loadData();
      setActiveTab('Published');
      setNotice(json.publication?.visibility === 'public' && json.publication?.status === 'pending'
        ? 'Published for public review. Approve it in moderation before it appears publicly.'
        : 'Agent published.');
    } catch (err) {
      setNotice(err.message || 'Publish failed');
    } finally {
      setLoading(false);
    }
  };

  const moderate = async (publicationId, action, isFeatured = null) => {
    setLoading(true);
    setNotice('');
    try {
      const res = await fetch(`${API}/marketplace/admin/moderation/${publicationId}`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          moderator_id: userId,
          action,
          reason: `Moderated from Published Agents: ${action}`,
          is_featured: isFeatured,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Moderation failed');
      await loadData();
      setNotice(`Moderation updated: ${json.publication?.status || action}`);
    } catch (err) {
      setNotice(err.message || 'Moderation failed');
    } finally {
      setLoading(false);
    }
  };

  const copyShare = async (slug) => {
    const url = `${window.location.origin}/agent/${slug}`;
    try {
      await navigator.clipboard.writeText(url);
      setNotice(`Share URL copied: ${url}`);
    } catch {
      setNotice(url);
    }
  };

  const S = styles(loading);
  const pendingCount = moderation.filter((item) => item.status === 'pending').length;

  return (
    <div style={S.page}>
      <style>{`
        @media (max-width: 1120px) {
          .published-grid-2,
          .published-grid-3,
          .published-grid-4 { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 680px) {
          .published-tabs { grid-template-columns: 1fr !important; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>Published Agents</h1>
            <div style={S.sub}>Publish private workspace agents, create public listings, cloneable URLs, and admin moderation.</div>
          </div>
          <button type="button" onClick={loadData} disabled={loading} style={S.primaryButton}>
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>

        {notice && <div style={S.notice}>{notice}</div>}

        <div className="published-grid-4" style={S.grid4}>
          <Metric label="Published" value={summary.total_published || 0} color="#38bdf8" />
          <Metric label="Public" value={summary.public_agents || 0} color="#34d399" />
          <Metric label="Pending" value={summary.pending_review || pendingCount || 0} color="#fbbf24" />
          <Metric label="Clones" value={summary.total_clones || 0} color="#f472b6" />
        </div>

        <div className="published-tabs" style={S.tabs}>
          {['Published', 'Publish Agent', 'Moderation'].map((tab) => (
            <button key={tab} type="button" onClick={() => setActiveTab(tab)} style={{ ...S.tab, ...(activeTab === tab ? S.activeTab : {}) }}>
              {tab}{tab === 'Moderation' && pendingCount ? ` (${pendingCount})` : ''}
            </button>
          ))}
        </div>

        {activeTab === 'Published' && (
          <div className="published-grid-3" style={S.grid3}>
            {published.length === 0 ? (
              <section style={S.panel}>
                <div style={S.sectionTitle}>No Published Agents</div>
                <p style={S.muted}>Choose an AI Studio agent and publish it privately for your organization or publicly for marketplace review.</p>
                <button type="button" onClick={() => setActiveTab('Publish Agent')} style={S.primaryButton}>Publish Agent</button>
              </section>
            ) : published.map((item) => (
              <PublicationCard key={item.id} item={item} S={S} onCopy={() => copyShare(item.slug)} />
            ))}
          </div>
        )}

        {activeTab === 'Publish Agent' && (
          <div className="published-grid-2" style={S.grid2}>
            <section style={S.panel}>
              <div style={S.sectionTitle}>Publish Existing Agent</div>
              <div style={S.formGrid}>
                <Field label="AI Studio Agent">
                  <select value={form.agent_id} onChange={(e) => selectAgent(e.target.value)} style={S.input}>
                    <option value="">Select agent</option>
                    {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                  </select>
                </Field>
                <Field label="Visibility">
                  <select value={form.visibility} onChange={(e) => setForm({ ...form, visibility: e.target.value })} style={S.input}>
                    <option value="private">Private Workspace</option>
                    <option value="public">Public Marketplace</option>
                  </select>
                </Field>
                <Field label="Title">
                  <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={S.input} />
                </Field>
                <Field label="Category">
                  <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} style={S.input} />
                </Field>
                <Field label="Description" wide>
                  <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={S.textarea} />
                </Field>
                <Field label="Tags" wide>
                  <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="code, support, research" style={S.input} />
                </Field>
                <label style={S.checkbox}>
                  <input type="checkbox" checked={form.allow_cloning} onChange={(e) => setForm({ ...form, allow_cloning: e.target.checked })} />
                  <span>Allow users to clone this agent into AI Studio</span>
                </label>
              </div>
              <button type="button" onClick={publishAgent} disabled={loading} style={{ ...S.primaryButton, marginTop: 14 }}>
                {loading ? 'Publishing' : 'Publish Agent'}
              </button>
            </section>

            <section style={S.panel}>
              <div style={S.sectionTitle}>Publishing Rules</div>
              <InfoRow label="Private Workspace" value="Visible inside the organization workspace." />
              <InfoRow label="Public Marketplace" value="Submitted to moderation before public discovery." />
              <InfoRow label="Share URL" value="/agent/{published-slug}" />
              <InfoRow label="Clone" value="Creates a private AI Studio copy for the user." />
              <p style={S.muted}>
                Existing AI Studio agents keep working exactly as before. Publishing creates a separate marketplace record with usage,
                reviews, moderation status, and share metadata.
              </p>
            </section>
          </div>
        )}

        {activeTab === 'Moderation' && (
          <section style={S.panel}>
            <div style={S.sectionTitle}>Admin Moderation Controls</div>
            {!isAdmin && <div style={S.notice}>Your current local role is not admin. Controls are visible for development, but production should enforce role checks server-side.</div>}
            <div className="published-grid-3" style={S.grid3}>
              {moderation.length === 0 ? (
                <div style={S.muted}>No marketplace submissions yet.</div>
              ) : moderation.map((item) => (
                <ModerationCard key={item.id} item={item} S={S} onModerate={moderate} />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function PublicationCard({ item, S, onCopy }) {
  const shareUrl = `${window.location.origin}/agent/${item.slug}`;
  return (
    <section style={S.panel}>
      <div style={S.identity}>
        <div style={S.avatar}>{item.agent?.avatar || initials(item.title)}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#f8fafc', fontWeight: 900, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</div>
          <div style={S.muted}>{item.description || 'Published EVA agent'}</div>
        </div>
      </div>
      <InfoRow label="Visibility" value={item.visibility} />
      <InfoRow label="Status" value={item.status} />
      <InfoRow label="Rating" value={`${item.average_rating || 0}/5`} />
      <InfoRow label="Uses" value={item.total_uses || 0} />
      <InfoRow label="Share" value={shareUrl} />
      <button type="button" onClick={onCopy} style={{ ...S.secondaryButton, marginTop: 10 }}>Copy Share URL</button>
    </section>
  );
}

function ModerationCard({ item, S, onModerate }) {
  return (
    <section style={S.subPanel}>
      <div style={S.identity}>
        <div style={S.avatar}>{item.agent?.avatar || initials(item.title)}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#f8fafc', fontWeight: 900 }}>{item.title}</div>
          <div style={S.muted}>{item.owner_id} / {item.visibility}</div>
        </div>
      </div>
      <InfoRow label="Status" value={item.status} />
      <InfoRow label="Category" value={item.category} />
      <InfoRow label="Published" value={formatDate(item.published_at)} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
        <button type="button" onClick={() => onModerate(item.id, 'approve')} style={S.primaryButton}>Approve</button>
        <button type="button" onClick={() => onModerate(item.id, 'reject')} style={S.warningButton}>Reject</button>
        <button type="button" onClick={() => onModerate(item.id, 'hide')} style={S.secondaryButton}>Hide</button>
        <button type="button" onClick={() => onModerate(item.id, 'approve', !item.is_featured)} style={S.secondaryButton}>
          {item.is_featured ? 'Unfeature' : 'Feature'}
        </button>
      </div>
    </section>
  );
}

function Field({ label, children, wide = false }) {
  return (
    <label style={{ display: 'grid', gap: 6, gridColumn: wide ? '1 / -1' : 'auto' }}>
      <span style={{ color: '#94a3b8', fontSize: 12, fontWeight: 850 }}>{label}</span>
      {children}
    </label>
  );
}

function Metric({ label, value, color }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 14, minHeight: 82 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{ color, fontSize: 23, fontWeight: 900, marginTop: 6 }}>{value}</div>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, background: '#111827', border: '1px solid rgba(148,163,184,.14)', borderRadius: 8, padding: '9px 10px', marginTop: 8 }}>
      <span style={{ color: '#94a3b8', fontSize: 12 }}>{label}</span>
      <span style={{ color: '#e5e7eb', fontSize: 12, fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value || '-'}</span>
    </div>
  );
}

function safeUser() {
  try {
    return JSON.parse(localStorage.getItem('aria_user') || '{}');
  } catch {
    return {};
  }
}

function tagList(value) {
  return String(value || '').split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function initials(name = 'AI') {
  return String(name || 'AI').split(/\s+/).map((part) => part[0]).join('').slice(0, 3).toUpperCase() || 'AI';
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function styles(loading) {
  return {
    page: { minHeight: 'calc(100vh - 52px)', background: '#07111a', color: '#e5e7eb', padding: 22, fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif' },
    shell: { maxWidth: 1380, margin: '0 auto', display: 'grid', gap: 16 },
    header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap' },
    title: { margin: 0, color: '#f8fafc', fontSize: 24, fontWeight: 900 },
    sub: { color: '#94a3b8', fontSize: 13, marginTop: 4 },
    grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, alignItems: 'start' },
    grid3: { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 },
    grid4: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10 },
    panel: { background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 16, boxShadow: '0 16px 36px rgba(0,0,0,.24)', minWidth: 0 },
    subPanel: { background: '#111827', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 12, minWidth: 0 },
    sectionTitle: { color: '#cbd5e1', fontSize: 13, fontWeight: 900, marginBottom: 10 },
    muted: { color: '#94a3b8', fontSize: 12, lineHeight: 1.5 },
    notice: { color: '#bae6fd', background: 'rgba(14,165,233,.12)', border: '1px solid rgba(56,189,248,.22)', borderRadius: 8, padding: 10, fontSize: 13 },
    tabs: { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 8 },
    tab: { border: '1px solid transparent', borderRadius: 8, background: 'transparent', color: '#94a3b8', fontSize: 12, fontWeight: 850, padding: '9px 8px', cursor: 'pointer' },
    activeTab: { background: 'linear-gradient(135deg, rgba(37,99,235,.28), rgba(20,184,166,.22))', color: '#f8fafc', border: '1px solid rgba(96,165,250,.28)' },
    formGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 },
    input: { width: '100%', boxSizing: 'border-box', border: '1px solid rgba(148,163,184,.22)', borderRadius: 8, background: '#111827', color: '#e5e7eb', padding: '10px 11px', outline: 'none' },
    textarea: { width: '100%', minHeight: 98, boxSizing: 'border-box', resize: 'vertical', border: '1px solid rgba(148,163,184,.22)', borderRadius: 8, background: '#111827', color: '#e5e7eb', padding: '10px 11px', outline: 'none' },
    checkbox: { display: 'flex', alignItems: 'center', gap: 9, gridColumn: '1 / -1', color: '#cbd5e1', fontSize: 12 },
    primaryButton: { border: 'none', borderRadius: 8, padding: '10px 13px', color: '#fff', fontWeight: 850, background: 'linear-gradient(135deg,#2563eb,#0f766e)', cursor: loading ? 'not-allowed' : 'pointer' },
    secondaryButton: { border: '1px solid rgba(96,165,250,.25)', borderRadius: 8, padding: '10px 13px', color: '#bfdbfe', fontWeight: 850, background: 'rgba(37,99,235,.14)', cursor: loading ? 'not-allowed' : 'pointer' },
    warningButton: { border: '1px solid rgba(251,191,36,.25)', borderRadius: 8, padding: '10px 13px', color: '#fde68a', fontWeight: 850, background: 'rgba(217,119,6,.14)', cursor: loading ? 'not-allowed' : 'pointer' },
    identity: { display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 },
    avatar: { width: 42, height: 42, borderRadius: 8, background: 'linear-gradient(135deg,#2563eb,#14b8a6)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 900, flexShrink: 0 },
  };
}

