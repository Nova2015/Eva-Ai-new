import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const tabs = ['Organization', 'Members', 'Roles', 'Shared Chats', 'Shared Documents', 'Shared Memory', 'Usage Analytics'];

const roleCopy = {
  Owner: ['Full organization control', 'Billing and workspace ownership', 'Member and role management'],
  Admin: ['Invite and remove members', 'Manage shared knowledge', 'View usage analytics'],
  Developer: ['Use Code Assistant and Agent OS', 'Upload project files', 'Access shared memory'],
  User: ['Chat with EVA', 'Use shared documents', 'Create personal memories'],
  Viewer: ['Read shared chats', 'View documents', 'Limited workspace access'],
};

export default function TeamWorkspace({ API = defaultApi }) {
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

  const [activeTab, setActiveTab] = useState('Members');
  const [workspace, setWorkspace] = useState({
    organization: {},
    members: [],
    roles: ['Owner', 'Admin', 'Developer', 'User', 'Viewer'],
    counts: {},
    role_counts: [],
    recent_usage: [],
  });
  const [invite, setInvite] = useState({ name: '', email: '', role: 'User' });
  const [selectedUsage, setSelectedUsage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const organizationId = workspace.organization?.id || 'default-org';

  const loadWorkspace = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId, organization_id: organizationId });
      const res = await fetch(`${API}/team/workspace?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Team workspace failed');
      setWorkspace(json);
    } catch (err) {
      setError(err.message || 'Team workspace failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadWorkspace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId]);

  const inviteMember = async () => {
    if (!invite.email.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/team/members`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          organization_id: organizationId,
          user_id: userId,
          name: invite.name,
          email: invite.email,
          role: invite.role,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Invite failed');
      setInvite({ name: '', email: '', role: 'User' });
      await loadWorkspace();
    } catch (err) {
      setError(err.message || 'Invite failed');
    } finally {
      setLoading(false);
    }
  };

  const changeRole = async (memberId, role) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/team/members/${memberId}/role`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ organization_id: organizationId, user_id: userId, role }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Role update failed');
      await loadWorkspace();
    } catch (err) {
      setError(err.message || 'Role update failed');
    } finally {
      setLoading(false);
    }
  };

  const removeMember = async (memberId) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ organization_id: organizationId, user_id: userId });
      const res = await fetch(`${API}/team/members/${memberId}?${params.toString()}`, {
        method: 'DELETE',
        headers,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Remove failed');
      if (selectedUsage?.member?.id === memberId) setSelectedUsage(null);
      await loadWorkspace();
    } catch (err) {
      setError(err.message || 'Remove failed');
    } finally {
      setLoading(false);
    }
  };

  const viewUsage = async (memberId) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ organization_id: organizationId });
      const res = await fetch(`${API}/team/members/${memberId}/usage?${params.toString()}`, { headers });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Usage failed');
      setSelectedUsage(json);
      setActiveTab('Usage Analytics');
    } catch (err) {
      setError(err.message || 'Usage failed');
    } finally {
      setLoading(false);
    }
  };

  const S = {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: '#09131c',
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
      color: '#94a3b8',
      fontSize: 13,
      marginTop: 4,
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
    ghostButton: {
      border: '1px solid rgba(148,163,184,.22)',
      borderRadius: 8,
      padding: '8px 10px',
      color: '#cbd5e1',
      fontWeight: 800,
      background: '#111827',
      cursor: loading ? 'not-allowed' : 'pointer',
      whiteSpace: 'nowrap',
    },
    dangerButton: {
      border: '1px solid rgba(248,113,113,.3)',
      borderRadius: 8,
      padding: '8px 10px',
      color: '#fecaca',
      fontWeight: 800,
      background: 'rgba(127,29,29,.28)',
      cursor: loading ? 'not-allowed' : 'pointer',
      whiteSpace: 'nowrap',
    },
    sectionTitle: {
      color: '#cbd5e1',
      fontSize: 13,
      fontWeight: 850,
      marginBottom: 10,
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
  };

  const renderTab = () => {
    if (activeTab === 'Organization') {
      return (
        <div style={{ display: 'grid', gap: 14 }}>
          <div className="team-grid" style={S.grid4}>
            <Stat label="Members" value={workspace.counts?.members || 0} />
            <Stat label="Invited" value={workspace.counts?.invited_members || 0} />
            <Stat label="Shared Docs" value={workspace.counts?.shared_documents || 0} />
            <Stat label="Usage Events" value={workspace.counts?.usage_events || 0} />
          </div>
          <div style={S.panel}>
            <div style={S.sectionTitle}>Organization</div>
            <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: 10, color: '#cbd5e1', fontSize: 13 }}>
              <div style={{ color: '#64748b' }}>Name</div>
              <div>{workspace.organization?.name || 'EVA Workspace'}</div>
              <div style={{ color: '#64748b' }}>Slug</div>
              <div>{workspace.organization?.slug || 'eva-workspace'}</div>
              <div style={{ color: '#64748b' }}>Created</div>
              <div>{workspace.organization?.created_at || '-'}</div>
            </div>
          </div>
        </div>
      );
    }

    if (activeTab === 'Members') {
      return (
        <div className="team-grid" style={S.grid2}>
          <div style={S.panel}>
            <div style={S.sectionTitle}>Invite Member</div>
            <div style={{ display: 'grid', gap: 10 }}>
              <input value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} placeholder="Name" style={S.input} />
              <input value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} placeholder="email@company.com" style={S.input} />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: 8 }}>
                <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })} style={S.input}>
                  {(workspace.roles || []).map((role) => <option key={role} value={role}>{role}</option>)}
                </select>
                <button type="button" onClick={inviteMember} disabled={loading || !invite.email.trim()} style={S.button}>Invite</button>
              </div>
            </div>
          </div>
          <MembersList
            members={workspace.members || []}
            roles={workspace.roles || []}
            loading={loading}
            styles={S}
            onRole={changeRole}
            onRemove={removeMember}
            onUsage={viewUsage}
          />
        </div>
      );
    }

    if (activeTab === 'Roles') {
      return (
        <div className="team-grid" style={S.grid4}>
          {(workspace.roles || []).map((role) => (
            <div key={role} style={S.panel}>
              <div style={{ color: '#f8fafc', fontWeight: 850, marginBottom: 9 }}>{role}</div>
              <div style={{ display: 'grid', gap: 7 }}>
                {(roleCopy[role] || []).map((item) => (
                  <div key={item} style={{ color: '#94a3b8', fontSize: 12, lineHeight: 1.35 }}>{item}</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      );
    }

    if (activeTab === 'Usage Analytics') {
      return (
        <div className="team-grid" style={S.grid2}>
          <div style={S.panel}>
            <div style={S.sectionTitle}>Member Usage</div>
            {selectedUsage?.member ? (
              <div style={{ display: 'grid', gap: 10 }}>
                <div>
                  <div style={{ color: '#f8fafc', fontWeight: 850 }}>{selectedUsage.member.name}</div>
                  <div style={{ color: '#64748b', fontSize: 12 }}>{selectedUsage.member.email}</div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                  <Stat label="Events" value={selectedUsage.summary?.events || 0} compact />
                  <Stat label="Tokens" value={selectedUsage.summary?.tokens || 0} compact />
                  <Stat label="Cost" value={`$${Number(selectedUsage.summary?.cost || 0).toFixed(3)}`} compact />
                </div>
              </div>
            ) : (
              <div style={{ color: '#64748b', fontSize: 13 }}>Select View Usage from a member row.</div>
            )}
          </div>
          <div style={S.panel}>
            <div style={S.sectionTitle}>Recent Usage</div>
            <UsageList rows={selectedUsage?.logs || workspace.recent_usage || []} />
          </div>
        </div>
      );
    }

    const countMap = {
      'Shared Chats': workspace.counts?.shared_chats || 0,
      'Shared Documents': workspace.counts?.shared_documents || 0,
      'Shared Memory': workspace.counts?.shared_memories || 0,
    };
    return (
      <div style={S.panel}>
        <div style={S.sectionTitle}>{activeTab}</div>
        <div style={{ color: '#f8fafc', fontSize: 28, fontWeight: 850 }}>{countMap[activeTab] || 0}</div>
        <div style={{ color: '#94a3b8', fontSize: 13, marginTop: 8 }}>
          {activeTab} will connect to team-scoped records in the next workspace update.
        </div>
      </div>
    );
  };

  return (
    <div style={S.page}>
      <style>{`
        @media (max-width: 1100px) {
          .team-grid { grid-template-columns: 1fr !important; }
          .member-row { grid-template-columns: 1fr !important; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>Team Workspace</h1>
            <div style={S.sub}>Organization, members, roles, shared resources, memory, and analytics.</div>
          </div>
          <button type="button" onClick={loadWorkspace} disabled={loading} style={S.button}>{loading ? 'Refreshing' : 'Refresh'}</button>
        </div>

        {error && (
          <div style={{ color: '#fecaca', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(248,113,113,.25)', borderRadius: 8, padding: 10, fontSize: 13 }}>
            {error}
          </div>
        )}

        <div style={S.tabs}>
          {tabs.map((tab) => (
            <button key={tab} type="button" onClick={() => setActiveTab(tab)} style={{ ...S.tab, ...(activeTab === tab ? S.activeTab : {}) }}>
              {tab}
            </button>
          ))}
        </div>

        {renderTab()}
      </div>
    </div>
  );
}

function Stat({ label, value, compact = false }) {
  return (
    <div style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: compact ? 10 : 14 }}>
      <div style={{ color: '#94a3b8', fontSize: 11 }}>{label}</div>
      <div style={{ color: '#f8fafc', fontSize: compact ? 18 : 24, fontWeight: 850, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function StatusPill({ status }) {
  const colors = {
    active: ['rgba(16,185,129,.14)', '#34d399'],
    invited: ['rgba(59,130,246,.15)', '#60a5fa'],
    removed: ['rgba(239,68,68,.15)', '#fca5a5'],
  };
  const c = colors[status] || colors.invited;
  return (
    <span style={{ display: 'inline-flex', borderRadius: 999, padding: '4px 9px', background: c[0], color: c[1], fontSize: 11, fontWeight: 850, textTransform: 'uppercase' }}>
      {status || 'invited'}
    </span>
  );
}

function MembersList({ members, roles, loading, styles, onRole, onRemove, onUsage }) {
  return (
    <div style={styles.panel}>
      <div style={styles.sectionTitle}>Members</div>
      <div style={{ display: 'grid', gap: 8 }}>
        {members.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>No members yet.</div>
        ) : members.map((member) => (
          <div
            key={member.id}
            className="member-row"
            style={{
              display: 'grid',
              gridTemplateColumns: '1.2fr 150px 125px 250px',
              gap: 10,
              alignItems: 'center',
              background: '#111827',
              border: '1px solid rgba(148,163,184,.15)',
              borderRadius: 8,
              padding: 10,
            }}
          >
            <div>
              <div style={{ color: '#f8fafc', fontWeight: 850, fontSize: 13 }}>{member.name}</div>
              <div style={{ color: '#64748b', fontSize: 11, marginTop: 3 }}>{member.email}</div>
            </div>
            <select
              value={member.role}
              disabled={loading || member.role === 'Owner'}
              onChange={(e) => onRole(member.id, e.target.value)}
              style={{
                ...styles.input,
                opacity: member.role === 'Owner' ? 0.7 : 1,
                cursor: member.role === 'Owner' ? 'not-allowed' : 'pointer',
              }}
            >
              {roles.map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
            <StatusPill status={member.status} />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button type="button" disabled={loading} onClick={() => onUsage(member.id)} style={styles.ghostButton}>Usage</button>
              {member.role === 'Owner' ? (
                <span style={{ ...styles.ghostButton, cursor: 'default', opacity: 0.72 }}>Locked</span>
              ) : (
                <button type="button" disabled={loading} onClick={() => onRemove(member.id)} style={styles.dangerButton}>Remove</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function UsageList({ rows }) {
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No usage events yet.</div>
      ) : rows.map((row) => (
        <div key={row.id} style={{ background: '#111827', border: '1px solid rgba(148,163,184,.15)', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ color: '#f8fafc', fontWeight: 850, fontSize: 13 }}>{row.action}</div>
            <div style={{ color: '#64748b', fontSize: 11 }}>{row.created_at}</div>
          </div>
          <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 5 }}>
            {row.member_name || row.member_email || row.user_id || 'Workspace'}
          </div>
        </div>
      ))}
    </div>
  );
}

