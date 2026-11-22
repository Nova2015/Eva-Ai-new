import { useCallback, useEffect, useMemo, useState } from 'react';
import AnalyticsSettingsPanel from './AnalyticsSettingsPanel';
import AppearanceSettingsPanel from './AppearanceSettingsPanel';
import BillingSettingsPanel from './BillingSettingsPanel';
import ChatSettingsPanel from './ChatSettingsPanel';
import DeveloperSettingsPanel from './DeveloperSettingsPanel';
import IntegrationsSettingsPanel from './IntegrationsSettingsPanel';
import KnowledgeBaseSettingsPanel from './KnowledgeBaseSettingsPanel';
import ModelSettingsPanel from './ModelSettingsPanel';
import SecuritySettingsPanel from './SecuritySettingsPanel';
import TeamSettingsPanel from './TeamSettingsPanel';
import VoiceSettingsPanel from './VoiceSettingsPanel';
import { LANGUAGE_OPTIONS, languageCodeFromLabel } from '../lib/languages';
import { notifyLanguageChanged } from '../lib/i18n';
import { ButtonRow, Panel, Select, SettingRow, StatusBadge, TextInput, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import { useTheme } from '../context/ThemeContext';
import './SettingsModal.css';

// Update 58 — `adminOnly` sections are AI-engineering surfaces (model
// selection, retrieval tuning, evaluation, admin reporting). They stay in the
// code and remain fully functional in the admin workspace; end users see only
// the conversation-product settings.
const sections = [
  { id: 'profile', label: 'Profile', description: 'Your account identity, plan, and session.' },
  { id: 'general', label: 'General', description: 'Workspace identity, language, startup behavior, and default experience controls.' },
  { id: 'appearance', label: 'Appearance', description: 'Theme, accent, density, typography, and layout preferences.' },
  { id: 'voice', label: 'Voice', description: 'Voice profile, speaking style, speed, pitch, and preview for Jarvis Mode and Read aloud.' },
  { id: 'models', label: 'AI Models', description: 'Provider credentials, defaults, model selection, temperature, and token limits.', adminOnly: true },
  { id: 'chats', label: 'Chats', description: 'Conversation behavior, memory, exports, streaming, markdown, and file controls.' },
  { id: 'memory', label: 'Memory', description: 'Personalization, project context, preferences, search, edit, delete, and forget controls.' },
  { id: 'knowledge', label: 'Knowledge Base', description: 'Embedding, vector storage, chunking, retrieval, reranking, and indexing controls.', adminOnly: true },
  { id: 'integrations', label: 'Integrations', description: 'External services, webhooks, OAuth placeholders, and masked credentials.' },
  { id: 'security', label: 'Security', description: '2FA, alerts, sessions, password, data export, account deletion, and activity.' },
  { id: 'team', label: 'Team', description: 'Workspace, invites, roles, limits, team billing placeholder, and audit readiness.' },
  { id: 'billing', label: 'Billing', description: 'Plans, subscription, usage limits, invoices, payment placeholder, and billing contact.' },
  { id: 'analytics', label: 'Analytics', description: 'Usage tracking, monitoring, error tracking, retention, and admin reporting.', adminOnly: true },
  { id: 'ai-safety', label: 'AI Safety & Automation', description: 'Update intelligence, admin notifications, safety monitoring, and approval controls.', adminOnly: true },
  { id: 'developer', label: 'Developer', description: 'Domain training, evaluation, monitoring, admin console, plugins, and agents.', adminOnly: true },
];

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('aria_user') || '{}');
  } catch {
    return {};
  }
}

function isAdminViewer() {
  const user = readStoredUser();
  const role = String(user.role || 'user').toLowerCase();
  const name = String(user.username || user.name || user.email || '').toLowerCase();
  return (
    ['admin', 'administrator', 'superadmin', 'super_admin'].includes(role)
    || name === 'admin'
    || name === 'admin@eva.ai'
    || user.isAdmin === true
    || user.is_admin === true
    || localStorage.getItem('aria_is_admin') === 'true'
  );
}

function readMemoryUserId() {
  try {
    const user = JSON.parse(localStorage.getItem('aria_user') || '{}');
    return user.email || user.username || user.name || 'user_001';
  } catch {
    return 'user_001';
  }
}

function MemorySettingsPanel({ API }) {
  const userId = readMemoryUserId();
  const [enabled, setEnabled] = useState(() => localStorage.getItem('eva_memory_enabled') !== 'false');
  const [query, setQuery] = useState('');
  const [memoryText, setMemoryText] = useState('');
  const [memoryType, setMemoryType] = useState('preference');
  const [importance, setImportance] = useState(3);
  const [data, setData] = useState({ memories: [], recent_chats: [], search_results: [] });
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');

  const loadMemories = useCallback(async (search = '') => {
    setLoading(true);
    setStatus('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      if (search.trim()) params.set('q', search.trim());
      const next = await settingsRequest(API, `/memory?${params.toString()}`);
      setData(next);
    } catch (error) {
      setStatus(error.message || 'Memory load failed');
    } finally {
      setLoading(false);
    }
  }, [API, userId]);

  useEffect(() => {
    loadMemories('');
  }, [loadMemories]);

  const updateEnabled = (value) => {
    setEnabled(value);
    localStorage.setItem('eva_memory_enabled', value ? 'true' : 'false');
    setStatus(value ? 'Memory enabled' : 'Memory disabled');
  };

  const addMemory = async () => {
    if (!memoryText.trim()) return;
    setLoading(true);
    try {
      await settingsRequest(API, '/memory', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          content: memoryText.trim(),
          memory_type: memoryType,
          importance: Number(importance),
        }),
      });
      setMemoryText('');
      setStatus('Memory saved');
      await loadMemories('');
    } catch (error) {
      setStatus(error.message || 'Save failed');
    } finally {
      setLoading(false);
    }
  };

  const searchMemories = async () => {
    if (!query.trim()) {
      await loadMemories('');
      return;
    }
    setLoading(true);
    try {
      const result = await settingsRequest(API, '/memory/search', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, query, limit: 20 }),
      });
      setData((current) => ({ ...current, search_results: result.results || [] }));
      setStatus('Search complete');
    } catch (error) {
      setStatus(error.message || 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  const saveEdit = async () => {
    if (!editing?.content?.trim()) return;
    setLoading(true);
    try {
      await settingsRequest(API, `/memory/${editing.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          user_id: userId,
          content: editing.content.trim(),
          memory_type: editing.memory_type,
          importance: Number(editing.importance || 1),
        }),
      });
      setEditing(null);
      setStatus('Memory updated');
      await loadMemories(query);
    } catch (error) {
      setStatus(error.message || 'Update failed');
    } finally {
      setLoading(false);
    }
  };

  const deleteMemory = async (memoryId) => {
    if (!window.confirm('Delete this memory?')) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ user_id: userId });
      await settingsRequest(API, `/memory/${memoryId}?${params.toString()}`, { method: 'DELETE' });
      setStatus('Memory deleted');
      await loadMemories(query);
    } catch (error) {
      setStatus(error.message || 'Delete failed');
    } finally {
      setLoading(false);
    }
  };

  const forgetAll = async () => {
    if (!window.confirm('Forget all EVA memories for this user? This cannot be undone.')) return;
    setLoading(true);
    try {
      await settingsRequest(API, '/memory/forget-all', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId }),
      });
      setData({ memories: [], recent_chats: [], search_results: [] });
      setStatus('All memories forgotten');
    } catch (error) {
      setStatus(error.message || 'Forget failed');
    } finally {
      setLoading(false);
    }
  };

  const shownMemories = query.trim() ? (data.search_results || []) : (data.memories || []);

  return (
    <>
      <Panel title="Personalization / Memory" subtitle="Control whether EVA can use and save long-term user, project, and preference memory.">
        <SettingRow title="Memory" detail="When off, chat requests do not retrieve or save long-term memories.">
          <Toggle checked={enabled} onChange={updateEnabled} />
        </SettingRow>
        <SettingRow title="Search memories" detail="Find project facts, preferences, goals, and recent useful context.">
          <div style={{ display: 'flex', gap: 8, width: '100%' }}>
            <TextInput value={query} onChange={setQuery} placeholder="Search memories" />
            <button type="button" className="eva-settings-button" onClick={searchMemories} disabled={loading}>Search</button>
          </div>
        </SettingRow>
      </Panel>

      <Panel title="Remember Manually" subtitle="Save a useful fact. Secrets, passwords, API keys, and bank details are rejected by the backend.">
        <textarea className="eva-settings-textarea" value={memoryText} onChange={(event) => setMemoryText(event.target.value)} placeholder="Example: User prefers concise implementation summaries and uses EVA RAG with React/FastAPI." />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px 120px', gap: 8, marginTop: 10 }}>
          <Select value={memoryType} onChange={setMemoryType} options={['preference', 'project', 'goal', 'skill', 'long_term']} />
          <input className="eva-settings-input" type="number" min="1" max="5" value={importance} onChange={(event) => setImportance(event.target.value)} />
          <button type="button" className="eva-settings-button primary" onClick={addMemory} disabled={loading || !memoryText.trim()}>Remember</button>
        </div>
      </Panel>

      <Panel title="Saved Memories" subtitle={`${shownMemories.length} visible memories for ${userId}.`}>
        <div style={{ display: 'grid', gap: 8 }}>
          {shownMemories.length === 0 ? (
            <div className="eva-settings-row-detail">No memories found.</div>
          ) : shownMemories.map((memory) => (
            <div key={memory.id} style={{ border: '1px solid var(--eva-settings-line)', borderRadius: 12, background: 'var(--eva-settings-button)', padding: 12 }}>
              {editing?.id === memory.id ? (
                <div style={{ display: 'grid', gap: 8 }}>
                  <textarea className="eva-settings-textarea" value={editing.content} onChange={(event) => setEditing({ ...editing, content: event.target.value })} />
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 110px auto auto', gap: 8 }}>
                    <Select value={editing.memory_type || 'long_term'} onChange={(value) => setEditing({ ...editing, memory_type: value })} options={['preference', 'project', 'goal', 'skill', 'long_term']} />
                    <input className="eva-settings-input" type="number" min="1" max="5" value={editing.importance || 1} onChange={(event) => setEditing({ ...editing, importance: event.target.value })} />
                    <button type="button" className="eva-settings-button primary" onClick={saveEdit} disabled={loading}>Save</button>
                    <button type="button" className="eva-settings-button" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                    <strong style={{ color: 'var(--eva-settings-text)', fontSize: 13 }}>{memory.memory_type || 'memory'} / importance {memory.importance || 1}</strong>
                    <span style={{ color: 'var(--eva-settings-muted)', fontSize: 11 }}>{memory.created_at}</span>
                  </div>
                  <div style={{ color: 'var(--eva-settings-text)', fontSize: 13, lineHeight: 1.55, marginTop: 8, whiteSpace: 'pre-wrap' }}>{memory.content}</div>
                  {!String(memory.id).startsWith('chat-') && (
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <button type="button" className="eva-settings-button" onClick={() => setEditing({ ...memory })}>Edit</button>
                      <button type="button" className="eva-settings-button danger" onClick={() => deleteMemory(memory.id)}>Delete</button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      </Panel>

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button danger" onClick={forgetAll} disabled={loading}>Forget all memories</button>
        <button type="button" className="eva-settings-button" onClick={() => loadMemories(query)} disabled={loading}>Refresh</button>
      </ButtonRow>
    </>
  );
}

const aiSafetyDefaults = {
  enable_update_intelligence: true,
  show_admin_notifications: true,
  check_ai_feature_updates: true,
  check_security_threats: true,
  check_ethics_regulation_updates: true,
  check_package_vulnerabilities: true,
  require_admin_approval_before_applying_suggestions: true,
};

function AISafetyAutomationPanel({ API }) {
  const { settings, update, loading, status, save } = useRemoteSettings(API, '/settings/ai-safety-automation', aiSafetyDefaults);

  return (
    <>
      <Panel title="Update Intelligence" subtitle="Local safety and update monitoring controls. Suggestions still require explicit admin approval and do not auto-edit source code.">
        <SettingRow title="Enable update intelligence" detail="Show the admin Update Intelligence monitor and allow manual check workflows.">
          <Toggle checked={!!settings.enable_update_intelligence} onChange={(value) => update('enable_update_intelligence', value)} />
        </SettingRow>
        <SettingRow title="Show admin notifications" detail="Surface local fallback notifications for admins when real-time sources are not configured.">
          <Toggle checked={!!settings.show_admin_notifications} onChange={(value) => update('show_admin_notifications', value)} />
        </SettingRow>
        <SettingRow title="Check AI feature updates" detail="Track AI new features, LLM model updates, RAG improvements, prompt engineering, and automation changes.">
          <Toggle checked={!!settings.check_ai_feature_updates} onChange={(value) => update('check_ai_feature_updates', value)} />
        </SettingRow>
        <SettingRow title="Check security threats" detail="Monitor hacking alerts, developer security risks, token theft, malicious commands, exposed keys, and phishing links.">
          <Toggle checked={!!settings.check_security_threats} onChange={(value) => update('check_security_threats', value)} />
        </SettingRow>
        <SettingRow title="Check ethics/regulation updates" detail="Watch medical, legal, financial, privacy, misinformation, minor safety, and regulated advice risks.">
          <Toggle checked={!!settings.check_ethics_regulation_updates} onChange={(value) => update('check_ethics_regulation_updates', value)} />
        </SettingRow>
        <SettingRow title="Check package vulnerabilities" detail="Track suspicious npm/pip package and dependency audit recommendations without installing packages.">
          <Toggle checked={!!settings.check_package_vulnerabilities} onChange={(value) => update('check_package_vulnerabilities', value)} />
        </SettingRow>
        <SettingRow title="Require admin approval before applying suggestions" detail="Approving only changes status to approved; implementation remains a separate manual task.">
          <Toggle checked={!!settings.require_admin_approval_before_applying_suggestions} onChange={(value) => update('require_admin_approval_before_applying_suggestions', value)} />
        </SettingRow>
      </Panel>

      <ButtonRow status={loading ? 'Saving...' : status}>
        <button type="button" className="eva-settings-button primary" onClick={() => save(settings)} disabled={loading}>Save AI safety settings</button>
      </ButtonRow>
    </>
  );
}

export default function SettingsModal({
  API = '',
  open = false,
  onClose,
  initialSection = 'general',
}) {
  const { resolvedTheme } = useTheme();
  const [active, setActive] = useState(initialSection || 'general');
  const [general, setGeneral] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('eva_general_settings') || '{}');
    } catch {
      return {};
    }
  });
  const [generalStatus, setGeneralStatus] = useState('');

  // Update 58: engineering panels are admin-only; users get the
  // conversation-product settings.
  const visibleSections = useMemo(
    () => (isAdminViewer() ? sections : sections.filter((section) => !section.adminOnly)),
    []
  );
  const storedUser = useMemo(readStoredUser, []);

  const activeSection = useMemo(
    () => visibleSections.find((section) => section.id === active) || visibleSections[0],
    [active, visibleSections]
  );

  useEffect(() => {
    if (open) setActive(initialSection || 'general');
  }, [open, initialSection]);

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (event) => {
      if (event.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  const updateGeneral = (key, value) => {
    setGeneral((current) => ({ ...current, [key]: value }));
  };

  const saveGeneral = () => {
    localStorage.setItem('eva_general_settings', JSON.stringify(general));
    setGeneralStatus('Saved');
  };

  return (
    <div
      className={`eva-settings-backdrop ${resolvedTheme === 'light' ? 'eva-settings-light' : 'eva-settings-dark'}`}
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
      style={{
        '--eva-settings-bg': 'var(--surface)',
        '--eva-settings-side': 'var(--sidebar-bg)',
        '--eva-settings-panel': 'var(--card-bg)',
        '--eva-settings-input': 'var(--input-bg)',
        '--eva-settings-text': 'var(--text)',
        '--eva-settings-muted': 'var(--text3)',
        '--eva-settings-line': 'var(--border)',
        '--eva-settings-button': 'var(--surface2)',
        '--eva-settings-hover': 'var(--accent-soft)',
        '--eva-settings-active': 'var(--accent-soft)',
      }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <div className="eva-settings-modal">
        <aside className="eva-settings-nav">
          <div className="eva-settings-brand">
            <div className="eva-settings-logo">E</div>
            <div>
              <h2 className="eva-settings-title">Settings</h2>
              <div className="eva-settings-subtitle">EVA workspace controls</div>
            </div>
          </div>

          <nav className="eva-settings-menu" aria-label="Settings sections">
            {visibleSections.map((section) => (
              <button
                key={section.id}
                type="button"
                className={`eva-settings-menu-button ${active === section.id ? 'is-active' : ''}`}
                onClick={() => setActive(section.id)}
              >
                {section.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="eva-settings-content">
          <header className="eva-settings-header">
            <div>
              <h1 className="eva-settings-heading">{activeSection.label}</h1>
              <p className="eva-settings-description">{activeSection.description}</p>
            </div>
            <button type="button" className="eva-settings-close" aria-label="Close settings" onClick={onClose}>
              x
            </button>
          </header>

          <div className="eva-settings-stack">
            {active === 'profile' && (
              <Panel title="Account" subtitle="Your EVA identity for this browser session.">
                <SettingRow title="Name" detail="Display name from your sign-in provider.">
                  <StatusBadge>{storedUser.name || storedUser.username || 'Not signed in'}</StatusBadge>
                </SettingRow>
                <SettingRow title="Email" detail="Used for sign-in and account recovery.">
                  <StatusBadge>{storedUser.email || '—'}</StatusBadge>
                </SettingRow>
                <SettingRow title="Plan" detail="Change this from Billing.">
                  <StatusBadge tone="positive">{storedUser.plan || 'Free'}</StatusBadge>
                </SettingRow>
                <SettingRow title="Sign out" detail="Clears this browser session and returns to login.">
                  <button
                    type="button"
                    className="eva-settings-button"
                    onClick={() => {
                      localStorage.removeItem('aria_user');
                      localStorage.removeItem('aria_token');
                      localStorage.removeItem('aria_is_admin');
                      window.location.assign('/login');
                    }}
                  >
                    Sign out
                  </button>
                </SettingRow>
              </Panel>
            )}
            {active === 'general' && (
              <>
                <Panel title="Workspace" subtitle="Basic defaults stored locally for this workspace session.">
                  <SettingRow title="Workspace name" detail="Shown across team, cloud, and shared agent surfaces.">
                    <TextInput value={general.workspaceName || 'EVA Workspace'} onChange={(value) => updateGeneral('workspaceName', value)} />
                  </SettingRow>
                  <SettingRow title="Language" detail="EVA replies in this language, and the main interface follows it.">
                    <Select
                      value={general.language || 'Auto detect'}
                      onChange={(value) => {
                        updateGeneral('language', value);
                        // useRemoteSettings persists asynchronously, so notify on
                        // the next tick — firing now would have open views re-read
                        // the previous value and appear to ignore the change.
                        setTimeout(() => notifyLanguageChanged(languageCodeFromLabel(value)), 0);
                      }}
                      options={LANGUAGE_OPTIONS}
                    />
                  </SettingRow>
                  <SettingRow title="Startup page" detail="The first workspace area after sign in.">
                    <Select value={general.startupPage || 'Chat'} onChange={(value) => updateGeneral('startupPage', value)} options={['Chat', 'Files', 'Run Center', 'Security Center', 'Agent Studio']} />
                  </SettingRow>
                  <SettingRow title="Compact startup" detail="Use denser layout in operational pages.">
                    <Toggle checked={!!general.compactMode} onChange={(value) => updateGeneral('compactMode', value)} />
                  </SettingRow>
                </Panel>
                <ButtonRow status={generalStatus}>
                  <button type="button" className="eva-settings-button primary" onClick={saveGeneral}>Save general</button>
                </ButtonRow>
              </>
            )}

            {active === 'appearance' && <AppearanceSettingsPanel API={API} />}
            {active === 'voice' && <VoiceSettingsPanel />}
            {active === 'models' && <ModelSettingsPanel API={API} />}
            {active === 'chats' && <ChatSettingsPanel API={API} />}
            {active === 'memory' && <MemorySettingsPanel API={API} />}
            {active === 'knowledge' && <KnowledgeBaseSettingsPanel API={API} />}
            {active === 'integrations' && <IntegrationsSettingsPanel API={API} />}
            {active === 'security' && <SecuritySettingsPanel API={API} />}
            {active === 'team' && <TeamSettingsPanel API={API} />}
            {active === 'billing' && <BillingSettingsPanel API={API} />}
            {active === 'analytics' && <AnalyticsSettingsPanel API={API} />}
            {active === 'ai-safety' && <AISafetyAutomationPanel API={API} />}
            {active === 'developer' && <DeveloperSettingsPanel API={API} />}
          </div>
        </main>
      </div>
    </div>
  );
}
