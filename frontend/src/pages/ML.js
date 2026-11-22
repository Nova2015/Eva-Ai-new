import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';



/* ── Design tokens — matches ARIA dark theme ─────────────────────────────── */
const C = {
  bg:      'var(--bg)',
  bg2:     'var(--bg2)',
  surface: 'var(--surface)',
  surf2:   'var(--surface2)',
  border:  'var(--border)',
  accent:  'var(--accent)',
  cyan:    'var(--cyan)',
  green:   'var(--green)',
  purple:  'var(--purple)',
  warn:    'var(--warn)',
  red:     'var(--red)',
  text:    'var(--text)',
  text2:   'var(--text2)',
  text3:   'var(--text3)',
  mono:    'var(--mono)',
  sans:    'var(--sans)',
};

/* ── Helpers ─────────────────────────────────────────────────────────────── */
const card = (extra = {}) => ({
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 12,
  padding: 20,
  ...extra,
});

const badge = (color, bg) => ({
  padding: '3px 10px', borderRadius: 20,
  fontSize: '0.62rem', fontFamily: C.mono, fontWeight: 600,
  color, background: bg,
  border: `1px solid ${color}40`,
});

const btn = (accent = C.accent) => ({
  padding: '9px 20px', borderRadius: 8, border: 'none',
  background: `linear-gradient(135deg, ${accent}, ${accent}cc)`,
  color: '#fff', fontSize: '0.78rem', fontWeight: 700,
  cursor: 'pointer', fontFamily: C.sans,
  boxShadow: `0 2px 10px ${accent}40`,
  transition: 'opacity .2s',
});

const textarea = {
  width: '100%', background: C.bg2,
  border: `1px solid ${C.border}`, borderRadius: 8,
  padding: '10px 14px', color: C.text,
  fontFamily: C.sans, fontSize: '0.8rem',
  outline: 'none', resize: 'vertical', minHeight: 90,
};

const label = {
  fontSize: '0.62rem', color: C.text3,
  fontFamily: C.mono, textTransform: 'uppercase',
  letterSpacing: '0.1em', display: 'block', marginBottom: 6,
};

const sentimentColor = (label) =>
  label === 'POSITIVE' ? C.green : label === 'NEGATIVE' ? C.red : C.warn;

const DEFAULT_API = process.env.REACT_APP_API_BASE || 'http://127.0.0.1:3000';
const USER_TRAINING_WORKSPACE = 'User training workspace';
const READY_STATUS = 'Ready';

function getLocalUserNamespace() {
  try {
    const user = JSON.parse(localStorage.getItem('aria_user') || '{}');
    return user.email || user.username || user.name || user.id || '';
  } catch {
    return '';
  }
}

function authHeaders() {
  const token = localStorage.getItem('aria_token') || localStorage.getItem('token') || localStorage.getItem('authToken') || '';
  return {
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function apiError(error, fallback = 'Something went wrong. Please try again.') {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || item.message || 'Invalid field').join(' ');
  return detail || error?.message || fallback;
}

function formatMetric(value, kind = '') {
  if (value === undefined || value === null) return 'n/a';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (kind === 'accuracy') return `${(number * 100).toFixed(1)}%`;
  return number.toFixed(3);
}

function mainMetric(metrics = {}) {
  if (metrics.accuracy !== undefined) return `Accuracy ${formatMetric(metrics.accuracy, 'accuracy')}`;
  if (metrics.r2_score !== undefined) return `R2 ${formatMetric(metrics.r2_score)}`;
  if (metrics.mae !== undefined) return `MAE ${formatMetric(metrics.mae)}`;
  if (metrics.error) return 'Failed';
  return 'n/a';
}

function formatDate(value) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function statusColor(status) {
  return status === 'failed' ? C.red : C.green;
}

function useSelectedWorkspaceId() {
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(() => localStorage.getItem('eva_selected_workspace_id') || '');
  useEffect(() => {
    const syncWorkspace = () => setSelectedWorkspaceId(localStorage.getItem('eva_selected_workspace_id') || '');
    window.addEventListener('storage', syncWorkspace);
    window.addEventListener('eva:workspace-selected', syncWorkspace);
    return () => {
      window.removeEventListener('storage', syncWorkspace);
      window.removeEventListener('eva:workspace-selected', syncWorkspace);
    };
  }, []);
  return selectedWorkspaceId;
}

function useWorkspaceInfo(API, selectedWorkspaceId) {
  const [workspace, setWorkspace] = useState(null);
  useEffect(() => {
    let alive = true;
    if (!selectedWorkspaceId) {
      setWorkspace(null);
      return () => { alive = false; };
    }
    axios.get(`${API}/api/workspaces`, { headers: authHeaders() })
      .then((response) => {
        if (!alive) return;
        const items = response.data?.workspaces || [];
        setWorkspace(items.find((item) => String(item.id) === String(selectedWorkspaceId)) || null);
      })
      .catch(() => {
        if (alive) setWorkspace(null);
      });
    return () => { alive = false; };
  }, [API, selectedWorkspaceId]);
  return workspace;
}



/* ── Sub-tab pill ─────────────────────────────────────────────────────────── */
function Tabs({ tabs, active, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 20, borderBottom: `1px solid ${C.border}`, paddingBottom: 14 }}>
      {tabs.map(t => {
        const on = active === t.id;
        return (
          <button key={t.id} onClick={() => onChange(t.id)} style={{
            padding: '7px 16px', borderRadius: 8, border: `1px solid`,
            borderColor: on ? C.accent : C.border,
            background: on ? `${C.accent}18` : 'transparent',
            color: on ? C.accent : C.text2,
            fontSize: '0.78rem', fontWeight: on ? 700 : 500,
            cursor: 'pointer', fontFamily: C.sans, transition: 'all .2s',
          }}>{t.icon} {t.label}</button>
        );
      })}
    </div>
  );
}

/* ── Progress bar ─────────────────────────────────────────────────────────── */
function Bar({ value, color = C.accent, label: lbl, max = 1 }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: '0.7rem', color: C.text2 }}>{lbl}</span>
        <span style={{ fontSize: '0.7rem', color, fontFamily: C.mono }}>{pct}%</span>
      </div>
      <div style={{ height: 6, background: C.border, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`,
          background: `linear-gradient(90deg, ${color}, ${color}aa)`,
          borderRadius: 3, transition: 'width .6s ease',
        }} />
      </div>
    </div>
  );
}

/* ── Spinner ──────────────────────────────────────────────────────────────── */
function Spinner({ color = '#fff' }) {
  return (
    <span style={{
      display: 'inline-block', width: 14, height: 14,
      border: `2px solid ${color}40`, borderTop: `2px solid ${color}`,
      borderRadius: '50%', animation: 'spin .7s linear infinite',
    }} />
  );
}

/* ══════════════════════════════════════════════════════════════════════════════
   PANEL 1 — DOCUMENT CLASSIFIER
══════════════════════════════════════════════════════════════════════════════ */
function TrainingPanel({ API, selectedWorkspaceId, workspace }) {
  const [datasetFile, setDatasetFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [training, setTraining] = useState(false);
  const [uploadInfo, setUploadInfo] = useState(null);
  const [targetColumn, setTargetColumn] = useState('');
  const [taskType, setTaskType] = useState('auto');
  const [uploadError, setUploadError] = useState('');
  const [trainError, setTrainError] = useState('');
  const [trainResult, setTrainResult] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [successMessage, setSuccessMessage] = useState('');
  const [reportError, setReportError] = useState('');
  const [reportText, setReportText] = useState('');
  const [reportTitle, setReportTitle] = useState('');

  const effectiveWorkspaceId = selectedWorkspaceId || getLocalUserNamespace() || 'default';
  const workspaceName = workspace?.name || (selectedWorkspaceId ? 'Selected workspace' : USER_TRAINING_WORKSPACE);
  const workspaceStatus = selectedWorkspaceId ? 'Workspace selected' : READY_STATUS;
  const inputStyle = {
    width: '100%',
    background: C.bg2,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    padding: '9px 12px',
    color: C.text,
    fontFamily: C.sans,
    fontSize: '0.78rem',
    outline: 'none',
  };

  const loadJobs = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/ml/jobs`, {
        params: { workspace_id: effectiveWorkspaceId },
        headers: authHeaders(),
      });
      setJobs(data.jobs || []);
    } catch {
      setJobs([]);
    }
  }, [API, effectiveWorkspaceId]);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  async function uploadDataset(event) {
    event.preventDefault();
    setUploadError('');
    setTrainError('');
    setSuccessMessage('');
    setReportError('');
    setTrainResult(null);
    if (!datasetFile) {
      setUploadError('Choose a CSV dataset first.');
      return;
    }
    if (!datasetFile.name.toLowerCase().endsWith('.csv')) {
      setUploadError('Only CSV datasets are supported right now.');
      return;
    }

    const formData = new FormData();
    formData.append('file', datasetFile);
    formData.append('workspace_id', effectiveWorkspaceId);

    setUploading(true);
    try {
      const { data } = await axios.post(`${API}/api/ml/upload`, formData, { headers: authHeaders() });
      setUploadInfo(data);
      const nextColumns = data.columns || [];
      setTargetColumn(nextColumns[nextColumns.length - 1] || '');
      await loadJobs();
    } catch (error) {
      setUploadError(apiError(error, 'Dataset upload failed.'));
    } finally {
      setUploading(false);
    }
  }

  async function trainModel(event) {
    event.preventDefault();
    setTrainError('');
    setSuccessMessage('');
    setReportError('');
    setTrainResult(null);
    if (!uploadInfo?.filename) {
      setTrainError('Upload a CSV dataset before training.');
      return;
    }
    if (!targetColumn) {
      setTrainError('Choose the column you want EVA to predict.');
      return;
    }

    setTraining(true);
    try {
      const { data } = await axios.post(`${API}/api/ml/train`, {
        workspace_id: effectiveWorkspaceId,
        filename: uploadInfo.filename,
        target_column: targetColumn,
        task_type: taskType,
      }, { headers: authHeaders() });
      setTrainResult(data);
      setSuccessMessage(`Model trained and saved to ${selectedWorkspaceId ? 'this workspace' : 'your user training workspace'}.`);
      await loadJobs();
    } catch (error) {
      setTrainError(apiError(error, 'Training failed. Check your CSV columns and try again.'));
    } finally {
      setTraining(false);
    }
  }

  async function downloadReport(job) {
    setReportError('');
    try {
      const { data } = await axios.get(`${API}/api/ml/jobs/${job.id}/report`, {
        headers: authHeaders(),
        responseType: 'text',
      });
      const title = `Report - ${job.dataset_filename || job.filename}`;
      setReportTitle(title);
      setReportText(data);
      const blob = new Blob([data], { type: 'text/plain;charset=utf-8' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `eva-ml-report-${job.id}.txt`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      setReportError(apiError(error, 'Could not download this training report.'));
    }
  }

  const columns = uploadInfo?.columns || [];
  const resultMetrics = trainResult?.metrics || {};

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <form style={card()} onSubmit={uploadDataset}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
            <div>
              <span style={label}>Workspace</span>
              <div style={{ color: C.text, fontSize: '0.88rem', fontWeight: 700 }}>{workspaceName}</div>
            </div>
            <span style={badge(C.green, `${C.green}15`)}>
              {workspaceStatus}
            </span>
          </div>

          <span style={label}>CSV dataset</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setDatasetFile(event.target.files?.[0] || null)}
            disabled={uploading}
            style={inputStyle}
          />
          <div style={{ fontSize: '0.68rem', color: C.text3, marginTop: 8 }}>
            Upload a CSV file for {selectedWorkspaceId ? 'this workspace' : 'your user training workspace'}.
          </div>
          {uploadError && <div style={{ marginTop: 10, fontSize: '0.72rem', color: C.red }}>{uploadError}</div>}
          <button
            type="submit"
            disabled={uploading}
            style={{ ...btn(C.accent), marginTop: 12, opacity: uploading ? 0.55 : 1 }}
          >
            {uploading ? <Spinner /> : 'Upload dataset'}
          </button>
        </form>

        <form style={card()} onSubmit={trainModel}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
            <div>
              <span style={label}>Column to predict</span>
              <div style={{ color: C.text3, fontSize: '0.72rem' }}>Choose the column you want EVA to predict.</div>
            </div>
            {uploadInfo && <span style={badge(C.cyan, `${C.cyan}15`)}>{uploadInfo.rows} rows</span>}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
            <select
              value={targetColumn}
              onChange={(event) => setTargetColumn(event.target.value)}
              disabled={!columns.length || training}
              style={inputStyle}
            >
              <option value="">Select target column</option>
              {columns.map((column) => <option key={column} value={column}>{column}</option>)}
            </select>
            <select
              value={taskType}
              onChange={(event) => setTaskType(event.target.value)}
              disabled={!uploadInfo || training}
              style={inputStyle}
            >
              <option value="auto">Auto</option>
              <option value="classification">Classification</option>
              <option value="regression">Regression</option>
            </select>
          </div>

          {uploadInfo && (
            <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 8, background: C.bg2, border: `1px solid ${C.border}`, color: C.text2, fontSize: '0.72rem' }}>
              Dataset uploaded: <strong style={{ color: C.text }}>{uploadInfo.filename}</strong>
            </div>
          )}
          {trainError && <div style={{ marginTop: 10, fontSize: '0.72rem', color: C.red }}>{trainError}</div>}
          {successMessage && <div style={{ marginTop: 10, fontSize: '0.72rem', color: C.green }}>{successMessage}</div>}
          <button
            type="submit"
            disabled={!uploadInfo || !targetColumn || training}
            style={{ ...btn(C.green), marginTop: 12, opacity: !uploadInfo || !targetColumn || training ? 0.55 : 1 }}
          >
            {training ? <Spinner /> : 'Train model'}
          </button>
        </form>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={card()}>
          <span style={label}>Training result</span>
          {!trainResult ? (
            <div style={{ padding: '34px 0', textAlign: 'center', color: C.text3, fontSize: '0.82rem' }}>
              Result card appears after training.
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: C.text3, fontSize: '0.72rem' }}>Workspace name</span>
                <strong style={{ color: C.text, fontSize: '0.76rem' }}>{workspaceName}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: C.text3, fontSize: '0.72rem' }}>Dataset filename</span>
                <strong style={{ color: C.text, fontSize: '0.76rem' }}>{trainResult.filename}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: C.text3, fontSize: '0.72rem' }}>Task type</span>
                <span style={badge(C.cyan, `${C.cyan}15`)}>{trainResult.task_type}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: C.text3, fontSize: '0.72rem' }}>Model</span>
                <strong style={{ color: C.green, fontSize: '0.76rem' }}>{trainResult.model}</strong>
              </div>
              {Object.entries(resultMetrics).map(([key, value]) => (
                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <span style={{ color: C.text3, fontSize: '0.72rem' }}>{key === 'r2_score' ? 'R2 score' : key}</span>
                  <strong style={{ color: key === 'accuracy' ? C.green : C.text, fontSize: '0.76rem' }}>
                    {formatMetric(value, key)}
                  </strong>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: C.text3, fontSize: '0.72rem' }}>Rows used</span>
                <strong style={{ color: C.text, fontSize: '0.76rem' }}>{trainResult.rows_used}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: C.text3, fontSize: '0.72rem' }}>Features used</span>
                <strong style={{ color: C.text, fontSize: '0.76rem' }}>{trainResult.features_used}</strong>
              </div>
            </div>
          )}
        </div>

        <div style={card()}>
          <span style={label}>Training History</span>
          {jobs.length === 0 ? (
            <div style={{ color: C.text3, fontSize: '0.78rem' }}>No training jobs yet. Upload a dataset and train your first model.</div>
          ) : (
            <div style={{ display: 'grid', gap: 10, maxHeight: 360, overflowY: 'auto' }}>
              {jobs.map((job) => (
                <div key={job.id} style={{ padding: 12, borderRadius: 8, border: `1px solid ${C.border}`, background: C.bg2 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                    <strong style={{ color: C.text, fontSize: '0.78rem' }}>{job.dataset_filename || job.filename}</strong>
                    <span style={badge(statusColor(job.status), `${statusColor(job.status)}15`)}>{job.status || 'completed'}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, color: C.text3, fontSize: '0.68rem', lineHeight: 1.45 }}>
                    <div><strong style={{ color: C.text2 }}>Target</strong><br />{job.target_column}</div>
                    <div><strong style={{ color: C.text2 }}>Task type</strong><br />{job.task_type}</div>
                    <div><strong style={{ color: C.text2 }}>Model</strong><br />{job.model}</div>
                    <div><strong style={{ color: C.text2 }}>Main metric</strong><br />{mainMetric(job.metrics)}</div>
                    <div><strong style={{ color: C.text2 }}>Created date</strong><br />{formatDate(job.created_at)}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => downloadReport(job)}
                    style={{ ...btn(C.cyan), marginTop: 10, padding: '7px 12px', fontSize: '0.7rem' }}
                  >
                    View/Download report
                  </button>
                </div>
              ))}
            </div>
          )}
          {reportError && <div style={{ marginTop: 10, fontSize: '0.72rem', color: C.red }}>{reportError}</div>}
        </div>

        {reportText && (
          <div style={card()}>
            <span style={label}>{reportTitle || 'Training report'}</span>
            <pre style={{
              margin: 0,
              maxHeight: 240,
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              color: C.text2,
              fontFamily: C.mono,
              fontSize: '0.68rem',
              lineHeight: 1.55,
              background: C.bg2,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              padding: 12,
            }}>{reportText}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

function ClassifierPanel({ API, selectedWorkspaceId }) {
  const [text, setText]         = useState('');
  const [result, setResult]     = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');
  const [retrain, setRetrain]   = useState(false);
  const [samples, setSamples]   = useState('');
  const [sampleLabel, setLabel] = useState('Technical');

  const LABELS = ['Technical','Legal','Medical','Financial','Research','General'];
  const LABEL_COLORS = {
    Technical: C.accent, Legal: C.purple, Medical: C.red,
    Financial: C.green, Research: C.cyan, General: C.warn,
  };

  const examples = [
    { text: 'The neural network achieved 94% accuracy on the test set using dropout regularization.', label: 'Technical' },
    { text: 'The patient presented with acute myocardial infarction requiring immediate intervention.', label: 'Medical' },
    { text: 'Q3 revenue increased by 23% year-over-year driven by strong enterprise sales.', label: 'Financial' },
    { text: 'The parties agree that any disputes shall be resolved through binding arbitration.', label: 'Legal' },
  ];
  const effectiveWorkspaceId = selectedWorkspaceId || getLocalUserNamespace() || 'default';

  async function classify() {
    if (!text.trim()) return;
    setLoading(true); setError(''); setResult(null);
    try {
      const { data } = await axios.post(`${API}/ml/classify`, { text, workspace_id: effectiveWorkspaceId });
      setResult(data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  async function doRetrain() {
    if (!samples.trim()) return;
    setLoading(true); setError('');
    try {
      await axios.post(`${API}/ml/classifier/retrain`, [{ text: samples, label: sampleLabel, workspace_id: effectiveWorkspaceId }]);
      setRetrain(false); setSamples('');
      alert('✅ Classifier retrained successfully!');
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* Left: Input */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={card()}>
          <span style={label}>Document text</span>
          <textarea
            style={textarea}
            placeholder="Paste any document text to auto-classify it..."
            value={text} onChange={e => setText(e.target.value)}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            {examples.map((ex, i) => (
              <button key={i} onClick={() => setText(ex.text)} style={{
                fontSize: '0.62rem', padding: '3px 10px', borderRadius: 20,
                border: `1px solid ${LABEL_COLORS[ex.label]}40`,
                background: `${LABEL_COLORS[ex.label]}15`,
                color: LABEL_COLORS[ex.label], cursor: 'pointer',
              }}>{ex.label} example</button>
            ))}
          </div>
          {error && <div style={{ marginTop: 10, fontSize: '0.72rem', color: C.red }}>⚠ {error}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button style={btn(C.accent)} onClick={classify} disabled={loading}>
              {loading ? <Spinner /> : '🔍 Classify'}
            </button>
            <button style={{ ...btn(C.purple), background: 'transparent', border: `1px solid ${C.purple}`, color: C.purple, boxShadow: 'none' }}
              onClick={() => setRetrain(!retrain)}>
              ⚙ Retrain
            </button>
          </div>
        </div>

        {/* Retrain panel */}
        {retrain && (
          <div style={card({ border: `1px solid ${C.purple}40` })}>
            <span style={{ ...label, color: C.purple }}>Add training sample</span>
            <textarea style={{ ...textarea, minHeight: 60 }} placeholder="New training text..."
              value={samples} onChange={e => setSamples(e.target.value)} />
            <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
              <select value={sampleLabel} onChange={e => setLabel(e.target.value)} style={{
                background: C.bg2, border: `1px solid ${C.border}`, borderRadius: 6,
                padding: '6px 10px', color: C.text, fontFamily: C.sans, fontSize: '0.78rem', outline: 'none',
              }}>
                {LABELS.map(l => <option key={l}>{l}</option>)}
              </select>
              <button style={btn(C.purple)} onClick={doRetrain} disabled={loading}>
                {loading ? <Spinner /> : 'Train'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Right: Result */}
      <div style={card()}>
        <span style={label}>Classification result</span>
        {!result ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: C.text3, fontSize: '0.82rem' }}>
            <div style={{ fontSize: '2rem', marginBottom: 10 }}>📂</div>
            Result will appear here
          </div>
        ) : (
          <>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '16px', borderRadius: 10, marginBottom: 16,
              background: `${LABEL_COLORS[result.label] || C.accent}12`,
              border: `1px solid ${LABEL_COLORS[result.label] || C.accent}30`,
            }}>
              <div style={{ fontSize: '2rem' }}>
                {result.label === 'Technical' ? '⚙️' : result.label === 'Legal' ? '⚖️' :
                 result.label === 'Medical' ? '🏥' : result.label === 'Financial' ? '💰' :
                 result.label === 'Research' ? '🔬' : '📄'}
              </div>
              <div>
                <div style={{ fontSize: '1.1rem', fontWeight: 800, color: LABEL_COLORS[result.label] || C.accent }}>
                  {result.label}
                </div>
                <div style={{ fontSize: '0.72rem', color: C.text2, marginTop: 2 }}>
                  {Math.round(result.confidence * 100)}% confident
                </div>
              </div>
            </div>

            <span style={label}>Probability breakdown</span>
            {Object.entries(result.probabilities || {})
              .sort((a, b) => b[1] - a[1])
              .map(([lbl, prob]) => (
                <Bar key={lbl} lbl={lbl} label={lbl} value={prob}
                  color={LABEL_COLORS[lbl] || C.accent} />
              ))}
          </>
        )}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════════
   PANEL 2 — SENTIMENT ANALYSIS
══════════════════════════════════════════════════════════════════════════════ */
function SentimentPanel({ API, selectedWorkspaceId }) {
  const [text, setText]       = useState('');
  const [result, setResult]   = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');
  const [mode, setMode]       = useState('single'); // 'single' | 'conversation'
  const [convInput, setConv]  = useState('');
  const [convResult, setConvR]= useState(null);
  const [messages, setMessages] = useState([
    { role: 'user',      content: 'I love how fast ARIA responds!' },
    { role: 'assistant', content: 'Thank you! I try my best.' },
    { role: 'user',      content: 'But sometimes the answers are wrong.' },
    { role: 'assistant', content: 'I apologize for any errors. I will improve.' },
  ]);

  const examples = [
    'The RAG pipeline works amazingly well, I love the results!',
    'This is broken and completely useless, terrible experience.',
    'The system processed the document in 2.3 seconds.',
    'I am somewhat satisfied but there is room for improvement.',
  ];
  const effectiveWorkspaceId = selectedWorkspaceId || getLocalUserNamespace() || 'default';

  async function analyze() {
    if (!text.trim()) return;
    setLoading(true); setError(''); setResult(null);
    try {
      const { data } = await axios.post(`${API}/ml/sentiment`, { text, workspace_id: effectiveWorkspaceId });
      setResult(data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  async function analyzeConv() {
    setLoading(true); setError(''); setConvR(null);
    try {
      const { data } = await axios.post(`${API}/ml/sentiment/conversation`, { text: '', messages, workspace_id: effectiveWorkspaceId });
      setConvR(data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  const SentimentIcon = ({ label }) =>
    label === 'POSITIVE' ? '😊' : label === 'NEGATIVE' ? '😟' : '😐';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: 8 }}>
        {[['single','💬 Single Text'],['conversation','🗣 Conversation']].map(([id, lbl]) => (
          <button key={id} onClick={() => setMode(id)} style={{
            padding: '7px 16px', borderRadius: 8, border: `1px solid`,
            borderColor: mode === id ? C.cyan : C.border,
            background: mode === id ? `${C.cyan}18` : 'transparent',
            color: mode === id ? C.cyan : C.text2,
            fontSize: '0.78rem', fontWeight: mode === id ? 700 : 500,
            cursor: 'pointer', fontFamily: C.sans,
          }}>{lbl}</button>
        ))}
      </div>

      {mode === 'single' ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={card()}>
            <span style={label}>Text to analyze</span>
            <textarea style={textarea} placeholder="Enter any text to detect sentiment..."
              value={text} onChange={e => setText(e.target.value)} />
            <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
              {examples.map((ex, i) => (
                <button key={i} onClick={() => setText(ex)} style={{
                  fontSize: '0.58rem', padding: '3px 8px', borderRadius: 20,
                  border: `1px solid ${C.border}`, background: 'transparent',
                  color: C.text3, cursor: 'pointer',
                }}>{ex.slice(0, 28)}…</button>
              ))}
            </div>
            {error && <div style={{ marginTop: 8, fontSize: '0.72rem', color: C.red }}>⚠ {error}</div>}
            <button style={{ ...btn(C.cyan), marginTop: 12 }} onClick={analyze} disabled={loading}>
              {loading ? <Spinner /> : '🧠 Analyze Sentiment'}
            </button>
          </div>

          <div style={card()}>
            <span style={label}>Sentiment result</span>
            {!result ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: C.text3, fontSize: '0.82rem' }}>
                <div style={{ fontSize: '2.5rem', marginBottom: 10 }}>🎭</div>
                Result will appear here
              </div>
            ) : (
              <>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16,
                  padding: 16, borderRadius: 10,
                  background: `${sentimentColor(result.label)}12`,
                  border: `1px solid ${sentimentColor(result.label)}30`,
                }}>
                  <span style={{ fontSize: '2.5rem' }}><SentimentIcon label={result.label} /></span>
                  <div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 800, color: sentimentColor(result.label) }}>
                      {result.label}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: C.text2, marginTop: 2 }}>
                      Score: {result.score} · Compound: {result.compound}
                    </div>
                    <div style={{ fontSize: '0.62rem', color: C.text3, marginTop: 2 }}>
                      Model: {result.mode}
                    </div>
                  </div>
                </div>
                <Bar label="Confidence" value={result.score} color={sentimentColor(result.label)} />
                <div style={{
                  marginTop: 12, padding: '10px 14px', borderRadius: 8,
                  background: C.bg2, border: `1px solid ${C.border}`,
                  fontSize: '0.72rem', color: C.text2, fontFamily: C.mono,
                }}>
                  compound: {result.compound > 0 ? '+' : ''}{result.compound}
                </div>
              </>
            )}
          </div>
        </div>
      ) : (
        /* Conversation mode */
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={card()}>
            <span style={label}>Conversation messages</span>
            <div style={{ maxHeight: 260, overflowY: 'auto', marginBottom: 12 }}>
              {messages.map((m, i) => (
                <div key={i} style={{
                  display: 'flex', gap: 8, marginBottom: 8, alignItems: 'flex-start',
                }}>
                  <span style={{
                    fontSize: '0.6rem', padding: '2px 7px', borderRadius: 20,
                    background: m.role === 'user' ? `${C.accent}20` : `${C.green}20`,
                    color: m.role === 'user' ? C.accent : C.green,
                    fontFamily: C.mono, flexShrink: 0, marginTop: 2,
                  }}>{m.role}</span>
                  <span style={{ fontSize: '0.75rem', color: C.text2, flex: 1 }}>{m.content}</span>
                  <button onClick={() => setMessages(msgs => msgs.filter((_, j) => j !== i))}
                    style={{ background: 'none', border: 'none', color: C.red, cursor: 'pointer', fontSize: '0.7rem' }}>✕</button>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                placeholder="Add message..."
                value={convInput} onChange={e => setConv(e.target.value)}
                style={{ flex: 1, background: C.bg2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', color: C.text, fontFamily: C.sans, fontSize: '0.75rem', outline: 'none' }}
                onKeyDown={e => {
                  if (e.key === 'Enter' && convInput.trim()) {
                    setMessages(m => [...m, { role: 'user', content: convInput }]);
                    setConv('');
                  }
                }}
              />
            </div>
            {error && <div style={{ marginTop: 8, fontSize: '0.72rem', color: C.red }}>⚠ {error}</div>}
            <button style={{ ...btn(C.cyan), marginTop: 12 }} onClick={analyzeConv} disabled={loading}>
              {loading ? <Spinner /> : '🧠 Analyze Conversation'}
            </button>
          </div>

          <div style={card()}>
            <span style={label}>Conversation sentiment</span>
            {!convResult ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: C.text3 }}>
                <div style={{ fontSize: '2rem', marginBottom: 10 }}>🗣</div>
                Run analysis to see results
              </div>
            ) : (
              <>
                <div style={{
                  padding: 14, borderRadius: 10, marginBottom: 14,
                  background: `${sentimentColor(convResult.overall)}12`,
                  border: `1px solid ${sentimentColor(convResult.overall)}30`,
                }}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 700, color: sentimentColor(convResult.overall), marginBottom: 4 }}>
                    Overall: {convResult.overall}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: C.text2 }}>
                    Avg compound: {convResult.avg_compound > 0 ? '+' : ''}{convResult.avg_compound}
                  </div>
                </div>
                <span style={label}>Message breakdown</span>
                {(convResult.breakdown || []).map((b, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '7px 0', borderBottom: `1px solid ${C.border}40`,
                    fontSize: '0.72rem',
                  }}>
                    <span style={{ color: b.role === 'user' ? C.accent : C.green, fontFamily: C.mono }}>{b.role}</span>
                    <span style={{ ...badge(sentimentColor(b.label), `${sentimentColor(b.label)}15`) }}>{b.label}</span>
                    <span style={{ color: C.text3, fontFamily: C.mono }}>{b.compound > 0 ? '+' : ''}{b.compound}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════════
   PANEL 3 — EMBEDDING TRAINER
══════════════════════════════════════════════════════════════════════════════ */
function EmbeddingPanel({ API, selectedWorkspaceId }) {
  const [status, setStatus]     = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');
  const [pairs, setPairs]       = useState([
    { sentence1: 'machine learning model', sentence2: 'deep learning neural network', label: '0.9' },
    { sentence1: 'legal contract clause',  sentence2: 'terms and conditions agreement', label: '0.95' },
    { sentence1: 'machine learning',       sentence2: 'cooking recipe ingredients', label: '0.05' },
  ]);
  const [epochs, setEpochs]     = useState(3);
  const [trainRes, setTrainRes] = useState(null);
  const [sim1, setSim1]         = useState('The RAG pipeline retrieves documents');
  const [sim2, setSim2]         = useState('Document retrieval augmented generation');
  const [simRes, setSimRes]     = useState(null);
  const effectiveWorkspaceId = selectedWorkspaceId || getLocalUserNamespace() || 'default';

  const fetchStatus = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/ml/embeddings/status`);
      setStatus(data);
    } catch {}
  }, [API]);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  function addPair() {
    setPairs(p => [...p, { sentence1: '', sentence2: '', label: '0.8' }]);
  }

  function updatePair(i, field, val) {
    setPairs(p => p.map((pair, j) => j === i ? { ...pair, [field]: val } : pair));
  }

  async function train() {
    const valid = pairs.filter(p => p.sentence1.trim() && p.sentence2.trim());
    if (!valid.length) return;
    setLoading(true); setError(''); setTrainRes(null);
    try {
      const formatted = valid.map(p => ({ ...p, label: parseFloat(p.label) }));
      const { data } = await axios.post(`${API}/ml/embeddings/train`, { pairs: formatted, epochs, workspace_id: effectiveWorkspaceId });
      setTrainRes(data);
      fetchStatus();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  async function computeSim() {
    if (!sim1.trim() || !sim2.trim()) return;
    setLoading(true); setError('');
    try {
      const { data } = await axios.post(`${API}/ml/embeddings/similarity`, { text1: sim1, text2: sim2, workspace_id: effectiveWorkspaceId });
      setSimRes(data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  }

  const simColor = simRes
    ? simRes.similarity > 0.75 ? C.green : simRes.similarity > 0.45 ? C.warn : C.red
    : C.accent;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Status card */}
      {status && (
        <div style={card()}>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <div>
              <span style={label}>Base model</span>
              <span style={{ fontSize: '0.82rem', color: C.accent, fontFamily: C.mono }}>{status.base_model}</span>
            </div>
            <div>
              <span style={label}>Custom model</span>
              <span style={badge(status.custom_trained ? C.green : C.warn, status.custom_trained ? `${C.green}18` : `${C.warn}18`)}>
                {status.custom_trained ? '✓ Trained' : '○ Not trained'}
              </span>
            </div>
            {status.training_log?.length > 0 && (
              <div>
                <span style={label}>Last training</span>
                <span style={{ fontSize: '0.78rem', color: C.text2 }}>
                  {status.training_log[status.training_log.length - 1]?.timestamp}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Training pairs */}
        <div style={card()}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={label}>Training pairs</span>
            <button onClick={addPair} style={{
              fontSize: '0.65rem', padding: '3px 10px', borderRadius: 20,
              border: `1px solid ${C.purple}`, background: `${C.purple}15`,
              color: C.purple, cursor: 'pointer',
            }}>+ Add pair</button>
          </div>

          <div style={{ maxHeight: 240, overflowY: 'auto', marginBottom: 12 }}>
            {pairs.map((p, i) => (
              <div key={i} style={{
                padding: '10px', borderRadius: 8, border: `1px solid ${C.border}`,
                background: C.bg2, marginBottom: 8,
              }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 60px', gap: 6 }}>
                  <input
                    placeholder="Sentence 1..." value={p.sentence1}
                    onChange={e => updatePair(i, 'sentence1', e.target.value)}
                    style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, padding: '5px 8px', color: C.text, fontFamily: C.sans, fontSize: '0.72rem', outline: 'none' }}
                  />
                  <input
                    placeholder="Sentence 2..." value={p.sentence2}
                    onChange={e => updatePair(i, 'sentence2', e.target.value)}
                    style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, padding: '5px 8px', color: C.text, fontFamily: C.sans, fontSize: '0.72rem', outline: 'none' }}
                  />
                  <input
                    type="number" min="0" max="1" step="0.05" value={p.label}
                    onChange={e => updatePair(i, 'label', e.target.value)}
                    style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, padding: '5px 8px', color: C.purple, fontFamily: C.mono, fontSize: '0.72rem', outline: 'none' }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: '0.7rem', color: C.text3 }}>Epochs:</span>
            <input type="number" min="1" max="20" value={epochs}
              onChange={e => setEpochs(Number(e.target.value))}
              style={{ width: 50, background: C.bg2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '5px 8px', color: C.text, fontFamily: C.mono, fontSize: '0.78rem', outline: 'none' }}
            />
            <button style={btn(C.purple)} onClick={train} disabled={loading}>
              {loading ? <Spinner /> : '🚀 Train Model'}
            </button>
          </div>

          {error && <div style={{ marginTop: 8, fontSize: '0.72rem', color: C.red }}>⚠ {error}</div>}
          {trainRes && (
            <div style={{
              marginTop: 10, padding: '10px 14px', borderRadius: 8,
              background: `${C.green}12`, border: `1px solid ${C.green}30`,
              fontSize: '0.75rem', color: C.green,
            }}>{trainRes.message || '✅ Training complete!'}</div>
          )}
        </div>

        {/* Similarity tester */}
        <div style={card()}>
          <span style={label}>Semantic similarity tester</span>
          <div style={{ marginBottom: 10 }}>
            <span style={{ ...label, marginBottom: 4 }}>Text A</span>
            <textarea style={{ ...textarea, minHeight: 60 }}
              value={sim1} onChange={e => setSim1(e.target.value)} />
          </div>
          <div style={{ marginBottom: 10 }}>
            <span style={{ ...label, marginBottom: 4 }}>Text B</span>
            <textarea style={{ ...textarea, minHeight: 60 }}
              value={sim2} onChange={e => setSim2(e.target.value)} />
          </div>
          <button style={btn(C.cyan)} onClick={computeSim} disabled={loading}>
            {loading ? <Spinner /> : '⚡ Compute Similarity'}
          </button>

          {simRes && (
            <div style={{
              marginTop: 14, padding: 16, borderRadius: 10,
              background: `${simColor}12`, border: `1px solid ${simColor}30`,
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '2rem', fontWeight: 800, color: simColor, fontFamily: C.mono }}>
                {Math.round(simRes.similarity * 100)}%
              </div>
              <div style={{ fontSize: '0.78rem', color: simColor, fontWeight: 700, marginTop: 4 }}>
                {simRes.label}
              </div>
              <Bar label="Similarity score" value={simRes.similarity} color={simColor} />
            </div>
          )}

          <div style={{ marginTop: 14, padding: '10px 14px', borderRadius: 8, background: C.bg2, border: `1px solid ${C.border}`, fontSize: '0.68rem', color: C.text3, lineHeight: 1.6 }}>
            <strong style={{ color: C.text2 }}>Label guide:</strong><br />
            1.0 = identical · 0.8+ = very similar<br />
            0.6–0.8 = related · 0.3–0.6 = somewhat similar<br />
            0–0.3 = different topics
          </div>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════════
   MAIN ML PAGE
══════════════════════════════════════════════════════════════════════════════ */
export default function ML({ API: apiProp }) {
  const API = apiProp || DEFAULT_API;
  const [tab, setTab]         = useState('training');
  const [health, setHealth]   = useState(null);
  const [healthError, setHealthError] = useState(false);
  const selectedWorkspaceId = useSelectedWorkspaceId();
  const selectedWorkspace = useWorkspaceInfo(API, selectedWorkspaceId);

  const tabs = [
    { id: 'training',   icon: 'ML',  label: 'ML Training' },
    { id: 'classifier', icon: '🏷',  label: 'Document Classifier' },
    { id: 'sentiment',  icon: '🎭',  label: 'Sentiment Analysis' },
    { id: 'embeddings', icon: '🧬',  label: 'Embedding Trainer' },
  ];

  useEffect(() => {
    setHealthError(false);
    axios.get(`${API}/ml/health`)
      .then(r => setHealth(r.data))
      .catch(() => setHealthError(true));
  }, [API]);

  return (
    <div style={{ fontFamily: C.sans }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: '1rem', fontWeight: 700, color: C.text }}>ML & Deep Learning</div>
          <div style={{ fontSize: '0.65rem', color: C.text3, fontFamily: C.mono, marginTop: 2 }}>
            scikit-learn · transformers · sentence-transformers
          </div>
        </div>

        {/* Health badges */}
        {health ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span
              style={badge(
                health.classifier?.loaded ? C.green : C.red,
                `${health.classifier?.loaded ? C.green : C.red}15`
              )}
            >
              🏷 Classifier {health.classifier?.loaded ? 'ready' : 'offline'}
            </span>

            <span
              style={badge(
                health.sentiment?.loaded ? C.green : C.warn,
                `${health.sentiment?.loaded ? C.green : C.warn}15`
              )}
            >
              🎭 Sentiment ({health.sentiment?.mode || 'offline'})
            </span>

            <span
              style={badge(
                health.embeddings?.custom_trained ? C.purple : C.text3,
                `${health.embeddings?.custom_trained ? C.purple : C.text3}15`
              )}
            >
              🧬 {health.embeddings?.custom_trained ? 'Custom model' : 'Base model'}
            </span>
          </div>
        ) : healthError ? (
          <span style={badge(C.text3, `${C.text3}15`)}>⚠ ML health unavailable</span>
        ) : null}
      </div>

      {/* Tabs */}
      <Tabs tabs={tabs} active={tab} onChange={setTab} />

      {/* Panels */}
      {tab === 'training'    && <TrainingPanel   API={API} selectedWorkspaceId={selectedWorkspaceId} workspace={selectedWorkspace} />}
      {tab === 'classifier'  && <ClassifierPanel  API={API} selectedWorkspaceId={selectedWorkspaceId} />}
      {tab === 'sentiment'   && <SentimentPanel   API={API} selectedWorkspaceId={selectedWorkspaceId} />}
      {tab === 'embeddings'  && <EmbeddingPanel   API={API} selectedWorkspaceId={selectedWorkspaceId} />}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
