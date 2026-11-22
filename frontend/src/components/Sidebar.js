import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { NavLink, useNavigate } from 'react-router-dom';
import useTranslation from '../lib/useTranslation';
import {
  Bot,
  Box,
  Clock3,
  Database,
  Files,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings,
  Shield,
  Trash2,
  UserRound,
} from 'lucide-react';

// Update 58 — the user-facing sidebar is conversation-only (Chat, History,
// Profile, Settings), matching the ChatGPT/Claude/Gemini shape. Everything
// below that is an AI-engineering surface and belongs to the admin
// workspace, so each entry is adminOnly rather than deleted: the routes
// still exist, the admin workspace still reaches them, and deep links do
// not 404. End users simply never see them.
//
// EVA already picks General AI / RAG / Vision / OCR / Code / CAD per message
// on the backend (route_query + intent detection + auto-retrieval), so there
// is no mode for a user to choose and no page for one to visit.
const navItems = [
  { to: '/chat',            label: 'Chat',           icon: MessageSquare },
  { to: '/knowledge',       label: 'Files',          icon: Files,        adminOnly: true },
  { to: '/agent-studio',    label: 'Agents',         icon: Bot,          adminOnly: true },
  { to: '/ml',              label: 'ML Training',    icon: Bot,          adminOnly: true },
  { to: '/rag',             label: 'RAG Center',     icon: Database,     adminOnly: true },
  { to: '/cad-studio',      label: 'CAD Studio',     icon: Box,          adminOnly: true },
  { to: '/security-center', label: 'Security',       icon: Shield,       adminOnly: true },
];

function fallbackConversations() {
  const now = new Date().toISOString();
  return [{ id: 1, title: 'New conversation', active: true, pinned: false, createdAt: now, updatedAt: now }];
}

function normalizeConversation(conversation, index = 0) {
  const id = conversation.id || conversation.session_id || `local_${Date.now()}_${index}`;
  const createdAt = conversation.createdAt || conversation.created_at || conversation.created || new Date().toISOString();
  return {
    ...conversation,
    id,
    title: conversation.title || 'New conversation',
    active: !!conversation.active,
    pinned: !!conversation.pinned,
    createdAt,
    updatedAt: conversation.updatedAt || conversation.updated_at || createdAt,
  };
}

function normalizeConversations(items) {
  const normalized = (Array.isArray(items) && items.length ? items : fallbackConversations())
    .map(normalizeConversation);

  if (!normalized.some((conversation) => conversation.active)) {
    normalized[0] = { ...normalized[0], active: true };
  }

  return normalized;
}

function readConversations() {
  try {
    const saved = JSON.parse(localStorage.getItem('eva_conversations') || 'null');
    return normalizeConversations(saved);
  } catch {
    return fallbackConversations();
  }
}

function writeConversations(conversations) {
  const normalized = normalizeConversations(conversations);
  localStorage.setItem('eva_conversations', JSON.stringify(normalized));
  return normalized;
}

function dispatchChatCommand(type, payload = {}) {
  const command = { id: Date.now(), type, createdAt: Date.now(), ...payload };
  localStorage.setItem('eva_chat_command', JSON.stringify(command));
  window.dispatchEvent(new CustomEvent('eva:chat-command', { detail: command }));
}

function startOfDay(date) {
  const value = new Date(date);
  value.setHours(0, 0, 0, 0);
  return value;
}

function groupConversations(conversations) {
  const now = startOfDay(new Date());
  const pinned = conversations.filter((conversation) => conversation.pinned);
  const regular = conversations.filter((conversation) => !conversation.pinned);
  const groups = [];

  if (pinned.length) groups.push(['Pinned', pinned]);

  const buckets = {
    Today: [],
    Yesterday: [],
    'Last 7 Days': [],
    Older: [],
  };

  regular.forEach((conversation) => {
    const date = startOfDay(conversation.updatedAt || conversation.createdAt || Date.now());
    const days = Math.floor((now - date) / 86400000);
    if (days <= 0) buckets.Today.push(conversation);
    else if (days === 1) buckets.Yesterday.push(conversation);
    else if (days <= 7) buckets['Last 7 Days'].push(conversation);
    else buckets.Older.push(conversation);
  });

  Object.entries(buckets).forEach(([label, items]) => {
    if (items.length) groups.push([label, items]);
  });

  return groups;
}

export default function Sidebar({ onOpenSettings, onNavigate, adminMode = false }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const storedUser = (() => {
    try {
      return JSON.parse(localStorage.getItem('aria_user') || '{}');
    } catch {
      return {};
    }
  })();
  const rawRole = String(storedUser.role || 'user').toLowerCase();
  const rawUserName = String(storedUser.username || storedUser.name || storedUser.email || '').toLowerCase();
  const isAdmin = ['admin', 'administrator', 'superadmin', 'super_admin'].includes(rawRole) || rawUserName === 'admin' || rawUserName === 'admin@eva.ai' || storedUser.isAdmin === true || storedUser.is_admin === true || localStorage.getItem('aria_is_admin') === 'true';
  const isAdminWorkspace = adminMode || (window.location.port === '8003' && process.env.REACT_APP_ADMIN_MODE === 'true');
  const visibleNavItems = navItems.filter((item) => (item.adminOnly ? isAdminWorkspace && isAdmin : true));
  const [conversations, setConversations] = useState(readConversations);
  const [query, setQuery] = useState('');
  const [menuFor, setMenuFor] = useState(null);
  const [menuPosition, setMenuPosition] = useState(null);
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState('');
  const menuRef = useRef(null);

  useEffect(() => {
    const sync = (event) => {
      if (event?.detail?.conversations) {
        setConversations(normalizeConversations(event.detail.conversations));
        return;
      }
      setConversations(readConversations());
    };

    window.addEventListener('storage', sync);
    window.addEventListener('eva:chat-state', sync);
    window.addEventListener('eva:chat-history-changed', sync);

    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener('eva:chat-state', sync);
      window.removeEventListener('eva:chat-history-changed', sync);
    };
  }, []);

  useEffect(() => {
    const close = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuFor(null);
        setMenuPosition(null);
      }
    };
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setMenuFor(null);
        setMenuPosition(null);
        setRenamingId(null);
      }
    };
    document.addEventListener('mousedown', close);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  const commitConversations = (updater) => {
    setConversations((current) => {
      const next = typeof updater === 'function' ? updater(current) : updater;
      return writeConversations(next);
    });
  };

  const startNewChat = () => {
    navigate('/chat');
    dispatchChatCommand('new');
    onNavigate?.();
  };

  const selectConversation = (conversation) => {
    navigate('/chat');
    commitConversations((current) => current.map((item) => ({ ...item, active: String(item.id) === String(conversation.id) })));
    dispatchChatCommand('select', { conversationId: conversation.id });
    setMenuFor(null);
    onNavigate?.();
  };

  const beginRename = (conversation) => {
    setRenamingId(conversation.id);
    setRenameValue(conversation.title || 'New conversation');
    setMenuFor(null);
    setMenuPosition(null);
  };

  const commitRename = (conversationId) => {
    const title = renameValue.trim().slice(0, 80) || 'New conversation';
    commitConversations((current) => current.map((conversation) => (
      String(conversation.id) === String(conversationId)
        ? { ...conversation, title, updatedAt: new Date().toISOString() }
        : conversation
    )));
    dispatchChatCommand('rename', { conversationId, title });
    setRenamingId(null);
    setRenameValue('');
  };

  const togglePin = (conversation) => {
    const pinned = !conversation.pinned;
    commitConversations((current) => current.map((item) => (
      String(item.id) === String(conversation.id)
        ? { ...item, pinned, updatedAt: new Date().toISOString() }
        : item
    )));
    dispatchChatCommand('pin', { conversationId: conversation.id, pinned });
    setMenuFor(null);
    setMenuPosition(null);
  };

  const deleteConversation = (conversation) => {
    if (!window.confirm(`Delete "${conversation.title || 'New conversation'}"?`)) return;
    const wasActive = !!conversation.active;
    commitConversations((current) => {
      const remaining = current.filter((item) => String(item.id) !== String(conversation.id));
      if (!remaining.length) return fallbackConversations();
      if (wasActive && !remaining.some((item) => item.active)) {
        remaining[0] = { ...remaining[0], active: true };
      }
      return remaining;
    });
    dispatchChatCommand('delete', { conversationId: conversation.id });
    setMenuFor(null);
    setMenuPosition(null);
    navigate('/chat');
    onNavigate?.();
  };

  const openConversationMenu = (conversation, event) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 176;
    const menuHeight = 124;
    const left = Math.max(10, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 10));
    const top = Math.max(10, Math.min(rect.bottom + 6, window.innerHeight - menuHeight - 10));
    setMenuPosition({ left, top });
    setMenuFor((current) => (String(current) === String(conversation.id) ? null : conversation.id));
  };

  const filteredConversations = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const sorted = [...conversations].sort((a, b) => {
      if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
      return new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0);
    });
    if (!needle) return sorted;
    return sorted.filter((conversation) => (conversation.title || '').toLowerCase().includes(needle));
  }, [conversations, query]);

  const groupedConversations = useMemo(
    () => groupConversations(filteredConversations),
    [filteredConversations]
  );
  const menuConversation = conversations.find((conversation) => String(conversation.id) === String(menuFor));
  const historyMenu = menuConversation && menuPosition ? (
    <div
      ref={menuRef}
      className="eva-sidebar-history-menu"
      style={{ left: menuPosition.left, top: menuPosition.top }}
    >
      <button type="button" onClick={() => beginRename(menuConversation)}>
        <Pencil size={14} />
        <span>Rename</span>
      </button>
      <button type="button" onClick={() => togglePin(menuConversation)}>
        {menuConversation.pinned ? <PinOff size={14} /> : <Pin size={14} />}
        <span>{menuConversation.pinned ? 'Unpin' : 'Pin'}</span>
      </button>
      <button type="button" className="danger" onClick={() => deleteConversation(menuConversation)}>
        <Trash2 size={14} />
        <span>Delete</span>
      </button>
    </div>
  ) : null;

  return (
    <>
    <aside className="eva-sidebar" aria-label="EVA workspace sidebar">
      <div className="eva-sidebar-brand">
        <div className="eva-sidebar-logo">E</div>
        <div>
          <div className="eva-sidebar-title">EVA</div>
          <div className="eva-sidebar-subtitle">AI Workspace</div>
        </div>
      </div>

      <div className="eva-sidebar-new-wrap">
        <button type="button" className="eva-sidebar-new-chat" onClick={startNewChat}>
          <Plus size={10} />
          <span>New Chat</span>
        </button>
      </div>

      <nav className="eva-sidebar-primary-nav" aria-label="Primary EVA navigation">
        {visibleNavItems.map(({ to, label, icon: Icon, externalUrl }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `eva-sidebar-link${isActive ? ' is-active' : ''}`}
            onClick={(event) => {
              if (externalUrl) {
                event.preventDefault();
                window.open(externalUrl, '_blank', 'noopener,noreferrer');
              }
              onNavigate?.();
            }}
          >
            <Icon size={17} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <section className="eva-sidebar-history" aria-label="Chat history">
        <div className="eva-sidebar-section-label">
          <Clock3 size={13} />
          <span>{t('nav.history')}</span>
        </div>

        <label className="eva-sidebar-search" aria-label="Search chats">
          <Search size={14} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search chats" />
        </label>

        <div className="eva-sidebar-history-list">
          {groupedConversations.length === 0 && (
            <div className="eva-sidebar-empty">No chats found</div>
          )}

          {groupedConversations.map(([label, items]) => (
            <div key={label} className="eva-sidebar-history-group">
              <div className="eva-sidebar-history-group-label">{label}</div>
              {items.map((conversation) => (
                <div
                  key={conversation.id}
                  className={`eva-sidebar-history-row ${conversation.active ? 'is-active' : ''}`}
                  onContextMenu={(event) => {
                    openConversationMenu(conversation, event);
                  }}
                >
                  {renamingId === conversation.id ? (
                    <input
                      className="eva-sidebar-rename-input"
                      value={renameValue}
                      autoFocus
                      onChange={(event) => setRenameValue(event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') commitRename(conversation.id);
                        if (event.key === 'Escape') {
                          setRenamingId(null);
                          setRenameValue('');
                        }
                      }}
                      onBlur={() => commitRename(conversation.id)}
                    />
                  ) : (
                    <>
                      <button
                        type="button"
                        className="eva-sidebar-history-item"
                        onClick={() => selectConversation(conversation)}
                        title={conversation.title || 'New conversation'}
                      >
                        {conversation.pinned ? <Pin size={13} /> : <MessageSquare size={14} />}
                        <span>{conversation.title || 'New conversation'}</span>
                      </button>

                      <button
                        type="button"
                        className="eva-sidebar-history-menu-button"
                        onClick={(event) => openConversationMenu(conversation, event)}
                        aria-label="Conversation actions"
                      >
                        <MoreHorizontal size={15} />
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      <div className="eva-sidebar-footer">
        <button
          type="button"
          className="eva-sidebar-link eva-sidebar-settings"
          onClick={() => {
            onOpenSettings?.('profile');
            onNavigate?.();
          }}
        >
          <UserRound size={18} />
          <span>{t('nav.profile')}</span>
        </button>
        <button
          type="button"
          className="eva-sidebar-link eva-sidebar-settings"
          onClick={() => {
            onOpenSettings?.('general');
            onNavigate?.();
          }}
        >
          <Settings size={18} />
          <span>{t('nav.settings')}</span>
        </button>
      </div>
    </aside>
    {historyMenu && createPortal(historyMenu, document.body)}
    </>
  );
}
