import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

export default function AgentMarketplace({ API = defaultApi, shareMode = false }) {
  const { slug } = useParams();
  const navigate = useNavigate();
  const storedUser = safeUser();
  const userId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const organizationId = storedUser.organization_id || 'default-org';
  const token = localStorage.getItem('aria_token');
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }), [token]);

  const [agents, setAgents] = useState([]);
  const [summary, setSummary] = useState({ summary: {}, categories: [], popular: [] });
  const [selected, setSelected] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [filters, setFilters] = useState({ query: '', category: '', visibility: '' });
  const [review, setReview] = useState({ rating: 5, review: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadMarketplace = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        user_id: userId,
        organization_id: organizationId,
        status: 'approved',
        limit: '100',
      });
      if (filters.query) params.set('query', filters.query);
      if (filters.category) params.set('category', filters.category);
      if (filters.visibility) params.set('visibility', filters.visibility);
      const [agentsRes, summaryRes] = await Promise.all([
        fetch(`${API}/marketplace/agents?${params.toString()}`, { headers }),
        fetch(`${API}/marketplace/summary?${new URLSearchParams({ user_id: userId, organization_id: organizationId })}`, { headers }),
      ]);
      const agentsJson = await agentsRes.json().catch(() => ({}));
      const summaryJson = await summaryRes.json().catch(() => ({}));
      if (!agentsRes.ok) throw new Error(agentsJson.detail || 'Marketplace failed');
      if (!summaryRes.ok) throw new Error(summaryJson.detail || 'Marketplace summary failed');
      setAgents(agentsJson.agents || []);
      setSummary({
        summary: summaryJson.summary || {},
        categories: summaryJson.categories || [],
        popular: summaryJson.popular || [],
      });
    } catch (err) {
      setError(err.message || 'Marketplace unavailable');
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (identifier) => {
    if (!identifier) return;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId, organization_id: organizationId });
      const res = await fetch(`${API}/marketplace/agents/${identifier}?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Agent detail failed');
      setSelected(json.publication || null);
      setReviews(json.reviews || []);
      if (!shareMode && json.publication?.slug) navigate(`/marketplace?agent=${json.publication.slug}`, { replace: true });
    } catch (err) {
      setError(err.message || 'Agent detail failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMarketplace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId, organizationId]);

  useEffect(() => {
    if (slug) loadDetail(slug);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, API, userId, organizationId]);

  const cloneAgent = async () => {
    if (!selected) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/marketplace/published/${selected.id}/clone`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          organization_id: organizationId,
          name: `${selected.title} Copy`,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Clone failed');
      await loadMarketplace();
      setError(`Cloned into AI Studio: ${json.agent?.name || 'Agent'}`);
    } catch (err) {
      setError(err.message || 'Clone failed');
    } finally {
      setLoading(false);
    }
  };

  const addReview = async () => {
    if (!selected) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/marketplace/published/${selected.id}/reviews`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          rating: review.rating,
          review: review.review,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Review failed');
      setReviews(json.reviews || []);
      setReview({ rating: 5, review: '' });
      await loadDetail(selected.slug || selected.id);
    } catch (err) {
      setError(err.message || 'Review failed');
    } finally {
      setLoading(false);
    }
  };

  const copyShare = async () => {
    if (!selected?.slug) return;
    const url = `${window.location.origin}/agent/${selected.slug}`;
    try {
      await navigator.clipboard.writeText(url);
      setError(`Share URL copied: ${url}`);
    } catch {
      setError(url);
    }
  };

  const S = styles(loading);
  const stats = summary.summary || {};

  return (
    <div style={S.page}>
      <style>{`
        @media (max-width: 1120px) {
          .market-grid-2,
          .market-grid-3,
          .market-grid-4 { grid-template-columns: 1fr !important; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>{shareMode ? 'Published Agent' : 'Agent Marketplace'}</h1>
            <div style={S.sub}>Discover, clone, rate, and share EVA agents across the cloud workspace.</div>
          </div>
          <button type="button" onClick={loadMarketplace} disabled={loading} style={S.primaryButton}>
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>

        {error && <div style={S.notice}>{error}</div>}

        {!shareMode && (
          <>
            <div className="market-grid-4" style={S.grid4}>
              <Metric label="Published" value={stats.total_published || 0} color="#38bdf8" />
              <Metric label="Public Agents" value={stats.public_agents || 0} color="#34d399" />
              <Metric label="Uses" value={stats.total_uses || 0} color="#fbbf24" />
              <Metric label="Clones" value={stats.total_clones || 0} color="#f472b6" />
            </div>

            <section style={S.panel}>
              <div className="market-grid-3" style={S.filterGrid}>
                <input
                  value={filters.query}
                  onChange={(e) => setFilters({ ...filters, query: e.target.value })}
                  placeholder="Search published agents"
                  style={S.input}
                />
                <input
                  value={filters.category}
                  onChange={(e) => setFilters({ ...filters, category: e.target.value })}
                  placeholder="Category"
                  style={S.input}
                />
                <button type="button" onClick={loadMarketplace} disabled={loading} style={S.primaryButton}>Search</button>
              </div>
            </section>
          </>
        )}

        <div className="market-grid-2" style={S.grid2}>
          {!shareMode && (
            <section style={S.panel}>
              <div style={S.sectionTitle}>Marketplace</div>
              <div className="market-grid-3" style={S.grid3}>
                {agents.length === 0 ? (
                  <div style={S.muted}>No approved public agents yet. Publish one from Published Agents, then approve it in moderation.</div>
                ) : agents.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} S={S} onOpen={() => loadDetail(agent.slug || agent.id)} />
                ))}
              </div>
            </section>
          )}

          <section style={S.panel}>
            <div style={S.sectionTitle}>Agent Details</div>
            {!selected ? (
              <div style={S.muted}>Select an agent to inspect tools, reviews, usage, clone options, and share URL.</div>
            ) : (
              <div style={S.stack}>
                <div style={S.identity}>
                  <div style={S.avatar}>{selected.agent?.avatar || initials(selected.title)}</div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: '#f8fafc', fontSize: 20, fontWeight: 900 }}>{selected.title}</div>
                    <div style={S.muted}>{selected.description || selected.agent?.description}</div>
                  </div>
                </div>
                <div className="market-grid-4" style={S.grid4}>
                  <Metric label="Rating" value={`${selected.average_rating || 0}/5`} color="#fbbf24" compact />
                  <Metric label="Reviews" value={selected.review_count || 0} color="#38bdf8" compact />
                  <Metric label="Uses" value={selected.total_uses || 0} color="#34d399" compact />
                  <Metric label="Clones" value={selected.total_clones || 0} color="#f472b6" compact />
                </div>
                <InfoRow label="Model" value={selected.agent?.model} />
                <InfoRow label="Category" value={selected.category} />
                <InfoRow label="Tools" value={(selected.agent?.tools || []).join(', ') || 'None'} />
                <InfoRow label="Knowledge" value={(selected.agent?.knowledge_base || []).join(', ') || 'None'} />
                <InfoRow label="Share URL" value={`${window.location.origin}/agent/${selected.slug}`} />
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button type="button" onClick={cloneAgent} disabled={loading || !selected.allow_cloning} style={S.primaryButton}>Clone Agent</button>
                  <button type="button" onClick={copyShare} style={S.secondaryButton}>Copy Share URL</button>
                </div>

                <div style={S.reviewBox}>
                  <div style={S.sectionTitle}>Rate This Agent</div>
                  <select value={review.rating} onChange={(e) => setReview({ ...review, rating: Number(e.target.value) })} style={S.input}>
                    {[5, 4, 3, 2, 1].map((item) => <option key={item} value={item}>{item} stars</option>)}
                  </select>
                  <textarea
                    value={review.review}
                    onChange={(e) => setReview({ ...review, review: e.target.value })}
                    placeholder="Share what worked well or what should improve."
                    style={S.textarea}
                  />
                  <button type="button" onClick={addReview} disabled={loading} style={S.secondaryButton}>Submit Review</button>
                </div>

                <div>
                  <div style={S.sectionTitle}>Reviews</div>
                  {reviews.length === 0 ? (
                    <div style={S.muted}>No reviews yet.</div>
                  ) : reviews.map((item) => (
                    <div key={item.id} style={S.review}>
                      <div style={{ color: '#fbbf24', fontWeight: 900 }}>{item.rating}/5</div>
                      <div>
                        <div style={{ color: '#f8fafc', fontWeight: 850 }}>{item.user_id}</div>
                        <div style={S.muted}>{item.review || 'No written review.'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function AgentCard({ agent, S, onOpen }) {
  return (
    <button type="button" onClick={onOpen} style={S.agentCard}>
      <div style={S.identity}>
        <div style={S.avatar}>{agent.agent?.avatar || initials(agent.title)}</div>
        <div style={{ minWidth: 0, textAlign: 'left' }}>
          <div style={{ color: '#f8fafc', fontWeight: 900, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{agent.title}</div>
          <div style={S.muted}>{agent.description || agent.agent?.description || 'Published EVA agent'}</div>
        </div>
      </div>
      <InfoRow label="Category" value={agent.category} />
      <InfoRow label="Rating" value={`${agent.average_rating || 0}/5`} />
      <InfoRow label="Uses" value={agent.total_uses || 0} />
    </button>
  );
}

function Metric({ label, value, color, compact = false }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: compact ? 10 : 14, minHeight: compact ? 64 : 82 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{ color, fontSize: compact ? 18 : 23, fontWeight: 900, marginTop: 6 }}>{value}</div>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, background: '#111827', border: '1px solid rgba(148,163,184,.14)', borderRadius: 8, padding: '9px 10px' }}>
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

function initials(name = 'AI') {
  return String(name || 'AI').split(/\s+/).map((part) => part[0]).join('').slice(0, 3).toUpperCase() || 'AI';
}

function styles(loading) {
  return {
    page: { minHeight: 'calc(100vh - 52px)', background: '#07111a', color: '#e5e7eb', padding: 22, fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif' },
    shell: { maxWidth: 1380, margin: '0 auto', display: 'grid', gap: 16 },
    stack: { display: 'grid', gap: 12 },
    header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap' },
    title: { margin: 0, color: '#f8fafc', fontSize: 24, fontWeight: 900 },
    sub: { color: '#94a3b8', fontSize: 13, marginTop: 4 },
    grid2: { display: 'grid', gridTemplateColumns: '1.08fr .92fr', gap: 14, alignItems: 'start' },
    grid3: { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 },
    grid4: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10 },
    filterGrid: { display: 'grid', gridTemplateColumns: '1.2fr .8fr auto', gap: 10 },
    panel: { background: '#0f172a', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, padding: 16, boxShadow: '0 16px 36px rgba(0,0,0,.24)', minWidth: 0 },
    sectionTitle: { color: '#cbd5e1', fontSize: 13, fontWeight: 900, marginBottom: 10 },
    muted: { color: '#94a3b8', fontSize: 12, lineHeight: 1.5 },
    notice: { color: '#bae6fd', background: 'rgba(14,165,233,.12)', border: '1px solid rgba(56,189,248,.22)', borderRadius: 8, padding: 10, fontSize: 13 },
    input: { width: '100%', boxSizing: 'border-box', border: '1px solid rgba(148,163,184,.22)', borderRadius: 8, background: '#111827', color: '#e5e7eb', padding: '10px 11px', outline: 'none' },
    textarea: { width: '100%', minHeight: 88, boxSizing: 'border-box', resize: 'vertical', border: '1px solid rgba(148,163,184,.22)', borderRadius: 8, background: '#111827', color: '#e5e7eb', padding: '10px 11px', outline: 'none' },
    primaryButton: { border: 'none', borderRadius: 8, padding: '10px 13px', color: '#fff', fontWeight: 850, background: 'linear-gradient(135deg,#2563eb,#0f766e)', cursor: loading ? 'not-allowed' : 'pointer' },
    secondaryButton: { border: '1px solid rgba(96,165,250,.25)', borderRadius: 8, padding: '10px 13px', color: '#bfdbfe', fontWeight: 850, background: 'rgba(37,99,235,.14)', cursor: loading ? 'not-allowed' : 'pointer' },
    agentCard: { display: 'grid', gap: 9, textAlign: 'left', border: '1px solid rgba(148,163,184,.18)', borderRadius: 8, background: '#111827', padding: 12, cursor: 'pointer' },
    identity: { display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 },
    avatar: { width: 42, height: 42, borderRadius: 8, background: 'linear-gradient(135deg,#2563eb,#14b8a6)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 900, flexShrink: 0 },
    reviewBox: { display: 'grid', gap: 8, background: '#111827', border: '1px solid rgba(148,163,184,.14)', borderRadius: 8, padding: 12 },
    review: { display: 'grid', gridTemplateColumns: '46px 1fr', gap: 10, background: '#111827', border: '1px solid rgba(148,163,184,.14)', borderRadius: 8, padding: 10, marginBottom: 8 },
  };
}

