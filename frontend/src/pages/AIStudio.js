import { useEffect, useMemo, useRef, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const tabs = ['My Agents', 'Client Jobs', 'Create Agent', 'Agent Templates', 'Agent Marketplace', 'Agent Analytics', 'Agent Chat'];
const tabLabels = {
  'Agent Templates': 'Templates',
  'Agent Marketplace': 'Marketplace',
  'Agent Analytics': 'Analytics',
};
const studioOfflineMessage = 'EVA backend is offline. Draft tools are still available locally.';
const studioStatusCards = [
  { title: 'EVA Chat Ready', detail: 'Agent chat and local drafting tools are available.' },
  { title: 'RAG Ready', detail: 'Document context stays connected through RAG Center.' },
  { title: 'Client Jobs Draft Mode', detail: 'Replies, CAD plans, and deliverables require manual approval.' },
  { title: 'Local AI Mode', detail: 'Free/local model routing and safe template fallbacks.' },
];
const agentChatQuickPrompts = [
  { label: 'Analyze client request', action: 'analyze_client_request', prompt: 'Analyze this client request and recommend next steps.' },
  { label: 'Generate CAD plan', action: 'generate_cad_plan', prompt: 'Generate a CAD task plan for this client job.' },
  { label: 'Draft client reply', action: 'draft_client_reply', prompt: 'Draft a professional client reply for this CAD job.' },
  { label: 'Create client questions', action: 'create_client_questions', prompt: 'Create questions to ask the client before starting.' },
  { label: 'Estimate time and price', action: 'estimate_time_price', prompt: 'Estimate the timeline and price range for this CAD client job.' },
  { label: 'Create deliverables checklist', action: 'create_deliverables_checklist', prompt: 'Create a deliverables and quality checklist for this client job.' },
];

const modelOptions = [
  'openai/gpt-oss-120b',
  'qwen3-coder',
  'gemma2-9b-it',
  'mixtral-8x7b',
];

const emptyForm = {
  name: 'Python Mentor',
  description: 'Teach Python to beginners.',
  system_prompt: 'You are Python Mentor. Teach Python with simple examples, patient explanations, and practical exercises.',
  model: 'qwen3-coder',
  knowledge_base: 'Python PDFs',
  tools: ['code_assistant', 'rag'],
  avatar: 'PM',
  visibility: 'private',
};

const defaultFreelanceSkills = ['AutoCAD', 'SolidWorks', 'CAD', 'Mechanical Design', '3D Modeling'];
const clientJobStatuses = ['Inbox', 'Draft', 'In Progress', 'Ready to Send', 'Completed'];
const deliverableStatuses = ['Uploaded', 'Ready', 'Needs Check'];
const estimateComplexities = ['Low', 'Medium', 'High'];
const cadTaskChecklistItems = [
  'Review client request',
  'Check units and dimensions',
  'Open source/reference file',
  'Create or edit CAD drawing/model',
  'Export required formats',
  'Attach final deliverables',
];
const qualityCheckItems = [
  'DWG/DXF opens correctly',
  'STEP/STP opens correctly',
  'PDF drawing has dimensions',
  'File names are clear',
  'Units are correct',
  'Client instructions completed',
];

function clientJobStatus(status) {
  const value = status || 'Inbox';
  if (clientJobStatuses.includes(value)) return value;
  if (value === 'Saved') return 'Draft';
  if (value === 'Applied') return 'In Progress';
  if (value === 'Won' || value === 'Lost' || value === 'Skip') return 'Completed';
  return 'Inbox';
}

function clientJobTitle(job) {
  return job?.job_title || 'New client request';
}

function clientJobUpdatedAt(job) {
  return job?.updated_at || job?.updatedAt || job?.created_at || new Date().toISOString();
}

function clientReplyBody(result) {
  return result?.proposal_long || result?.proposal_short || '';
}

function authHeaders(contentType = 'application/json') {
  const token = localStorage.getItem('aria_token') || localStorage.getItem('token') || localStorage.getItem('authToken') || '';
  return {
    ...(contentType ? { 'Content-Type': contentType } : {}),
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function friendlyErrorMessage(err, fallback = studioOfflineMessage) {
  const message = String(err?.message || err || '').trim();
  if (!message || /failed to fetch|networkerror|load failed/i.test(message)) return fallback;
  return message;
}

function clientJobChatFallback(message, action = 'analyze_client_request') {
  const text = String(message || '').trim() || 'the client CAD request';
  const sections = {
    job_title: 'Client CAD request',
    task_type: 'CAD drafting',
    cad_software: 'AutoCAD',
    required_outputs: ['DWG', 'PDF'],
    task_plan: [
      'Review the client request and attachments.',
      'Confirm dimensions, units, source files, and final formats.',
      'Create or edit the CAD drawing/model.',
      'Export requested deliverables.',
      'Run quality checks before manual delivery.',
    ],
    questions: [
      'What final file formats do you need?',
      'Are the dimensions in mm or inches?',
      'Do you need 2D drawing, 3D model, or both?',
      'Should I include manufacturing drawings?',
      'Do you have source CAD files or reference images?',
    ],
    estimate: 'Estimated time: 2-6 hours for simple CAD work; 1-3 days for detailed modeling or manufacturing drawings. Suggested price range: $50-$150.',
    reply_draft: `Hi,\n\nThanks for sharing the CAD request. I understand you need help with ${text}.\n\nI can review the files, confirm dimensions and output formats, complete the CAD work, export the deliverables, and run a quality check before sending final files.\n\nA few details to confirm:\n- What final file formats do you need?\n- Are dimensions in mm or inches?\n- Do you need 2D drawing, 3D model, or both?\n\nEstimated timeline and price can be finalized after I review the source files.\n\nBest regards,`,
    checklist: [
      'Review client request',
      'Confirm units and dimensions',
      'Check source/reference files',
      'Create CAD drawing/model',
      'Export deliverables',
      'Quality check files',
      'Manually review before sending',
    ],
  };
  return {
    ok: true,
    answer: 'EVA backend is offline. Draft tools are still available locally. I prepared a safe template result for manual review.',
    action,
    sections,
    model_used: 'template-fallback',
    approval_required: true,
  };
}

export default function AIStudio({ API = defaultApi, initialTab = 'My Agents' }) {
  const storedUser = (() => {
    try {
      return JSON.parse(localStorage.getItem('aria_user') || '{}');
    } catch {
      return {};
    }
  })();
  const userId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const organizationId = storedUser.organization_id || 'default-org';
  const token = localStorage.getItem('aria_token');
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }), [token]);

  const [activeTab, setActiveTab] = useState(tabs.includes(initialTab) ? initialTab : 'My Agents');
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(() => localStorage.getItem('eva_selected_workspace_id') || '');
  const [agents, setAgents] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [tools, setTools] = useState([]);
  const [analytics, setAnalytics] = useState({ summary: {}, popular_agents: [], recent_usage: [], tool_usage: [] });
  const [form, setForm] = useState(emptyForm);
  const [chatAgentId, setChatAgentId] = useState('eva-ai');
  const [chatMessage, setChatMessage] = useState('Paste a client CAD request here, then choose an action.');
  const [chatAction, setChatAction] = useState('analyze_client_request');
  const [chatLog, setChatLog] = useState([]);
  const [clientJobChatResult, setClientJobChatResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadStudio = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      const [agentsRes, templatesRes, toolsRes, analyticsRes] = await Promise.all([
        fetch(`${API}/ai-studio/agents?${params.toString()}`, { headers }),
        fetch(`${API}/ai-studio/templates`, { headers }),
        fetch(`${API}/ai-studio/tools`, { headers }),
        fetch(`${API}/ai-studio/analytics?${params.toString()}`, { headers }),
      ]);
      const agentsJson = await agentsRes.json().catch(() => ({}));
      const templatesJson = await templatesRes.json().catch(() => ({}));
      const toolsJson = await toolsRes.json().catch(() => ({}));
      const analyticsJson = await analyticsRes.json().catch(() => ({}));
      if (!agentsRes.ok) throw new Error(agentsJson.detail || 'Agents failed');
      if (!templatesRes.ok) throw new Error(templatesJson.detail || 'Templates failed');
      if (!toolsRes.ok) throw new Error(toolsJson.detail || 'Tools failed');
      if (!analyticsRes.ok) throw new Error(analyticsJson.detail || 'Analytics failed');
      setAgents(agentsJson.agents || []);
      setTemplates(templatesJson.templates || []);
      setTools(toolsJson.tools || []);
      setAnalytics({
        summary: analyticsJson.summary || {},
        popular_agents: analyticsJson.popular_agents || [],
        recent_usage: analyticsJson.recent_usage || [],
        tool_usage: analyticsJson.tool_usage || [],
      });
    } catch (err) {
      setError(friendlyErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStudio();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId]);

  useEffect(() => {
    setActiveTab(tabs.includes(initialTab) ? initialTab : 'My Agents');
  }, [initialTab]);

  useEffect(() => {
    const syncWorkspace = () => setSelectedWorkspaceId(localStorage.getItem('eva_selected_workspace_id') || '');
    window.addEventListener('storage', syncWorkspace);
    window.addEventListener('eva:workspace-selected', syncWorkspace);
    return () => {
      window.removeEventListener('storage', syncWorkspace);
      window.removeEventListener('eva:workspace-selected', syncWorkspace);
    };
  }, []);

  const updateForm = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  const selectedTools = new Set(form.tools || []);

  const toggleTool = (toolId) => {
    const next = new Set(form.tools || []);
    if (next.has(toolId)) next.delete(toolId);
    else next.add(toolId);
    updateForm('tools', Array.from(next));
  };

  const knowledgeList = (text) => String(text || '')
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);

  const createAgent = async (payload = null) => {
    const source = payload || {
      ...form,
      knowledge_base: knowledgeList(form.knowledge_base),
    };
    if (!source.name?.trim()) {
      setError('Agent name is required.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/ai-studio/agents`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          user_id: userId,
          organization_id: organizationId,
          name: source.name,
          description: source.description || '',
          system_prompt: source.system_prompt || 'You are a helpful AI agent.',
          model: source.model || 'openai/gpt-oss-120b',
          knowledge_base: source.knowledge_base || [],
          tools: source.tools || [],
          avatar: source.avatar || initials(source.name),
          visibility: source.visibility || 'private',
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Create agent failed');
      await loadStudio();
      setChatAgentId(json.agent?.id || chatAgentId);
      setActiveTab('My Agents');
    } catch (err) {
      setError(friendlyErrorMessage(err, 'Create agent failed.'));
    } finally {
      setLoading(false);
    }
  };

  const deleteAgent = async (agentId) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ user_id: userId });
      const res = await fetch(`${API}/ai-studio/agents/${agentId}?${params.toString()}`, {
        method: 'DELETE',
        headers,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Delete failed');
      await loadStudio();
      if (chatAgentId === agentId) setChatAgentId('eva-ai');
    } catch (err) {
      setError(friendlyErrorMessage(err, 'Delete failed.'));
    } finally {
      setLoading(false);
    }
  };

  const applyTemplate = (template) => {
    setForm({
      name: template.name,
      description: template.description || '',
      system_prompt: template.system_prompt || '',
      model: template.model || 'openai/gpt-oss-120b',
      knowledge_base: (template.knowledge_base || []).join('\n'),
      tools: template.tools || [],
      avatar: template.avatar || initials(template.name),
      visibility: 'private',
    });
    setActiveTab('Create Agent');
  };

  const installTemplate = (template) => {
    createAgent({
      name: template.name,
      description: template.description || '',
      system_prompt: template.system_prompt || 'You are a helpful AI agent.',
      model: template.model || 'openai/gpt-oss-120b',
      knowledge_base: template.knowledge_base || [],
      tools: template.tools || [],
      avatar: template.avatar || initials(template.name),
      visibility: 'private',
    });
  };

  const sendAgentMessage = async () => {
    if (!chatMessage.trim()) return;
    const userMessage = chatMessage.trim();
    const nextHistory = [...chatLog, { role: 'user', content: userMessage }];
    setChatLog(nextHistory);
    setChatMessage('');
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/api/agents/client-job/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId || '',
          job_id: localStorage.getItem('eva_selected_client_job_id') || '',
          message: userMessage,
          action: chatAction,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Agent chat failed');
      setClientJobChatResult(json);
      setChatLog([...nextHistory, { role: 'assistant', content: json.answer || 'No response', agent: `EVA Client Jobs / ${json.model_used || 'local'}`, sections: json.sections }]);
    } catch (err) {
      const friendly = friendlyErrorMessage(err);
      const fallback = clientJobChatFallback(userMessage, chatAction);
      setClientJobChatResult(fallback);
      setError(friendly);
      setChatLog([
        ...nextHistory,
        {
          role: 'assistant',
          content: `${friendly}\n\n${fallback.answer}`,
          agent: 'EVA Local',
          sections: fallback.sections,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const activeReplyDraft = clientJobChatResult?.sections?.reply_draft || clientJobChatResult?.answer || '';

  const saveClientJobAgentResult = (switchToClientJobs = false) => {
    if (!clientJobChatResult) return;
    const payload = {
      ...clientJobChatResult,
      saved_at: new Date().toISOString(),
    };
    localStorage.setItem('eva_client_job_agent_result', JSON.stringify(payload));
    localStorage.setItem('eva_client_job_compose_draft', JSON.stringify({
      to: '',
      subject: 'Re: CAD client request',
      body: activeReplyDraft,
      attachments: [],
      deliverables: [],
      driveShareLink: '',
      saved_at: new Date().toISOString(),
    }));
    window.dispatchEvent(new CustomEvent('eva:client-job-agent-result', { detail: payload }));
    if (switchToClientJobs) setActiveTab('Client Jobs');
  };

  const autoFillClientJobFromAgentResult = () => {
    if (!clientJobChatResult) return;
    const selectedClientJobId = localStorage.getItem('eva_selected_client_job_id') || '';
    if (!selectedClientJobId) {
      setError('Please select or create a client job first.');
      return;
    }
    const payload = {
      ...clientJobChatResult,
      job_id: selectedClientJobId,
      saved_at: new Date().toISOString(),
      auto_fill: true,
    };
    localStorage.setItem('eva_client_job_auto_fill', JSON.stringify(payload));
    window.dispatchEvent(new CustomEvent('eva:client-job-auto-fill', { detail: payload }));
    setError('');
    setActiveTab('Client Jobs');
  };

  const copyClientJobReply = async () => {
    if (!activeReplyDraft.trim()) return;
    try {
      await navigator.clipboard.writeText(activeReplyDraft);
      setError('');
    } catch {
      setError('Could not copy reply. Select the reply text and copy it manually.');
    }
  };

  const S = styles(loading);
  const chatOptions = [{ id: 'eva-ai', name: 'EVA AI', avatar: 'E' }, ...agents];
  const selectedChatAgent = chatOptions.find((agent) => agent.id === chatAgentId) || chatOptions[0];

  return (
    <div style={S.page}>
      <style>{`
        @keyframes studioFade {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes studioShimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
        .studio-tab-content { animation: studioFade .24s ease both; }
        .studio-tab-button,
        .studio-card-hover,
        .ai-action-button,
        .client-mail-item {
          transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease, background .18s ease;
        }
        .studio-tab-button:hover,
        .studio-card-hover:hover,
        .ai-action-button:hover,
        .client-mail-item:hover {
          transform: translateY(-1px);
          border-color: rgba(56,189,248,.42) !important;
          box-shadow: 0 14px 34px rgba(8,47,73,.28);
        }
        .studio-skeleton {
          position: relative;
          overflow: hidden;
        }
        .studio-skeleton::after {
          content: "";
          position: absolute;
          inset: 0;
          background: linear-gradient(90deg, transparent, rgba(148,163,184,.12), transparent);
          animation: studioShimmer 1.4s ease-in-out infinite;
        }
        @media (max-width: 1120px) {
          .studio-grid-2,
          .studio-grid-3,
          .studio-grid-4 { grid-template-columns: 1fr !important; }
          .freelance-job-row { grid-template-columns: 1fr !important; }
          .freelance-cad-steps { grid-template-columns: 1fr !important; }
          .client-jobs-layout { grid-template-columns: 1fr !important; }
          .client-jobs-compact { grid-template-columns: 1fr !important; }
          .client-deliverable-row { grid-template-columns: 1fr !important; }
          .studio-cards { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
          .studio-right-rail { position: static !important; }
        }
        @media (max-width: 680px) {
          .studio-cards { grid-template-columns: 1fr !important; }
          .studio-tabs { grid-template-columns: 1fr 1fr !important; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>AI Studio</h1>
            <div style={S.sub}>Create agents, manage client jobs, analyze files, and automate work with EVA.</div>
          </div>
          <button type="button" onClick={loadStudio} disabled={loading} style={S.primaryButton}>
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>

        <div className="studio-cards" style={S.statusGrid}>
          {studioStatusCards.map((card) => (
            <section key={card.title} className="studio-card-hover" style={S.statusCard}>
              <strong>{card.title}</strong>
              <span>{card.detail}</span>
            </section>
          ))}
        </div>

        {loading && (
          <div className="studio-cards" style={S.skeletonGrid}>
            {[0, 1, 2].map((item) => <div key={item} className="studio-skeleton" style={S.skeletonCard} />)}
          </div>
        )}

        <div className="studio-tabs" style={S.tabs}>
          {tabs.map((tab) => (
            <button
              key={tab}
              className="studio-tab-button"
              type="button"
              onClick={() => setActiveTab(tab)}
              style={{ ...S.tab, ...(activeTab === tab ? S.activeTab : {}) }}
            >
              {tabLabels[tab] || tab}
            </button>
          ))}
        </div>

        {error && <div style={S.error}>{error}</div>}

        <div key={activeTab} className="studio-tab-content" style={S.tabContent}>
        {activeTab === 'Client Jobs' && (
          <FreelanceModePanel API={API} S={S} selectedWorkspaceId={selectedWorkspaceId} />
        )}

        {activeTab === 'My Agents' && (
          <div style={S.stack}>
            <div className="studio-cards" style={S.grid4}>
              <Metric label="Custom Agents" value={agents.length} color="#38bdf8" />
              <Metric label="Templates" value={templates.length} color="#fbbf24" />
              <Metric label="Tools" value={tools.length} color="#34d399" />
              <Metric label="Agent Chats" value={analytics.summary?.total_chats || 0} color="#f472b6" />
            </div>
            <div className="studio-grid-3" style={S.grid3}>
              {agents.length === 0 ? (
                <section style={S.panel}>
                  <div style={S.sectionTitle}>No Agents Yet</div>
                  <p style={S.muted}>Create a custom agent or install a template to start building your AI workspace.</p>
                  <button type="button" onClick={() => setActiveTab('Create Agent')} style={S.primaryButton}>Create Agent</button>
                </section>
              ) : agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  S={S}
                  onChat={() => { setChatAgentId(agent.id); setActiveTab('Agent Chat'); }}
                  onDelete={() => deleteAgent(agent.id)}
                />
              ))}
            </div>
          </div>
        )}

        {activeTab === 'Create Agent' && (
          <div className="studio-grid-2" style={S.grid2}>
            <section style={S.panel}>
              <div style={S.sectionTitle}>Create Agent Form</div>
              <div style={S.formGrid}>
                <Field label="Agent Name">
                  <input value={form.name} onChange={(e) => updateForm('name', e.target.value)} style={S.input} />
                </Field>
                <Field label="Avatar">
                  <input value={form.avatar} onChange={(e) => updateForm('avatar', e.target.value)} style={S.input} maxLength={4} />
                </Field>
                <Field label="Description">
                  <input value={form.description} onChange={(e) => updateForm('description', e.target.value)} style={S.input} />
                </Field>
                <Field label="Model">
                  <select value={form.model} onChange={(e) => updateForm('model', e.target.value)} style={S.input}>
                    {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
                  </select>
                </Field>
                <Field label="System Prompt" wide>
                  <textarea value={form.system_prompt} onChange={(e) => updateForm('system_prompt', e.target.value)} style={S.textarea} />
                </Field>
                <Field label="Knowledge Base" wide>
                  <textarea value={form.knowledge_base} onChange={(e) => updateForm('knowledge_base', e.target.value)} placeholder="Python PDFs&#10;Company SOP&#10;Project EVA" style={S.shortTextarea} />
                </Field>
                <Field label="Tools" wide>
                  <div style={S.toolGrid}>
                    {tools.map((tool) => (
                      <label key={tool.id} style={{ ...S.toolOption, ...(selectedTools.has(tool.id) ? S.toolSelected : {}) }}>
                        <input type="checkbox" checked={selectedTools.has(tool.id)} onChange={() => toggleTool(tool.id)} />
                        <span>
                          <strong>{tool.name}</strong>
                          <small>{tool.description}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                </Field>
              </div>
              <button type="button" onClick={() => createAgent()} disabled={loading} style={{ ...S.primaryButton, marginTop: 14 }}>
                {loading ? 'Creating' : 'Create Agent'}
              </button>
            </section>

            <section style={S.panel}>
              <div style={S.sectionTitle}>Live Preview</div>
              <div style={S.previewAgent}>
                <div style={S.avatar}>{form.avatar || initials(form.name)}</div>
                <div>
                  <div style={{ color: '#f8fafc', fontSize: 18, fontWeight: 850 }}>{form.name || 'New Agent'}</div>
                  <div style={S.muted}>{form.description || 'No description yet.'}</div>
                </div>
              </div>
              <InfoRow label="Model" value={form.model} />
              <InfoRow label="Knowledge" value={knowledgeList(form.knowledge_base).join(', ') || 'None selected'} />
              <InfoRow label="Tools" value={(form.tools || []).join(', ') || 'None selected'} />
              <div style={{ marginTop: 12, color: '#94a3b8', fontSize: 12, lineHeight: 1.6 }}>
                {form.system_prompt}
              </div>
            </section>
          </div>
        )}

        {activeTab === 'Agent Templates' && (
          <div className="studio-grid-3" style={S.grid3}>
            {templates.map((template) => (
              <TemplateCard key={template.id} template={template} S={S} primaryLabel="Use Template" onPrimary={() => applyTemplate(template)} />
            ))}
          </div>
        )}

        {activeTab === 'Agent Marketplace' && (
          <div style={S.stack}>
            <section style={S.panel}>
              <div style={S.sectionTitle}>Agent Marketplace</div>
              <p style={S.muted}>Install ready-made agents into your workspace, then customize them in Create Agent.</p>
            </section>
            <div className="studio-grid-3" style={S.grid3}>
              {templates.map((template) => (
                <TemplateCard key={template.id} template={template} S={S} primaryLabel="Install Agent" onPrimary={() => installTemplate(template)} />
              ))}
            </div>
          </div>
        )}

        {activeTab === 'Agent Analytics' && (
          <div style={S.stack}>
            <div className="studio-cards" style={S.grid4}>
              <Metric label="Total Agents" value={analytics.summary?.total_agents || 0} color="#38bdf8" />
              <Metric label="Agent Chats" value={analytics.summary?.total_chats || 0} color="#f472b6" />
              <Metric label="Tokens Used" value={formatNumber(analytics.summary?.tokens_used || 0)} color="#fbbf24" />
              <Metric label="Tools Available" value={analytics.summary?.tools || 0} color="#34d399" />
            </div>
            <div className="studio-grid-3" style={S.grid3}>
              <RankPanel title="Popular Agents" rows={analytics.popular_agents || []} titleKey="name" meta={(row) => `${row.chats} chats / ${formatNumber(row.tokens)} tokens`} S={S} />
              <RankPanel title="Tool Usage" rows={analytics.tool_usage || []} titleKey="tool_name" meta={(row) => `${row.agents} agents`} S={S} />
              <RankPanel title="Recent Usage" rows={analytics.recent_usage || []} titleKey="agent_name" meta={(row) => `${formatNumber(row.tokens)} tokens / ${formatDate(row.created_at)}`} S={S} />
            </div>
          </div>
        )}

        {activeTab === 'Agent Chat' && (
          <div className="studio-grid-2" style={S.chatGrid}>
            <section style={S.panel}>
              <div style={S.chatHeader}>
                <div>
                  <div style={S.sectionTitle}>Agent Chat</div>
                  <p style={S.muted}>A focused mini chat for client work, agents, checklists, and estimates.</p>
                </div>
                <span style={S.statusBadge}>Local fallback ready</span>
              </div>
              <select value={chatAgentId} onChange={(e) => setChatAgentId(e.target.value)} style={S.input}>
                {chatOptions.map((agent) => (
                  <option key={agent.id} value={agent.id}>{agent.name}</option>
                ))}
              </select>
              <div style={S.quickChips}>
                {agentChatQuickPrompts.map((prompt) => (
                  <button
                    key={prompt.action}
                    type="button"
                    onClick={() => {
                      setChatAction(prompt.action);
                      setChatMessage(prompt.prompt);
                    }}
                    style={{ ...S.chipButton, ...(chatAction === prompt.action ? S.chipButtonActive : {}) }}
                  >
                    {prompt.label}
                  </button>
                ))}
              </div>
              <div style={S.chatBox}>
                {chatLog.length === 0 ? (
                  <div style={S.chatEmpty}>
                    <strong>Ask {selectedChatAgent?.name || 'EVA'} to help with a client workflow.</strong>
                    <span>Try a quick chip, paste a client request, or ask for a reply draft. If the backend is offline, EVA keeps the draft tools local.</span>
                  </div>
                ) : chatLog.map((item, index) => (
                  <div key={index} style={{ ...S.chatBubble, ...(item.role === 'user' ? S.userBubble : S.assistantBubble) }}>
                    <div style={S.chatRole}>{item.role === 'user' ? 'You' : (item.agent || 'Agent')}</div>
                    <div style={{ whiteSpace: 'pre-wrap' }}>{item.content}</div>
                  </div>
                ))}
              </div>
              <div style={S.chatComposer}>
                <textarea value={chatMessage} onChange={(e) => setChatMessage(e.target.value)} style={S.shortTextarea} />
                <button type="button" onClick={sendAgentMessage} disabled={loading || !chatMessage.trim()} style={{ ...S.primaryButton, opacity: loading || !chatMessage.trim() ? 0.55 : 1 }}>
                  {loading ? 'Sending' : 'Send'}
                </button>
              </div>
              {clientJobChatResult && (
                <div style={S.agentResultWrap}>
                  <div style={S.agentResultHeader}>
                    <div>
                      <div style={S.sectionTitle}>Client Job Result</div>
                      <p style={S.muted}>Model: {clientJobChatResult.model_used || 'local'} | Draft only | Manual approval required</p>
                    </div>
                    <div style={S.buttonRow}>
                      <button type="button" onClick={autoFillClientJobFromAgentResult} style={S.primaryButton}>Auto-fill Job</button>
                      <button type="button" onClick={() => saveClientJobAgentResult(true)} style={S.secondaryButton}>Apply to Job</button>
                      <button type="button" onClick={copyClientJobReply} disabled={!activeReplyDraft.trim()} style={{ ...S.secondaryButton, opacity: activeReplyDraft.trim() ? 1 : 0.55 }}>Copy Reply</button>
                      <button type="button" onClick={() => saveClientJobAgentResult(false)} style={S.secondaryButton}>Add to Draft</button>
                    </div>
                  </div>
                  <div className="studio-grid-2" style={S.resultGrid}>
                    <ResultCard title="EVA Answer" value={clientJobChatResult.answer} S={S} />
                    <ResultCard title="Job Title" value={clientJobChatResult.sections?.job_title} S={S} />
                    <ResultCard title="Task Type" value={clientJobChatResult.sections?.task_type} S={S} />
                    <ResultCard title="Required Outputs" list={clientJobChatResult.sections?.required_outputs} S={S} />
                    <ResultCard title="CAD Plan" list={clientJobChatResult.sections?.task_plan} S={S} />
                    <ResultCard title="Questions" list={clientJobChatResult.sections?.questions} S={S} />
                    <ResultCard title="Estimate" value={clientJobChatResult.sections?.estimate} S={S} />
                    <ResultCard title="Reply Draft" value={clientJobChatResult.sections?.reply_draft} S={S} />
                    <ResultCard title="Checklist" list={clientJobChatResult.sections?.checklist} S={S} />
                  </div>
                </div>
              )}
            </section>

            <section style={S.panel}>
              <div style={S.sectionTitle}>Agent Options</div>
              <div style={S.optionList}>
                {chatOptions.map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => setChatAgentId(agent.id)}
                    style={{ ...S.agentOption, ...(chatAgentId === agent.id ? S.agentOptionActive : {}) }}
                  >
                    <span style={S.smallAvatar}>{agent.avatar || initials(agent.name)}</span>
                    <span>
                      <strong>{agent.name}</strong>
                      <small>{agent.description || 'Default EVA AI assistant'}</small>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          </div>
        )}
        </div>
      </div>
    </div>
  );
}

function FreelanceModePanel({ API, S, selectedWorkspaceId }) {
  const [jobText, setJobText] = useState('');
  const [skillsText, setSkillsText] = useState(defaultFreelanceSkills.join(', '));
  const [uploadName, setUploadName] = useState('');
  const [clientName, setClientName] = useState('');
  const [jobTitleDraft, setJobTitleDraft] = useState('');
  const [clientFileName, setClientFileName] = useState('');
  const [clientPhotoName, setClientPhotoName] = useState('');
  const [cadRequest, setCadRequest] = useState('');
  const [cadSoftware, setCadSoftware] = useState('AutoCAD');
  const [cadOutput, setCadOutput] = useState('DWG');
  const [cadFileName, setCadFileName] = useState('');
  const [cadNotice, setCadNotice] = useState('');
  const [cadResult, setCadResult] = useState(null);
  const [cadLoading, setCadLoading] = useState(false);
  const [cadWorkerStatus, setCadWorkerStatus] = useState(null);
  const [cadWorkerPreview, setCadWorkerPreview] = useState(null);
  const [cadWorkerRunResult, setCadWorkerRunResult] = useState(null);
  const [cadWorkerLoading, setCadWorkerLoading] = useState('');
  const [analysis, setAnalysis] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [notice, setNotice] = useState('');
  const [freelanceError, setFreelanceError] = useState('');
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [jobSearch, setJobSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('Inbox');
  const [composeOpen, setComposeOpen] = useState(true);
  const [composeTo, setComposeTo] = useState('');
  const [composeSubject, setComposeSubject] = useState('');
  const [composeBody, setComposeBody] = useState('');
  const [deliverables, setDeliverables] = useState([]);
  const [checklistsByJob, setChecklistsByJob] = useState({});
  const [generatedReply, setGeneratedReply] = useState('');
  const [replyLoading, setReplyLoading] = useState(false);
  const [estimateDraft, setEstimateDraft] = useState({});
  const [driveStatus, setDriveStatus] = useState(null);
  const [driveLoading, setDriveLoading] = useState('');
  const [driveShareLink, setDriveShareLink] = useState('');
  const [driveFolderStructure, setDriveFolderStructure] = useState(null);
  const requestInputRef = useRef(null);
  const clientFileInputRef = useRef(null);
  const deliverableInputRef = useRef(null);

  const profileSkills = () => skillsText
    .split(/[\n,]/)
    .map((skill) => skill.trim())
    .filter(Boolean);

  const loadJobs = async () => {
    if (!selectedWorkspaceId) {
      setJobs([]);
      return;
    }
    setHistoryLoading(true);
    setFreelanceError('');
    try {
      const params = new URLSearchParams({ workspace_id: selectedWorkspaceId });
      const res = await fetch(`${API}/api/freelance/jobs?${params.toString()}`, { headers: authHeaders() });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not load client job history.');
      setJobs(Array.isArray(json.jobs) ? json.jobs : []);
    } catch (err) {
      setFreelanceError(friendlyErrorMessage(err, studioOfflineMessage));
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, selectedWorkspaceId]);

  useEffect(() => {
    if (!jobs.length) {
      setSelectedJobId('');
      localStorage.removeItem('eva_selected_client_job_id');
      return;
    }
    if (!selectedJobId || !jobs.some((job) => job.id === selectedJobId)) {
      setSelectedJobId(jobs[0].id);
      localStorage.setItem('eva_selected_client_job_id', jobs[0].id);
    }
  }, [jobs, selectedJobId]);

  useEffect(() => {
    try {
      const draft = JSON.parse(localStorage.getItem('eva_client_job_compose_draft') || '{}');
      if (draft && typeof draft === 'object') {
        setComposeTo(draft.to || '');
        setComposeSubject(draft.subject || '');
        setComposeBody(draft.body || '');
        setDeliverables(Array.isArray(draft.deliverables) ? draft.deliverables : []);
        setDriveShareLink(draft.driveShareLink || '');
      }
    } catch {
      // Ignore stale local draft data.
    }
  }, []);

  useEffect(() => {
    const applyAgentResult = (rawResult, options = {}) => {
      const result = rawResult && typeof rawResult === 'object' ? rawResult : {};
      const sections = result.sections || {};
      const selectedForAutofill = selectedJobId || localStorage.getItem('eva_selected_client_job_id') || '';
      if (options.autoFill && !selectedForAutofill) {
        setNotice('Please select or create a client job first.');
        return;
      }
      const hasExistingDetails = Boolean(selectedForAutofill) || [
        jobTitleDraft,
        jobText,
        cadRequest,
        composeBody,
        generatedReply,
        cadResult?.task_type,
        cadResult?.task_plan?.join(' '),
        estimateDraft.reason,
      ].some((value) => String(value || '').trim());
      if (options.autoFill && hasExistingDetails && !window.confirm('Replace existing job details?')) {
        setNotice('Auto-fill cancelled. Existing job details were kept.');
        return;
      }
      if (options.autoFill && sections.job_title) {
        setJobTitleDraft(String(sections.job_title).slice(0, 120));
      }
      if (options.autoFill && sections.cad_software && ['AutoCAD', 'SolidWorks', 'Fusion 360', 'FreeCAD', 'Onshape'].includes(sections.cad_software)) {
        setCadSoftware(sections.cad_software);
      }
      const requiredOutputs = Array.isArray(sections.required_outputs)
        ? sections.required_outputs
        : Array.isArray(sections.deliverables) ? sections.deliverables : [];
      const firstOutput = requiredOutputs.find((item) => ['DWG', 'DXF', 'STEP/STP', 'PDF', 'PNG'].includes(item));
      if (options.autoFill && firstOutput) {
        setCadOutput(firstOutput);
      }
      if (Array.isArray(sections.task_plan) && sections.task_plan.length) {
        setCadResult((current) => ({
          ...(current || {}),
          task_type: sections.task_type || current?.task_type || '',
          software: sections.cad_software || current?.software || '',
          deliverables: requiredOutputs.length ? requiredOutputs : current?.deliverables || [],
          task_plan: sections.task_plan,
          agent_questions: Array.isArray(sections.questions) ? sections.questions : current?.agent_questions || [],
          agent_checklist: Array.isArray(sections.checklist) ? sections.checklist : current?.agent_checklist || [],
          summary: result.answer || current?.summary || '',
        }));
      }
      if (sections.reply_draft) {
        setGeneratedReply(sections.reply_draft);
        setComposeBody(sections.reply_draft);
        setComposeSubject((current) => current || 'Re: CAD client request');
        setComposeOpen(true);
      }
      if (sections.estimate) {
        setEstimateDraft((current) => ({
          ...current,
          reason: sections.estimate,
        }));
      }
      setNotice(options.autoFill ? 'Client job auto-filled from Agent Chat. Review manually before sending.' : 'Agent Chat result added to Client Jobs draft. Review manually before sending.');
    };
    try {
      const autoFill = JSON.parse(localStorage.getItem('eva_client_job_auto_fill') || '{}');
      if (autoFill && autoFill.sections) {
        applyAgentResult(autoFill, { autoFill: true });
        localStorage.removeItem('eva_client_job_auto_fill');
      }
      const stored = JSON.parse(localStorage.getItem('eva_client_job_agent_result') || '{}');
      if (stored && stored.sections) {
        applyAgentResult(stored);
        localStorage.removeItem('eva_client_job_agent_result');
      }
    } catch {
      // Ignore stale agent result data.
    }
    const handleAgentResult = (event) => applyAgentResult(event.detail);
    const handleAutoFill = (event) => applyAgentResult(event.detail, { autoFill: true });
    window.addEventListener('eva:client-job-agent-result', handleAgentResult);
    window.addEventListener('eva:client-job-auto-fill', handleAutoFill);
    return () => {
      window.removeEventListener('eva:client-job-agent-result', handleAgentResult);
      window.removeEventListener('eva:client-job-auto-fill', handleAutoFill);
    };
  }, [cadRequest, cadResult, composeBody, estimateDraft.reason, generatedReply, jobText, jobTitleDraft, selectedJobId]);

  useEffect(() => {
    refreshDriveStatus(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, selectedWorkspaceId]);

  async function refreshDriveStatus(silent = false) {
    setDriveLoading('status');
    try {
      const res = await fetch(`${API}/api/integrations/google-drive/status`, { headers: authHeaders() });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not check Google Drive status.');
      setDriveStatus(json);
      if (!silent) setNotice(json.connected ? 'Google Drive connected. You can save deliverables.' : 'Google Drive is not connected.');
    } catch (err) {
      const friendly = friendlyErrorMessage(err, 'Google Drive is not connected.');
      setDriveStatus({ ok: false, connected: false, message: friendly });
      if (!silent) setNotice(friendly);
    } finally {
      setDriveLoading('');
    }
  }

  const handleJobFile = async (event, kind = 'file') => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (kind === 'photo') {
      if (!/\.(png|jpg|jpeg)$/i.test(file.name)) {
        setFreelanceError('Upload a PNG or JPG client reference photo.');
        return;
      }
      setClientPhotoName(file.name);
      setNotice('Client photo attached locally. Draft tools are available; no email will be sent.');
      return;
    }
    if (!/\.(pdf|dwg|dxf|step|stp|png|jpg|jpeg|zip)$/i.test(file.name)) {
      setFreelanceError('Upload a supported client file: PDF, DWG, DXF, STEP/STP, image, or ZIP.');
      return;
    }
    setClientFileName(file.name);
    setUploadName(file.name);
    setNotice('Client file attached locally. Upload processing remains draft-only in this workspace.');
  };

  const handleCadFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!/\.(pdf|dwg|dxf|step|stp|sldprt|sldasm|png|jpg|jpeg)$/i.test(file.name)) {
      setCadNotice('Upload a supported client CAD/reference file.');
      return;
    }
    setCadFileName(file.name);
    setCadNotice('Reference file selected. CAD client work is draft mode; no file was uploaded or processed yet.');
  };

  const handleDeliverableFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!/\.(dwg|dxf|step|stp|pdf|png|jpg|jpeg|zip)$/i.test(file.name)) {
      setNotice('Upload a deliverable file: DWG, DXF, STEP/STP, PDF, PNG, JPG, JPEG, or ZIP.');
      return;
    }
    const item = {
      id: `deliverable_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      name: file.name,
      size: file.size,
      type: file.type || 'CAD deliverable',
      status: 'Uploaded',
      added_at: new Date().toISOString(),
    };
    setDeliverables((current) => [...current, item]);
    setNotice('Deliverable attached to this draft. Review before sending manually.');
  };

  const connectGoogleDrive = async () => {
    await refreshDriveStatus(true);
    setNotice('Google Drive is not connected. Connect Google Drive first.');
  };

  const saveDeliverablesToDrive = async () => {
    if (!selectedJobId || !selectedWorkspaceId) {
      setNotice('Select a saved client job before saving deliverables to Google Drive.');
      return;
    }
    if (!deliverables.length) {
      setNotice('Attach deliverables before saving to Google Drive.');
      return;
    }
    setDriveLoading('save');
    setFreelanceError('');
    try {
      const res = await fetch(`${API}/api/client-jobs/${selectedJobId}/drive/save`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          deliverables: deliverables.map((file) => ({
            name: file.name,
            size: file.size,
            type: file.type,
            status: file.status,
          })),
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not save deliverables to Google Drive.');
      setDriveFolderStructure(json.folder_structure || json.job?.analysis?.google_drive?.folder_structure || null);
      if (json.job) setJobs((current) => current.map((job) => (job.id === json.job.id ? json.job : job)));
      setNotice(json.message || (json.connected ? 'Google Drive save placeholder completed.' : 'Google Drive is not connected. Connect Google Drive first.'));
    } catch (err) {
      setFreelanceError(friendlyErrorMessage(err, 'Could not save deliverables to Google Drive.'));
    } finally {
      setDriveLoading('');
    }
  };

  const createClientShareLink = async () => {
    if (!selectedJobId || !selectedWorkspaceId) {
      setNotice('Select a saved client job before creating a share link.');
      return;
    }
    setDriveLoading('share');
    setFreelanceError('');
    try {
      const res = await fetch(`${API}/api/client-jobs/${selectedJobId}/drive/share-link`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          deliverables: deliverables.map((file) => ({
            name: file.name,
            size: file.size,
            type: file.type,
            status: file.status,
          })),
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not create Google Drive share link.');
      const link = json.share_link || json.job?.analysis?.google_drive?.share_link || '';
      setDriveShareLink(link);
      setDriveFolderStructure(json.folder_structure || json.job?.analysis?.google_drive?.folder_structure || null);
      if (json.job) setJobs((current) => current.map((job) => (job.id === json.job.id ? json.job : job)));
      setNotice(json.message || (link ? 'Client share link created. Review before sharing manually.' : 'Google Drive is not connected. Connect Google Drive first.'));
    } catch (err) {
      setFreelanceError(friendlyErrorMessage(err, 'Could not create Google Drive share link.'));
    } finally {
      setDriveLoading('');
    }
  };

  const copyDriveShareLink = async () => {
    if (!driveShareLink) {
      setNotice('No Drive share link available yet.');
      return;
    }
    try {
      await navigator.clipboard.writeText(driveShareLink);
      setNotice('Drive share link copied. Review manually before sending.');
    } catch {
      setFreelanceError('Could not copy Drive share link. Select the link and copy it manually.');
    }
  };

  const insertDriveLinkIntoDraft = () => {
    if (!driveShareLink) {
      setNotice('No Drive share link available yet.');
      return;
    }
    setComposeBody((current) => {
      const prefix = current.trim() ? `${current.trim()}\n\n` : '';
      return `${prefix}Please review the deliverables here: ${driveShareLink}`;
    });
    setComposeOpen(true);
    setNotice('Drive link inserted into reply draft. Manual approval required.');
  };

  const updateDeliverableStatus = (id, status) => {
    setDeliverables((current) => current.map((item) => (item.id === id ? { ...item, status } : item)));
  };

  const removeDeliverable = (id) => {
    setDeliverables((current) => current.filter((item) => item.id !== id));
    setNotice('Deliverable removed from draft attachments.');
  };

  const toggleChecklistItem = (group, item) => {
    const checklistKey = selectedJobId || 'draft';
    const itemKey = `${group}:${item}`;
    setChecklistsByJob((current) => ({
      ...current,
      [checklistKey]: {
        ...(current[checklistKey] || {}),
        [itemKey]: !current[checklistKey]?.[itemKey],
      },
    }));
  };

  const startNewClientJob = () => {
    setSelectedJobId('');
    localStorage.removeItem('eva_selected_client_job_id');
    setAnalysis(null);
    setJobText('');
    setClientName('');
    setJobTitleDraft('');
    setClientFileName('');
    setClientPhotoName('');
    setUploadName('');
    setCadRequest('');
    setComposeTo('');
    setComposeSubject('');
    setComposeBody('');
    setGeneratedReply('');
    setEstimateDraft({});
    setDriveShareLink('');
    setDriveFolderStructure(null);
    setComposeOpen(true);
    setNotice('New client job draft opened.');
  };

  const requestCadPlan = async (mode = 'plan') => {
    if (!selectedWorkspaceId) {
      setCadNotice('Please create or select a workspace first.');
      return;
    }
    if (!cadRequest.trim()) {
      setCadNotice('Paste the client CAD request first.');
      return;
    }
    setCadLoading(true);
    setCadNotice('');
    try {
      const res = await fetch(`${API}/api/cad/${mode === 'analyze' ? 'analyze' : 'plan'}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          client_request: cadRequest,
          cad_software: cadSoftware,
          output_format: cadOutput,
          reference_filename: cadFileName || '',
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not generate CAD plan.');
      setCadResult(json);
      if (json.proposal_email_draft) {
        setComposeBody(json.proposal_email_draft);
        setComposeSubject((current) => current || 'Re: CAD client work');
        setComposeOpen(true);
      }
      setCadNotice(mode === 'analyze' ? 'CAD request analyzed locally. Manual approval required.' : 'CAD task plan and client reply draft generated locally.');
    } catch (err) {
      setCadNotice(friendlyErrorMessage(err, 'Could not generate CAD plan.'));
    } finally {
      setCadLoading(false);
    }
  };

  const checkCadWorkerStatus = async () => {
    setCadWorkerLoading('status');
    setCadNotice('');
    try {
      const res = await fetch(`${API}/api/cad/worker/status`, { headers: authHeaders() });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not check CAD worker status.');
      setCadWorkerStatus(json);
      setCadNotice(json.message || `CAD worker is ${json.enabled ? 'enabled' : 'disabled'}.`);
    } catch (err) {
      setCadNotice(friendlyErrorMessage(err, 'Could not check CAD worker status.'));
    } finally {
      setCadWorkerLoading('');
    }
  };

  const createCadWorkerPreview = async () => {
    if (!selectedWorkspaceId) {
      setCadNotice('Please create or select a workspace first.');
      return;
    }
    if (!cadRequest.trim()) {
      setCadNotice('Paste the client CAD request first.');
      return;
    }
    setCadWorkerLoading('preview');
    setCadNotice('');
    setCadWorkerRunResult(null);
    try {
      const outputList = [cadOutput];
      const analyzeRes = await fetch(`${API}/api/cad/analyze-job`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          request_text: cadRequest,
          software: cadSoftware,
          outputs: outputList,
        }),
      });
      const analysisJson = await analyzeRes.json().catch(() => ({}));
      if (!analyzeRes.ok) throw new Error(analysisJson.detail || 'Could not analyze CAD task for worker preview.');
      const previewRes = await fetch(`${API}/api/cad/worker/command-preview`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          task_type: analysisJson.task_type || 'AutoCAD drafting',
          software: 'Own CAD',
          instructions: `Target CAD software: ${cadSoftware}. Client request: ${cadRequest}`,
          outputs: outputList,
        }),
      });
      const previewJson = await previewRes.json().catch(() => ({}));
      if (!previewRes.ok) throw new Error(previewJson.detail || 'Could not create CAD command preview.');
      setCadWorkerPreview(previewJson);
      setCadNotice(previewJson.message || 'CAD command preview created. Approval required before running.');
    } catch (err) {
      setCadNotice(friendlyErrorMessage(err, 'Could not create CAD command preview.'));
    } finally {
      setCadWorkerLoading('');
    }
  };

  const approveAndRunCadWorker = async () => {
    const preview = cadWorkerPreview?.preview;
    if (!selectedWorkspaceId || !preview) {
      setCadNotice('Create a CAD command preview before approving a run.');
      return;
    }
    setCadWorkerLoading('run');
    setCadNotice('');
    try {
      const res = await fetch(`${API}/api/cad/worker/run-approved`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          task_type: preview.task_type,
          software: preview.software || 'Own CAD',
          instructions: preview.instructions,
          outputs: preview.outputs || [cadOutput],
          approved: true,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not run approved CAD worker command.');
      setCadWorkerRunResult(json);
      setCadNotice(json.message || 'Approved CAD worker request processed safely.');
    } catch (err) {
      setCadNotice(friendlyErrorMessage(err, 'Could not run approved CAD worker command.'));
    } finally {
      setCadWorkerLoading('');
    }
  };

  const analyzeJob = async () => {
    const requestForAnalysis = [
      clientName.trim() && `Client: ${clientName.trim()}`,
      jobTitleDraft.trim() && `Job title: ${jobTitleDraft.trim()}`,
      jobText.trim(),
    ].filter(Boolean).join('\n\n');
    if (!selectedWorkspaceId) {
      setFreelanceError('Please create or select a workspace first.');
      return;
    }
    if (!requestForAnalysis.trim()) {
      setFreelanceError('Paste a client request or upload a client request list before analyzing.');
      return;
    }
    setBusy(true);
    setNotice('');
    setFreelanceError('');
    try {
      const res = await fetch(`${API}/api/freelance/analyze`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          workspace_id: selectedWorkspaceId,
          job_text: requestForAnalysis,
          profile_skills: profileSkills(),
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Client request analysis failed.');
      setAnalysis(json);
      setSelectedJobId(json.job?.id || '');
      setComposeSubject(`Re: ${json.job?.job_title || json.job_title || jobTitleDraft || 'CAD client request'}`);
      setComposeBody(clientReplyBody(json));
      setGeneratedReply('');
      setEstimateDraft({});
      setDriveShareLink('');
      setDriveFolderStructure(null);
      setComposeOpen(true);
      setCadRequest(jobText);
      setStatusFilter('Draft');
      setNotice('Client request analyzed and saved to this workspace. Review manually before replying.');
      await loadJobs();
    } catch (err) {
      setFreelanceError(friendlyErrorMessage(err, 'EVA backend is offline. Draft tools are still available locally.'));
    } finally {
      setBusy(false);
    }
  };

  const viewJob = (job) => {
    const savedAnalysis = job.analysis || {};
    const nextAnalysis = {
      ok: true,
      workspace_id: job.workspace_id,
      job_title: job.job_title,
      fit_score: job.fit_score,
      recommendation: job.recommendation,
      proposal_short: job.proposal,
      ...savedAnalysis,
    };
    setAnalysis(nextAnalysis);
    setJobText(job.job_text || '');
    setCadRequest(job.job_text || '');
    setJobTitleDraft(clientJobTitle(job));
    setClientName('');
    setClientFileName('');
    setClientPhotoName('');
    setUploadName('');
    setSelectedJobId(job.id);
    localStorage.setItem('eva_selected_client_job_id', job.id);
    setComposeSubject(`Re: ${clientJobTitle(job)}`);
    setComposeBody(clientReplyBody(nextAnalysis));
    setGeneratedReply('');
    setEstimateDraft({});
    setDriveShareLink(savedAnalysis.google_drive?.share_link || '');
    setDriveFolderStructure(savedAnalysis.google_drive?.folder_structure || null);
    setComposeOpen(true);
    setNotice('Saved client reply loaded for review.');
  };

  const updateJobStatus = async (job, status) => {
    if (!selectedWorkspaceId) return;
    setFreelanceError('');
    try {
      const res = await fetch(`${API}/api/freelance/jobs/${job.id}/status`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ workspace_id: selectedWorkspaceId, status }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Could not update client job status.');
      const updatedAt = new Date().toISOString();
      setJobs((current) => current.map((item) => (item.id === job.id ? { ...json.job, updated_at: updatedAt } : item)));
      setNotice(`Client job marked as ${status}.`);
    } catch (err) {
      setFreelanceError(friendlyErrorMessage(err, 'Could not update client job status.'));
    }
  };

  const changeSelectedStatus = async (status) => {
    const selectedJob = jobs.find((job) => job.id === selectedJobId);
    if (!selectedJob) {
      setNotice('Select or save a client job before changing status.');
      return;
    }
    await updateJobStatus(selectedJob, status);
  };

  const saveDraft = async () => {
    const draft = {
      to: composeTo,
      subject: composeSubject,
      body: composeBody,
      attachments,
      deliverables,
      driveShareLink,
      saved_at: new Date().toISOString(),
    };
    localStorage.setItem('eva_client_job_compose_draft', JSON.stringify(draft));
    const selectedJob = jobs.find((job) => job.id === selectedJobId);
    if (selectedJob) {
      await updateJobStatus(selectedJob, 'Draft');
      return;
    }
    setNotice('Draft saved locally. Analyze the client request to save it inside this workspace.');
  };

  const copyReply = async () => {
    const text = generatedReply || composeBody || clientReplyBody(analysis);
    if (!text.trim()) {
      setNotice('Generate or write a client reply draft first.');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setNotice('Client reply copied. Review manually before sending.');
    } catch {
      setFreelanceError('Could not copy reply. Select the text and copy it manually.');
    }
  };

  const buildClientReplyFallback = () => {
    const deliverableLines = deliverables.length
      ? deliverables.map((file) => `- ${file.name} (${file.status})`).join('\n')
      : `- ${cadOutput || 'Required CAD output'}\n- Reviewed source/reference files if provided`;
    const planLines = cadResult?.task_plan?.length
      ? cadResult.task_plan.map((item) => `- ${item}`).join('\n')
      : '- Review the request, confirm dimensions/units, complete CAD work, export final files, and quality check deliverables.';
    const missingQuestions = [];
    if (!cadFileName) missingQuestions.push('Could you please share the source/reference CAD or drawing file if available?');
    if (!cadRequest.toLowerCase().includes('unit') && !jobText.toLowerCase().includes('unit')) missingQuestions.push('Please confirm the required units and any critical dimensions.');
    if (!deliverables.length) missingQuestions.push('Please confirm the exact final formats you want delivered.');
    const questions = missingQuestions.length ? missingQuestions.map((item) => `- ${item}`).join('\n') : '- I have the key details needed to proceed.';
    const timeline = qualityProgress.complete ? 'I can prepare this for your review after final file packaging.' : 'I can share a first reviewed draft after confirming the remaining details.';

    return `Hi,\n\nThanks for sharing the CAD request. I understand that you need ${cadSoftware} support for ${cadRequest || jobText || 'the requested CAD work'}.\n\nPlanned deliverables:\n${deliverableLines}\n\nWork plan:\n${planLines}\n\nA few details to confirm:\n${questions}\n\nTimeline: ${timeline}\n\nI will review the files and final exports carefully before sending anything over.\n\nBest regards,`;
  };

  const generateClientReply = async () => {
    const requestText = cadRequest.trim() || jobText.trim();
    if (!requestText) {
      setNotice('Paste or select a client request before generating a reply.');
      return;
    }
    const cadDone = cadTaskChecklistItems.filter((item) => activeChecklist[`cadTask:${item}`]);
    const qualityDone = qualityCheckItems.filter((item) => activeChecklist[`quality:${item}`]);
    const ragSummary = [
      uploadName && `Client request list: ${uploadName}`,
      cadFileName && `CAD/reference file: ${cadFileName}`,
      cadResult?.summary && `CAD summary: ${cadResult.summary}`,
      cadResult?.task_type && `Task type: ${cadResult.task_type}`,
    ].filter(Boolean).join('\n') || 'No extra RAG summary is available. Use the visible client request and attachments only.';
    const prompt = `Generate a clear client reply draft for CAD client work. Do not include a send instruction. Keep it professional, concise, and ready for manual review.\n\nRequired sections:\n- Greeting\n- Short work understanding\n- Deliverables list\n- Questions if information is missing\n- Timeline estimate\n- Closing\n\nClient request:\n${requestText}\n\nWorkspace/job context:\nWorkspace ID: ${selectedWorkspaceId || 'not selected'}\nJob title: ${selectedJob ? clientJobTitle(selectedJob) : 'New client request'}\nSoftware: ${cadSoftware}\nPlanned output: ${cadOutput}\n\nRAG/context summary:\n${ragSummary}\n\nCAD task plan:\n${cadResult?.task_plan?.length ? cadResult.task_plan.join('\n') : 'No generated CAD task plan yet.'}\n\nCAD task checklist completed:\n${cadDone.length ? cadDone.join('\n') : 'None checked yet.'}\n\nQuality check completed:\n${qualityDone.length ? qualityDone.join('\n') : 'None checked yet.'}\n\nDeliverables attached:\n${deliverables.length ? deliverables.map((file) => `${file.name} (${file.status})`).join('\n') : 'No deliverables attached yet.'}`;

    setReplyLoading(true);
    setFreelanceError('');
    setNotice('');
    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          question: prompt,
          workspace_id: selectedWorkspaceId || 'default',
          user_id: 'client_jobs',
          memory_enabled: false,
        }),
      });
      const json = await res.json().catch(() => ({}));
      const answer = json.answer || json.response || json.message || '';
      if (!res.ok || !String(answer).trim()) throw new Error(json.detail || 'EVA model router unavailable.');
      setGeneratedReply(String(answer).trim());
      setNotice('Client reply generated with EVA. Review before applying or copying.');
    } catch {
      const fallback = buildClientReplyFallback();
      setGeneratedReply(fallback);
      setNotice('EVA model router unavailable. Template fallback generated for manual review.');
    } finally {
      setReplyLoading(false);
      setComposeOpen(true);
    }
  };

  const applyGeneratedReply = () => {
    if (!generatedReply.trim()) {
      setNotice('Generate a client reply first.');
      return;
    }
    setComposeBody(generatedReply);
    setComposeSubject((current) => current || `Re: ${selectedJob ? clientJobTitle(selectedJob) : 'CAD client request'}`);
    setNotice('Generated reply applied to draft. Manual approval required.');
  };

  const markReady = async () => {
    const selectedJob = jobs.find((job) => job.id === selectedJobId);
    if (!selectedJob) {
      setNotice('Analyze and save the client request before marking it ready.');
      return;
    }
    await updateJobStatus(selectedJob, 'Ready to Send');
  };

  const exportTrainingData = async () => {
    if (!selectedWorkspaceId) {
      setFreelanceError('Please create or select a workspace first.');
      return;
    }
    setFreelanceError('');
    try {
      const params = new URLSearchParams({ workspace_id: selectedWorkspaceId });
      const res = await fetch(`${API}/api/freelance/export?${params.toString()}`, { headers: authHeaders(null) });
      if (!res.ok) {
        const json = await res.json().catch(() => ({}));
        throw new Error(json.detail || 'Could not export client job training data.');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `eva-client-job-training-${selectedWorkspaceId}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setNotice('Client job training data exported.');
    } catch (err) {
      setFreelanceError(friendlyErrorMessage(err, 'Could not export client job training data.'));
    }
  };

  const result = analysis || {};
  const scoreColor = Number(result.fit_score || 0) >= 75 ? '#34d399' : Number(result.fit_score || 0) >= 55 ? '#fbbf24' : '#f87171';
  const selectedJob = jobs.find((job) => job.id === selectedJobId) || null;
  const selectedStatus = clientJobStatus(selectedJob?.status);
  const activeChecklistKey = selectedJobId || 'draft';
  const activeChecklist = checklistsByJob[activeChecklistKey] || {};
  const checklistProgress = (items, group) => {
    const completed = items.filter((item) => activeChecklist[`${group}:${item}`]).length;
    return { completed, total: items.length, complete: completed === items.length };
  };
  const cadTaskProgress = checklistProgress(cadTaskChecklistItems, 'cadTask');
  const qualityProgress = checklistProgress(qualityCheckItems, 'quality');
  const jobQuery = jobSearch.trim().toLowerCase();
  const filteredJobs = jobs.filter((job) => {
    const status = clientJobStatus(job.status);
    const haystack = `${job.job_title || ''} ${job.job_text || ''} ${job.recommendation || ''}`.toLowerCase();
    return status === statusFilter && (!jobQuery || haystack.includes(jobQuery));
  });
  const statusCounts = clientJobStatuses.reduce((acc, status) => {
    acc[status] = jobs.filter((job) => clientJobStatus(job.status) === status).length;
    return acc;
  }, {});
  const attachments = [
    clientFileName && `Client file: ${clientFileName}`,
    clientPhotoName && `Client photo: ${clientPhotoName}`,
    uploadName && uploadName !== clientFileName && `Client request list: ${uploadName}`,
    cadFileName && `CAD reference: ${cadFileName}`,
    cadOutput && `Planned output: ${cadOutput}`,
    ...deliverables.map((file) => `Deliverable: ${file.name} (${file.status})`),
    driveShareLink && `Drive share link: ${driveShareLink}`,
  ].filter(Boolean);
  const requestContext = `${clientName} ${jobTitleDraft} ${jobText} ${cadRequest}`.toLowerCase();
  const ragContext = [
    uploadName,
    cadFileName,
    cadResult?.summary,
    cadResult?.task_type,
    ...(Array.isArray(cadResult?.task_plan) ? cadResult.task_plan : []),
  ].filter(Boolean).join(' ').toLowerCase();
  const clientQuestions = (() => {
    const questions = [];
    const addQuestion = (question) => {
      if (!questions.includes(question)) questions.push(question);
    };
    if (Array.isArray(cadResult?.agent_questions)) {
      cadResult.agent_questions.forEach(addQuestion);
    }
    if (!/\b(dwg|dxf|step|stp|pdf|png|format|formats|deliverable|export)\b/.test(requestContext)) {
      addQuestion('What final file formats do you need?');
    }
    if (!/\b(mm|millimeter|millimeters|inch|inches|unit|units|cm|meter|metre)\b/.test(requestContext)) {
      addQuestion('Are the dimensions in mm or inches?');
    }
    if (!/\b(2d|3d|drawing|drawings|model|models)\b/.test(requestContext)) {
      addQuestion('Do you need 2D drawing, 3D model, or both?');
    }
    if (!/\b(manufacturing|fabrication|tolerance|tolerances|bom|assembly|shop drawing)\b/.test(requestContext) || /\b(manufacturing|sheet metal|cnc|fabrication)\b/.test(ragContext)) {
      addQuestion('Should I include manufacturing drawings?');
    }
    if (!cadFileName && !/\b(reference|image|photo|source|cad file|dwg|dxf|step|stp|sldprt|sldasm)\b/.test(ragContext)) {
      addQuestion('Do you have reference images or source CAD files?');
    }
    if (!activeChecklist['cadTask:Check units and dimensions']) {
      addQuestion('Are there any critical dimensions, tolerances, or scale requirements I should follow?');
    }
    if (!activeChecklist['cadTask:Export required formats'] && !deliverables.some((file) => file.status === 'Ready')) {
      addQuestion('Which final exports should I prepare for delivery?');
    }
    if (!/\b(deadline|urgent|today|tomorrow|hours|days|date)\b/.test(requestContext)) {
      addQuestion('What deadline or review date should I plan for?');
    }
    return questions.slice(0, 6);
  })();
  const clientQuestionsText = clientQuestions.map((question) => `- ${question}`).join('\n');
  const suggestedEstimate = (() => {
    const estimateText = `${requestContext} ${ragContext} ${cadSoftware} ${cadOutput}`.toLowerCase();
    if (/\b(manufacturing drawing|manufacturing drawings|drawing package|fabrication drawing|fabrication drawings|tolerance|tolerances|bom|assembly drawing)\b/.test(estimateText)) {
      return {
        complexity: 'High',
        estimatedTime: '6-15 hours',
        priceRange: '$100-$300',
        reason: 'Manufacturing drawing packages need full dimensioning, tolerances, title blocks, exports, and careful review.',
      };
    }
    if (/\b(3d model|3d modeling|model from sketch|from sketch|product model|render|rendering|concept sketch)\b/.test(estimateText)) {
      return {
        complexity: 'High',
        estimatedTime: '4-10 hours',
        priceRange: '$80-$200',
        reason: 'Creating a 3D model from sketch or reference usually needs interpretation, modeling, revisions, and export checks.',
      };
    }
    if (/\b(cnc|dxf|flat pattern|laser cut|plasma|waterjet|sheet metal)\b/.test(estimateText)) {
      return {
        complexity: 'Medium',
        estimatedTime: '2-6 hours',
        priceRange: '$40-$120',
        reason: 'CNC/DXF or flat-pattern work needs clean geometry, scale checks, and machine-ready export review.',
      };
    }
    if (/\b(solidworks|sldprt|sldasm)\b/.test(estimateText) && /\b(minor|small|quick|edit|modify|change|revision|fix)\b/.test(estimateText)) {
      return {
        complexity: 'Low',
        estimatedTime: '1-2 hours',
        priceRange: '$15-$50',
        reason: 'Minor SolidWorks edits are usually limited changes when the source file and dimensions are clear.',
      };
    }
    if (/\b(pdf)\b/.test(estimateText) && /\b(dwg|autocad|trace|convert|redraw)\b/.test(estimateText)) {
      return {
        complexity: 'Low',
        estimatedTime: '2-4 hours',
        priceRange: '$20-$60',
        reason: 'Simple PDF to DWG drafting is typically a short redraw/cleanup task when dimensions and scale are available.',
      };
    }
    return {
      complexity: 'Medium',
      estimatedTime: '3-6 hours',
      priceRange: '$50-$150',
      reason: 'This looks like a general CAD task; final time and price depend on source files, dimensions, revisions, and output formats.',
    };
  })();
  const activeEstimate = {
    complexity: estimateDraft.complexity || suggestedEstimate.complexity,
    estimatedTime: estimateDraft.estimatedTime || suggestedEstimate.estimatedTime,
    priceRange: estimateDraft.priceRange || suggestedEstimate.priceRange,
    reason: estimateDraft.reason || suggestedEstimate.reason,
  };
  const updateEstimateField = (field, value) => {
    setEstimateDraft((current) => ({ ...current, [field]: value }));
  };
  const addEstimateToDraft = () => {
    const estimateText = [
      'Timeline and price estimate:',
      `- Complexity: ${activeEstimate.complexity}`,
      `- Estimated time: ${activeEstimate.estimatedTime}`,
      `- Suggested price range: ${activeEstimate.priceRange}`,
      `- Reason: ${activeEstimate.reason}`,
      '',
      'This is an estimate for review and can be adjusted after confirming the final requirements.',
    ].join('\n');
    setComposeBody((current) => {
      const prefix = current.trim() ? `${current.trim()}\n\n` : '';
      return `${prefix}${estimateText}`;
    });
    setComposeOpen(true);
    setNotice('Estimate added to reply draft. Review and edit before sending manually.');
  };

  const addQuestionsToDraft = () => {
    if (!clientQuestionsText) {
      setNotice('No client questions are available yet.');
      return;
    }
    setComposeBody((current) => {
      const prefix = current.trim() ? `${current.trim()}\n\n` : '';
      return `${prefix}Questions to confirm:\n${clientQuestionsText}`;
    });
    setComposeOpen(true);
    setNotice('Client questions added to reply draft. Review before sending manually.');
  };

  const copyClientQuestions = async () => {
    if (!clientQuestionsText) {
      setNotice('No client questions are available yet.');
      return;
    }
    try {
      await navigator.clipboard.writeText(clientQuestionsText);
      setNotice('Client questions copied. Review manually before sending.');
    } catch {
      setFreelanceError('Could not copy questions. Select the questions and copy them manually.');
    }
  };
  const prepareDeliverables = () => {
    setComposeOpen(true);
    setNotice('Attach final CAD deliverables, check file status, then save the draft for manual review.');
  };
  const hasClientRequest = [clientName, jobTitleDraft, jobText, cadRequest].some((value) => String(value || '').trim());
  const hasUploadedFiles = Boolean(clientFileName || clientPhotoName || uploadName || cadFileName);
  const hasEvaAnalysis = Boolean(analysis);
  const hasCadPlan = Boolean(cadResult?.task_plan?.length);
  const hasChecklist = cadTaskProgress.completed > 0
    || qualityProgress.completed > 0
    || Boolean(cadResult?.agent_checklist?.length);
  const hasDeliverables = deliverables.length > 0;
  const hasReplyDraft = Boolean(composeBody.trim() || generatedReply.trim() || clientReplyBody(analysis).trim());
  const isReady = selectedStatus === 'Ready to Send' || selectedStatus === 'Completed';
  const focusClientRequest = () => {
    requestInputRef.current?.focus();
    setNotice('Paste the client request, then use Analyze Request.');
  };
  const openClientFilePicker = () => {
    clientFileInputRef.current?.click();
  };
  const openDeliverablePicker = () => {
    deliverableInputRef.current?.click();
  };
  const createChecklist = () => {
    setCadResult((current) => ({
      ...(current || {}),
      agent_checklist: current?.agent_checklist?.length ? current.agent_checklist : [
        'Review client request',
        'Confirm units and dimensions',
        'Create or edit CAD drawing/model',
        'Export required formats',
        'Attach final deliverables',
        'Quality check before manual sending',
      ],
    }));
    setNotice('Checklist created locally. Review and tick items manually.');
  };
  const nextAction = (() => {
    if (!hasClientRequest) {
      return {
        title: 'Paste client request',
        detail: 'Add the client request before EVA can analyze this job.',
        button: 'Paste Request',
        onClick: focusClientRequest,
        disabled: false,
      };
    }
    if (!hasUploadedFiles) {
      return {
        title: 'Upload client files',
        detail: 'Attach the client PDF, CAD file, reference image, or ZIP for context.',
        button: 'Upload File',
        onClick: openClientFilePicker,
        disabled: false,
      };
    }
    if (!hasEvaAnalysis) {
      return {
        title: 'Analyze request',
        detail: 'Score the client job and save the analysis in this workspace.',
        button: 'Analyze Request',
        onClick: analyzeJob,
        disabled: busy || !selectedWorkspaceId,
      };
    }
    if (!hasCadPlan) {
      return {
        title: 'Generate CAD plan',
        detail: 'Create a CAD task plan before starting work.',
        button: 'Generate CAD Plan',
        onClick: () => requestCadPlan('plan'),
        disabled: cadLoading || !selectedWorkspaceId || !cadRequest.trim(),
      };
    }
    if (!hasChecklist) {
      return {
        title: 'Create checklist',
        detail: 'Prepare the CAD work and quality checklist for manual review.',
        button: 'Create Checklist',
        onClick: createChecklist,
        disabled: false,
      };
    }
    if (!hasDeliverables) {
      return {
        title: 'Attach deliverables',
        detail: 'Attach final CAD outputs before drafting the client handoff.',
        button: 'Attach Deliverables',
        onClick: openDeliverablePicker,
        disabled: false,
      };
    }
    if (!hasReplyDraft) {
      return {
        title: 'Generate client reply',
        detail: 'Draft a reply for manual approval. EVA will not send email.',
        button: 'Generate Reply',
        onClick: generateClientReply,
        disabled: replyLoading || !hasClientRequest,
      };
    }
    if (!isReady) {
      return {
        title: 'Review and mark ready',
        detail: 'Review the request, plan, deliverables, and reply before marking ready.',
        button: 'Mark Ready',
        onClick: markReady,
        disabled: !selectedJob,
      };
    }
    return {
      title: 'Copy reply and send manually',
      detail: 'Copy the reviewed reply. EVA will not send or submit anything.',
      button: 'Copy Reply',
      onClick: copyReply,
      disabled: !hasReplyDraft,
    };
  })();
  const aiActions = [
    { label: 'Analyze Request', detail: 'Score and save this client job', onClick: analyzeJob, disabled: busy || !selectedWorkspaceId || !hasClientRequest },
    { label: 'Generate CAD Plan', detail: 'Create a task plan from the request', onClick: () => requestCadPlan('plan'), disabled: cadLoading || !selectedWorkspaceId || !cadRequest.trim() },
    { label: 'Generate Client Reply', detail: 'Draft a manual reply', onClick: generateClientReply, disabled: replyLoading || !hasClientRequest },
    { label: 'Create Questions', detail: 'Add missing-detail questions', onClick: addQuestionsToDraft, disabled: !clientQuestionsText },
    { label: 'Estimate Time & Price', detail: `${activeEstimate.estimatedTime} / ${activeEstimate.priceRange}`, onClick: addEstimateToDraft, disabled: false },
    { label: 'Prepare Deliverables', detail: 'Review final attachments', onClick: prepareDeliverables, disabled: false },
    { label: 'Save Draft', detail: 'Store reply locally', onClick: saveDraft, disabled: false },
  ];

  return (
    <div style={S.stack}>
      <section style={S.clientJobsTop}>
        <div>
          <div style={S.sectionTitle}>Client Jobs</div>
          <p style={S.muted}>
            Gmail-style request desk for CAD work. Draft only, manual approval required, no email sending.
          </p>
        </div>
        <button type="button" onClick={exportTrainingData} disabled={!selectedWorkspaceId || historyLoading} style={{ ...S.secondaryButton, opacity: !selectedWorkspaceId ? 0.55 : 1 }}>
          Export Client Training Data
        </button>
      </section>

      {!selectedWorkspaceId && (
        <div style={S.error}>Please create or select a workspace first.</div>
      )}
      {(freelanceError || notice) && (
        <div style={freelanceError ? S.error : S.success}>{freelanceError || notice}</div>
      )}

      <section style={S.detailSection}>
        <div style={S.sectionTitle}>Google Drive</div>
        <div style={S.driveStatusRow}>
          <div>
            <strong>{driveStatus?.connected ? 'Google Drive: Connected' : 'Google Drive: Not Connected'}</strong>
            <p style={S.muted}>
              {driveStatus?.connected ? 'Google Drive connected. You can save deliverables.' : 'Google Drive is not connected.'}
            </p>
          </div>
          <div style={S.buttonRow}>
            <button type="button" onClick={connectGoogleDrive} disabled={driveLoading === 'status'} style={{ ...S.secondaryButton, opacity: driveLoading === 'status' ? 0.55 : 1 }}>
              Connect Google Drive
            </button>
            <button type="button" onClick={() => refreshDriveStatus(false)} disabled={driveLoading === 'status'} style={{ ...S.secondaryButton, opacity: driveLoading === 'status' ? 0.55 : 1 }}>
              {driveLoading === 'status' ? 'Refreshing' : 'Refresh Status'}
            </button>
          </div>
        </div>
      </section>

      <div className="client-jobs-layout" style={S.clientJobsLayout}>
        <aside style={S.mailPanel}>
          <div style={S.mailPanelTitle}>Client job list</div>
          <input
            value={jobSearch}
            onChange={(event) => setJobSearch(event.target.value)}
            placeholder="Search jobs"
            style={S.input}
          />
          <div style={S.statusFilterList}>
            {clientJobStatuses.map((status) => (
              <button
                key={status}
                type="button"
                onClick={() => setStatusFilter(status)}
                style={{ ...S.statusFilter, ...(statusFilter === status ? S.statusFilterActive : {}) }}
              >
                <span>{status}</span>
                <strong>{statusCounts[status] || 0}</strong>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={startNewClientJob}
            style={S.secondaryButton}
          >
            + New Client Job
          </button>
          <div style={S.mailList}>
            {historyLoading ? (
              <div style={S.emptyState}>Loading client jobs...</div>
            ) : filteredJobs.length === 0 ? (
              <div style={S.emptyState}>
                {jobs.length === 0 ? 'No client jobs yet. Create your first client job.' : `No client jobs in ${statusFilter}.`}
              </div>
            ) : (
              filteredJobs.map((job) => (
                <button
                  key={job.id}
                  className="client-mail-item"
                  type="button"
                  onClick={() => viewJob(job)}
                  style={{ ...S.mailItem, ...(selectedJobId === job.id ? S.mailItemActive : {}) }}
                >
                  <span style={S.mailItemTitle}>{clientJobTitle(job)}</span>
                  <span style={S.statusBadge}>{clientJobStatus(job.status)}</span>
                  <span>{(job.job_text || '').slice(0, 96) || 'No request text saved.'}</span>
                  <span style={S.mailItemMeta}>
                    <strong>Last updated</strong>
                    <em>{formatDate(clientJobUpdatedAt(job))}</em>
                  </span>
                </button>
              ))
            )}
          </div>
        </aside>

        <main style={S.detailPanel}>
          <div style={S.detailHeader}>
            <div style={{ minWidth: 0 }}>
              <div style={S.detailTitle}>{selectedJob ? clientJobTitle(selectedJob) : 'New client request'}</div>
              <div style={S.muted}>
                Status: {selectedJob ? selectedStatus : 'Draft'} | Last updated: {selectedJob ? formatDate(clientJobUpdatedAt(selectedJob)) : 'Not saved'} | Manual approval required
              </div>
            </div>
            {analysis && (
              <div style={{ ...S.scorePill, color: scoreColor }}>
                {result.fit_score || 0}
                <span>fit</span>
              </div>
            )}
          </div>
          <div style={S.statusActionRow}>
            <button type="button" onClick={() => changeSelectedStatus('Draft')} disabled={!selectedJob || selectedStatus === 'Draft'} style={{ ...S.secondaryButton, opacity: !selectedJob || selectedStatus === 'Draft' ? 0.55 : 1 }}>Move to Draft</button>
            <button type="button" onClick={() => changeSelectedStatus('In Progress')} disabled={!selectedJob || selectedStatus === 'In Progress'} style={{ ...S.secondaryButton, opacity: !selectedJob || selectedStatus === 'In Progress' ? 0.55 : 1 }}>Start Work</button>
            <button type="button" onClick={() => changeSelectedStatus('Ready to Send')} disabled={!selectedJob || selectedStatus === 'Ready to Send'} style={{ ...S.secondaryButton, opacity: !selectedJob || selectedStatus === 'Ready to Send' ? 0.55 : 1 }}>Mark Ready</button>
            <button type="button" onClick={() => changeSelectedStatus('Completed')} disabled={!selectedJob || selectedStatus === 'Completed'} style={{ ...S.secondaryButton, opacity: !selectedJob || selectedStatus === 'Completed' ? 0.55 : 1 }}>Mark Completed</button>
          </div>

          <section style={S.nextActionCard}>
            <div style={{ minWidth: 0 }}>
              <div style={S.nextActionEyebrow}>Next Action</div>
              <div style={S.nextActionTitle}>{nextAction.title}</div>
              <p style={{ ...S.muted, margin: '5px 0 0' }}>{nextAction.detail}</p>
            </div>
            <button
              type="button"
              onClick={nextAction.onClick}
              disabled={nextAction.disabled}
              style={{ ...S.primaryButton, opacity: nextAction.disabled ? 0.55 : 1 }}
            >
              {nextAction.button}
            </button>
          </section>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>{selectedJob ? 'Selected Job Workspace' : 'Create Client Job'}</div>
            <div className="studio-grid-2" style={S.grid2}>
              <Field label="Client name">
                <input value={clientName} onChange={(event) => setClientName(event.target.value)} placeholder="Client name" style={S.input} />
              </Field>
              <Field label="Job title">
                <input value={jobTitleDraft} onChange={(event) => setJobTitleDraft(event.target.value)} placeholder="CAD redraw, product model, drawing package..." style={S.input} />
              </Field>
              <Field label="CAD software">
                <select value={cadSoftware} onChange={(event) => setCadSoftware(event.target.value)} style={S.input}>
                  {['AutoCAD', 'SolidWorks', 'Fusion 360', 'FreeCAD', 'Onshape'].map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              </Field>
              <Field label="Required output">
                <select value={cadOutput} onChange={(event) => setCadOutput(event.target.value)} style={S.input}>
                  {['DWG', 'DXF', 'STEP/STP', 'PDF', 'PNG'].map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              </Field>
            </div>
            <textarea
              ref={requestInputRef}
              value={jobText}
              onChange={(event) => {
                setJobText(event.target.value);
                setCadRequest(event.target.value);
              }}
              placeholder="Paste the client request here..."
              style={{ ...S.textarea, minHeight: 130, marginTop: 10 }}
            />
            <div className="client-jobs-compact" style={S.compactRow}>
              <Field label="Profile skills">
                <input value={skillsText} onChange={(event) => setSkillsText(event.target.value)} style={S.input} />
              </Field>
              <div style={S.buttonRow}>
                <label style={{ ...S.secondaryButton, display: 'inline-grid', placeItems: 'center' }}>
                  Upload file
                  <input
                    ref={clientFileInputRef}
                    type="file"
                    name="file"
                    accept=".pdf,.dwg,.dxf,.step,.stp,.png,.jpg,.jpeg,.zip"
                    onChange={(event) => handleJobFile(event, 'file')}
                    style={{ display: 'none' }}
                  />
                </label>
                <label style={{ ...S.secondaryButton, display: 'inline-grid', placeItems: 'center' }}>
                  Upload photo
                  <input
                    type="file"
                    name="file"
                    accept=".png,.jpg,.jpeg"
                    onChange={(event) => handleJobFile(event, 'photo')}
                    style={{ display: 'none' }}
                  />
                </label>
                <button type="button" onClick={analyzeJob} disabled={busy || !selectedWorkspaceId || !hasClientRequest} style={{ ...S.primaryButton, opacity: busy || !selectedWorkspaceId || !hasClientRequest ? 0.55 : 1 }}>
                  {busy ? 'Analyzing' : 'Analyze & Save'}
                </button>
              </div>
            </div>
            <p style={S.muted}>Draft only. Files stay in local draft state here unless an existing safe workspace endpoint is used later.</p>
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>Uploaded files</div>
            {attachments.length === 0 ? (
              <div style={S.emptyState}>No client files attached yet.</div>
            ) : (
              <div style={S.tagWrap}>
                {attachments.map((item) => <span key={item} style={S.tag}>{item}</span>)}
              </div>
            )}
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>Questions to Ask Client</div>
            <p style={S.muted}>EVA suggests these from the request, available context, checklist progress, and missing deliverable details.</p>
            <ul style={S.cleanList}>
              {clientQuestions.map((question) => <li key={question}>{question}</li>)}
            </ul>
            <div style={S.buttonRow}>
              <button type="button" onClick={addQuestionsToDraft} style={S.secondaryButton}>Add to Reply Draft</button>
              <button type="button" onClick={copyClientQuestions} style={S.secondaryButton}>Copy Questions</button>
            </div>
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>Timeline & Price Estimate</div>
            <p style={S.muted}>Rule-based suggestion only. Edit the estimate before adding it to a client reply.</p>
            <div className="studio-grid-2" style={S.grid2}>
              <Field label="Complexity">
                <select value={activeEstimate.complexity} onChange={(event) => updateEstimateField('complexity', event.target.value)} style={S.input}>
                  {estimateComplexities.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </Field>
              <Field label="Estimated time">
                <input value={activeEstimate.estimatedTime} onChange={(event) => updateEstimateField('estimatedTime', event.target.value)} style={S.input} />
              </Field>
              <Field label="Suggested price range">
                <input value={activeEstimate.priceRange} onChange={(event) => updateEstimateField('priceRange', event.target.value)} style={S.input} />
              </Field>
              <Field label="Reason for estimate">
                <textarea value={activeEstimate.reason} onChange={(event) => updateEstimateField('reason', event.target.value)} style={S.shortTextarea} />
              </Field>
            </div>
            <div style={S.buttonRow}>
              <button type="button" onClick={addEstimateToDraft} style={S.secondaryButton}>Add estimate to reply draft</button>
            </div>
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>CAD Client Work</div>
            <p style={S.muted}>CAD worker runs locally only. Manual approval required. Email sending disabled.</p>
            <div className="studio-grid-2" style={S.grid2}>
              <Field label="CAD software">
                <select value={cadSoftware} onChange={(event) => setCadSoftware(event.target.value)} style={S.input}>
                  {['AutoCAD', 'SolidWorks', 'Fusion 360', 'FreeCAD', 'Onshape'].map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              </Field>
              <Field label="Output">
                <select value={cadOutput} onChange={(event) => setCadOutput(event.target.value)} style={S.input}>
                  {['DWG', 'DXF', 'STEP/STP', 'PDF', 'PNG'].map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              </Field>
            </div>
            <textarea
              value={cadRequest}
              onChange={(event) => setCadRequest(event.target.value)}
              placeholder="CAD-specific notes, dimensions, drawing requirements..."
              style={{ ...S.shortTextarea, marginTop: 10 }}
            />
            <div style={S.buttonRow}>
              <label style={{ ...S.secondaryButton, display: 'inline-grid', placeItems: 'center' }}>
                Upload CAD/reference file
                <input
                  type="file"
                  name="file"
                  accept=".pdf,.dwg,.dxf,.step,.stp,.sldprt,.sldasm,.png,.jpg,.jpeg"
                  onChange={handleCadFile}
                  style={{ display: 'none' }}
                />
              </label>
              <button type="button" onClick={() => requestCadPlan('analyze')} disabled={cadLoading || !cadRequest.trim()} style={{ ...S.secondaryButton, opacity: cadLoading || !cadRequest.trim() ? 0.55 : 1 }}>
                Analyze CAD Task
              </button>
              <button type="button" onClick={() => requestCadPlan('plan')} disabled={cadLoading || !cadRequest.trim()} style={{ ...S.primaryButton, opacity: cadLoading || !cadRequest.trim() ? 0.55 : 1 }}>
                {cadLoading ? 'Drafting' : 'Create Task Plan'}
              </button>
            </div>
            {cadNotice && <div style={{ ...S.muted, marginTop: 8 }}>{cadNotice}</div>}
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>CAD task plan</div>
            {cadResult?.task_type && <InfoRow label="Task type" value={cadResult.task_type} />}
            {cadResult?.software && <InfoRow label="CAD software" value={cadResult.software} />}
            {Array.isArray(cadResult?.deliverables) && cadResult.deliverables.length > 0 && (
              <InfoRow label="Required outputs" value={cadResult.deliverables.join(', ')} />
            )}
            {cadResult?.task_plan?.length ? (
              <ol style={S.cleanList}>
                {cadResult.task_plan.map((item) => <li key={item}>{item}</li>)}
              </ol>
            ) : (
              <div style={S.emptyState}>Create a CAD task plan to see the checklist.</div>
            )}
            {Array.isArray(cadResult?.agent_checklist) && cadResult.agent_checklist.length > 0 && (
              <div style={S.workerBox}>
                <strong>Agent checklist</strong>
                {cadResult.agent_checklist.map((item) => <span key={item}>{item}</span>)}
              </div>
            )}
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>CAD Task Checklist</div>
            <div style={S.muted}>{cadTaskProgress.completed}/{cadTaskProgress.total} completed</div>
            <div style={S.checklist}>
              {cadTaskChecklistItems.map((item) => (
                <label key={item} style={S.checkItem}>
                  <input
                    type="checkbox"
                    checked={!!activeChecklist[`cadTask:${item}`]}
                    onChange={() => toggleChecklistItem('cadTask', item)}
                  />
                  <span>{item}</span>
                </label>
              ))}
            </div>
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>Quality Check</div>
            <div style={S.muted}>{qualityProgress.completed}/{qualityProgress.total} completed</div>
            <div style={S.checklist}>
              {qualityCheckItems.map((item) => (
                <label key={item} style={S.checkItem}>
                  <input
                    type="checkbox"
                    checked={!!activeChecklist[`quality:${item}`]}
                    onChange={() => toggleChecklistItem('quality', item)}
                  />
                  <span>{item}</span>
                </label>
              ))}
            </div>
            {qualityProgress.complete && (
              <div style={S.success}>Ready for client review</div>
            )}
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>Deliverables</div>
            <p style={S.muted}>Attach final CAD deliverables to the draft. Nothing is sent automatically.</p>
            <div style={S.buttonRow}>
              <label style={{ ...S.secondaryButton, display: 'inline-grid', placeItems: 'center' }}>
                Upload Deliverable
                  <input
                    ref={deliverableInputRef}
                    type="file"
                    name="file"
                    accept=".dwg,.dxf,.step,.stp,.pdf,.png,.jpg,.jpeg,.zip"
                  onChange={handleDeliverableFile}
                  style={{ display: 'none' }}
                />
              </label>
              <button type="button" onClick={saveDeliverablesToDrive} disabled={!!driveLoading || !selectedJobId || !deliverables.length} style={{ ...S.secondaryButton, opacity: driveLoading || !selectedJobId || !deliverables.length ? 0.55 : 1 }}>
                {driveLoading === 'save' ? 'Saving' : 'Save to Google Drive'}
              </button>
              <button type="button" onClick={createClientShareLink} disabled={!!driveLoading || !selectedJobId} style={{ ...S.secondaryButton, opacity: driveLoading || !selectedJobId ? 0.55 : 1 }}>
                {driveLoading === 'share' ? 'Creating Link' : 'Create Client Share Link'}
              </button>
              <button type="button" onClick={copyDriveShareLink} disabled={!driveShareLink} style={{ ...S.secondaryButton, opacity: driveShareLink ? 1 : 0.55 }}>
                Copy Share Link
              </button>
            </div>
            {!driveStatus?.connected && <p style={S.muted}>Google Drive is not connected. Connect Google Drive first.</p>}
            {driveFolderStructure && (
              <div style={S.workerBox}>
                <strong>Drive folder structure</strong>
                <span>{driveFolderStructure.root}/</span>
                <span>{driveFolderStructure.job}/</span>
                <span>{driveFolderStructure.source_files}/</span>
                <span>{driveFolderStructure.deliverables}/</span>
                <span>{driveFolderStructure.reports}/</span>
              </div>
            )}
            {driveShareLink && (
              <div style={S.workerBox}>
                <strong>Client share link</strong>
                <span>{driveShareLink}</span>
              </div>
            )}
            {deliverables.length === 0 ? (
              <div style={S.emptyState}>No deliverables attached yet.</div>
            ) : (
              <div style={S.deliverableList}>
                {deliverables.map((file) => (
                  <div key={file.id} className="client-deliverable-row" style={S.deliverableItem}>
                    <div style={{ minWidth: 0 }}>
                      <strong>{file.name}</strong>
                      <span>{formatFileSize(file.size)} | Added {formatDate(file.added_at)}</span>
                    </div>
                    <select value={file.status} onChange={(event) => updateDeliverableStatus(file.id, event.target.value)} style={S.statusSelect}>
                      {deliverableStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
                    </select>
                    <button type="button" onClick={() => removeDeliverable(file.id)} style={S.secondaryButton}>Remove</button>
                  </div>
                ))}
              </div>
            )}
            <p style={S.muted}>User must review deliverables before sending manually.</p>
          </div>

          <div style={S.detailSection}>
            <div style={S.sectionTitle}>Local CAD Worker</div>
            <div style={S.buttonRow}>
              <button type="button" onClick={checkCadWorkerStatus} disabled={!!cadWorkerLoading} style={{ ...S.secondaryButton, opacity: cadWorkerLoading ? 0.55 : 1 }}>
                {cadWorkerLoading === 'status' ? 'Checking' : 'Check CAD Worker Status'}
              </button>
              <button type="button" onClick={createCadWorkerPreview} disabled={!!cadWorkerLoading || !selectedWorkspaceId || !cadRequest.trim()} style={{ ...S.secondaryButton, opacity: cadWorkerLoading || !selectedWorkspaceId || !cadRequest.trim() ? 0.55 : 1 }}>
                {cadWorkerLoading === 'preview' ? 'Creating Preview' : 'Create Command Preview'}
              </button>
              <button type="button" onClick={approveAndRunCadWorker} disabled={!!cadWorkerLoading || !cadWorkerPreview} style={{ ...S.primaryButton, opacity: cadWorkerLoading || !cadWorkerPreview ? 0.55 : 1 }}>
                {cadWorkerLoading === 'run' ? 'Submitting' : 'Approve & Run'}
              </button>
            </div>
            {cadWorkerStatus && <div style={S.workerBox}>Status: {cadWorkerStatus.status}. {cadWorkerStatus.message}</div>}
            {cadWorkerPreview && <pre style={S.previewJson}>{JSON.stringify(cadWorkerPreview.preview, null, 2)}</pre>}
            {cadWorkerRunResult && <pre style={S.previewJson}>{JSON.stringify(cadWorkerRunResult, null, 2)}</pre>}
          </div>
        </main>

        <aside className="studio-right-rail" style={S.rightRail}>
          <section style={S.aiActionsPanel}>
            <div>
              <div style={S.sectionTitle}>AI actions</div>
              <p style={S.muted}>Use EVA to prepare drafts. Nothing is sent or executed automatically.</p>
            </div>
            <div style={S.aiActionList}>
              {aiActions.map((action) => (
                <button
                  key={action.label}
                  type="button"
                  onClick={action.onClick}
                  disabled={action.disabled}
                  className="ai-action-button"
                  style={{ ...S.aiActionButton, opacity: action.disabled ? 0.52 : 1 }}
                >
                  <strong>{action.label}</strong>
                  <span>{action.detail}</span>
                </button>
              ))}
            </div>
            {!selectedWorkspaceId && <div style={S.emptyState}>Select a workspace to save client jobs. Local draft tools still work.</div>}
          </section>

          <section style={composeOpen ? S.composePanel : S.composePanelClosed}>
          {composeOpen ? (
            <>
              <div style={S.composeHeader}>
                <span>Client reply draft</span>
                <button type="button" onClick={() => setComposeOpen(false)} aria-label="Close compose" style={S.iconButton}>x</button>
              </div>
              <input
                value={composeTo}
                onChange={(event) => setComposeTo(event.target.value)}
                placeholder="To"
                style={S.composeInput}
              />
              <input
                value={composeSubject}
                onChange={(event) => setComposeSubject(event.target.value)}
                placeholder="Subject"
                style={S.composeInput}
              />
              <div style={S.composeGenerator}>
                <button
                  type="button"
                  onClick={generateClientReply}
                  disabled={replyLoading || (!cadRequest.trim() && !jobText.trim())}
                  style={{ ...S.primaryButton, opacity: replyLoading || (!cadRequest.trim() && !jobText.trim()) ? 0.55 : 1 }}
                >
                  {replyLoading ? 'Generating' : 'Generate Client Reply'}
                </button>
                <button type="button" onClick={applyGeneratedReply} disabled={!generatedReply.trim()} style={{ ...S.secondaryButton, opacity: generatedReply.trim() ? 1 : 0.55 }}>Apply to Draft</button>
                <button type="button" onClick={copyReply} disabled={!generatedReply.trim() && !composeBody.trim()} style={{ ...S.secondaryButton, opacity: generatedReply.trim() || composeBody.trim() ? 1 : 0.55 }}>Copy Reply</button>
                <button type="button" onClick={generateClientReply} disabled={replyLoading || (!cadRequest.trim() && !jobText.trim())} style={{ ...S.secondaryButton, opacity: replyLoading || (!cadRequest.trim() && !jobText.trim()) ? 0.55 : 1 }}>Regenerate</button>
              </div>
              {generatedReply && (
                <div style={S.generatedReplyBox}>
                  <strong>EVA reply preview</strong>
                  <span>{generatedReply}</span>
                </div>
              )}
              <textarea
                value={composeBody}
                onChange={(event) => setComposeBody(event.target.value)}
                placeholder="Message body"
                style={S.composeBody}
              />
              <div style={S.composeAttachments}>
                <strong>Attachments list</strong>
                {attachments.length === 0 ? (
                  <span>No deliverables attached yet.</span>
                ) : (
                  <div style={S.tagWrap}>{attachments.map((item) => <span key={item} style={S.tag}>{item}</span>)}</div>
                )}
              </div>
              <div style={S.composeGenerator}>
                <button type="button" onClick={insertDriveLinkIntoDraft} disabled={!driveShareLink} style={{ ...S.secondaryButton, opacity: driveShareLink ? 1 : 0.55 }}>
                  Insert Drive link into reply draft
                </button>
              </div>
              <div style={S.composeActions}>
                <button type="button" onClick={saveDraft} style={S.secondaryButton}>Save Draft</button>
                <button type="button" onClick={copyReply} style={S.secondaryButton}>Copy Reply</button>
                <button type="button" onClick={markReady} style={S.primaryButton}>Mark Ready</button>
                <button type="button" onClick={() => setComposeOpen(false)} style={S.secondaryButton}>Close</button>
              </div>
              <p style={S.muted}>No Send button yet. Email sending disabled. Manual approval required.</p>
            </>
          ) : (
            <button type="button" onClick={() => setComposeOpen(true)} style={S.primaryButton}>Open Draft</button>
          )}
          </section>
        </aside>
      </div>
    </div>
  );
}

function Field({ label, children, wide = false }) {
  return (
    <label style={{ display: 'grid', gap: 6, gridColumn: wide ? '1 / -1' : 'auto' }}>
      <span style={{ color: 'var(--text3)', fontSize: 12, fontWeight: 800 }}>{label}</span>
      {children}
    </label>
  );
}

function Metric({ label, value, color }) {
  return (
    <div className="studio-card-hover" style={{ background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 20, padding: 14, minHeight: 82, backdropFilter: 'blur(20px)' }}>
      <div style={{ color: 'var(--text3)', fontSize: 11 }}>{label}</div>
      <div style={{ color, fontSize: 23, fontWeight: 850, marginTop: 6, overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</div>
    </div>
  );
}

function AgentCard({ agent, S, onChat, onDelete }) {
  return (
    <section className="studio-card-hover" style={S.panel}>
      <div style={S.previewAgent}>
        <div style={S.avatar}>{agent.avatar || initials(agent.name)}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text)', fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{agent.name}</div>
          <div style={S.muted}>{agent.description || 'Custom AI agent'}</div>
        </div>
      </div>
      <InfoRow label="Model" value={agent.model || 'default'} />
      <InfoRow label="Tools" value={(agent.tools || []).join(', ') || 'None'} />
      <InfoRow label="Knowledge" value={(agent.knowledge_base || []).join(', ') || 'None'} />
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button type="button" onClick={onChat} style={S.secondaryButton}>Chat</button>
        <button type="button" onClick={onDelete} style={S.dangerButton}>Delete</button>
      </div>
    </section>
  );
}

function TemplateCard({ template, S, primaryLabel, onPrimary }) {
  return (
    <section className="studio-card-hover" style={S.panel}>
      <div style={S.previewAgent}>
        <div style={S.avatar}>{template.avatar || initials(template.name)}</div>
        <div>
          <div style={{ color: 'var(--text)', fontWeight: 850 }}>{template.name}</div>
          <div style={S.muted}>{template.description}</div>
        </div>
      </div>
      <InfoRow label="Model" value={template.model} />
      <InfoRow label="Tools" value={(template.tools || []).join(', ') || 'None'} />
      <InfoRow label="Knowledge" value={(template.knowledge_base || []).join(', ') || 'None'} />
      <button type="button" onClick={onPrimary} style={{ ...S.primaryButton, marginTop: 12 }}>
        {primaryLabel}
      </button>
    </section>
  );
}

function RankPanel({ title, rows, titleKey, meta, S }) {
  return (
    <section style={S.panel}>
      <div style={S.sectionTitle}>{title}</div>
      <div style={{ display: 'grid', gap: 8 }}>
        {rows.length === 0 ? (
          <div style={S.muted}>No data yet.</div>
        ) : rows.map((row, index) => (
          <div key={`${row[titleKey]}-${index}`} style={S.rankRow}>
            <div style={{ color: '#38bdf8', fontWeight: 850 }}>{index + 1}</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: 'var(--text)', fontWeight: 800, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row[titleKey] || 'Unknown'}</div>
              <div style={S.muted}>{meta(row)}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ResultCard({ title, value = '', list = [], S }) {
  const items = Array.isArray(list) ? list.filter(Boolean) : [];
  const text = String(value || '').trim();
  return (
    <section style={S.resultCard}>
      <div style={S.sectionTitle}>{title}</div>
      {items.length ? (
        <ul style={S.cleanList}>
          {items.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : text ? (
        <div style={S.resultText}>{text}</div>
      ) : (
        <div style={S.muted}>No result yet.</div>
      )}
    </section>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 12, padding: '9px 10px', marginTop: 8 }}>
      <span style={{ color: 'var(--text3)', fontSize: 12 }}>{label}</span>
      <span style={{ color: 'var(--text)', fontSize: 12, fontWeight: 800, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  );
}

function styles(loading) {
  return {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: 'var(--bg)',
      color: 'var(--text)',
      padding: 22,
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    },
    shell: {
      maxWidth: 1260,
      margin: '0 auto',
      display: 'grid',
      gap: 16,
    },
    stack: {
      display: 'grid',
      gap: 14,
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
      color: 'var(--text)',
      fontSize: 23,
      fontWeight: 850,
    },
    sub: {
      color: 'var(--text3)',
      fontSize: 13,
      marginTop: 4,
    },
    statusGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 12,
    },
    statusCard: {
      display: 'grid',
      gap: 7,
      minHeight: 92,
      border: '1px solid rgba(56,189,248,.18)',
      borderRadius: 14,
      background: 'linear-gradient(180deg, rgba(15,23,42,.78), rgba(2,6,23,.5))',
      padding: 14,
      boxShadow: '0 16px 34px rgba(2,6,23,.26)',
      color: 'var(--text2)',
      fontSize: 12,
      lineHeight: 1.5,
    },
    skeletonGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
      gap: 12,
    },
    skeletonCard: {
      minHeight: 54,
      border: '1px solid rgba(148,163,184,.14)',
      borderRadius: 14,
      background: 'rgba(15,23,42,.5)',
    },
    tabs: {
      display: 'grid',
      gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
      gap: 8,
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 20,
      padding: 8,
    },
    tab: {
      border: '1px solid transparent',
      borderRadius: 8,
      background: 'transparent',
      color: 'var(--text3)',
      fontSize: 12,
      fontWeight: 800,
      padding: '9px 8px',
      cursor: 'pointer',
      whiteSpace: 'nowrap',
    },
    activeTab: {
      background: 'var(--accent-soft)',
      color: 'var(--text)',
      border: '1px solid var(--border2)',
      boxShadow: '0 0 0 1px rgba(56,189,248,.12), 0 10px 24px rgba(14,165,233,.18)',
    },
    tabContent: {
      display: 'grid',
      gap: 14,
    },
    panel: {
      background: 'var(--card-bg)',
      border: '1px solid var(--border)',
      borderRadius: 20,
      padding: 16,
      boxShadow: '0 16px 36px rgba(0,0,0,.24), 0 0 28px var(--accent-glow)',
      backdropFilter: 'blur(20px)',
      minWidth: 0,
    },
    clientJobsTop: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 12,
      flexWrap: 'wrap',
      background: 'var(--card-bg)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: 14,
      minWidth: 0,
    },
    clientJobsLayout: {
      display: 'grid',
      gridTemplateColumns: '280px minmax(0, 1fr) 340px',
      gap: 12,
      alignItems: 'start',
    },
    mailPanel: {
      display: 'grid',
      gap: 10,
      background: 'var(--card-bg)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: 12,
      minWidth: 0,
      maxHeight: 'calc(100vh - 220px)',
      overflow: 'auto',
    },
    detailPanel: {
      display: 'grid',
      gap: 12,
      background: 'var(--card-bg)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: 14,
      minWidth: 0,
    },
    rightRail: {
      display: 'grid',
      gap: 12,
      minWidth: 0,
      alignSelf: 'start',
      position: 'sticky',
      top: 12,
    },
    aiActionsPanel: {
      display: 'grid',
      gap: 10,
      background: 'var(--card-bg)',
      border: '1px solid rgba(56,189,248,.18)',
      borderRadius: 12,
      padding: 12,
      minWidth: 0,
      boxShadow: '0 18px 38px rgba(2,6,23,.28)',
    },
    aiActionList: {
      display: 'grid',
      gap: 8,
    },
    aiActionButton: {
      display: 'grid',
      gap: 4,
      width: '100%',
      textAlign: 'left',
      border: '1px solid rgba(148,163,184,.16)',
      borderRadius: 10,
      background: 'rgba(15,23,42,.46)',
      color: 'var(--text2)',
      padding: 10,
      cursor: 'pointer',
      fontSize: 12,
    },
    composePanel: {
      display: 'grid',
      gap: 0,
      background: 'rgba(15,23,42,.96)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      minWidth: 0,
      maxHeight: 'calc(100vh - 160px)',
      overflow: 'auto',
      boxShadow: '0 22px 55px rgba(0,0,0,.42)',
      resize: 'both',
    },
    composePanelClosed: {
      display: 'grid',
      gap: 8,
      justifyItems: 'stretch',
      background: 'rgba(15,23,42,.96)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: 12,
      minWidth: 0,
      boxShadow: '0 18px 40px rgba(0,0,0,.36)',
    },
    composeHeader: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
      background: 'rgba(2,6,23,.72)',
      color: 'var(--text)',
      padding: '10px 12px',
      fontSize: 13,
      fontWeight: 900,
    },
    composeInput: {
      width: '100%',
      border: 'none',
      borderBottom: '1px solid rgba(148,163,184,.16)',
      background: 'transparent',
      color: 'var(--text)',
      padding: '10px 12px',
      outline: 'none',
      boxSizing: 'border-box',
      fontSize: 13,
    },
    composeBody: {
      width: '100%',
      minHeight: 260,
      maxHeight: '42vh',
      border: 'none',
      borderBottom: '1px solid rgba(148,163,184,.16)',
      background: 'transparent',
      color: 'var(--text)',
      padding: 12,
      outline: 'none',
      boxSizing: 'border-box',
      fontSize: 13,
      resize: 'vertical',
    },
    composeAttachments: {
      display: 'grid',
      gap: 8,
      padding: 12,
      color: 'var(--text3)',
      fontSize: 12,
      maxHeight: 120,
      overflow: 'auto',
    },
    composeGenerator: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      padding: 12,
      borderBottom: '1px solid rgba(148,163,184,.16)',
    },
    generatedReplyBox: {
      display: 'grid',
      gap: 8,
      margin: 12,
      maxHeight: 180,
      overflow: 'auto',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 10,
      background: 'rgba(2,6,23,.3)',
      color: 'var(--text2)',
      padding: 10,
      fontSize: 12,
      lineHeight: 1.5,
      whiteSpace: 'pre-wrap',
    },
    composeActions: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      padding: 12,
      borderTop: '1px solid rgba(148,163,184,.14)',
    },
    iconButton: {
      width: 28,
      height: 28,
      display: 'grid',
      placeItems: 'center',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      background: 'transparent',
      color: 'var(--text3)',
      cursor: 'pointer',
      fontWeight: 900,
      lineHeight: 1,
    },
    mailPanelTitle: {
      color: 'var(--text2)',
      fontSize: 14,
      fontWeight: 900,
    },
    statusFilterList: {
      display: 'grid',
      gap: 6,
    },
    statusFilter: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      border: '1px solid transparent',
      borderRadius: 8,
      padding: '8px 10px',
      background: 'transparent',
      color: 'var(--text3)',
      cursor: 'pointer',
      fontWeight: 800,
      textAlign: 'left',
    },
    statusFilterActive: {
      background: 'var(--accent-soft)',
      borderColor: 'var(--border2)',
      color: 'var(--text)',
    },
    mailList: {
      display: 'grid',
      gap: 8,
    },
    mailItem: {
      display: 'grid',
      gap: 5,
      width: '100%',
      border: '1px solid rgba(148,163,184,.14)',
      borderRadius: 10,
      background: 'rgba(15,23,42,.42)',
      color: 'var(--text3)',
      padding: 10,
      cursor: 'pointer',
      textAlign: 'left',
    },
    mailItemActive: {
      borderColor: 'rgba(56,189,248,.5)',
      background: 'rgba(14,165,233,.13)',
      color: 'var(--text)',
    },
    mailItemTitle: {
      color: 'var(--text2)',
      fontWeight: 900,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    },
    statusBadge: {
      justifySelf: 'start',
      border: '1px solid rgba(96,165,250,.26)',
      borderRadius: 999,
      background: 'rgba(37,99,235,.13)',
      color: '#bfdbfe',
      padding: '3px 8px',
      fontSize: 11,
      fontWeight: 900,
    },
    mailItemMeta: {
      display: 'flex',
      justifyContent: 'space-between',
      gap: 8,
      fontSize: 11,
      color: 'var(--text3)',
    },
    detailHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 12,
      borderBottom: '1px solid rgba(148,163,184,.12)',
      paddingBottom: 12,
    },
    statusActionRow: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      borderBottom: '1px solid rgba(148,163,184,.12)',
      paddingBottom: 12,
    },
    nextActionCard: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 12,
      flexWrap: 'wrap',
      border: '1px solid rgba(45,212,191,.24)',
      borderRadius: 12,
      background: 'linear-gradient(135deg, rgba(20,184,166,.16), rgba(37,99,235,.12))',
      padding: 14,
      boxShadow: '0 18px 40px rgba(2,6,23,.24)',
      minWidth: 0,
    },
    nextActionEyebrow: {
      color: '#5eead4',
      fontSize: 11,
      fontWeight: 900,
      textTransform: 'uppercase',
      letterSpacing: 0,
    },
    nextActionTitle: {
      color: 'var(--text)',
      fontSize: 17,
      fontWeight: 900,
      marginTop: 4,
    },
    driveStatusRow: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 12,
      flexWrap: 'wrap',
      color: 'var(--text2)',
      fontSize: 13,
    },
    detailTitle: {
      color: 'var(--text)',
      fontSize: 18,
      fontWeight: 900,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    },
    detailSection: {
      display: 'grid',
      gap: 10,
      border: '1px solid rgba(148,163,184,.12)',
      borderRadius: 10,
      padding: 12,
      background: 'rgba(15,23,42,.28)',
      minWidth: 0,
    },
    compactRow: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) auto',
      gap: 10,
      alignItems: 'end',
    },
    scorePill: {
      display: 'grid',
      placeItems: 'center',
      minWidth: 58,
      minHeight: 46,
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 10,
      background: 'rgba(2,6,23,.34)',
      fontSize: 20,
      fontWeight: 950,
    },
    cleanList: {
      margin: 0,
      paddingLeft: 18,
      color: 'var(--text2)',
      fontSize: 13,
      lineHeight: 1.6,
    },
    deliverableList: {
      display: 'grid',
      gap: 8,
    },
    deliverableItem: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) 150px auto',
      gap: 8,
      alignItems: 'center',
      border: '1px solid rgba(148,163,184,.14)',
      borderRadius: 10,
      background: 'rgba(2,6,23,.28)',
      padding: 10,
      color: 'var(--text2)',
      fontSize: 12,
    },
    sectionTitle: {
      color: 'var(--text2)',
      fontSize: 13,
      fontWeight: 850,
      marginBottom: 10,
    },
    grid4: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 12,
    },
    grid3: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
      gap: 14,
    },
    grid2: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 14,
    },
    chatGrid: {
      display: 'grid',
      gridTemplateColumns: '1.3fr .7fr',
      gap: 14,
    },
    chatHeader: {
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 12,
      flexWrap: 'wrap',
      marginBottom: 12,
    },
    quickChips: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginTop: 10,
    },
    chipButton: {
      border: '1px solid rgba(96,165,250,.24)',
      borderRadius: 999,
      background: 'rgba(37,99,235,.12)',
      color: 'var(--text2)',
      padding: '7px 10px',
      cursor: 'pointer',
      fontSize: 12,
      fontWeight: 800,
    },
    chipButtonActive: {
      borderColor: 'rgba(45,212,191,.46)',
      background: 'rgba(20,184,166,.18)',
      color: 'var(--text)',
    },
    chatEmpty: {
      display: 'grid',
      placeItems: 'center',
      textAlign: 'center',
      gap: 8,
      minHeight: 190,
      color: 'var(--text3)',
      lineHeight: 1.5,
      padding: 18,
    },
    chatComposer: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) auto',
      gap: 10,
      alignItems: 'end',
    },
    agentResultWrap: {
      display: 'grid',
      gap: 12,
      marginTop: 14,
      border: '1px solid rgba(56,189,248,.18)',
      borderRadius: 14,
      background: 'rgba(15,23,42,.34)',
      padding: 12,
    },
    agentResultHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 12,
      flexWrap: 'wrap',
    },
    resultGrid: {
      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
    },
    resultCard: {
      display: 'grid',
      gap: 8,
      minWidth: 0,
      border: '1px solid rgba(148,163,184,.16)',
      borderRadius: 12,
      background: 'rgba(2,6,23,.34)',
      padding: 12,
    },
    resultText: {
      color: 'var(--text2)',
      fontSize: 12,
      lineHeight: 1.55,
      whiteSpace: 'pre-wrap',
      maxHeight: 220,
      overflow: 'auto',
    },
    formGrid: {
      display: 'grid',
      gridTemplateColumns: '1fr 140px',
      gap: 12,
    },
    input: {
      width: '100%',
      borderRadius: 12,
      border: '1px solid var(--border)',
      background: 'var(--input-bg)',
      color: 'var(--text)',
      padding: '10px 11px',
      outline: 'none',
      boxSizing: 'border-box',
      fontSize: 13,
    },
    textarea: {
      width: '100%',
      minHeight: 150,
      borderRadius: 12,
      border: '1px solid var(--border)',
      background: 'var(--input-bg)',
      color: 'var(--text)',
      padding: 11,
      outline: 'none',
      boxSizing: 'border-box',
      fontSize: 13,
      resize: 'vertical',
    },
    shortTextarea: {
      width: '100%',
      minHeight: 88,
      borderRadius: 12,
      border: '1px solid var(--border)',
      background: 'var(--input-bg)',
      color: 'var(--text)',
      padding: 11,
      outline: 'none',
      boxSizing: 'border-box',
      fontSize: 13,
      resize: 'vertical',
    },
    primaryButton: {
      border: 'none',
      borderRadius: 8,
      padding: '10px 13px',
      color: '#fff',
      fontWeight: 850,
      background: 'linear-gradient(135deg,var(--accent),#0f766e)',
      cursor: loading ? 'not-allowed' : 'pointer',
      whiteSpace: 'nowrap',
    },
    secondaryButton: {
      border: '1px solid rgba(96,165,250,.24)',
      borderRadius: 8,
      padding: '9px 12px',
      color: 'var(--text)',
      background: 'var(--accent-soft)',
      fontWeight: 800,
      cursor: 'pointer',
    },
    dangerButton: {
      border: '1px solid rgba(248,113,113,.25)',
      borderRadius: 8,
      padding: '9px 12px',
      color: '#fecaca',
      background: 'rgba(239,68,68,.12)',
      fontWeight: 800,
      cursor: 'pointer',
    },
    error: {
      color: '#fecaca',
      background: 'rgba(239,68,68,.12)',
      border: '1px solid rgba(248,113,113,.25)',
      borderRadius: 8,
      padding: 10,
      fontSize: 13,
    },
    success: {
      color: '#bbf7d0',
      background: 'rgba(34,197,94,.12)',
      border: '1px solid rgba(74,222,128,.24)',
      borderRadius: 8,
      padding: 10,
      fontSize: 13,
    },
    muted: {
      color: 'var(--text3)',
      fontSize: 12,
      lineHeight: 1.5,
    },
    previewAgent: {
      display: 'flex',
      gap: 11,
      alignItems: 'center',
      marginBottom: 12,
    },
    avatar: {
      width: 44,
      height: 44,
      borderRadius: 8,
      display: 'grid',
      placeItems: 'center',
      color: '#fff',
      fontWeight: 900,
      background: 'linear-gradient(135deg,var(--accent),#14b8a6)',
      flexShrink: 0,
    },
    smallAvatar: {
      width: 30,
      height: 30,
      borderRadius: 8,
      display: 'grid',
      placeItems: 'center',
      color: '#fff',
      fontWeight: 900,
      background: 'linear-gradient(135deg,var(--accent),#14b8a6)',
      flexShrink: 0,
    },
    toolGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
      gap: 8,
    },
    toolOption: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 9,
      border: '1px solid rgba(148,163,184,.18)',
      background: '#111827',
      borderRadius: 8,
      padding: 10,
      color: '#cbd5e1',
      fontSize: 12,
    },
    toolSelected: {
      borderColor: 'rgba(56,189,248,.45)',
      background: 'rgba(14,165,233,.12)',
    },
    buttonRow: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      alignItems: 'center',
      marginTop: 12,
    },
    stepList: {
      display: 'grid',
      gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
      gap: 8,
      marginTop: 12,
    },
    stepItem: {
      minWidth: 0,
      display: 'grid',
      gap: 6,
      border: '1px solid rgba(148,163,184,.16)',
      borderRadius: 10,
      background: 'rgba(15,23,42,.5)',
      color: 'var(--text2)',
      padding: 10,
      fontSize: 12,
    },
    scoreCircle: {
      width: 112,
      height: 112,
      display: 'grid',
      placeItems: 'center',
      justifySelf: 'start',
      border: '2px solid #38bdf8',
      borderRadius: 16,
      background: 'rgba(15,23,42,.54)',
      fontSize: 32,
      fontWeight: 900,
    },
    tagWrap: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 7,
    },
    tag: {
      border: '1px solid rgba(148,163,184,.2)',
      borderRadius: 999,
      background: 'rgba(15,23,42,.56)',
      color: 'var(--text2)',
      padding: '5px 9px',
      fontSize: 12,
      fontWeight: 750,
    },
    proposalBox: {
      display: 'grid',
      gap: 7,
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 12,
      background: 'rgba(15,23,42,.48)',
      padding: 12,
      color: 'var(--text2)',
      fontSize: 13,
      lineHeight: 1.55,
      whiteSpace: 'pre-wrap',
    },
    workerBox: {
      display: 'grid',
      gap: 6,
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 10,
      background: 'rgba(2,6,23,.34)',
      padding: 10,
      color: 'var(--text2)',
      fontSize: 12,
    },
    previewJson: {
      margin: 0,
      maxHeight: 220,
      overflow: 'auto',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      color: '#cbd5e1',
      fontSize: 12,
      lineHeight: 1.45,
    },
    checklist: {
      display: 'grid',
      gap: 8,
    },
    checkItem: {
      display: 'flex',
      alignItems: 'center',
      gap: 9,
      border: '1px solid rgba(148,163,184,.16)',
      borderRadius: 10,
      background: 'rgba(15,23,42,.5)',
      color: 'var(--text2)',
      padding: '9px 10px',
      fontSize: 13,
    },
    historyHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 12,
      flexWrap: 'wrap',
      marginBottom: 12,
    },
    emptyState: {
      border: '1px dashed rgba(148,163,184,.24)',
      borderRadius: 12,
      color: 'var(--text3)',
      padding: 16,
      fontSize: 13,
      textAlign: 'center',
    },
    jobList: {
      display: 'grid',
      gap: 8,
    },
    jobRow: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) 64px 90px 120px auto',
      gap: 9,
      alignItems: 'center',
      border: '1px solid rgba(148,163,184,.16)',
      borderRadius: 12,
      background: 'rgba(15,23,42,.5)',
      padding: 10,
    },
    scoreBadge: {
      fontSize: 20,
      fontWeight: 900,
      textAlign: 'center',
    },
    recommendation: {
      color: 'var(--text2)',
      fontSize: 12,
      fontWeight: 850,
    },
    statusSelect: {
      border: '1px solid var(--border)',
      borderRadius: 8,
      background: 'var(--input-bg)',
      color: 'var(--text)',
      padding: '8px 9px',
      outline: 'none',
      fontSize: 12,
    },
    chatBox: {
      minHeight: 300,
      maxHeight: 420,
      overflowY: 'auto',
      background: '#111827',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: 12,
      display: 'grid',
      gap: 10,
      margin: '12px 0',
    },
    chatBubble: {
      borderRadius: 8,
      padding: 11,
      fontSize: 13,
      lineHeight: 1.5,
    },
    userBubble: {
      background: 'rgba(37,99,235,.16)',
      border: '1px solid rgba(96,165,250,.25)',
    },
    assistantBubble: {
      background: 'rgba(20,184,166,.13)',
      border: '1px solid rgba(45,212,191,.22)',
    },
    chatRole: {
      color: '#94a3b8',
      fontSize: 11,
      fontWeight: 850,
      marginBottom: 4,
    },
    optionList: {
      display: 'grid',
      gap: 8,
    },
    agentOption: {
      display: 'flex',
      alignItems: 'center',
      gap: 9,
      textAlign: 'left',
      border: '1px solid rgba(148,163,184,.18)',
      background: '#111827',
      color: '#cbd5e1',
      borderRadius: 8,
      padding: 10,
      cursor: 'pointer',
    },
    agentOptionActive: {
      borderColor: 'rgba(56,189,248,.45)',
      background: 'rgba(14,165,233,.12)',
    },
    rankRow: {
      display: 'grid',
      gridTemplateColumns: '28px 1fr',
      gap: 8,
      alignItems: 'center',
      background: '#111827',
      border: '1px solid rgba(148,163,184,.15)',
      borderRadius: 8,
      padding: 10,
    },
  };
}

function initials(value) {
  const text = String(value || 'AI').trim();
  return text
    .split(/\s+/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || 'AI';
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatFileSize(bytes) {
  const size = Number(bytes || 0);
  if (!size) return '0 KB';
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

