import { useState, useRef, useCallback, useEffect } from 'react';
import './uploadProgress.css';

// Ã¢â€â‚¬Ã¢â€â‚¬ Fetch with timeout Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
async function fetchWithTimeout(url, options = {}, ms = 245000, attempt = 0) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(tid);
    return res;
  } catch (err) {
    clearTimeout(tid);
    if (err.name === 'AbortError') {
      if (attempt === 0) {
        console.warn(`[RAG] Backend may be waking up; retrying once after ${ms}ms timeout: ${url}`);
        await new Promise(resolve => setTimeout(resolve, 2500));
        return fetchWithTimeout(url, options, ms, 1);
      }
      console.error(`[RAG] Backend is taking longer than expected to respond: ${url}`);
      throw new Error('Backend is taking longer than expected to respond.');
    }
    throw err;
  }
}

const defaultApi = process.env.REACT_APP_API_BASE || 'http://127.0.0.1:8000';
// RAG service (upload / ingest / query / stats / documents) lives on the HF service with
// persistent Supabase storage Ã¢â‚¬â€ not Render. Override with REACT_APP_RAG_API_BASE if needed.
const RAG_API = process.env.REACT_APP_RAG_API_BASE || 'http://127.0.0.1:7860';

function getHeaders() {
  const token = ['aria_token', 'token', 'access_token', 'authToken']
    .map(k => localStorage.getItem(k)).find(Boolean) || '';
  // Update 65: knowledge-base WRITES (ingest-url, document delete) are gated
  // by X-Train-Key on the ML service. Same localStorage slot the Training
  // Center writes, so setting the key once covers both admin surfaces.
  const trainKey = localStorage.getItem('trainKey') || '';
  return {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
    ...(trainKey ? { 'X-Train-Key': trainKey } : {}),
  };
}

// Ã¢â€â‚¬Ã¢â€â‚¬ ML Intent Detection (client-side lightweight classifier) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function getLocalUserNamespace() {
  try {
    const user = JSON.parse(localStorage.getItem('aria_user') || '{}');
    return user.email || user.username || user.name || user.id || '';
  } catch {
    return '';
  }
}

async function readJsonResponse(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    if (text.includes('<!doctype') || text.includes('<html')) {
      throw new Error('RAG API returned the app page instead of JSON. Check that the /rag routes are mounted on the HF RAG service.');
    }
    return { detail: text.slice(0, 200) };
  }
}

function ragErrorMessage(res, data, action) {
  if (res.status === 401) return 'Session expired or missing. Please log in again before using RAG.';
  // Update 65: writes are gated by X-Train-Key Ã¢â‚¬â€ say exactly how to fix it
  // rather than surfacing a bare 403.
  if (res.status === 403) {
    return `RAG ${action} needs the admin key. Open the Training Center `
      + '(/admin/training), paste TRAIN_ADMIN_KEY into the X-Train-Key box and '
      + 'click Save key, then retry here.';
  }
  if (res.status === 405) return `RAG ${action} used a method the backend does not allow. Check the /rag route and HTTP method.`;
  return data.detail || data.message || `RAG ${action} failed (${res.status})`;
}

const INTENT_PATTERNS = {
  code:       /\b(code|function|class|bug|error|debug|implement|script|syntax|python|javascript|api)\b/i,
  document:   /\b(document|file|pdf|upload|content|summarize|extract|read|page)\b/i,
  learning:   /\b(learn|explain|what is|how does|tutorial|concept|understand|teach)\b/i,
  search:     /\b(find|search|look up|retrieve|get me|where is|list all)\b/i,
  analysis:   /\b(analyze|compare|evaluate|assess|review|score|rank)\b/i,
};

function detectIntent(query) {
  for (const [intent, pattern] of Object.entries(INTENT_PATTERNS)) {
    if (pattern.test(query)) return intent;
  }
  return 'general';
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Model Router Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
const MODEL_ROUTES = {
  code:     { model: 'Qwen Coder / Claude',   color: '#818cf8', emoji: 'Ã¢Å¡Â¡' },
  document: { model: 'Gemini Flash',          color: '#34d399', emoji: 'Ã°Å¸â€œâ€ž' },
  learning: { model: 'GPT-4o-mini',           color: '#fbbf24', emoji: 'Ã°Å¸â€œÅ¡' },
  search:   { model: 'Gemini Flash',          color: '#38bdf8', emoji: 'Ã°Å¸â€Â' },
  analysis: { model: 'Claude Sonnet',         color: '#f472b6', emoji: 'Ã°Å¸Â§Â ' },
  general:  { model: 'Groq Llama / Gemini Flash', color: '#a78bfa', emoji: 'Ã°Å¸â€™Â¬' },
};

// Ã¢â€â‚¬Ã¢â€â‚¬ Source badge Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function SourceBadge({ source }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700,
      background: 'rgba(56,189,248,.1)', border: '1px solid rgba(56,189,248,.2)', color: '#7dd3fc',
    }}>
      Ã°Å¸â€œÅ½ {source}
    </span>
  );
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Message bubble Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
const RAG_MODES = [
  ['auto', 'Automatic', 'EVA chooses best'],
  ['hybrid', 'Hybrid', 'Best accuracy'],
  ['vector', 'Vector RAG', 'Semantic document search'],
  ['vectorless', 'Vectorless RAG', 'Fast keyword search'],
];

function prettyMode(mode) {
  const found = RAG_MODES.find(([value]) => value === mode);
  return found ? found[1] : String(mode || 'Automatic');
}

function MessageBubble({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div style={{
      display: 'flex', flexDirection: isUser ? 'row-reverse' : 'row',
      gap: 10, alignItems: 'flex-start', padding: '4px 0',
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
        background: isUser ? 'linear-gradient(135deg,#7c3aed,#a855f7)' : 'linear-gradient(135deg,#0f766e,#2563eb)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, color: '#fff', fontWeight: 700,
      }}>
        {isUser ? 'U' : 'E'}
      </div>
      <div style={{ maxWidth: '75%', display: 'flex', flexDirection: 'column', gap: 6, alignItems: isUser ? 'flex-end' : 'flex-start' }}>
        <div style={{
          padding: '10px 14px', borderRadius: isUser ? '14px 4px 14px 14px' : '4px 14px 14px 14px',
          background: isUser ? 'rgba(124,58,237,.2)' : 'rgba(255,255,255,.05)',
          border: `1px solid ${isUser ? 'rgba(124,58,237,.3)' : 'rgba(255,255,255,.08)'}`,
          color: '#e8e0ff', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap',
        }}>
          {msg.content}
        </div>
        {msg.sources?.length > 0 && (
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {msg.sources.map((s, i) => <SourceBadge key={i} source={s} />)}
          </div>
        )}
        {msg.intent && (
          <div style={{ fontSize: 10, color: '#4a2d7a', display: 'flex', gap: 6 }}>
            <span>Intent: <span style={{ color: MODEL_ROUTES[msg.intent]?.color }}>{msg.intent}</span></span>
            <span>â†’ {MODEL_ROUTES[msg.intent]?.model}</span>
          </div>
        )}
        {!isUser && msg.modeUsed && (
          <div style={S.responseMeta}>
            <span>Mode used: {prettyMode(msg.modeUsed)}</span>
            {msg.fallbackUsed && <span style={S.fallbackBadge}>Fallback used</span>}
          </div>
        )}
      </div>
    </div>
  );
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Document card Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function DocCard({ doc, onDelete }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.08)',
      borderRadius: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <div style={{ fontSize: 20, flexShrink: 0 }}>
        {doc.type === 'pdf' ? 'Ã°Å¸â€œâ€ž' : doc.type === 'txt' ? 'Ã°Å¸â€œÂ' : doc.type === 'url' ? 'Ã°Å¸Å’Â' : 'Ã°Å¸â€œÂ'}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: '#e8e0ff', fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</div>
        <div style={{ color: '#4a2d7a', fontSize: 10, marginTop: 2 }}>{doc.chunks} chunks Ã‚Â· {doc.category}</div>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        <span style={{
          padding: '2px 6px', borderRadius: 999, fontSize: 9, fontWeight: 700,
          background: 'rgba(52,211,153,.1)', border: '1px solid rgba(52,211,153,.2)', color: '#34d399',
        }}>indexed</span>
        <button onClick={() => onDelete(doc.id)} style={{ background: 'none', border: 'none', color: '#4a2d7a', cursor: 'pointer', fontSize: 14, padding: '0 2px' }}>Ãƒâ€”</button>
      </div>
    </div>
  );
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Upload progress (async job) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
// Friendly text for every REAL backend state (job_manager.py). CHUNKING and
// VALIDATING are real states the backend emits, so they are covered here Ã¢â‚¬â€ no
// state is dropped. Any status not in this map falls back to the backend's own
// `current_step` string, so nothing is ever labelled with an invented name.
export const STAGE_LABELS = {
  QUEUED:    'Queued for processingÃ¢â‚¬Â¦',
  PARSING:   'Reading documentÃ¢â‚¬Â¦',
  CHUNKING:  'Chunking textÃ¢â‚¬Â¦',
  VALIDATING:'Validating chunksÃ¢â‚¬Â¦',
  EMBEDDING: 'Generating embeddingsÃ¢â‚¬Â¦',
  INDEXING:  'Indexing vectorsÃ¢â‚¬Â¦',
  COMPLETE:  'Upload complete',
  FAILED:    'Upload failed',
  CANCELLED: 'Upload cancelled',
};
const TERMINAL_STATES = new Set(['COMPLETE', 'FAILED', 'CANCELLED']);

export function stageLabel(job) {
  if (!job) return '';
  return STAGE_LABELS[job.status] || job.current_step || 'ProcessingÃ¢â‚¬Â¦';
}

// Renders real job state. Progress bar animates from the payload's numeric
// `progress`; if the backend sends no numeric progress, an indeterminate
// shimmer is shown and NO percentage is displayed (never fabricated).
export function UploadProgress({ job, stalled }) {
  if (!job) return null;
  const status = job.status;
  const isComplete = status === 'COMPLETE';
  const isFailed = status === 'FAILED';
  const isCancelled = status === 'CANCELLED';
  const hasProgress = typeof job.progress === 'number' && !Number.isNaN(job.progress);
  const pct = hasProgress ? Math.max(0, Math.min(100, job.progress)) : null;

  const dotClass = isComplete ? 'eva-up__dot--complete'
    : isFailed ? 'eva-up__dot--error'
    : isCancelled ? 'eva-up__dot--cancel' : '';
  const fillClass = isComplete ? 'eva-up__fill--complete'
    : isFailed ? 'eva-up__fill--error' : '';
  const label = stageLabel(job);

  return (
    <div className="eva-up" data-status={status}>
      <div className={`eva-up__row${isFailed ? ' eva-up__row--error' : ''}`}>
        <span className={`eva-up__dot ${dotClass}`.trim()} aria-hidden="true" />
        <span
          className={`eva-up__label${isComplete ? ' eva-up__check' : ''}`.trim()}
          aria-live="polite"
        >
          {isComplete ? 'âœ“ ' : isFailed ? 'âœ• ' : isCancelled ? 'âŠ˜ ' : ''}{label}
          {isComplete && typeof job.chunk_count === 'number' && job.chunk_count > 0
            ? ` â€” ${job.chunk_count} chunks`
            : ''}
        </span>
        {pct != null && !isFailed && !isCancelled && (
          <span className="eva-up__pct">{pct}%</span>
        )}
      </div>

      {!isCancelled && (
        <div className={`eva-up__track${pct == null && !isComplete && !isFailed ? ' eva-up__track--indeterminate' : ''}`}>
          <div
            className={`eva-up__fill ${fillClass}`.trim()}
            style={pct != null ? { width: `${isComplete ? 100 : pct}%` } : undefined}
          />
        </div>
      )}

      {isFailed && job.error && (
        <div className="eva-up__stall" style={{ color: '#f87171' }}>{job.error}</div>
      )}
      {stalled && !TERMINAL_STATES.has(status) && (
        <div className="eva-up__stall" aria-live="polite">Ã¢Å¡Â  Taking longer than expectedÃ¢â‚¬Â¦ still working.</div>
      )}
    </div>
  );
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Main RAG 2.0 Component Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
// eslint-disable-next-line no-unused-vars -- API prop kept intentionally; RAG calls now use RAG_API (HF).
export default function RAGCenter({ API = defaultApi }) {
  const [messages, setMessages] = useState([
    { id: 1, role: 'assistant', content: 'RAG 2.0 ready. Upload documents, paste a URL, or ask anything. I detect intent and route to the best model automatically.', sources: [] }
  ]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [docs, setDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [uploadMsg, setUploadMsg] = useState('');       // used by URL ingest + errors
  const [uploadJob, setUploadJob] = useState(null);     // async file-upload job state
  const [uploadStall, setUploadStall] = useState(false);

  const [tab, setTab] = useState('chat'); // chat | documents | settings
  const [topK, setTopK] = useState(5);
  const [scoreThreshold, setScoreThreshold] = useState(0.3);
  const [selectedModel, setSelectedModel] = useState('auto');
  const [ragMode, setRagMode] = useState('auto');
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(() => localStorage.getItem('eva_selected_workspace_id') || '');

  const [stats, setStats] = useState({ total_documents: 0, total_chunks: 0, collections: [] });
  const [uploadLimits, setUploadLimits] = useState(null); // { mode, max_upload_mb, max_chunks, async_jobs }
  const [ragStatus, setRagStatus] = useState({
    online: false,
    vector_rag: 'unavailable',
    vectorless_rag: 'unavailable',
    default_mode: 'auto',
  });

  const fileRef = useRef(null);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const pollRef = useRef(null);   // setInterval id for job polling
  const stallRef = useRef(null);  // setTimeout id for stall warning

  // Clear any running poll/stall timers. Called on terminal state and unmount.
  const clearUploadTimers = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (stallRef.current) { clearTimeout(stallRef.current); stallRef.current = null; }
  }, []);

  // Cleanup on unmount Ã¢â‚¬â€ assert no interval/timeout leaks past this component.
  useEffect(() => clearUploadTimers, [clearUploadTimers]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    const syncWorkspace = () => setSelectedWorkspaceId(localStorage.getItem('eva_selected_workspace_id') || '');
    window.addEventListener('storage', syncWorkspace);
    window.addEventListener('eva:workspace-selected', syncWorkspace);
    return () => {
      window.removeEventListener('storage', syncWorkspace);
      window.removeEventListener('eva:workspace-selected', syncWorkspace);
    };
  }, []);

  const effectiveWorkspaceId = selectedWorkspaceId || getLocalUserNamespace() || 'default';
  const workspaceQuery = `?workspace_id=${encodeURIComponent(effectiveWorkspaceId)}`;

  const loadStats = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${RAG_API}/rag/stats${workspaceQuery}`, { headers: getHeaders() }, 45000);
      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'stats load'));
      setStats({
        total_documents: data.document_count ?? data.total_documents ?? 0,
        total_chunks: data.chunk_count ?? data.total_chunks ?? 0,
        collections: data.collections || [],
      });
    } catch (e) {
      setError(e.message);
    }
  }, [workspaceQuery]);

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${RAG_API}/rag/status`, { headers: getHeaders() }, 45000);
      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'status load'));
      setRagStatus({
        online: data.online ?? true,
        vector_rag: data.vector_rag || 'unavailable',
        vectorless_rag: data.vectorless_rag || 'unavailable',
        default_mode: data.default_mode || 'auto',
      });
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const loadDocuments = useCallback(async () => {
    setDocsLoading(true);
    try {
      const res = await fetchWithTimeout(`${RAG_API}/rag/documents${workspaceQuery}`, { headers: getHeaders() }, 45000);
      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'documents load'));
      setDocs(data.documents || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setDocsLoading(false);
    }
  }, [workspaceQuery]);

  const loadLimits = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${RAG_API}/rag/limits`, { headers: getHeaders() }, 45000);
      const data = await readJsonResponse(res);
      if (res.ok && (data.max_upload_mb != null || data.max_upload_label)) setUploadLimits(data);
    } catch {
      // Soft-fail: older deployed backends may not have this route yet.
      // uploadFile() falls back to a conservative default when uploadLimits is null.
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadStats();
    loadDocuments();
    loadLimits();
  }, [loadStatus, loadStats, loadDocuments, loadLimits]);

  const sendQuery = useCallback(async () => {
    const q = query.trim();
    if (!q || loading) return;

    const intent = detectIntent(q);
    const route = MODEL_ROUTES[intent];

    const userMsg = { id: Date.now(), role: 'user', content: q, intent };
    setMessages(prev => [...prev, userMsg]);
    setQuery('');
    setLoading(true);
    setError('');

    try {
      const res = await fetchWithTimeout(`${RAG_API}/rag/chat`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          message: q,
          mode: ragMode,
          workspace_id: effectiveWorkspaceId,
          top_k: topK,
          score_threshold: scoreThreshold,
          model_preference: selectedModel === 'auto' ? intent : selectedModel,
          intent,
        }),
      }, 20000);

      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'chat'));

      const assistantMsg = {
        id: Date.now() + 1,
        role: 'assistant',
        content: data.answer || data.response || data.result || 'No answer returned.',
        sources: data.sources || data.source_documents || [],
        intent,
        model: route.model,
        score: data.confidence_score || data.confidence,
        modeUsed: data.mode_used || data.mode,
        fallbackUsed: !!data.fallback_used,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (e) {
      setError(e.message);
      setMessages(prev => [...prev, {
        id: Date.now() + 1, role: 'assistant',
        content: `Error: ${e.message}`, sources: [],
      }]);
    }
    setLoading(false);
  }, [query, loading, ragMode, effectiveWorkspaceId, topK, scoreThreshold, selectedModel]);

  const uploadFile = async (file) => {
    if (!file) return;
    const maxMb = uploadLimits?.max_upload_mb ?? null;
    if (maxMb != null && file.size > maxMb * 1024 * 1024) { setError(`File too large (max ${maxMb}MB)`); return; }

    clearUploadTimers();
    setUploadJob(null);
    setUploadStall(false);
    setDocsLoading(true);
    setUploadMsg('Uploading and indexing...');
    setError('');

    try {
      const form = new FormData();
      form.append('file', file);
      form.append('workspace_id', effectiveWorkspaceId);
      const token = ['aria_token', 'token', 'access_token', 'authToken'].map(k => localStorage.getItem(k)).find(Boolean) || '';
      const res = await fetchWithTimeout(`${RAG_API}/rag/upload`, {
        method: 'POST',
        headers: {
          'ngrok-skip-browser-warning': 'true',
          ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: form,
      }, 30000);

      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'upload'));

      if (!data.job_id) throw new Error(data.detail || 'Upload job was not created');

      // Async job accepted Ã¢â‚¬â€ clear the pre-job message and drive the animated
      // stage UI from the real /rag/jobs/{id} payload.
      setUploadMsg('');
      setUploadStall(false);
      setUploadJob({
        status: data.status || 'QUEUED',
        current_step: data.message || 'Queued',
        progress: typeof data.progress === 'number' ? data.progress : 0,
        chunk_count: 0,
        error: null,
      });

      await new Promise((resolve) => {
        let lastStatus = null;

        // Arm a 20s stall timer for the CURRENT state. If the same state
        // persists past 20s we surface an honest notice but KEEP polling Ã¢â‚¬â€
        // CPU embedding can legitimately be slow; we never auto-fail.
        const armStall = (status) => {
          if (stallRef.current) clearTimeout(stallRef.current);
          setUploadStall(false);
          stallRef.current = setTimeout(() => setUploadStall(true), 20000);
          lastStatus = status;
        };

        const finish = async (jobData, isError) => {
          clearUploadTimers();
          setUploadStall(false);
          setUploadJob(jobData);
          try {
            await loadDocuments();
            await loadStats();
            await loadStatus();
          } catch (loadErr) {
            setError(loadErr.message);
          }
          if (isError) setError(jobData.error || 'Upload failed');
          resolve();
        };

        armStall(data.status || 'QUEUED');
        pollRef.current = setInterval(async () => {
          try {
            const jobRes = await fetchWithTimeout(`${RAG_API}/rag/jobs/${data.job_id}`, { headers: getHeaders() }, 8000);
            const jobData = await readJsonResponse(jobRes);
            if (!jobRes.ok) {
              finish({ status: 'FAILED', current_step: 'Failed', progress: 100, error: jobData.detail || jobData.error || 'Job lookup failed' }, true);
              return;
            }
            // Reset the stall timer only when the state actually advances.
            if (jobData.status !== lastStatus) armStall(jobData.status);
            setUploadJob(jobData);
            if (TERMINAL_STATES.has(jobData.status)) {
              finish(jobData, jobData.status !== 'COMPLETE');
            }
          } catch (e) {
            finish({ status: 'FAILED', current_step: 'Failed', progress: 100, error: e.message }, true);
          }
        }, 1000);
      });
    } catch (e) {
      setError(e.message);
      setUploadMsg('');
    } finally {
      setDocsLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const ingestUrl = async () => {
    const url = urlInput.trim();
    if (!url) return;
    setDocsLoading(true);
    setUploadMsg('Fetching and indexing URL...');
    setError('');
    try {
      const res = await fetchWithTimeout(`${RAG_API}/rag/ingest-url`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ url, workspace_id: effectiveWorkspaceId }),
      }, 30000);
      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'URL ingest'));
      setUploadMsg(`âœ… URL indexed: ${data.chunks_created || '?'} chunks`);
      setUrlInput('');
      await loadDocuments();
      await loadStats();
      await loadStatus();
    } catch (e) {
      setError(e.message);
      setUploadMsg('');
    } finally {
      setDocsLoading(false);
    }
  };

  const deleteDoc = async (docId) => {
    try {
      const suffix = `?workspace_id=${encodeURIComponent(effectiveWorkspaceId)}`;
      const res = await fetchWithTimeout(`${RAG_API}/rag/document/${docId}${suffix}`, { method: 'DELETE', headers: getHeaders() }, 8000);
      const data = await readJsonResponse(res);
      if (!res.ok) throw new Error(ragErrorMessage(res, data, 'document delete'));
      setDocs(prev => prev.filter(d => d.id !== docId));
      await loadStats();
      await loadStatus();
    } catch (e) {
      setError(e.message);
    }
  };

  const clearConversation = () => {
    setMessages([{ id: Date.now(), role: 'assistant', content: 'Conversation cleared. Ask me anything.', sources: [] }]);
  };

  const currentIntent = query ? detectIntent(query) : null;
  const currentRoute = currentIntent ? MODEL_ROUTES[currentIntent] : null;
  const uploadLimitLabel = uploadLimits?.max_upload_label || (uploadLimits?.max_upload_mb ? `${uploadLimits.max_upload_mb}MB` : 'Loading limits...');

  return (
    <div style={S.root}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.headerLeft}>
          <div style={S.logo}>RAG 2.0</div>
          <div style={S.logoSub}>Retrieval-Augmented Generation Ã‚Â· Intent-Aware Ã‚Â· Model-Routed</div>
        </div>
        <div style={S.headerStats}>
          <StatusBadge label="Mode" value={selectedWorkspaceId ? 'Workspace Selected' : 'Ready User Mode'} />
          <StatusBadge label="Vector" value={ragStatus.vector_rag} />
          <StatusBadge label="Vectorless" value={ragStatus.vectorless_rag} />
          <StatusBadge label="Default" value={ragStatus.default_mode} />
          <StatPill label="Docs" value={stats.total_documents} color="#38bdf8" />
          <StatPill label="Chunks" value={stats.total_chunks} color="#34d399" />
          <StatPill label="Collections" value={stats.collections?.length || 0} color="#a78bfa" />
        </div>
      </div>

      {/* Tabs */}
      <div style={S.tabs}>
        {['chat', 'documents', 'settings'].map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ ...S.tab, ...(tab === t ? S.tabActive : {}) }}>
            {t === 'chat' ? 'Ã°Å¸â€™Â¬ Chat' : t === 'documents' ? 'Ã°Å¸â€œÂ Documents' : 'Ã¢Å¡â„¢Ã¯Â¸Â Settings'}
          </button>
        ))}
      </div>

      {error && <div style={S.error}>Ã¢Å¡Â  {error} <button onClick={() => setError('')} style={S.errorClose}>Ãƒâ€”</button></div>}

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ CHAT TAB Ã¢â€â‚¬Ã¢â€â‚¬ */}
      {tab === 'chat' && (
        <div style={S.chatLayout}>
          <div style={S.chatMessages}>
            {messages.map(msg => <MessageBubble key={msg.id} msg={msg} />)}
            {loading && (
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '4px 0' }}>
                <div style={S.aiBubble}>E</div>
                <div style={S.thinkingBubble}>
                  <span style={S.dot1} />
                  <span style={S.dot2} />
                  <span style={S.dot3} />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div style={S.inputArea}>
            <div style={S.modeSelector}>
              {RAG_MODES.map(([value, label, detail]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setRagMode(value)}
                  style={{ ...S.modeBtn, ...(ragMode === value ? S.modeBtnActive : {}) }}
                >
                  <span>{label}</span>
                  <small>{detail}</small>
                </button>
              ))}
            </div>
            {currentRoute && (
              <div style={S.routerBadge}>
                <span>{currentRoute.emoji} Routing to</span>
                <span style={{ color: currentRoute.color, fontWeight: 700 }}>{currentRoute.model}</span>
                <span style={{ color: '#4a2d7a' }}>Ã‚Â· intent: {currentIntent}</span>
              </div>
            )}
            <div style={S.inputRow}>
              <textarea
                ref={inputRef}
                style={S.textarea}
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Ask anything Ã¢â‚¬â€ EVA detects intent and routes to the best model..."
                rows={2}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuery(); } }}
              />
              <div style={S.inputButtons}>
                <button onClick={sendQuery} disabled={loading || !query.trim()} style={S.sendBtn}>
                  {loading ? 'Ã¢ÂÂ³' : 'Ã¢â€ â€˜'}
                </button>
                <button onClick={clearConversation} style={S.clearBtn} title="Clear chat">Ã°Å¸â€”â€˜</button>
              </div>
            </div>
            <div style={S.inputHint}>Enter to send Ã‚Â· Shift+Enter for newline</div>
          </div>
        </div>
      )}

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ DOCUMENTS TAB Ã¢â€â‚¬Ã¢â€â‚¬ */}
      {tab === 'documents' && (
        <div style={S.docsLayout}>
          <div style={S.uploadSection}>
            <div style={S.sectionTitle}>Upload Documents</div>
            <div style={S.uploadGrid}>
              <button style={S.uploadBtn} onClick={() => fileRef.current?.click()} disabled={docsLoading}>
                <span style={{ fontSize: 24 }}>Ã°Å¸â€œâ€ž</span>
                <span style={{ fontWeight: 700, color: '#e8e0ff' }}>Upload File</span>
                <span style={{ fontSize: 11, color: '#4a2d7a' }}>
                  PDF, TXT, MD, DOCX (max {uploadLimitLabel}{uploadLimits?.mode === 'local' ? ', local mode' : ''})
                </span>
              </button>
              <div style={S.urlIngest}>
                <div style={{ color: '#8b7ab0', fontSize: 12, marginBottom: 6 }}>Ã°Å¸Å’Â Ingest URL</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input
                    style={S.urlInput}
                    value={urlInput}
                    onChange={e => setUrlInput(e.target.value)}
                    placeholder="https://example.com/article"
                    onKeyDown={e => e.key === 'Enter' && ingestUrl()}
                  />
                  <button style={S.ingestBtn} onClick={ingestUrl} disabled={docsLoading || !urlInput.trim()}>
                    {docsLoading ? 'â€¦' : 'Ingest'}
                  </button>
                </div>
              </div>
            </div>
            <input ref={fileRef} type="file" style={{ display: 'none' }} accept=".pdf,.txt,.md,.docx,.csv,.json" onChange={e => uploadFile(e.target.files?.[0])} />
            {uploadMsg && <div style={S.uploadMsg}>{uploadMsg}</div>}
            <UploadProgress job={uploadJob} stalled={uploadStall} />
          </div>

          <div style={S.sectionTitle}>Indexed Documents ({docs.length})</div>
          {docsLoading && <div style={{ color: '#4a2d7a', fontSize: 12, padding: '8px 0' }}>Loading documents...</div>}
          <div style={S.docsList}>
            {docs.length === 0 && !docsLoading && (
              <div style={{ color: '#4a2d7a', fontSize: 13, padding: 20, textAlign: 'center' }}>
                {selectedWorkspaceId ? 'No documents in this workspace yet. Upload a file or ingest a URL above.' : 'No documents in user mode yet. Upload a file or ingest a URL above.'}
              </div>
            )}
            {docs.map(doc => <DocCard key={doc.id} doc={doc} onDelete={deleteDoc} />)}
          </div>
        </div>
      )}

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ SETTINGS TAB Ã¢â€â‚¬Ã¢â€â‚¬ */}
      {tab === 'settings' && (
        <div style={S.settingsLayout}>
          <div style={S.settingsSection}>
            <div style={S.sectionTitle}>Retrieval Settings</div>
            <SettingRow label="Top-K Results" hint="Number of chunks to retrieve">
              <input type="range" min={1} max={20} value={topK} onChange={e => setTopK(Number(e.target.value))} style={{ flex: 1 }} />
              <span style={S.settingValue}>{topK}</span>
            </SettingRow>
            <SettingRow label="Score Threshold" hint="Minimum similarity score (0Ã¢â‚¬â€œ1)">
              <input type="range" min={0} max={1} step={0.05} value={scoreThreshold} onChange={e => setScoreThreshold(Number(e.target.value))} style={{ flex: 1 }} />
              <span style={S.settingValue}>{scoreThreshold.toFixed(2)}</span>
            </SettingRow>
          </div>

          <div style={S.settingsSection}>
            <div style={S.sectionTitle}>Model Router</div>
            <div style={{ color: '#8b7ab0', fontSize: 12, marginBottom: 12 }}>
              Override automatic intent-based routing, or leave on Auto.
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              {['auto', ...Object.keys(MODEL_ROUTES)].map(opt => (
                <label key={opt} style={S.radioRow}>
                  <input type="radio" name="model" value={opt} checked={selectedModel === opt} onChange={() => setSelectedModel(opt)} />
                  <span style={{ color: '#e8e0ff', fontSize: 12 }}>
                    {opt === 'auto' ? 'ðŸ¤– Auto (intent-based routing)' : `${MODEL_ROUTES[opt].emoji} ${opt} â†’ ${MODEL_ROUTES[opt].model}`}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div style={S.settingsSection}>
            <div style={S.sectionTitle}>EVA Architecture</div>
            <div style={S.archDiagram}>
              {[
                ['User Question', '#e8e0ff'],
                ['Ã¢â€ â€œ ML Intent Detection', '#a78bfa'],
                ['Ã¢â€ â€œ RAG Retriever', '#38bdf8'],
                ['Ã¢â€ â€œ Model Router', '#fbbf24'],
                ['Ã¢â€ â€œ Best LLM', '#34d399'],
                ['Ã¢â€ â€œ Answer + Feedback', '#f472b6'],
              ].map(([step, color], i) => (
                <div key={i} style={{ color, fontSize: 12, fontWeight: step.startsWith('â†“') ? 400 : 700, padding: '3px 0' }}>{step}</div>
              ))}
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes rag-pulse { 0%,80%,100%{opacity:0.2;transform:scale(.8)} 40%{opacity:1;transform:scale(1)} }
        .rag-dot { width:6px;height:6px;border-radius:50%;background:#8b5cf6;display:inline-block;margin:0 2px; }
        .rag-dot:nth-child(1){animation:rag-pulse 1.2s .0s infinite}
        .rag-dot:nth-child(2){animation:rag-pulse 1.2s .2s infinite}
        .rag-dot:nth-child(3){animation:rag-pulse 1.2s .4s infinite}
      `}</style>
    </div>
  );
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Small sub-components Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function StatPill({ label, value, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '4px 12px', background: 'rgba(255,255,255,.04)', borderRadius: 8, border: '1px solid rgba(255,255,255,.08)' }}>
      <div style={{ color, fontSize: 16, fontWeight: 900 }}>{value}</div>
      <div style={{ color: '#4a2d7a', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
    </div>
  );
}

function StatusBadge({ label, value }) {
  const normalized = String(value || 'unavailable').toLowerCase();
  const ready = normalized === 'ready' || normalized === 'hybrid' || normalized === 'auto' || normalized.includes('ready') || normalized.includes('selected');
  const fallback = normalized === 'fallback';
  const color = ready ? '#34d399' : fallback ? '#fbbf24' : '#f87171';
  const displayValue = String(value || 'unavailable');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '4px 10px', background: 'rgba(255,255,255,.04)', borderRadius: 8, border: `1px solid ${color}33` }}>
      <div style={{ color, fontSize: 11, fontWeight: 900, textTransform: 'capitalize' }}>{displayValue}</div>
      <div style={{ color: '#4a2d7a', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
    </div>
  );
}

function SettingRow({ label, hint, children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid rgba(255,255,255,.05)' }}>
      <div style={{ minWidth: 160 }}>
        <div style={{ color: '#e8e0ff', fontSize: 12, fontWeight: 600 }}>{label}</div>
        {hint && <div style={{ color: '#4a2d7a', fontSize: 10 }}>{hint}</div>}
      </div>
      {children}
    </div>
  );
}

// Ã¢â€â‚¬Ã¢â€â‚¬ Styles Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
const S = {
  root: { display: 'flex', flexDirection: 'column', height: '100%', background: '#060b16', color: '#e8e0ff', fontFamily: 'inherit', overflow: 'hidden' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,.07)', flexShrink: 0, flexWrap: 'wrap', gap: 10 },
  headerLeft: {},
  logo: { fontSize: 16, fontWeight: 900, background: 'linear-gradient(135deg,#7c3aed,#38bdf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' },
  logoSub: { fontSize: 10, color: '#4a2d7a', marginTop: 2 },
  headerStats: { display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' },
  tabs: { display: 'flex', borderBottom: '1px solid rgba(255,255,255,.07)', flexShrink: 0 },
  tab: { flex: 1, padding: '10px', background: 'none', border: 'none', color: '#4a2d7a', fontSize: 12, cursor: 'pointer', borderBottom: '2px solid transparent', transition: '.15s', fontWeight: 600 },
  tabActive: { color: '#c084fc', borderBottomColor: '#8b5cf6' },
  error: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, margin: '8px 16px', padding: '8px 12px', background: 'rgba(248,113,113,.1)', border: '1px solid rgba(248,113,113,.25)', borderRadius: 8, fontSize: 12, color: '#f87171', flexShrink: 0 },
  errorClose: { background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 16, padding: 0 },
  chatLayout: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  chatMessages: { flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 },
  aiBubble: { width: 28, height: 28, borderRadius: '50%', background: 'linear-gradient(135deg,#0f766e,#2563eb)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, color: '#fff', fontWeight: 700, flexShrink: 0 },
  thinkingBubble: { padding: '10px 14px', borderRadius: '4px 14px 14px 14px', background: 'rgba(255,255,255,.05)', border: '1px solid rgba(255,255,255,.08)', display: 'flex', alignItems: 'center', gap: 4 },
  dot1: { className: 'rag-dot' },
  dot2: { className: 'rag-dot' },
  dot3: { className: 'rag-dot' },
  inputArea: { flexShrink: 0, padding: '8px 12px', borderTop: '1px solid rgba(255,255,255,.07)', display: 'flex', flexDirection: 'column', gap: 6 },
  modeSelector: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  modeBtn: { padding: '5px 10px', borderRadius: 8, border: '1px solid rgba(255,255,255,.08)', background: 'rgba(255,255,255,.03)', color: '#8b7ab0', fontSize: 11, fontWeight: 700, cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 },
  modeBtnActive: { borderColor: 'rgba(56,189,248,.45)', background: 'rgba(56,189,248,.12)', color: '#7dd3fc' },
  responseMeta: { display: 'flex', gap: 6, flexWrap: 'wrap', color: '#7dd3fc', fontSize: 10, fontWeight: 700 },
  fallbackBadge: { color: '#fbbf24' },
  routerBadge: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: '#6b47a8', padding: '4px 6px', background: 'rgba(139,92,246,.06)', borderRadius: 6, border: '1px solid rgba(139,92,246,.1)' },
  inputRow: { display: 'flex', gap: 8, alignItems: 'flex-end' },
  textarea: { flex: 1, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.1)', borderRadius: 10, padding: '9px 12px', color: '#e8e0ff', fontSize: 13, outline: 'none', resize: 'none', fontFamily: 'inherit', lineHeight: 1.5 },
  inputButtons: { display: 'flex', flexDirection: 'column', gap: 4 },
  sendBtn: { width: 36, height: 36, borderRadius: 10, border: 'none', background: 'linear-gradient(135deg,#7c3aed,#a855f7)', color: '#fff', fontSize: 18, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 },
  clearBtn: { width: 36, height: 28, borderRadius: 8, border: '1px solid rgba(255,255,255,.08)', background: 'none', color: '#4a2d7a', fontSize: 14, cursor: 'pointer' },
  inputHint: { fontSize: 10, color: '#2a1f4a', textAlign: 'right' },
  docsLayout: { flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 },
  uploadSection: { background: 'rgba(255,255,255,.02)', border: '1px solid rgba(255,255,255,.07)', borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 10 },
  sectionTitle: { color: '#e8e0ff', fontSize: 13, fontWeight: 700, marginBottom: 4 },
  uploadGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 },
  uploadBtn: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: 14, background: 'rgba(139,92,246,.06)', border: '2px dashed rgba(139,92,246,.2)', borderRadius: 10, cursor: 'pointer', transition: '.15s', color: '#4a2d7a', fontSize: 12 },
  urlIngest: { display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 4px' },
  urlInput: { flex: 1, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 8, padding: '7px 10px', color: '#e8e0ff', fontSize: 12, outline: 'none' },
  ingestBtn: { padding: '7px 14px', borderRadius: 8, border: 'none', background: 'linear-gradient(135deg,#0f766e,#2563eb)', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' },
  uploadMsg: { fontSize: 12, color: '#34d399', padding: '4px 0' },
  docsList: { display: 'flex', flexDirection: 'column', gap: 6 },
  settingsLayout: { flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 },
  settingsSection: { background: 'rgba(255,255,255,.02)', border: '1px solid rgba(255,255,255,.07)', borderRadius: 10, padding: 14 },
  settingValue: { minWidth: 36, textAlign: 'right', color: '#c084fc', fontSize: 12, fontWeight: 700 },
  radioRow: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '4px 0' },
  archDiagram: { background: '#020617', borderRadius: 8, padding: '12px 16px', border: '1px solid rgba(255,255,255,.06)', lineHeight: 1.8 },
};


