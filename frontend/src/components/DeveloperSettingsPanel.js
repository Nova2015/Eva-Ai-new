import { useCallback, useEffect, useState } from 'react';
import { ButtonRow, NumberInput, Panel, Select, SettingRow, TextInput, Toggle, settingsRequest } from './SettingsPanelPrimitives';
import './DeveloperSettingsPanel.css';

const developerTabs = ['Domain Training', 'Domain Evaluation', 'Monitoring', 'Admin Console', 'Plugins', 'Agents'];
const domains = ['General', 'Mechanical Design', 'Automotive', 'Coding', 'Business', 'Custom'];
const methods = ['RAG only', 'Fine-tuning dataset', 'Both'];

export default function DeveloperSettingsPanel({ API }) {
  const [active, setActive] = useState('Domain Training');

  return (
    <div className="eva-dev-settings">
      <div className="eva-settings-tabs" role="tablist" aria-label="Developer settings">
        {developerTabs.map((tab) => (
          <button key={tab} type="button" className={active === tab ? 'is-active' : ''} onClick={() => setActive(tab)}>
            {tab}
          </button>
        ))}
      </div>
      {active === 'Domain Training' && <DomainTraining API={API} />}
      {active === 'Domain Evaluation' && <DomainEvaluation API={API} />}
      {active === 'Monitoring' && <MonitoringPanel API={API} />}
      {active === 'Admin Console' && <AdminConsole API={API} />}
      {active === 'Plugins' && <PluginsPanel API={API} />}
      {active === 'Agents' && <AgentsPanel API={API} />}
    </div>
  );
}

function DomainTraining({ API }) {
  const [form, setForm] = useState({ domain: 'General', training_method: 'RAG only', url: '', chunk_size: 900, chunk_overlap: 120 });
  const [file, setFile] = useState(null);
  const [datasets, setDatasets] = useState([]);
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const data = await settingsRequest(API, '/training/domain/datasets');
    setDatasets(data.datasets || []);
  }, [API]);

  useEffect(() => {
    load().catch((error) => setStatus(error.message));
  }, [load]);

  const upload = async () => {
    if (!file) {
      setStatus('Choose a PDF, DOCX, TXT, CSV, JSON, or JSONL file first');
      return;
    }
    const body = new FormData();
    body.append('file', file);
    body.append('domain', form.domain);
    body.append('training_method', form.training_method);
    const data = await settingsRequest(API, '/training/domain/upload', { method: 'POST', body });
    setStatus(`Uploaded ${data.dataset?.name || file.name}`);
    await load();
  };

  const addUrl = async () => {
    const data = await settingsRequest(API, '/training/domain/url', { method: 'POST', body: JSON.stringify(form) });
    setStatus(`Added ${data.dataset?.name || 'website'}`);
    await load();
  };

  const process = async (dataset_id) => {
    const data = await settingsRequest(API, '/training/domain/process', {
      method: 'POST',
      body: JSON.stringify({ dataset_id, chunk_size: form.chunk_size, chunk_overlap: form.chunk_overlap }),
    });
    setStatus(`Processed ${data.dataset?.name || dataset_id}`);
    await load();
  };

  const rebuild = async () => {
    const data = await settingsRequest(API, '/training/domain/rebuild-index', { method: 'POST', body: JSON.stringify({}) });
    setStatus(data.message || 'Rebuild complete');
    await load();
  };

  const deleteDataset = async (dataset_id) => {
    if (!window.confirm('Delete this dataset?')) return;
    await settingsRequest(API, `/training/domain/dataset/${dataset_id}`, { method: 'DELETE' });
    setStatus('Dataset deleted');
    await load();
  };

  const exportJsonl = () => {
    window.open(`${API || ''}/training/domain/export-jsonl`, '_blank', 'noopener,noreferrer');
  };

  return (
    <>
      <Panel title="Domain Training" subtitle="Collect, clean, chunk, index, and export domain data for EVA.">
        <SettingRow title="Upload dataset" detail="PDF, DOCX, TXT, CSV, JSON, and JSONL are accepted.">
          <input className="eva-settings-input" type="file" accept=".pdf,.docx,.txt,.csv,.json,.jsonl" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </SettingRow>
        <SettingRow title="Website URL" detail="Creates a website ingestion placeholder.">
          <TextInput value={form.url} placeholder="https://example.com/docs" onChange={(value) => setForm((current) => ({ ...current, url: value }))} />
        </SettingRow>
        <SettingRow title="Domain" detail="Used to group and evaluate datasets.">
          <Select value={form.domain} options={domains} onChange={(value) => setForm((current) => ({ ...current, domain: value }))} />
        </SettingRow>
        <SettingRow title="Training method" detail="Choose RAG, fine-tuning export, or both.">
          <Select value={form.training_method} options={methods} onChange={(value) => setForm((current) => ({ ...current, training_method: value }))} />
        </SettingRow>
        <SettingRow title="Chunk size" detail="Applied during processing.">
          <NumberInput value={form.chunk_size} min={128} max={8000} onChange={(value) => setForm((current) => ({ ...current, chunk_size: value }))} />
        </SettingRow>
        <SettingRow title="Chunk overlap" detail="Applied during processing.">
          <NumberInput value={form.chunk_overlap} min={0} max={2000} onChange={(value) => setForm((current) => ({ ...current, chunk_overlap: value }))} />
        </SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button" onClick={upload}>Upload</button>
          <button type="button" className="eva-settings-button" onClick={addUrl}>Add URL</button>
          <button type="button" className="eva-settings-button" onClick={rebuild}>Rebuild domain index</button>
          <button type="button" className="eva-settings-button primary" onClick={exportJsonl}>Export JSONL</button>
        </ButtonRow>
      </Panel>
      <Panel title="Dataset Preview" subtitle="Processing status and chunk counts.">
        <MiniTable
          rows={datasets}
          columns={['name', 'domain', 'training_method', 'status', 'chunk_count']}
          actions={(row) => (
            <>
              <button type="button" className="eva-settings-button" onClick={() => process(row.id)}>Process</button>
              <button type="button" className="eva-settings-button danger" onClick={() => deleteDataset(row.id)}>Delete</button>
            </>
          )}
        />
      </Panel>
    </>
  );
}

function DomainEvaluation({ API }) {
  const [file, setFile] = useState(null);
  const [question, setQuestion] = useState('');
  const [expected, setExpected] = useState('');
  const [results, setResults] = useState(null);
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const data = await settingsRequest(API, '/evaluation/domain/results');
    setResults(data.latest);
  }, [API]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const upload = async () => {
    if (!file) {
      setStatus('Choose a CSV, JSON, or JSONL evaluation file first');
      return;
    }
    const body = new FormData();
    body.append('file', file);
    const data = await settingsRequest(API, '/evaluation/domain/upload', { method: 'POST', body });
    setStatus(`Loaded ${data.count || 0} evaluation rows`);
  };

  const run = async () => {
    const questions = question ? [{ question, expected_answer: expected }] : undefined;
    const data = await settingsRequest(API, '/evaluation/domain/run', { method: 'POST', body: JSON.stringify({ questions }) });
    setResults(data.result);
    setStatus('Evaluation complete');
  };

  const exportReport = async () => {
    const data = await settingsRequest(API, '/evaluation/domain/report');
    const blob = new Blob([data.text || ''], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'eva-domain-evaluation.md';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Panel title="Domain Evaluation" subtitle="Run accuracy, hallucination, citation, and retrieval quality checks.">
        <SettingRow title="Evaluation dataset" detail="Upload CSV, JSON, or JSONL.">
          <input className="eva-settings-input" type="file" accept=".csv,.json,.jsonl" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </SettingRow>
        <SettingRow title="Manual test question" detail="Optional question for a quick run.">
          <TextInput value={question} onChange={setQuestion} placeholder="What should EVA answer?" />
        </SettingRow>
        <SettingRow title="Expected answer" detail="Used to score manual runs.">
          <textarea className="eva-settings-textarea" value={expected} onChange={(event) => setExpected(event.target.value)} />
        </SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button" onClick={upload}>Upload evaluation dataset</button>
          <button type="button" className="eva-settings-button primary" onClick={run}>Run evaluation</button>
          <button type="button" className="eva-settings-button" onClick={exportReport}>Export report</button>
        </ButtonRow>
      </Panel>
      <Panel title="Latest Results" subtitle="Scores are placeholders until connected to live answer generation.">
        <div className="eva-dev-score-grid">
          {['accuracy', 'hallucination', 'citation_match', 'retrieval_quality'].map((key) => (
            <div key={key} className="eva-dev-score">
              <span>{key.replaceAll('_', ' ')}</span>
              <strong>{results?.scores?.[key] ?? 0}%</strong>
            </div>
          ))}
        </div>
        <MiniTable rows={results?.failed_questions || []} columns={['question', 'expected_answer']} />
      </Panel>
    </>
  );
}

function MonitoringPanel({ API }) {
  const [status, setStatus] = useState(null);
  const [logs, setLogs] = useState([]);

  const load = useCallback(async () => {
    const [statusData, logData] = await Promise.all([
      settingsRequest(API, '/monitoring/status'),
      settingsRequest(API, '/monitoring/logs'),
    ]);
    setStatus(statusData);
    setLogs(logData.logs || []);
  }, [API]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  return (
    <>
      <Panel title="Production Monitoring" subtitle="Backend, usage, cost, latency, uptime, and admin signals.">
        <div className="eva-dev-score-grid">
          <Metric label="Backend" value={status?.status || 'unknown'} />
          <Metric label="Uptime" value={status?.metrics?.uptime_status || 'unknown'} />
          <Metric label="Latency p95" value={`${status?.metrics?.latency_p95_ms || 0} ms`} />
          <Metric label="Cost" value={`$${status?.costs?.estimated_monthly_cost || 0}`} />
        </div>
        <ButtonRow>
          <button type="button" className="eva-settings-button" onClick={load}>Refresh</button>
        </ButtonRow>
      </Panel>
      <Panel title="Request Logs" subtitle="Recent monitoring events.">
        <MiniTable rows={logs.slice(0, 10)} columns={['event', 'level', 'created_at']} />
      </Panel>
    </>
  );
}

function AdminConsole({ API }) {
  const [audit, setAudit] = useState([]);
  const [limits, setLimits] = useState({});
  const [workspaceName, setWorkspaceName] = useState('EVA Workspace');
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const [auditData, limitData] = await Promise.all([
      settingsRequest(API, '/team/audit'),
      settingsRequest(API, '/team/limits'),
    ]);
    setAudit(auditData.audit || []);
    setLimits(limitData.limits || {});
  }, [API]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const saveWorkspace = async () => {
    const data = await settingsRequest(API, '/team/workspace', { method: 'POST', body: JSON.stringify({ name: workspaceName }) });
    setStatus(`Saved ${data.workspace?.name || workspaceName}`);
    await load();
  };

  return (
    <>
      <Panel title="Admin Console" subtitle="Organization settings, workspace usage limits, and audit logs.">
        <SettingRow title="Workspace name" detail="Displayed in team/admin surfaces.">
          <TextInput value={workspaceName} onChange={setWorkspaceName} />
        </SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button primary" onClick={saveWorkspace}>Save organization settings</button>
        </ButtonRow>
      </Panel>
      <Panel title="Workspace Usage Limits">
        <div className="eva-dev-score-grid">
          {Object.entries(limits).map(([key, value]) => <Metric key={key} label={key.replaceAll('_', ' ')} value={value} />)}
        </div>
      </Panel>
      <Panel title="Admin Audit Logs">
        <MiniTable rows={audit} columns={['event', 'actor', 'created_at']} />
      </Panel>
    </>
  );
}

function PluginsPanel({ API }) {
  const [marketplace, setMarketplace] = useState([]);
  const [installed, setInstalled] = useState([]);
  const [tool, setTool] = useState({ name: '', description: '', api_endpoint: '', auth_type: 'None' });
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const [marketData, installedData] = await Promise.all([
      settingsRequest(API, '/plugins/marketplace'),
      settingsRequest(API, '/plugins/installed'),
    ]);
    setMarketplace(marketData.plugins || []);
    setInstalled(installedData.installed || []);
  }, [API]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const install = async (plugin_id) => {
    await settingsRequest(API, '/plugins/install', { method: 'POST', body: JSON.stringify({ plugin_id }) });
    setStatus('Plugin installed');
    await load();
  };

  const toggle = async (plugin_id, enabled) => {
    await settingsRequest(API, '/plugins/toggle', { method: 'POST', body: JSON.stringify({ plugin_id, enabled }) });
    await load();
  };

  const uninstall = async (plugin_id) => {
    if (!window.confirm('Uninstall this plugin?')) return;
    await settingsRequest(API, '/plugins/uninstall', { method: 'POST', body: JSON.stringify({ plugin_id }) });
    await load();
  };

  const testTool = async () => {
    const data = await settingsRequest(API, '/plugins/tools/test', { method: 'POST', body: JSON.stringify(tool) });
    setStatus(data.message || 'Tool tested');
  };

  const saveTool = async () => {
    await settingsRequest(API, '/plugins/tools/custom', { method: 'POST', body: JSON.stringify(tool) });
    setStatus('Custom tool saved');
    await load();
  };

  return (
    <>
      <Panel title="Plugin Marketplace" subtitle="Install approved plugin placeholders.">
        <MiniTable
          rows={marketplace}
          columns={['name', 'category', 'description']}
          actions={(row) => <button type="button" className="eva-settings-button" onClick={() => install(row.id)}>Install</button>}
        />
      </Panel>
      <Panel title="Installed Plugins">
        <MiniTable
          rows={installed}
          columns={['name', 'enabled', 'installed_at']}
          actions={(row) => (
            <>
              <Toggle checked={!!row.enabled} onChange={(value) => toggle(row.id, value)} />
              <button type="button" className="eva-settings-button danger" onClick={() => uninstall(row.id)}>Uninstall</button>
            </>
          )}
        />
      </Panel>
      <Panel title="Custom Tool Builder" subtitle="Dangerous endpoints are blocked by backend policy.">
        <SettingRow title="Tool name"><TextInput value={tool.name} onChange={(value) => setTool((current) => ({ ...current, name: value }))} /></SettingRow>
        <SettingRow title="Tool description"><TextInput value={tool.description} onChange={(value) => setTool((current) => ({ ...current, description: value }))} /></SettingRow>
        <SettingRow title="API endpoint"><TextInput value={tool.api_endpoint} onChange={(value) => setTool((current) => ({ ...current, api_endpoint: value }))} /></SettingRow>
        <SettingRow title="Auth type"><Select value={tool.auth_type} options={['None', 'API Key', 'OAuth', 'Bearer Token']} onChange={(value) => setTool((current) => ({ ...current, auth_type: value }))} /></SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button" onClick={testTool}>Test tool</button>
          <button type="button" className="eva-settings-button primary" onClick={saveTool}>Save custom tool</button>
        </ButtonRow>
      </Panel>
    </>
  );
}

function AgentsPanel({ API }) {
  const [agents, setAgents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [form, setForm] = useState({ name: 'Research Agent', role: 'Research assistant', allowed_tools: 'web_search,rag', knowledge_base: 'Default', approval_required: true, goal: 'Summarize the latest uploaded knowledge.' });
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const [agentsData, runsData] = await Promise.all([
      settingsRequest(API, '/agents'),
      settingsRequest(API, '/agents/runs'),
    ]);
    setAgents(agentsData.agents || []);
    setRuns(runsData.runs || []);
  }, [API]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const createAgent = async () => {
    const data = await settingsRequest(API, '/agents/create', {
      method: 'POST',
      body: JSON.stringify({ ...form, allowed_tools: form.allowed_tools.split(',').map((item) => item.trim()).filter(Boolean) }),
    });
    setStatus(`Created ${data.agent?.name || 'agent'}`);
    await load();
  };

  const runAgent = async (agent_id) => {
    const data = await settingsRequest(API, '/agents/run', { method: 'POST', body: JSON.stringify({ agent_id, goal: form.goal }) });
    setStatus(`Run ${data.run?.status || 'created'}`);
    await load();
  };

  const stopRun = async (run_id) => {
    await settingsRequest(API, '/agents/stop', { method: 'POST', body: JSON.stringify({ run_id }) });
    await load();
  };

  const exportWorkflow = async (agent_id) => {
    const data = await settingsRequest(API, `/agents/workflow/${agent_id}`);
    const blob = new Blob([JSON.stringify(data.workflow || {}, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'eva-agent-workflow.json';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Panel title="Create Agent" subtitle="Define persona, approved tools, knowledge base, workflow, and approval policy.">
        <SettingRow title="Agent name"><TextInput value={form.name} onChange={(value) => setForm((current) => ({ ...current, name: value }))} /></SettingRow>
        <SettingRow title="Agent role/persona"><TextInput value={form.role} onChange={(value) => setForm((current) => ({ ...current, role: value }))} /></SettingRow>
        <SettingRow title="Allowed tools"><TextInput value={form.allowed_tools} onChange={(value) => setForm((current) => ({ ...current, allowed_tools: value }))} /></SettingRow>
        <SettingRow title="Knowledge base"><TextInput value={form.knowledge_base} onChange={(value) => setForm((current) => ({ ...current, knowledge_base: value }))} /></SettingRow>
        <SettingRow title="Run goal"><TextInput value={form.goal} onChange={(value) => setForm((current) => ({ ...current, goal: value }))} /></SettingRow>
        <SettingRow title="Approval required" detail="Dangerous tool actions still require approval.">
          <Toggle checked={!!form.approval_required} onChange={(value) => setForm((current) => ({ ...current, approval_required: value }))} />
        </SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button primary" onClick={createAgent}>Create agent</button>
        </ButtonRow>
      </Panel>
      <Panel title="Agents">
        <MiniTable
          rows={agents}
          columns={['name', 'role', 'knowledge_base']}
          actions={(row) => (
            <>
              <button type="button" className="eva-settings-button" onClick={() => runAgent(row.id)}>Run</button>
              <button type="button" className="eva-settings-button" onClick={() => exportWorkflow(row.id)}>Export workflow JSON</button>
            </>
          )}
        />
      </Panel>
      <Panel title="Agent Run History">
        <MiniTable
          rows={runs}
          columns={['agent_id', 'status', 'goal', 'created_at']}
          actions={(row) => row.status !== 'stopped' && <button type="button" className="eva-settings-button" onClick={() => stopRun(row.id)}>Pause/stop</button>}
        />
      </Panel>
    </>
  );
}

function Metric({ label, value }) {
  return (
    <div className="eva-dev-score">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MiniTable({ rows = [], columns = [], actions }) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) {
    return <div className="eva-settings-empty">No records yet.</div>;
  }
  return (
    <div className="eva-dev-table">
      <div className="eva-dev-table-head" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr)) ${actions ? 'auto' : ''}` }}>
        {columns.map((column) => <span key={column}>{column.replaceAll('_', ' ')}</span>)}
        {actions && <span>Actions</span>}
      </div>
      {safeRows.slice(0, 12).map((row, index) => (
        <div key={row.id || index} className="eva-dev-table-row" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr)) ${actions ? 'auto' : ''}` }}>
          {columns.map((column) => <span key={column}>{String(row[column] ?? '')}</span>)}
          {actions && <div className="eva-dev-table-actions">{actions(row)}</div>}
        </div>
      ))}
    </div>
  );
}
