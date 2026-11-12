import { useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { Menu } from 'lucide-react';
import { RAG_API_BASE_URL } from '../lib/apiConfig';
const titles = {
  '/chat': ['Chat', 'EVA / chat'],
  '/knowledge': ['Files', 'EVA / files'],
  '/code-assistant': ['Code Workspace', 'EVA / code'],
  '/code-workspace': ['Code Workspace', 'EVA / code'],
  '/vision': ['Vision', 'EVA / vision'],
  '/security': ['Security Center', 'EVA / security'],
  '/update-intelligence': ['Update Intelligence', 'EVA / admin'],
  '/agent-center': ['Agents', 'EVA / agents'],
  '/agent-studio': ['Agents', 'EVA / agents'],
  '/ai-studio': ['Agents', 'EVA / agents'],
  '/marketplace': ['Marketplace', 'EVA / marketplace'],
  '/published-agents': ['Published Agents', 'EVA / published'],
  '/run-center': ['Run Center', 'EVA / runs'],
  '/memory': ['History', 'EVA / history'],
  '/team': ['Team', 'EVA / team'],
  '/analytics': ['Analytics', 'EVA / analytics'],
  '/billing': ['Billing Center', 'EVA / billing'],
  '/upload': ['Files', 'EVA / upload'],
  '/studio': ['Studio', 'EVA / studio'],
  '/ml': ['ML Playground', 'EVA / ml'],
};

const HEALTH_STATE = {
  UNKNOWN: 'UNKNOWN',
  CHECKING: 'CHECKING',
  ONLINE: 'ONLINE',
  // Some recent answers failed but not all â€” a provider hiccup with successful
  // retries is not an outage, and flapping straight to Offline on one blip
  // teaches people to ignore the indicator.
  DEGRADED: 'DEGRADED',
  OFFLINE: 'OFFLINE',
};

export default function Topbar({ API, onMenuClick, isMobile, onOpenSettings, onLogout }) {
  const { pathname } = useLocation();
  
  // Two REAL statuses, labeled distinctly. "Backend" = the main API (Render);
  // "AI" = the HF ML/RAG service Chat actually talks to. Never conflate them.
  const [backendHealth, setBackendHealth] = useState(HEALTH_STATE.UNKNOWN);
  const [aiHealth, setAiHealth] = useState(HEALTH_STATE.UNKNOWN);
  // Specific cause, surfaced in the tooltip instead of a generic error.
  const [, setAiReason] = useState('');
  const [title] = titles[pathname] || (pathname.startsWith('/agent/')
    ? ['Published Agent', 'EVA / marketplace']
    : ['EVA', 'EVA']);


  useEffect(() => {
    let cancelled = false;

    // Same strict status criteria + timeout for every health check, so two
    // indicators can never disagree about the same service.
    const healthStatus = async (base, path) => {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 8000);
      try {
        const res = await fetch(`${base}${path}`, {
          headers: { 'ngrok-skip-browser-warning': 'true' },
          signal: controller.signal,
        });
        clearTimeout(tid);
        return res.status === 200 ? HEALTH_STATE.ONLINE : HEALTH_STATE.OFFLINE;
      } catch (err) {
        clearTimeout(tid);
        console.error(err);
        return HEALTH_STATE.OFFLINE;
      }
    };

    const RAG_API = RAG_API_BASE_URL;

    // The AI indicator used to poll the ML service's /health, which returns
    // {"status":"ok"} whenever the process is alive. It therefore read
    // "AI Online" throughout the 2026-07-31 provider-quota outage, while every
    // answer came back "The AI service is temporarily unavailable".
    //
    // It now reads ai_status from the backend, which reports what real chat
    // requests actually did. Reachability of the ML process is still necessary
    // but not sufficient, so a transport failure there still forces Offline.
    const aiPathStatus = async () => {
      if (!API) return { state: HEALTH_STATE.OFFLINE, reason: 'no backend configured' };
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 8000);
      try {
        const res = await fetch(`${API}/api/health`, {
          headers: { 'ngrok-skip-browser-warning': 'true' },
          signal: controller.signal,
        });
        clearTimeout(tid);
        if (res.status !== 200) return { state: HEALTH_STATE.OFFLINE, reason: `backend HTTP ${res.status}` };
        const data = await res.json().catch(() => ({}));
        // Older backends have no ai_status. Treat their reachability as online
        // so this stays backward compatible during a rolling deploy.
        const reported = String(data.ai_status || 'unknown').toLowerCase();
        const reason = String(data.ai_reason || '');
        if (reported === 'offline') return { state: HEALTH_STATE.OFFLINE, reason };
        if (reported === 'degraded') return { state: HEALTH_STATE.DEGRADED, reason };
        return { state: HEALTH_STATE.ONLINE, reason: '' };
      } catch (err) {
        clearTimeout(tid);
        return { state: HEALTH_STATE.OFFLINE, reason: 'backend unreachable' };
      }
    };

    const checkHealth = async () => {
      if (!cancelled) {
        setBackendHealth(HEALTH_STATE.CHECKING);
        setAiHealth(HEALTH_STATE.CHECKING);
      }
      const [backendState, mlReachable, aiPath] = await Promise.all([
        API ? healthStatus(API, '/api/health') : Promise.resolve(HEALTH_STATE.OFFLINE),
        healthStatus(RAG_API, '/ml/health'),
        aiPathStatus(),
      ]);
      if (!cancelled) {
        setBackendHealth(backendState);
        if (mlReachable === HEALTH_STATE.OFFLINE) {
          setAiHealth(HEALTH_STATE.OFFLINE);
          setAiReason('AI service unreachable');
        } else {
          setAiHealth(aiPath.state);
          setAiReason(aiPath.reason || '');
        }
      }
    };

    checkHealth();
    const timer = setInterval(checkHealth, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [API]);

  // Healthy is the normal case, so it earns no pixels: a permanent green
  // "everything is fine" pair taught people to stop reading it, and it put
  // infrastructure on screen for users who cannot act on it. Only trouble shows,
  // and it says what it means for the person rather than which service failed.
  //
  // UNKNOWN and CHECKING deliberately count as "no problem yet" â€” the first poll
  // has not answered, and flashing a warning on every page load would be a lie.
  const backendDown = backendHealth === HEALTH_STATE.OFFLINE;
  const aiDown = aiHealth === HEALTH_STATE.OFFLINE;
  const aiDegraded = aiHealth === HEALTH_STATE.DEGRADED;
  const evaStruggling = backendDown || aiDown || aiDegraded;
  // Degraded alone is a hiccup with successful retries; anything down is worse.
  const troubleIsSevere = backendDown || aiDown;

  return (
    <header className="eva-topbar">
      <div className="eva-topbar-left">
        {isMobile && (
          <button type="button" className="eva-icon-button" onClick={onMenuClick} aria-label="Open sidebar">
            <Menu size={19} />
          </button>
        )}

        <div className="eva-topbar-title-wrap">
          <div className="eva-topbar-title">{isMobile ? 'EVA' : title}</div>
        </div>
      </div>

      <div className="eva-topbar-right">
        {!isMobile && evaStruggling && (
          <div
            className={`eva-topbar-status ${troubleIsSevere ? 'is-offline' : 'is-degraded'}`}
            role="status"
            title={troubleIsSevere
              ? 'EVA is having trouble right now. Some answers may fail â€” please try again shortly.'
              : 'EVA is responding slowly right now. Answers may take longer than usual.'}
          >
            <span />
            {troubleIsSevere ? 'EVA is having trouble' : 'EVA is running slowly'}
          </div>
        )}
      </div>
    </header>
  );
}

