import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, Search, Plus, GitBranch, Sparkles, Code2, ChevronRight } from 'lucide-react';

// ── Directory data ─────────────────────────────────────────────────────────────
const SKILLS = [
  { id: 'skill-creator',        title: 'Skill Creator',        provider: 'EVA',    description: 'Create and improve EVA skills, prompts, and workflows.',       icon: '🛠️',  route: '/skill-creator' },
  { id: 'canvas-design',        title: 'Canvas Design',        provider: 'EVA',    description: 'Create images, PDFs, posters, and thumbnails with AI.',         icon: '🎨',  route: '/canvas-design' },
  { id: 'web-artifacts-builder', title: 'Web Artifacts',       provider: 'EVA',    description: 'Build websites, dashboards, and HTML artifacts.',               icon: '🌐',  comingSoon: true },
  { id: 'theme-factory',        title: 'Theme Factory',        provider: 'EVA',    description: 'Create themes, color systems, and UI design tokens.',            icon: '🎭',  route: '/theme-factory' },
  { id: 'rag-tools',            title: 'RAG Tools',            provider: 'EVA',    description: 'Upload documents, search knowledge base, cite sources.',         icon: '📚',  route: '/rag' },
  { id: 'code-assistant',       title: 'Code Assistant',       provider: 'EVA',    description: 'Generate, fix, explain, and refactor code with AI.',             icon: '💻',  route: '/code-assistant' },
];

const CONNECTORS = [
  { id: 'google-drive', title: 'Google Drive',  provider: 'Google',  description: 'Access and sync files from your Google Drive.',        icon: '📁', connected: false },
  { id: 'github',       title: 'GitHub',        provider: 'GitHub',  description: 'Browse repos, create issues, and review code.',        icon: '🐙', connected: false },
  { id: 'gmail',        title: 'Gmail',         provider: 'Google',  description: 'Read, compose, and send emails via Gmail.',            icon: '📧', connected: false },
  { id: 'calendar',     title: 'Google Calendar', provider: 'Google', description: 'View and manage calendar events and meetings.',       icon: '📅', connected: false },
];

const PLUGINS = [
  { id: 'web-search',      title: 'Web Search',       provider: 'EVA',    description: 'Search the live web for current information.',         icon: '🔍', enabled: true  },
  { id: 'image-generator', title: 'Image Generator',  provider: 'EVA',    description: 'Generate images from text descriptions.',             icon: '🖼️', enabled: true  },
  { id: 'code-runner',     title: 'Code Runner',      provider: 'Piston', description: 'Execute Python, JS, and 50+ languages safely.',       icon: '▶️', enabled: false },
  { id: 'rag-tools-plugin', title: 'RAG Tools',       provider: 'EVA',    description: 'Retrieve from uploaded documents and knowledge base.', icon: '📚', enabled: true  },
];

// ── Main component ─────────────────────────────────────────────────────────────
// `embedded` renders the directory as PANEL CONTENT instead of its own modal:
// same tabs, search, list and detail, but without the fixed backdrop, the
// centred modal box or its header — the Tools Center already provides those.
// One component, two presentations; nothing is duplicated.
export default function DirectoryModal({ tab, onTabChange, onClose, embedded = false }) {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState(null);

  const tabs = [
    { id: 'skills',     label: 'Skills',     icon: <Sparkles size={14} />,  data: SKILLS },
    { id: 'connectors', label: 'Connectors', icon: <GitBranch size={14} />, data: CONNECTORS },
    { id: 'plugins',    label: 'Plugins',    icon: <Code2 size={14} />,     data: PLUGINS },
  ];

  const current = tabs.find(t => t.id === tab) || tabs[0];
  const filtered = current.data.filter(item =>
    !search || item.title.toLowerCase().includes(search.toLowerCase()) || item.description.toLowerCase().includes(search.toLowerCase())
  );
  const selected = filtered.find(i => i.id === selectedId) || filtered[0] || null;

  // Switching top-level category resets search + selection (detail defaults to first item).
  const selectCategory = (id) => {
    onTabChange(id);
    setSearch('');
    setSelectedId(null);
  };

  // Unchanged: clicking the action navigates to the exact same routes / placeholder alerts.
  const handleAction = (item) => {
    if (item.comingSoon) return; // capability has no backend yet — must never navigate (a dead route fell through App.js's `path="*"` catch-all and silently bounced to /chat)
    if (tab === 'skills' && item.route) {
      navigate(item.route);
      onClose();
    } else if (tab === 'connectors') {
      alert(`Connect ${item.title}: Coming soon. OAuth integration required.`);
    } else if (tab === 'plugins') {
      alert(`${item.title}: ${item.enabled ? 'Already enabled.' : 'Will be enabled in next update.'}`);
    }
  };

  // Action button label/color — identical semantics to the previous card buttons.
  const actionMeta = (item) => {
    const isConnected = item.connected === true;
    const isEnabled = item.enabled === true;
    const label = tab === 'skills' ? 'Open'
      : tab === 'connectors' ? (isConnected ? 'Connected' : 'Connect')
      : (isEnabled ? 'Enabled' : 'Enable');
    const color = tab === 'connectors'
      ? (isConnected ? '#22c55e' : 'var(--accent)')
      : tab === 'plugins'
      ? (isEnabled ? '#22c55e' : 'var(--accent)')
      : 'var(--accent)';
    return { label, color };
  };

  // Panel when embedded, modal when standalone.
  const Shell = ({ children }) => (embedded ? (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>{children}</div>
  ) : (
    <>
      <button
        type="button"
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 1100, border: 'none', cursor: 'default' }}
        aria-label="Close directory"
      />
      <div style={{
        position: 'fixed',
        top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 'min(96vw, 880px)',
        height: 'min(85vh, 600px)',
        background: 'var(--surface)',
        backdropFilter: 'blur(24px)',
        border: '1px solid rgba(124,58,237,.2)',
        borderRadius: 18,
        zIndex: 1101,
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 32px 80px rgba(0,0,0,.8)',
        animation: 'dir-fadein .18s ease',
        overflow: 'hidden',
      }}>{children}</div>
    </>
  ));

  return (
    <Shell>
        {/* Header — the Tools Center supplies its own when embedded */}
        {!embedded && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,.06)', flexShrink: 0 }}>
          <Sparkles size={16} style={{ color: 'var(--accent)' }} />
          <span style={{ color: 'var(--text)', fontSize: 15, fontWeight: 800 }}>EVA Directory</span>
          <span style={{ color: 'var(--text3)', fontSize: 11 }}>Skills · Connectors · Plugins</span>
          <button type="button" onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', display: 'flex', padding: 4 }}>
            <X size={16} />
          </button>
        </div>
        )}

        {/* Body: sidebar + detail */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

          {/* ── Left sidebar ───────────────────────────────────────────── */}
          <div style={{ width: 248, flexShrink: 0, borderRight: '1px solid rgba(255,255,255,.06)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>

            {/* Search */}
            <div style={{ padding: '12px 12px 8px', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'var(--surface2)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 8, padding: '6px 10px' }}>
                <Search size={12} style={{ color: 'var(--text3)', flexShrink: 0 }} />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={`Search ${current.label.toLowerCase()}...`}
                  style={{ flex: 1, background: 'none', border: 'none', outline: 'none', color: 'var(--text)', fontSize: 12, minWidth: 0 }}
                />
              </div>
            </div>

            {/* Category accordion with nested items */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px 12px' }}>
              {tabs.map(t => {
                const isActiveCat = tab === t.id;
                return (
                  <div key={t.id} style={{ marginBottom: 2 }}>
                    <button
                      type="button"
                      onClick={() => selectCategory(t.id)}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                        padding: '8px 10px', borderRadius: 8,
                        border: `1px solid ${isActiveCat ? 'color-mix(in srgb, var(--accent) 40%, transparent)' : 'transparent'}`,
                        background: isActiveCat ? 'color-mix(in srgb, var(--accent) 20%, transparent)' : 'transparent',
                        color: isActiveCat ? 'var(--accent)' : 'var(--text2)',
                        fontSize: 12.5, fontWeight: 700, cursor: 'pointer', transition: '.15s', textAlign: 'left',
                      }}
                    >
                      <ChevronRight size={13} style={{ transform: isActiveCat ? 'rotate(90deg)' : 'none', transition: 'transform .15s', flexShrink: 0 }} />
                      {t.icon}
                      <span style={{ flex: 1 }}>{t.label}</span>
                      <span style={{ color: 'var(--text3)', fontSize: 10, background: 'var(--surface2)', padding: '1px 7px', borderRadius: 99 }}>{t.data.length}</span>
                    </button>

                    {isActiveCat && (
                      <div style={{ padding: '4px 0 6px 6px' }}>
                        {filtered.length === 0 && (
                          <div style={{ color: 'var(--text3)', fontSize: 12, padding: '8px 12px' }}>No results for "{search}"</div>
                        )}
                        {filtered.map(item => {
                          const isSel = selected && selected.id === item.id;
                          return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => setSelectedId(item.id)}
                              style={{
                                width: '100%', display: 'flex', alignItems: 'center', gap: 9,
                                padding: '7px 10px', marginBottom: 2, borderRadius: 8,
                                border: `1px solid ${isSel ? 'color-mix(in srgb, var(--accent) 30%, transparent)' : 'transparent'}`,
                                background: isSel ? 'color-mix(in srgb, var(--accent) 12%, transparent)' : 'transparent',
                                color: isSel ? 'var(--text)' : 'var(--text2)',
                                fontSize: 12.5, fontWeight: isSel ? 600 : 500, cursor: 'pointer', transition: '.12s', textAlign: 'left',
                              }}
                            >
                              <span style={{ fontSize: 15, flexShrink: 0, lineHeight: 1 }}>{item.icon}</span>
                              <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title}</span>
                              {item.comingSoon && (
                                <span style={{ flexShrink: 0, fontSize: 9, fontWeight: 700, color: '#9333ea', background: 'rgba(147,51,234,0.14)', border: '1px solid rgba(124,58,237,.3)', borderRadius: 999, padding: '1px 6px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Soon</span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Right detail panel ─────────────────────────────────────── */}
          <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '26px 28px' }}>
            {selected ? (
              <>
                <div style={{ fontSize: 46, lineHeight: 1, marginBottom: 16 }}>{selected.icon}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
                  <span style={{ color: 'var(--text)', fontSize: 21, fontWeight: 800, letterSpacing: '-0.01em' }}>{selected.title}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 11, background: 'var(--surface2)', padding: '2px 9px', borderRadius: 99, border: '1px solid rgba(255,255,255,.07)' }}>{selected.provider}</span>
                </div>
                <div style={{ color: 'var(--text2)', fontSize: 14, lineHeight: 1.65, maxWidth: 520, marginBottom: 24 }}>{selected.description}</div>

                {selected.comingSoon ? (
                  <div>
                    <button
                      type="button"
                      disabled
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                        padding: '9px 18px', borderRadius: 9,
                        border: '1px solid rgba(255,255,255,.08)',
                        background: 'var(--surface2)',
                        color: 'var(--text2)', fontSize: 13, fontWeight: 700, cursor: 'not-allowed',
                      }}
                    >
                      Coming Soon
                    </button>
                    <div style={{ color: 'var(--text3)', fontSize: 12, marginTop: 10, maxWidth: 520, lineHeight: 1.5 }}>
                      Not available yet — there is no backend for this capability. It will open here once it ships.
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleAction(selected)}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6,
                      padding: '9px 18px', borderRadius: 9,
                      border: `1px solid ${actionMeta(selected).color}55`,
                      background:  `color-mix(in srgb, ${actionMeta(selected).color} 14%, transparent)`,
                      color: actionMeta(selected).color, fontSize: 13, fontWeight: 700, cursor: 'pointer', transition: '.15s',
                    }}
                  >
                    {tab === 'skills' ? <Plus size={14} /> : null}
                    {actionMeta(selected).label}
                  </button>
                )}
              </>
            ) : (
              <div style={{ color: 'var(--text3)', fontSize: 13, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                No {current.label.toLowerCase()} to show.
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '10px 20px', borderTop: '1px solid rgba(255,255,255,.05)', fontSize: 11, color: 'var(--text3)', flexShrink: 0 }}>
          {filtered.length} {current.label.toLowerCase()} available
        </div>

      <style>{`
        @keyframes dir-fadein { from { opacity:0; transform:translate(-50%,-46%) } to { opacity:1; transform:translate(-50%,-50%) } }
      `}</style>
    </Shell>
  );
}
