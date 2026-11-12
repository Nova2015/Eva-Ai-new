import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import Chat from './pages/Chat';
import Upload from './pages/Upload';
import Studio from './pages/Studio';
import SettingsModal from './components/SettingsModal';
import Login from './pages/Login';
import { useEffect, useMemo, useState } from 'react';
import ML from './pages/ML';
import AuthGuard from './components/AuthGuard';  
import SecurityDashboard from "./pages/SecurityDashboard"; 
import ThreatMonitor from "./pages/ThreatMonitor";
import { GoogleOAuthProvider } from '@react-oauth/google';
import CodeAssistant from './pages/CodeAssistant';
import Support from './pages/Support';
import Billing from './pages/Billing';
import SkillCreator from './pages/SkillCreator';
import CanvasDesign from './pages/CanvasDesign';
import CADStudio from './pages/CADStudio';
import ThemeFactory from './pages/ThemeFactory';
import MemoryCenter from './pages/MemoryCenter';
import AgentCenter from './pages/AgentCenter';
import TeamWorkspace from './pages/TeamWorkspace';
import AnalyticsDashboard from './pages/AnalyticsDashboard';
import AIStudio from './pages/AIStudio';
import RunCenter from './pages/RunCenter';
import AgentMarketplace from './pages/AgentMarketplace';
import PublishedAgents from './pages/PublishedAgents';
// BillingCenter (live /billing/* dashboard) unmounted for Slice 3 â€” the import
// is removed so CRA's unused-import warning can't fail CI builds. Re-import
// alongside real billing endpoints.
import RAGCenter from './pages/RAGCenter';
import SecurityCenter from './pages/SecurityCenter';
import { ensureLocalAuth } from './localAuth';
import { API_BASE_URL } from './lib/apiConfig';
import LandingPage from './pages/LandingPage';
import PricingPage from './pages/PricingPage';
import AboutPage from './pages/AboutPage';
import ContactPage from './pages/ContactPage';
import { ThemeProvider } from './context/ThemeContext';
import AgentPanel from './pages/AgentPanel';

const API = API_BASE_URL;
const ADMIN_WORKSPACE_PORT = '8003';
const isAdminPort = () => (typeof window !== 'undefined' && window.location.port === ADMIN_WORKSPACE_PORT);
const isAdminWorkspaceMode = () => (
  isAdminPort() && process.env.REACT_APP_ADMIN_MODE === 'true'
);
const IS_ADMIN_WORKSPACE = isAdminWorkspaceMode();

function AdminWorkspaceDisabled() {
  return (
    <section style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: 'var(--bg)', color: 'var(--text)' }}>
      <div style={{ maxWidth: 520, border: '1px solid var(--border)', borderRadius: 8, padding: 24, background: 'rgba(15,23,42,.82)' }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Admin workspace disabled.</h1>
        <p style={{ margin: '10px 0 0', color: 'var(--text3)', lineHeight: 1.5 }}>Run local admin mode to use this.</p>
      </div>
    </section>
  );
}

function LocalAdminGate({ onUnlock }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError('');

    if (!username.trim() || !password) {
      setError('Enter your admin username and password.');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(buildApiUrl('/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: username.trim(),
          password,
        }),
      });

      const data = await res.json().catch(() => ({}));
      const token = data.access_token || data.token;
      const role = String(data.user?.role || '').toLowerCase();

      if (!res.ok || !token) {
        throw new Error(data.detail || 'Backend login failed.');
      }

      if (!['admin', 'administrator', 'superadmin', 'super_admin'].includes(role)) {
        throw new Error('This account does not have administrator access.');
      }

      const verifyRes = await fetch(
        buildApiUrl('/api/admin/intelligence/status'),
        { headers: { Authorization: `Bearer ${token}` } }
      );

      if (!verifyRes.ok) {
        throw new Error('Backend did not authorize administrator access.');
      }

      localStorage.setItem('aria_token', token);
      localStorage.setItem('aria_user', JSON.stringify(data.user));
      setPassword('');
      onUnlock?.();
    } catch (err) {
      if (localStorage.getItem('aria_token') === 'local_admin_gate') {
        localStorage.removeItem('aria_token');
        localStorage.removeItem('aria_user');
      }
      setError(err.message || 'Admin authentication failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: 'var(--bg)', color: 'var(--text)' }}>
      <form onSubmit={submit} style={{ width: 'min(420px, 100%)', display: 'grid', gap: 14, border: '1px solid var(--border)', borderRadius: 8, padding: 24, background: 'rgba(15,23,42,.88)' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24 }}>Local Admin Workspace</h1>
          <p style={{ margin: '8px 0 0', color: 'var(--text3)', lineHeight: 1.45 }}>Administrator access is verified by the EVA backend.</p>
        </div>
        <label style={{ display: 'grid', gap: 6, color: 'var(--text2)', fontSize: 13 }}>
          Username
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" style={{ minHeight: 40, borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(2,6,23,.8)', color: 'var(--text)', padding: '0 12px' }} />
        </label>
        <label style={{ display: 'grid', gap: 6, color: 'var(--text2)', fontSize: 13 }}>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" style={{ minHeight: 40, borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(2,6,23,.8)', color: 'var(--text)', padding: '0 12px' }} />
        </label>
        {error && <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 13 }}>{error}</div>}
        <button type="submit" disabled={loading} style={{ minHeight: 40, borderRadius: 8, border: '1px solid rgba(96,165,250,.36)', background: 'rgba(37,99,235,.32)', color: 'var(--info-text)', fontWeight: 850, cursor: loading ? 'wait' : 'pointer' }}>
          {loading ? 'Verifying...' : 'Open Admin Workspace'}
        </button>
      </form>
    </section>
  );
}

const CURRENT_ADMIN_UPDATE = {
  id: '43B',
  title: 'Move admin data to Admin port',
  status: 'In Progress',
  scope: 'Admin only',
  approval: 'Pending Review',
  changedFiles: [
    {
      file: 'frontend/src/App.js',
      added: 42,
      removed: 8,
      change: 'Gated admin workspace to admin mode and port 8003',
      status: 'Modified',
    },
    {
      file: 'src/app.py',
      added: 6,
      removed: 2,
      change: 'Updated admin intelligence status with port architecture',
      status: 'Modified',
    },
    {
      file: 'frontend/src/components/Sidebar.js',
      added: 3,
      removed: 1,
      change: 'Hid admin navigation outside admin workspace mode',
      status: 'Modified',
    },
    {
      file: 'frontend/src/components/AuthGuard.js',
      added: 10,
      removed: 0,
      change: 'Blocked admin-only routes outside admin workspace mode',
      status: 'Modified',
    },
    {
      file: 'frontend/src/pages/Chat.js',
      added: 2,
      removed: 1,
      change: 'Hid admin suggestions outside admin workspace mode',
      status: 'Modified',
    },
    {
      file: 'frontend/src/pages/Login.js',
      added: 2,
      removed: 1,
      change: 'Redirected admin-mode login to Update Intelligence',
      status: 'Modified',
    },
  ],
};

const updateTools = ['Review', 'Scope', 'Terminal', 'Browser', 'Files', 'Side chat'];
const approvalStatuses = {
  'Pending Review': { tone: 'var(--warn)', note: 'Review pending. No automatic patch will be applied without admin approval.' },
  Approved: { tone: 'var(--green)', note: 'Approved, but automatic patch execution will be added later.' },
  Rejected: { tone: 'var(--red)', note: 'Rejected. No patch can be applied.' },
  'Needs Changes': { tone: 'var(--cyan)', note: 'Needs changes. Ask EVA for follow-up changes.' },
};
const patchScopes = [
  { id: 'review-only', label: 'Review only', description: 'No patch target selected. EVA can inspect and summarize only.' },
  { id: 'frontend', label: 'Frontend only', description: 'Limit future approved patch proposals to existing frontend files.' },
  { id: 'backend', label: 'Backend only', description: 'Limit future approved patch proposals to existing backend files.' },
  { id: 'rag', label: 'RAG routes only', description: 'Limit future approved patch proposals to RAG API and retrieval files.' },
  { id: 'auth-admin', label: 'Auth/Admin only', description: 'Limit future approved patch proposals to auth guards and admin workspace files.' },
];

function getUpdateSummary(update) {
  const files = update.changedFiles || [];
  const added = files.reduce((total, file) => total + Number(file.added || 0), 0);
  const removed = files.reduce((total, file) => total + Number(file.removed || 0), 0);
  return `${files.length} ${files.length === 1 ? 'file' : 'files'} changed +${added} -${removed}`;
}

function getUpdateToastMessage(update) {
  return `Current update: ${update.id} ${update.title} - ${update.status}`;
}

function emitAdminToast(message, id = `toast-${Date.now()}`) {
  window.dispatchEvent(new CustomEvent('eva:toast', {
    detail: { id, message, adminOnly: true },
  }));
}

function getStoredAdminUser() {
  try {
    return JSON.parse(localStorage.getItem('aria_user') || '{}');
  } catch {
    return {};
  }
}

function isUpdateWorkspaceAdmin(user) {
  const role = String(user.role || '').toLowerCase();
  const username = String(user.username || user.name || user.email || '').toLowerCase();
  return (
    ['admin', 'administrator', 'superadmin', 'super_admin'].includes(role) ||
    username === 'admin' ||
    username === 'admin@eva.ai' ||
    user.isAdmin === true ||
    user.is_admin === true ||
    localStorage.getItem('aria_is_admin') === 'true'
  );
}

function getAdminApiHeaders() {
  const token = localStorage.getItem('aria_token') || localStorage.getItem('token') || localStorage.getItem('access_token') || localStorage.getItem('authToken');
  return {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function buildApiUrl(path) {
  return `${String(API || '').replace(/\/$/, '')}${path}`;
}

function boolLabel(value) {
  return value ? 'Yes' : 'No';
}

function UpdateIntelligencePage() {
  const [activeTool, setActiveTool] = useState(() => {
    const requested = sessionStorage.getItem('eva_update_workspace_panel');
    return updateTools.includes(requested) ? requested : 'Review';
  });
  const [selectedFile, setSelectedFile] = useState(() => {
    const requestedFile = sessionStorage.getItem('eva_update_workspace_file');
    return CURRENT_ADMIN_UPDATE.changedFiles.find((file) => file.file === requestedFile) || CURRENT_ADMIN_UPDATE.changedFiles[0];
  });
  const [approvalStatus, setApprovalStatus] = useState(CURRENT_ADMIN_UPDATE.approval);
  const [selectedPatchScope, setSelectedPatchScope] = useState(patchScopes[0]);
  const [approvalHistory, setApprovalHistory] = useState([]);
  const storedUser = getStoredAdminUser();
  const isAdmin = isUpdateWorkspaceAdmin(storedUser);
  const [workspaceAction, setWorkspaceAction] = useState(() => sessionStorage.getItem('eva_update_workspace_action') || 'open');
  const [inspection, setInspection] = useState({
    loading: true,
    error: '',
    status: null,
    project: null,
    health: null,
  });

  useEffect(() => {
    sessionStorage.removeItem('eva_update_workspace_action');
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;

    const loadAdminInspection = async () => {
      setInspection((current) => ({ ...current, loading: true, error: '' }));
      try {
        const headers = getAdminApiHeaders();
        const [statusRes, projectRes, healthRes] = await Promise.all([
          fetch(buildApiUrl('/api/admin/intelligence/status'), { headers }),
          fetch(buildApiUrl('/api/admin/intelligence/project'), { headers }),
          fetch(buildApiUrl('/api/admin/intelligence/health'), { headers }),
        ]);

        if (!statusRes.ok || !projectRes.ok || !healthRes.ok) {
          throw new Error('Admin inspection backend unavailable.');
        }

        const [status, project, health] = await Promise.all([
          statusRes.json(),
          projectRes.json(),
          healthRes.json(),
        ]);

        if (!cancelled) {
          setInspection({ loading: false, error: '', status, project, health });
        }
      } catch {
        if (!cancelled) {
          setInspection({ loading: false, error: 'Admin inspection backend unavailable.', status: null, project: null, health: null });
        }
      }
    };

    loadAdminInspection();
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const currentUpdate = useMemo(() => ({
    ...CURRENT_ADMIN_UPDATE,
    id: inspection.status?.current_update || CURRENT_ADMIN_UPDATE.id,
    title: inspection.status?.name || CURRENT_ADMIN_UPDATE.title,
    status: inspection.status?.status || CURRENT_ADMIN_UPDATE.status,
  }), [inspection.status]);
  const changedFiles = useMemo(() => currentUpdate.changedFiles || [], [currentUpdate]);
  const updateSummary = useMemo(() => getUpdateSummary(currentUpdate), [currentUpdate]);

  useEffect(() => {
    if (!isAdmin || inspection.loading || !workspaceAction) return;
    if (inspection.error) {
      setTimeout(() => emitAdminToast('Admin inspection backend unavailable.', 'admin-inspection-unavailable'), 0);
      setWorkspaceAction('');
      return;
    }
    if (workspaceAction === 'file') {
      setTimeout(() => emitAdminToast(`Review opened for ${changedFiles[0].file}`, 'current-update-file-opened'), 0);
      setWorkspaceAction('');
      return;
    }
    setTimeout(() => emitAdminToast(getUpdateToastMessage(currentUpdate), workspaceAction ? `current-update-${workspaceAction}` : 'current-update-opened'), 0);
    setWorkspaceAction('');
  }, [changedFiles, currentUpdate, inspection.error, inspection.loading, isAdmin, workspaceAction]);

  if (!isAdmin) return null;

  const setApproval = (nextStatus) => {
    const logMap = {
      Approved: `Admin approved Update ${currentUpdate.id}`,
      Rejected: `Admin rejected Update ${currentUpdate.id}`,
      'Needs Changes': `Admin requested changes for Update ${currentUpdate.id}`,
    };
    const toastMap = {
      Approved: `Update approved by admin. Patch execution is still disabled in ${currentUpdate.id}.`,
      Rejected: 'Update rejected by admin.',
      'Needs Changes': `Update ${currentUpdate.id} marked as needs changes.`,
    };

    setApprovalStatus(nextStatus);
    setApprovalHistory((current) => [
      { id: `${nextStatus}-${Date.now()}`, text: logMap[nextStatus], time: new Date().toLocaleTimeString() },
      ...current,
    ]);
    emitAdminToast(toastMap[nextStatus], `approval-${nextStatus}-${Date.now()}`);
  };

  const choosePatchScope = (scope) => {
    setSelectedPatchScope(scope);
    setApprovalHistory((current) => [
      { id: `scope-${scope.id}-${Date.now()}`, text: `Admin selected patch scope: ${scope.label}`, time: new Date().toLocaleTimeString() },
      ...current,
    ]);
    emitAdminToast(`Patch scope selected: ${scope.label}. Patch execution remains disabled.`, `scope-${scope.id}-${Date.now()}`);
  };

  const openFile = (file) => {
    setSelectedFile(file);
    setActiveTool('Files');
    emitAdminToast(`Review opened for ${file.file}`, `file-${file.file}-${Date.now()}`);
  };

  const selectTool = (tool) => {
    setActiveTool(tool);
    if (tool === 'Review') emitAdminToast(getUpdateToastMessage(currentUpdate), `review-${Date.now()}`);
    if (tool === 'Files' && selectedFile) emitAdminToast(`Review opened for ${selectedFile.file}`, `files-${Date.now()}`);
  };

  const activityItems = [
    { title: 'Analyzing EVA project files', detail: `Loaded ${currentUpdate.id} ${currentUpdate.title} from current admin update state.` },
    { title: 'Selecting patch scope', detail: `${selectedPatchScope.label}: ${selectedPatchScope.description}` },
    { title: 'Tracking changed files', detail: updateSummary },
    { title: 'Waiting for admin review', detail: approvalStatuses[approvalStatus]?.note || approvalStatuses['Pending Review'].note },
  ];

  const logItems = [
    ...changedFiles.map((file) => `Editing ${file.file}`),
    `Current update status: ${currentUpdate.status}`,
    `Approval status: ${approvalStatus}`,
    `Patch scope: ${selectedPatchScope.label}`,
  ];

  const renderInspectionOverview = () => {
    if (inspection.loading) {
      return <div style={ui.inspectionNotice}>Loading admin inspection...</div>;
    }
    if (inspection.error) {
      return <div style={{ ...ui.inspectionNotice, ...ui.inspectionError }}>Admin inspection backend unavailable.</div>;
    }

    const status = inspection.status || {};
    const project = inspection.project || {};
    const health = inspection.health || {};

    return (
      <div className="update-inspection-grid" style={ui.inspectionGrid}>
        <section style={ui.inspectionCard}>
          <div style={ui.inspectionTitle}>Current Update</div>
          <div style={ui.inspectionValue}>Update {status.current_update || currentUpdate.id}</div>
          <div style={ui.inspectionText}>{status.name || currentUpdate.title}</div>
          <div style={ui.inspectionText}>Mode: {status.mode || 'admin_only'}</div>
        </section>
        <section style={ui.inspectionCard}>
          <div style={ui.inspectionTitle}>Backend Health</div>
          <div style={ui.inspectionValue}>{health.backend || 'unknown'}</div>
          <div style={ui.inspectionText}>Docs: {health.docs || '/api/docs'}</div>
          <div style={ui.inspectionText}>RAG: {health.rag_status || '/api/rag/status'}</div>
        </section>
        <section style={ui.inspectionCard}>
          <div style={ui.inspectionTitle}>Project Inspection</div>
          <div style={ui.inspectionText}>Frontend: {boolLabel(project.frontend_exists)}</div>
          <div style={ui.inspectionText}>Backend: {boolLabel(project.backend_exists)}</div>
          <div style={ui.inspectionText}>Routes: {project.current_routes_count || 0}</div>
        </section>
        <section style={ui.inspectionCard}>
          <div style={ui.inspectionTitle}>Safety Status</div>
          <div style={ui.inspectionText}>Patch execution: Disabled</div>
          <div style={ui.inspectionText}>Patch scope: {selectedPatchScope.label}</div>
          <div style={ui.inspectionText}>Terminal execution: Disabled</div>
          <div style={ui.inspectionText}>Secrets access: Blocked</div>
          <div style={ui.inspectionText}>User data access: Blocked</div>
        </section>
      </div>
    );
  };

  const renderProjectDetails = () => {
    if (inspection.loading) return <div style={ui.inspectionNotice}>Loading project inspection...</div>;
    if (inspection.error) return <div style={{ ...ui.inspectionNotice, ...ui.inspectionError }}>Admin inspection backend unavailable.</div>;
    const project = inspection.project || {};
    return (
      <div style={ui.fileDetail}>
        <div style={ui.detailRow}><span>Frontend exists</span><strong>{boolLabel(project.frontend_exists)}</strong></div>
        <div style={ui.detailRow}><span>Backend exists</span><strong>{boolLabel(project.backend_exists)}</strong></div>
        <div style={ui.detailRow}><span>package.json</span><strong>{boolLabel(project.package_json_exists)}</strong></div>
        <div style={ui.detailRow}><span>src/app.py</span><strong>{boolLabel(project.app_py_exists)}</strong></div>
        <div style={ui.detailRow}><span>API routes</span><strong>{project.current_routes_count || 0}</strong></div>
        <div style={ui.detailRow}><span>RAG status</span><strong>{project.rag_status_available ? 'Available' : 'Unavailable'}</strong></div>
        <div style={ui.detailRow}><span>Swagger docs</span><strong>{project.docs_available ? 'Available' : 'Unavailable'}</strong></div>
      </div>
    );
  };

  const renderBackendHealth = () => {
    if (inspection.loading) return <div style={ui.inspectionNotice}>Loading backend health...</div>;
    if (inspection.error) return <div style={{ ...ui.inspectionNotice, ...ui.inspectionError }}>Admin inspection backend unavailable.</div>;
    const health = inspection.health || {};
    const status = inspection.status || {};
    return (
      <div style={ui.fileDetail}>
        <div style={ui.detailRow}><span>Backend</span><strong>{health.backend || 'unknown'}</strong></div>
        <div style={ui.detailRow}><span>Docs</span><strong>{health.docs || '/api/docs'}</strong></div>
        <div style={ui.detailRow}><span>RAG status</span><strong>{health.rag_status || '/api/rag/status'}</strong></div>
        <div style={ui.detailRow}><span>Updated</span><strong>{health.timestamp || 'unknown'}</strong></div>
        <div style={ui.detailRow}><span>Patch execution</span><strong>{status.patch_execution || 'disabled'}</strong></div>
        <div style={ui.detailRow}><span>Scope mode</span><strong>{status.patch_scope_mode || 'manual_selection_only'}</strong></div>
        <div style={ui.detailRow}><span>Terminal execution</span><strong>{status.terminal_execution || 'disabled'}</strong></div>
        <div style={ui.detailRow}><span>Selected scope</span><strong>{selectedPatchScope.label}</strong></div>
      </div>
    );
  };

  const renderScopeSelector = () => (
    <div style={ui.scopePanel}>
      <div style={ui.scopeHeader}>
        <div>
          <h4 style={ui.reviewSectionTitle}>Auto Patch Scope</h4>
          <p style={ui.scopeCopy}>Scope selection is for future approved patch proposals only. No patch can run from this panel.</p>
        </div>
        <span style={ui.scopeBadge}>Execution disabled</span>
      </div>
      <div style={ui.scopeGrid}>
        {patchScopes.map((scope) => (
          <button
            key={scope.id}
            type="button"
            onClick={() => choosePatchScope(scope)}
            style={selectedPatchScope.id === scope.id ? { ...ui.scopeButton, ...ui.scopeButtonActive } : ui.scopeButton}
          >
            <strong>{scope.label}</strong>
            <span>{scope.description}</span>
          </button>
        ))}
      </div>
    </div>
  );

  const activePanel = () => {
    if (activeTool === 'Scope') {
      return (
        <div style={ui.toolContent}>
          <h3 style={ui.toolTitle}>Scope Selector</h3>
          <p style={ui.toolText}>Choose the boundary EVA should respect when a future admin-approved patch flow exists.</p>
          {renderScopeSelector()}
        </div>
      );
    }
    if (activeTool === 'Terminal') {
      return <ToolMessage title="Terminal" body="Terminal preview only. Backend command execution is disabled in 43B." />;
    }
    if (activeTool === 'Browser') {
      return <ToolMessage title="Browser" body="Browser preview not enabled yet." />;
    }
    if (activeTool === 'Side chat') {
      return <ToolMessage title="Side chat" body="Ask EVA about this update." />;
    }
    if (activeTool === 'Files') {
      return (
        <div style={ui.toolContent}>
          <h3 style={ui.toolTitle}>EVA Changed Files</h3>
          <div style={ui.currentUpdateStrip}>
            <strong>Update {currentUpdate.id}</strong>
            <span>{currentUpdate.title}</span>
            <em>{currentUpdate.status}</em>
          </div>
          <div style={ui.fileList}>
            {changedFiles.map((file) => (
              <button key={file.file} type="button" onClick={() => openFile(file)} style={selectedFile.file === file.file ? { ...ui.fileButton, ...ui.fileButtonActive } : ui.fileButton}>
                <span>{file.file}</span>
                <small>{file.status}</small>
              </button>
            ))}
          </div>
          <FileDetail file={selectedFile} update={currentUpdate} approvalStatus={approvalStatus} selectedPatchScope={selectedPatchScope} />
        </div>
      );
    }
    const approvalMeta = approvalStatuses[approvalStatus] || approvalStatuses['Pending Review'];
    return (
      <div style={ui.toolContent}>
        <h3 style={ui.toolTitle}>Approval Workflow</h3>
        <div style={{ ...ui.approvalBadge, color: approvalMeta.tone, borderColor: `${approvalMeta.tone}66`, background: `${approvalMeta.tone}14` }}>
          Approval: {approvalStatus}
        </div>
        <p style={ui.toolText}>{approvalMeta.note}</p>
        <div style={ui.reviewSummary}>{updateSummary}</div>
        <section style={ui.reviewSection}>
          {renderScopeSelector()}
        </section>
        <section style={ui.reviewSection}>
          <h4 style={ui.reviewSectionTitle}>Backend Health</h4>
          {renderBackendHealth()}
        </section>
        <section style={ui.reviewSection}>
          <h4 style={ui.reviewSectionTitle}>Project Inspection</h4>
          {renderProjectDetails()}
        </section>
        <section style={ui.reviewSection}>
          <h4 style={ui.reviewSectionTitle}>Safety Status</h4>
          <div style={ui.fileDetail}>
            <div style={ui.detailRow}><span>Patch execution</span><strong>Disabled</strong></div>
            <div style={ui.detailRow}><span>Selected scope</span><strong>{selectedPatchScope.label}</strong></div>
            <div style={ui.detailRow}><span>Terminal execution</span><strong>Disabled</strong></div>
            <div style={ui.detailRow}><span>Secrets access</span><strong>Blocked</strong></div>
            <div style={ui.detailRow}><span>User data access</span><strong>Blocked</strong></div>
          </div>
        </section>
        <div style={ui.approvalActions}>
          <button type="button" onClick={() => setApproval('Approved')} style={{ ...ui.approvalButton, ...ui.approveButton }}>Approve</button>
          <button type="button" onClick={() => setApproval('Rejected')} style={{ ...ui.approvalButton, ...ui.rejectButton }}>Reject</button>
          <button type="button" onClick={() => setApproval('Needs Changes')} style={{ ...ui.approvalButton, ...ui.needsButton }}>Needs Changes</button>
        </div>
        <section style={ui.reviewSection}>
          <h4 style={ui.reviewSectionTitle}>EVA Changed Files</h4>
          <div style={ui.fileList}>
            {changedFiles.map((file) => (
              <button key={file.file} type="button" onClick={() => openFile(file)} style={ui.fileButton}>
                <span>{file.file}</span>
                <small>{file.change}</small>
              </button>
            ))}
          </div>
        </section>
        <div style={ui.historyPanel}>
          <div style={ui.historyTitle}>Approval activity</div>
          {approvalHistory.length === 0 ? (
            <div style={ui.historyEmpty}>No approval action yet.</div>
          ) : approvalHistory.map((item) => (
            <div key={item.id} style={ui.historyItem}>
              <span>{item.text}</span>
              <small>{item.time}</small>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <section className="update-workspace-page" style={ui.workspacePage}>
      <style>{`
        @media (max-width: 980px) {
          .update-workspace-shell { grid-template-columns: 1fr !important; }
          .update-tool-shell { min-height: 420px !important; }
        }
        @media (max-width: 620px) {
          .update-workspace-page { padding: 14px !important; }
          .update-tool-shell { grid-template-columns: 1fr !important; }
          .update-tool-menu { flex-direction: row !important; overflow-x: auto !important; border-right: 0 !important; border-bottom: 1px solid var(--border) !important; }
          .update-inspection-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>

      <div className="update-workspace-shell" style={ui.workspaceShell}>
        <section style={ui.activityPane}>
          <div style={ui.workspaceTop}>
            <span style={ui.codexMark}><Sparkles size={17} /></span>
            <div>
              <div style={ui.kicker}>Update Intelligence</div>
              <h1 style={ui.workspaceTitle}>Update {currentUpdate.id}</h1>
              <p style={ui.workspaceSubtitle}>Admin code-change workspace</p>
            </div>
          </div>

          <div style={ui.taskCard}>
            <div style={ui.taskTitle}>{currentUpdate.title}</div>
            <div style={ui.taskMeta}>Status: {currentUpdate.status}. Scope: {currentUpdate.scope}. No backend file writing, terminal execution, or automatic patching.</div>
            <div style={ui.adminWorkspaceNote}>Admin EVA development workspace. Changes affect EVA only after rebuild/deploy.</div>
          </div>

          {renderInspectionOverview()}

          <div style={ui.timeline}>
            {activityItems.map((item, index) => (
              <article key={item.title} style={ui.timelineItem}>
                <div style={ui.timelineDot}>{index + 1}</div>
                <div>
                  <h2 style={ui.timelineTitle}>{item.title}</h2>
                  <p style={ui.timelineText}>{item.detail}</p>
                </div>
              </article>
            ))}
          </div>

          <div style={ui.logPanel}>
            {logItems.map((log) => (
              <div key={log} style={ui.logLine}>
                <span style={ui.logBullet} />
                {log}
              </div>
            ))}
            {approvalHistory.map((item) => (
              <div key={item.id} style={ui.logLine}>
                <span style={{ ...ui.logBullet, background: (approvalStatuses[approvalStatus] || approvalStatuses['Pending Review']).tone }} />
                {item.text}
              </div>
            ))}
          </div>

          <div style={ui.changedFooter}>
            <button type="button" onClick={() => openFile(changedFiles[0])} style={ui.changedFileLink}>
              {changedFiles[0].file}
            </button>
            <span style={ui.changeStat}>{updateSummary}</span>
          </div>

          <button type="button" onClick={() => selectTool('Review')} style={ui.reviewButton}>
            Review
          </button>
          <span style={{ ...ui.compactStatus, color: (approvalStatuses[approvalStatus] || approvalStatuses['Pending Review']).tone }}>
            Approval: {approvalStatus}
          </span>
        </section>

        <aside className="update-tool-shell" style={ui.toolShell}>
          <nav className="update-tool-menu" style={ui.toolMenu} aria-label="Update workspace tools">
            {updateTools.map((tool) => (
              <button key={tool} type="button" onClick={() => selectTool(tool)} style={activeTool === tool ? { ...ui.toolButton, ...ui.toolButtonActive } : ui.toolButton}>
                {tool}
              </button>
            ))}
          </nav>
          <section style={ui.toolPanel}>
            {activePanel()}
            <div style={ui.followupBox}>
              <input disabled placeholder="Ask for follow-up changes" style={ui.followupInput} />
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}

function ToolMessage({ title, body }) {
  return (
    <div style={ui.toolContent}>
      <h3 style={ui.toolTitle}>{title}</h3>
      <p style={ui.toolText}>{body}</p>
    </div>
  );
}

function FileDetail({ file, update, approvalStatus, selectedPatchScope }) {
  const approvalMeta = approvalStatuses[approvalStatus] || approvalStatuses['Pending Review'];
  return (
    <div style={ui.fileDetail}>
      <div style={ui.detailRow}><span>Current Update</span><strong>{update.id}</strong></div>
      <div style={ui.detailRow}><span>Update Title</span><strong>{update.title}</strong></div>
      <div style={ui.detailRow}><span>Update Status</span><strong>{update.status}</strong></div>
      <div style={ui.detailRow}><span>File path</span><strong>{file.file}</strong></div>
      <div style={ui.detailRow}><span>Change summary</span><strong>{file.change}</strong></div>
      <div style={ui.detailRow}><span>Status</span><strong>{file.status}</strong></div>
      <div style={ui.detailRow}><span>Added lines</span><strong>+{file.added}</strong></div>
      <div style={ui.detailRow}><span>Removed lines</span><strong>-{file.removed}</strong></div>
      <div style={ui.detailRow}><span>Review Status</span><strong>{approvalStatus}</strong></div>
      <div style={ui.detailRow}><span>Patch Scope</span><strong>{selectedPatchScope?.label || 'Review only'}</strong></div>
      <div style={ui.detailRow}><span>Patch Execution</span><strong>Disabled</strong></div>
      <div style={ui.detailRow}><span>Admin Approval Required</span><strong>Yes</strong></div>
      <div style={{ ...ui.fileStatusNote, borderColor: `${approvalMeta.tone}55`, color: approvalMeta.tone }}>
        {approvalMeta.note}
      </div>
    </div>
  );
}

function FloatingNotifications() {
  const [eventToasts, setEventToasts] = useState([]);
  const storedUser = getStoredAdminUser();
  const isAdmin = isUpdateWorkspaceAdmin(storedUser);

  useEffect(() => {
    const onToast = (event) => {
      const detail = event.detail || {};
      if (detail.adminOnly && !isAdmin) return;
      if (!detail.message) return;
      const toast = { id: detail.id || `toast-${Date.now()}`, message: detail.message };
      setEventToasts((current) => [toast, ...current.filter((item) => item.id !== toast.id)].slice(0, 4));
      setTimeout(() => {
        setEventToasts((current) => current.filter((item) => item.id !== toast.id));
      }, detail.duration || 6500);
    };

    window.addEventListener('eva:toast', onToast);
    return () => window.removeEventListener('eva:toast', onToast);
  }, [isAdmin]);

  if (!eventToasts.length) return null;

  return (
    <div style={ui.toastStack} aria-live="polite">
      {eventToasts.map((item) => (
        <div key={item.id} style={ui.toast}>
          <span style={ui.toastDot} />
          <span style={ui.toastText}>{item.message}</span>
          <button type="button" onClick={() => setEventToasts((current) => current.filter((toast) => toast.id !== item.id))} style={ui.toastClose} aria-label="Dismiss notification">
            x
          </button>
        </div>
      ))}
    </div>
  );
}

const ui = {
  workspacePage: { minHeight: '100%', padding: 18, color: 'var(--text, var(--text))', overflow: 'auto', background: 'radial-gradient(circle at top left, rgba(59,130,246,.12), transparent 34%), rgba(2,6,23,.18)' },
  workspaceShell: { display: 'grid', gridTemplateColumns: '45% minmax(0, 1fr)', gap: 14, minHeight: 'calc(100vh - 132px)' },
  activityPane: { display: 'flex', flexDirection: 'column', gap: 14, border: '1px solid var(--border)', borderRadius: 8, background: 'linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.92))', boxShadow: '0 22px 70px rgba(2,6,23,.36)', padding: 16 },
  workspaceTop: { display: 'flex', alignItems: 'center', gap: 12 },
  codexMark: { width: 36, height: 36, borderRadius: 8, display: 'grid', placeItems: 'center', border: '1px solid var(--border)', background: 'rgba(15,23,42,.9)', color: 'var(--info-text)' },
  kicker: { color: 'var(--info-text)', fontSize: 11, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '.08em' },
  workspaceTitle: { margin: '3px 0 2px', fontSize: 24, lineHeight: 1.12, color: 'var(--text)' },
  workspaceSubtitle: { margin: 0, color: 'var(--text3)', fontSize: 13 },
  taskCard: { border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(15,23,42,.58)', padding: 13 },
  taskTitle: { color: 'var(--text)', fontSize: 15, fontWeight: 850 },
  taskMeta: { marginTop: 6, color: 'var(--text3)', fontSize: 12, lineHeight: 1.5 },
  adminWorkspaceNote: { marginTop: 9, padding: 9, borderRadius: 8, border: '1px solid rgba(96,165,250,.24)', background: 'rgba(37,99,235,.1)', color: 'var(--info-text)', fontSize: 12, lineHeight: 1.45 },
  inspectionGrid: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 },
  inspectionCard: { minHeight: 116, border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(2,6,23,.34)', padding: 12 },
  inspectionTitle: { color: 'var(--info-text)', fontSize: 11, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 },
  inspectionValue: { color: 'var(--text)', fontSize: 16, fontWeight: 900, marginBottom: 6 },
  inspectionText: { color: 'var(--text3)', fontSize: 12, lineHeight: 1.45, marginTop: 3 },
  inspectionNotice: { border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(15,23,42,.46)', color: 'var(--text2)', padding: 12, fontSize: 12, lineHeight: 1.45 },
  inspectionError: { borderColor: 'rgba(248,113,113,.28)', background: 'rgba(127,29,29,.16)', color: 'var(--danger-text)' },
  timeline: { display: 'grid', gap: 10 },
  timelineItem: { display: 'grid', gridTemplateColumns: '28px 1fr', gap: 10, alignItems: 'start', padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(15,23,42,.42)' },
  timelineDot: { width: 24, height: 24, borderRadius: 999, display: 'grid', placeItems: 'center', background: 'rgba(37,99,235,.22)', color: 'var(--info-text)', fontSize: 11, fontWeight: 900, border: '1px solid rgba(96,165,250,.3)' },
  timelineTitle: { margin: 0, color: 'var(--text2)', fontSize: 13 },
  timelineText: { margin: '4px 0 0', color: 'var(--text3)', fontSize: 12, lineHeight: 1.45 },
  logPanel: { display: 'grid', gap: 8, border: '1px solid var(--border)', borderRadius: 8, padding: 12, background: 'rgba(2,6,23,.48)', fontFamily: 'var(--mono, Consolas, monospace)' },
  logLine: { display: 'flex', alignItems: 'center', gap: 9, color: 'var(--text2)', fontSize: 12 },
  logBullet: { width: 7, height: 7, borderRadius: 999, background: 'var(--green)', boxShadow: '0 0 16px rgba(34,197,94,.48)' },
  changedFooter: { marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', borderTop: '1px solid var(--border)', paddingTop: 12 },
  changedFileLink: { border: 0, background: 'transparent', color: 'var(--info-text)', fontFamily: 'var(--mono, Consolas, monospace)', fontSize: 12, cursor: 'pointer', padding: 0, textAlign: 'left' },
  changeStat: { color: 'var(--text2)', fontSize: 12, fontWeight: 800 },
  reviewButton: { alignSelf: 'flex-start', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minHeight: 36, padding: '8px 14px', borderRadius: 8, border: '1px solid rgba(96,165,250,.4)', background: 'rgba(37,99,235,.28)', color: 'var(--info-text)', fontWeight: 850, cursor: 'pointer' },
  compactStatus: { alignSelf: 'flex-start', fontSize: 11, fontWeight: 850, border: '1px solid var(--border)', borderRadius: 999, padding: '4px 9px', background: 'rgba(15,23,42,.52)' },
  toolShell: { display: 'grid', gridTemplateColumns: '132px 1fr', minHeight: 560, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'rgba(2,6,23,.78)', boxShadow: '0 22px 70px rgba(2,6,23,.28)' },
  toolMenu: { display: 'flex', flexDirection: 'column', gap: 6, padding: 10, borderRight: '1px solid var(--border)', background: 'rgba(15,23,42,.54)' },
  toolButton: { width: '100%', padding: '9px 10px', borderRadius: 8, border: '1px solid transparent', background: 'transparent', color: 'var(--text3)', fontSize: 12, fontWeight: 800, textAlign: 'left', cursor: 'pointer' },
  toolButtonActive: { borderColor: 'rgba(96,165,250,.38)', background: 'rgba(37,99,235,.2)', color: 'var(--text)' },
  toolPanel: { display: 'flex', flexDirection: 'column', minWidth: 0 },
  toolContent: { padding: 16, flex: 1 },
  toolTitle: { margin: 0, color: 'var(--text)', fontSize: 16 },
  toolText: { margin: '10px 0 0', color: 'var(--text3)', fontSize: 13, lineHeight: 1.55 },
  reviewSummary: { marginTop: 14, padding: 12, borderRadius: 8, border: '1px solid rgba(34,197,94,.24)', background: 'rgba(34,197,94,.08)', color: 'var(--success-text)', fontFamily: 'var(--mono, Consolas, monospace)', fontSize: 12, fontWeight: 850 },
  reviewSection: { marginTop: 14 },
  reviewSectionTitle: { margin: '0 0 8px', color: 'var(--text2)', fontSize: 12, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '.05em' },
  scopePanel: { border: '1px solid var(--border)', borderRadius: 8, padding: 12, background: 'rgba(15,23,42,.36)' },
  scopeHeader: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 10 },
  scopeCopy: { margin: 0, color: 'var(--text3)', fontSize: 12, lineHeight: 1.45 },
  scopeBadge: { flexShrink: 0, border: '1px solid rgba(248,113,113,.28)', borderRadius: 999, background: 'rgba(127,29,29,.16)', color: 'var(--danger-text)', padding: '5px 8px', fontSize: 10, fontWeight: 900, textTransform: 'uppercase' },
  scopeGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 },
  scopeButton: { display: 'grid', gap: 5, minHeight: 86, padding: 10, borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(2,6,23,.38)', color: 'var(--text2)', textAlign: 'left', cursor: 'pointer' },
  scopeButtonActive: { borderColor: 'rgba(96,165,250,.52)', background: 'rgba(37,99,235,.18)', boxShadow: 'inset 0 0 0 1px rgba(96,165,250,.14)' },
  approvalBadge: { display: 'inline-flex', alignItems: 'center', minHeight: 28, padding: '5px 10px', borderRadius: 999, border: '1px solid', fontSize: 11, fontWeight: 900, textTransform: 'uppercase' },
  approvalActions: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  approvalButton: { minHeight: 32, borderRadius: 8, padding: '7px 10px', fontSize: 12, fontWeight: 850, cursor: 'pointer' },
  approveButton: { border: '1px solid rgba(34,197,94,.34)', background: 'rgba(34,197,94,.12)', color: 'var(--success-text)' },
  rejectButton: { border: '1px solid rgba(248,113,113,.34)', background: 'rgba(248,113,113,.1)', color: 'var(--danger-text)' },
  needsButton: { border: '1px solid rgba(96,165,250,.38)', background: 'rgba(37,99,235,.14)', color: 'var(--info-text)' },
  historyPanel: { marginTop: 14, border: '1px solid var(--border)', borderRadius: 8, padding: 12, background: 'rgba(15,23,42,.34)' },
  historyTitle: { color: 'var(--text2)', fontSize: 12, fontWeight: 900, marginBottom: 8 },
  historyEmpty: { color: 'var(--text3)', fontSize: 12 },
  historyItem: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, color: 'var(--text2)', fontSize: 12, padding: '6px 0', borderTop: '1px solid var(--border)' },
  fileList: { display: 'grid', gap: 8, marginTop: 14 },
  fileButton: { display: 'grid', gap: 3, width: '100%', padding: 11, borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(15,23,42,.52)', color: 'var(--text2)', textAlign: 'left', cursor: 'pointer', fontFamily: 'var(--mono, Consolas, monospace)', fontSize: 12 },
  fileButtonActive: { borderColor: 'rgba(96,165,250,.42)', background: 'rgba(37,99,235,.18)' },
  fileDetail: { display: 'grid', gap: 8, marginTop: 14, border: '1px solid var(--border)', borderRadius: 8, padding: 12, background: 'rgba(15,23,42,.38)' },
  detailRow: { display: 'grid', gridTemplateColumns: '120px 1fr', gap: 12, color: 'var(--text3)', fontSize: 12 },
  fileStatusNote: { marginTop: 5, border: '1px solid', borderRadius: 8, padding: 10, background: 'rgba(15,23,42,.5)', fontSize: 12, fontWeight: 800 },
  followupBox: { borderTop: '1px solid var(--border)', padding: 12, background: 'rgba(15,23,42,.36)' },
  followupInput: { width: '100%', minHeight: 38, borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(2,6,23,.72)', color: 'var(--text3)', padding: '0 12px', fontSize: 13 },
  toastStack: { position: 'fixed', top: 78, right: 18, zIndex: 80, display: 'grid', gap: 10, maxWidth: 'min(360px, calc(100vw - 32px))', pointerEvents: 'none' },
  toast: { display: 'grid', gridTemplateColumns: '8px 1fr auto', alignItems: 'center', gap: 10, padding: '11px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'linear-gradient(145deg, rgba(15,23,42,.94), rgba(2,6,23,.92))', color: 'var(--text2)', boxShadow: '0 18px 52px rgba(2,6,23,.34)', pointerEvents: 'auto', backdropFilter: 'blur(14px)' },
  toastDot: { width: 8, height: 8, borderRadius: 999, background: 'var(--green)', boxShadow: '0 0 18px rgba(34,197,94,.5)' },
  toastText: { fontSize: 12, lineHeight: 1.45 },
  toastClose: { border: 0, background: 'transparent', color: 'var(--text3)', fontSize: 18, lineHeight: 1, cursor: 'pointer', padding: '0 2px' },
};

export default function App() {
  return (
    <ThemeProvider>
      <EvaApp />
    </ThemeProvider>
  );
}

function EvaApp() {
  ensureLocalAuth();

  const [loggedIn, setLoggedIn] = useState(true);
  const [adminUnlocked, setAdminUnlocked] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState('general');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const openSettings = (section = 'general') => {
    setSettingsSection(section || 'general');
    setSettingsOpen(true);
    if (isMobile) setSidebarOpen(false);
  };

  const closeMobileSidebar = () => {
    if (isMobile) setSidebarOpen(false);
  };

  if (isAdminPort() && !IS_ADMIN_WORKSPACE) return <AdminWorkspaceDisabled />;
  if (IS_ADMIN_WORKSPACE && !adminUnlocked) return <LocalAdminGate onUnlock={() => setAdminUnlocked(true)} />;
  if (!loggedIn && !IS_ADMIN_WORKSPACE) return <Login onLogin={() => setLoggedIn(true)} />;

  return (
    <GoogleOAuthProvider clientId="672306485076-4ju3digd9umndg2v40m3fv4vmcr37bg0.apps.googleusercontent.com">
      <HashRouter>
        <Routes>
          <Route path="/" element={<Navigate to={IS_ADMIN_WORKSPACE ? '/update-intelligence' : '/chat'} replace />} />
          <Route path="/features" element={<LandingPage focus="features" />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/contact" element={<ContactPage />} />

          {/* Login page â€” no sidebar, no topbar */}
          <Route path="/login" element={IS_ADMIN_WORKSPACE ? <Navigate to="/update-intelligence" replace /> : <Login />} />
          <Route path="/signup" element={IS_ADMIN_WORKSPACE ? <Navigate to="/update-intelligence" replace /> : <Login initialScreen="signup" />} />

          {/* All other pages â€” with sidebar + topbar */}
          <Route path="/*" element={
            <div className={`eva-app-shell ${sidebarOpen ? 'is-sidebar-open' : ''}`}>
              {isMobile && sidebarOpen && <div className="eva-sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}

              <div className="eva-sidebar-region">
                <Sidebar onOpenSettings={openSettings} onNavigate={closeMobileSidebar} adminMode={IS_ADMIN_WORKSPACE} />
              </div>

              <div className="eva-main-region">
                <Topbar
                  API={API}
                  onLogout={() => setLoggedIn(false)}
                  onOpenSettings={openSettings}
                  onMenuClick={() => setSidebarOpen(o => !o)}
                  isMobile={isMobile}
                />
                <main className="eva-route-surface">
                <Routes>
                  <Route path="/" element={<Navigate to="/chat" replace />} />
                  <Route path="/app" element={<Navigate to="/chat" replace />} />

                  {/* User + Admin */}
                  <Route
                    path="/chat"
                    element={
                      <AuthGuard>
                        <Chat API={API} onOpenSettings={openSettings} />
                      </AuthGuard>
                    }
                  />

                  {/* Admin only */}
                  <Route
                    path="/upload"
                    element={
                      <AuthGuard adminOnly>
                        <Upload API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/knowledge"
                    element={
                      <AuthGuard>
                        <Upload API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/support"
                    element={
                      <AuthGuard>
                        <Support />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/code-workspace"
                    element={
                      <AuthGuard adminOnly>
                        <CodeAssistant API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/code-assistant"
                    element={
                      <AuthGuard adminOnly>
                        <CodeAssistant API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/skill-creator"
                    element={
                      <AuthGuard>
                        <SkillCreator />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/canvas-design"
                    element={
                      <AuthGuard>
                        <CanvasDesign />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/cad-studio"
                    element={
                      <AuthGuard>
                        <CADStudio />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/theme-factory"
                    element={
                      <AuthGuard>
                        <ThemeFactory />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/vision"
                    element={
                      <AuthGuard>
                        <Chat API={API} onOpenSettings={openSettings} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/memory"
                    element={
                      <AuthGuard>
                        <MemoryCenter API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/agent-center"
                    element={
                      <AuthGuard>
                        <AgentCenter API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/agent-studio"
                    element={
                      <AuthGuard>
                        <AIStudio API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/freelance"
                    element={
                      <AuthGuard>
                        <AIStudio API={API} initialTab="Client Jobs" />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/ai-studio"
                    element={
                      <AuthGuard>
                        <AIStudio API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/marketplace"
                    element={
                      <AuthGuard>
                        <AgentMarketplace API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/agent/:slug"
                    element={
                      <AuthGuard>
                        <AgentMarketplace API={API} shareMode />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/published-agents"
                    element={
                      <AuthGuard>
                        <PublishedAgents API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/run-center"
                    element={
                      <AuthGuard>
                        <RunCenter API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/team"
                    element={
                      <AuthGuard>
                        <TeamWorkspace API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/analytics"
                    element={
                      <AuthGuard>
                        <AnalyticsDashboard API={API} />
                      </AuthGuard>
                    }
                  />

                  {/* Slice 3: display-only billing page. BillingCenter (live
                      /billing/* API dashboard) is intentionally unmounted until
                      paid plans + real billing endpoints launch. */}
                  <Route
                    path="/billing"
                    element={
                      <AuthGuard>
                        <Billing />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/studio"
                    element={
                      <AuthGuard adminOnly>
                        <Studio />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/ml"
                    element={
                      <AuthGuard>
                        <ML API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/settings"
                    element={<Navigate to="/chat" replace />}
                  />

                  <Route
                    path="/security"
                    element={
                      <AuthGuard adminOnly>
                        <SecurityDashboard API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/security-center"
                    element={
                      <AuthGuard adminOnly>
                        <SecurityCenter API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/update-intelligence"
                    element={IS_ADMIN_WORKSPACE ? (
                      <AuthGuard adminOnly>
                        <UpdateIntelligencePage />
                      </AuthGuard>
                    ) : <Navigate to="/chat" replace />}
                  />

                  <Route
                    path="/rag"
                    element={
                      <AuthGuard>
                        <RAGCenter API={API} />
                      </AuthGuard>
                    }
                  />

                  <Route
                    path="/threats"
                    element={
                      <AuthGuard adminOnly>
                        <ThreatMonitor />
                      </AuthGuard>
                    }
                  />
                  <Route
                    path="/agent"
                    element={
                      <AuthGuard adminOnly>
                        <AgentPanel />
                      </AuthGuard>
                    }
                  />

                  <Route path="*" element={<Navigate to="/chat" replace />} />
                </Routes>
                </main>
              </div>
              <FloatingNotifications />
              <SettingsModal
                API={API}
                open={settingsOpen}
                onClose={() => setSettingsOpen(false)}
                initialSection={settingsSection}
              />
            </div>
          } />
        </Routes>
      </HashRouter>
    </GoogleOAuthProvider>
  );
}

