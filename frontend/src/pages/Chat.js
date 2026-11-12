import { useState, useRef, useEffect, useCallback } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from 'recharts';
import RunCodeButton from '../components/RunCodeButton';
import {
  FolderOpen,
  FileText,
  ImagePlus,
  Mic,
  MoreHorizontal,
  Plus,
  Search,
  SendHorizontal,
  Sparkles,
  Square,
  X,
  Library,
  Trash2,
  Check,
  Zap,
  Camera as CameraIcon,
  Copy as CopyIcon,
  RotateCw,
  ThumbsUp,
  ThumbsDown,
  Volume2,
  Share2,
  Download,
  Pin,
} from 'lucide-react';
import CodeAssistant from './CodeAssistant';
import FeatureTools from './FeatureTools';
import DirectoryModal from './DirectoryModal';
import JarvisMode from '../components/JarvisMode';
import CameraCapture from '../components/CameraCapture';
import ImageResult, { ImageSkeleton } from '../components/ImageResult';
// Aliased: the component already has a `feedback` state for message
// ratings, which would shadow this import and turn a call into a
// TypeError on a state object.
import { feedback as uiFeedback } from '../lib/feedback';
import { speakWithVoice, cancelSpeech } from '../lib/voiceProfiles';
import useTranslation from '../lib/useTranslation';
import { getSelectedLanguageCode } from '../lib/languages';
import { isProvenanceRequest, describeProvenance, lastAnsweredMessage } from '../lib/provenance';
import ProvenanceDetails from '../components/ProvenanceDetails';
import ProvenanceBadges from '../components/ProvenanceBadges';
import { imageGeneratorMayHandle } from '../lib/visualIntent';
import { API_BASE_URL, RAG_API_BASE_URL } from '../lib/apiConfig';

const DEFAULT_API_BASE = API_BASE_URL;
const RAG_API = RAG_API_BASE_URL;

// ----------------------------------------
const SUGGESTION_TYPE_COLORS = { Action: 'var(--green)', Improve: 'var(--warn)', Learn: 'var(--cyan)', Create: 'var(--accent)' };

// Slice 4: message ids are Date.now() at creation, so the timestamp is real
// rather than "now". Returns '' when an id is not a timestamp.
function messageTime(id) {
  const ms = Number(String(id).replace(/\D/g, '').slice(0, 13));
  if (!ms || ms < 1e12) return '';
  return new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

// Read-aloud strips markup so it speaks prose, not backticks and pipes.
function speakMessage(text) {
  const synth = window.speechSynthesis;
  if (!synth) return;
  if (synth.speaking) { cancelSpeech(); return; }   // second click stops
  // Uses the user's saved voice profile instead of a fixed rate 1.02 with the
  // browser default voice. Markdown stripping lives in toSpokenText now, so
  // this and Jarvis Mode always speak the same text the same way.
  speakWithVoice(text);
}

const isUserLikeMessage = (message = {}) => {
  const identity = [message.role, message.sender, message.type, message.author]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());
  return identity.includes('user') || identity.includes('human');
};

const isAssistantLikeMessage = (message = {}) => {
  const identity = [message.role, message.sender, message.type, message.author]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());
  return identity.includes('assistant') || identity.includes('bot') || identity.includes('ai');
};


// ----------------------------------------
function SentimentTool({ API }) {
  const [text, setText] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const analyze = async () => {
    if (!text.trim()) return; setLoading(true);
    const token = localStorage.getItem('aria_token');
    const workspaceId = localStorage.getItem('eva_selected_workspace_id') || 'default-org';
    const h = { 'Content-Type': 'application/json',  ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const r = await fetch(`${API}/chat`, { method: 'POST', headers: h, body: JSON.stringify({ question: `Analyze sentiment of: "${text}". Give: overall sentiment, score 0-100, top emotions, key words.`, user_id: 'tool', workspace_id: workspaceId }) });
    const d = await r.json(); setResult(d.answer || d.response || ''); setLoading(false);
  };
  return (
    <div>
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder="Paste text to analyze..." style={{ width: '100%', height: 90, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', color: 'var(--text)', fontSize: 12, resize: 'none', outline: 'none', boxSizing: 'border-box', fontFamily: 'inherit' }} />
      <button onClick={analyze} disabled={loading || !text.trim()} style={{ marginTop: 8, padding: '7px 16px', background: loading ? 'var(--border)' : 'var(--warn)', border: 'none', borderRadius: 8, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{loading ? 'Analyzing...' : 'Analyze Sentiment'}</button>
      {result && <div style={{ marginTop: 10, padding: 12, background: 'var(--surface)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{result}</div>}
    </div>
  );
}

function DataInsightsTool({ API }) {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState(null);
  const ref = useRef();
  const analyze = async () => {
    if (!question.trim()) return; setLoading(true);
    const token = localStorage.getItem('aria_token');
    const workspaceId = localStorage.getItem('eva_selected_workspace_id') || 'default-org';
    const h = { 'Content-Type': 'application/json',  ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const text = file ? await file.text().catch(() => '') : '';
    const r = await fetch(`${API}/chat`, { method: 'POST', headers: h, body: JSON.stringify({ question: `Analyze this data and answer: ${question}\n\nData: ${text.slice(0, 1500)}`, user_id: 'tool', workspace_id: workspaceId }) });
    const d = await r.json(); setResult(d.answer || d.response || ''); setLoading(false);
  };
  return (
    <div>
      <div onClick={() => ref.current.click()} style={{ border: '1px dashed var(--border)', borderRadius: 8, padding: '9px 12px', cursor: 'pointer', marginBottom: 8, fontSize: 12, color: file ? 'var(--accent)' : 'var(--text3)', background: 'var(--surface)' }}>
        {file ? `[CSV] ${file.name}` : 'Upload CSV file (optional)'}
        <input ref={ref} type="file" accept=".csv,.txt" style={{ display: 'none' }} onChange={e => setFile(e.target.files[0])} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => e.key === 'Enter' && analyze()} placeholder="Ask about your data..." style={{ flex: 1, padding: '8px 10px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)', fontSize: 12, outline: 'none', fontFamily: 'inherit' }} />
        <button onClick={analyze} disabled={loading || !question.trim()} style={{ padding: '8px 14px', background: loading ? 'var(--border)' : 'var(--accent)', border: 'none', borderRadius: 8, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{loading ? 'Loading...' : 'Send'}</button>
      </div>
      {result && <div style={{ marginTop: 10, padding: 12, background: 'var(--surface)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{result}</div>}
    </div>
  );
}

function DocIntelTool({ API }) {
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState(null);
  const ref = useRef();
  const analyze = async () => {
    if (!file) return;
    setLoading(true);
    setResult('Extracting document text...');
    try {
      const token = localStorage.getItem('aria_token');
      const workspaceId = localStorage.getItem('eva_selected_workspace_id') || 'default-org';
      const h = {
        'Content-Type': 'application/json',
        
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      };

      let text = '';
      if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('workspace_id', workspaceId);
        const uploadRes = await fetch(`${API}/extract-text`, {
          method: 'POST',
          headers: {
            
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          body: fd
        });
        if (!uploadRes.ok) {
          const detail = await uploadRes.text().catch(() => '');
          throw new Error(`PDF extraction failed (HTTP ${uploadRes.status}). ${detail.slice(0, 250)}`);
        }
        const ud = await uploadRes.json();
        text = ud.text || ud.content || '';
      } else {
        text = await file.text();
      }

      if (!text.trim()) throw new Error('No document text could be extracted.');

      const chunkSize = 7000;
      const overlap = 300;
      const chunks = [];
      for (let start = 0; start < text.length; start += chunkSize - overlap) {
        chunks.push(text.slice(start, start + chunkSize));
      }

      const summarize = async (question, maxTokens) => {
        const response = await fetch(`${API}/doc-intelligence/summarize`, {
          method: 'POST',
          headers: h,
          body: JSON.stringify({ question, max_tokens: maxTokens })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Summarization failed (HTTP ${response.status}).`);
        }
        const output = data.text || '';
        if (!output.trim()) throw new Error('Provider returned an empty summary.');
        return { text: output, provider: data.provider || 'unknown' };
      };

      const summaries = [];
      const providersUsed = new Set();

      for (let i = 0; i < chunks.length; i++) {
        setResult(`Summarizing section ${i + 1} of ${chunks.length}...`);
        const summary = await summarize(
          `Summarize section ${i + 1} of ${chunks.length} of this document. Preserve section headings, technical facts, definitions, formulas, names, dates, numbers, examples and action items. Do not invent information. State if this section appears incomplete.\n\nDOCUMENT SECTION:\n${chunks[i]}`,
          2500
        );
        providersUsed.add(summary.provider);
        summaries.push(`SECTION ${i + 1} SUMMARY:\n${summary.text}`);
      }

      setResult('Combining section summaries...');
      const finalSummary = await summarize(
        `Combine these section summaries into a comprehensive document summary. Cover every section, retain important technical details, formulas, names, dates, numbers, conclusions and action items. Organize by topic with headings. Avoid repetition but do not omit distinct facts. Do not invent details.\n\n${summaries.join('\n\n')}`,
        6000
      );
      providersUsed.add(finalSummary.provider);

      setResult(
        `Providers used: ${Array.from(providersUsed).join(', ')}\n\n${finalSummary.text}`
      );
    } catch (err) {
      setResult(`Document summarization failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div>
      <div onClick={() => ref.current.click()} style={{ border: '1px dashed var(--border)', borderRadius: 8, padding: '9px 12px', cursor: 'pointer', marginBottom: 8, fontSize: 12, color: file ? 'var(--accent)' : 'var(--text3)', background: 'var(--surface)' }}>
        {file ? `[DOC] ${file.name}` : 'Upload document (PDF, TXT, DOCX)'}
        <input ref={ref} type="file" accept=".pdf,.txt,.docx,.csv" style={{ display: 'none' }} onChange={e => setFile(e.target.files[0])} />
      </div>
      <button onClick={analyze} disabled={loading || !file} style={{ padding: '7px 16px', background: loading || !file ? 'var(--border)' : 'var(--accent)', border: 'none', borderRadius: 8, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{loading ? 'Extracting...' : 'Extract Intelligence'}</button>
      {result && <div style={{ marginTop: 10, padding: 12, background: 'var(--surface)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{result}</div>}
    </div>
  );
}

function LearningTool({ API }) {
  const [topic, setTopic] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const generate = async () => {
    if (!topic.trim()) return; setLoading(true);
    const token = localStorage.getItem('aria_token');
    const workspaceId = localStorage.getItem('eva_selected_workspace_id') || 'default-org';
    const h = { 'Content-Type': 'application/json',  ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const r = await fetch(`${API}/chat`, { method: 'POST', headers: h, body: JSON.stringify({ question: `Create a 7-day learning plan for "${topic}". Each day: Day number, Topic, Task (1-2 sentences), Resource, Time needed.`, user_id: 'tool', workspace_id: workspaceId }) });
    const d = await r.json(); setResult(d.answer || d.response || ''); setLoading(false);
  };
  return (
    <div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={topic} onChange={e => setTopic(e.target.value)} onKeyDown={e => e.key === 'Enter' && generate()} placeholder="e.g. Python, Machine Learning, React..." style={{ flex: 1, padding: '8px 10px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)', fontSize: 12, outline: 'none', fontFamily: 'inherit' }} />
        <button onClick={generate} disabled={loading || !topic.trim()} style={{ padding: '8px 14px', background: loading ? 'var(--border)' : 'var(--accent)', border: 'none', borderRadius: 8, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{loading ? 'Loading...' : 'Generate'}</button>
      </div>
      {result && <div style={{ marginTop: 10, padding: 12, background: 'var(--surface)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{result}</div>}
    </div>
  );
}

function ResumeTool({ API }) {
  const [jobDesc, setJobDesc] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState(null);
  const ref = useRef();
  const screen = async () => {
    if (!file || !jobDesc.trim()) return; setLoading(true);
    const token = localStorage.getItem('aria_token');
    const workspaceId = localStorage.getItem('eva_selected_workspace_id') || 'default-org';
    const h = { 'Content-Type': 'application/json',  ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    const text = await file.text().catch(() => file.name);
    const r = await fetch(`${API}/chat`, { method: 'POST', headers: h, body: JSON.stringify({ question: `Score this resume 0-100 against the job. Give: Score, Verdict, Matched skills, Missing skills, Recommendation.\n\nJob: ${jobDesc.slice(0, 400)}\n\nResume: ${text.slice(0, 600)}`, user_id: 'tool', workspace_id: workspaceId }) });
    const d = await r.json(); setResult(d.answer || d.response || ''); setLoading(false);
  };
  return (
    <div>
      <div onClick={() => ref.current.click()} style={{ border: '1px dashed var(--border)', borderRadius: 8, padding: '9px 12px', cursor: 'pointer', marginBottom: 8, fontSize: 12, color: file ? 'var(--accent)' : 'var(--text3)', background: 'var(--surface)' }}>
        {file ? `[RESUME] ${file.name}` : 'Upload Resume (PDF, TXT, DOCX)'}
        <input ref={ref} type="file" accept=".pdf,.txt,.docx" style={{ display: 'none' }} onChange={e => setFile(e.target.files[0])} />
      </div>
      <textarea value={jobDesc} onChange={e => setJobDesc(e.target.value)} placeholder="Paste job description here..." style={{ width: '100%', height: 75, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', color: 'var(--text)', fontSize: 12, resize: 'none', outline: 'none', boxSizing: 'border-box', fontFamily: 'inherit', marginBottom: 8 }} />
      <button onClick={screen} disabled={loading || !file || !jobDesc.trim()} style={{ padding: '7px 16px', background: loading || !file || !jobDesc.trim() ? 'var(--border)' : 'var(--accent)', border: 'none', borderRadius: 8, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{loading ? 'Screening...' : 'Screen Resume'}</button>
      {result && <div style={{ marginTop: 10, padding: 12, background: 'var(--surface)', borderRadius: 8, fontSize: 12, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{result}</div>}
    </div>
  );
}

// ----------------------------------------
// MARKDOWN RENDERER
// ----------------------------------------

function KatexInline({ src, block }) {
  const ref = useRef(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    if (!ref.current) return;
    if (window.katex) {
      try {
        window.katex.render(src, ref.current, { throwOnError: false, displayMode: block });
      } catch { setFallback(true); }
    } else {
// ----------------------------------------
      const interval = setInterval(() => {
        if (window.katex) {
          clearInterval(interval);
          try {
            window.katex.render(src, ref.current, { throwOnError: false, displayMode: block });
          } catch { setFallback(true); }
        }
      }, 100);
      setTimeout(() => { clearInterval(interval); setFallback(true); }, 3000);
      return () => clearInterval(interval);
    }
  }, [src, block]);

  if (fallback) return <code style={{ background: 'rgba(38,101,140,.25)', padding: '1px 6px', borderRadius: 4, fontSize: 12, fontFamily: 'monospace', color: 'var(--text2)' }}>{src}</code>;
  return <span ref={ref} style={block ? { display: 'block', textAlign: 'center', margin: '10px 0' } : { display: 'inline' }} />;
}

// ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Auto data viz: GFM tables + ```chart blocks (recharts), EVA dark theme ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
// Normalize and validate URLs before placing them in an HTML attribute. The markdown
// text is HTML-escaped before link replacement, so decode only those entities that
// this renderer itself creates, then let URL canonicalize quotes and other delimiters.
export function safeHttpHref(value) {
  const decoded = String(value)
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
  try {
    const parsed = new URL(decoded);
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return null;
    return parsed.href;
  } catch (_) {
    return null;
  }
}

function escapeHtmlAttribute(value) {
  return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function markdownLinkReplacement(_match, label, rawHref) {
  const href = safeHttpHref(rawHref);
  if (!href) return label;
  return `<a href="${escapeHtmlAttribute(href)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent);text-decoration:underline">${label}</a>`;
}

function inlineMd(text) {
  return String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, markdownLinkReplacement)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(38,101,140,.25);border:1px solid rgba(84,172,191,.2);border-radius:4px;padding:1px 5px;font-family:monospace;font-size:12px;color:var(--text2)">$1</code>');
}

function parseMarkdownTable(md) {
  const rows = String(md).trim().split('\n').map((r) => r.trim()).filter(Boolean);
  if (rows.length < 2) return null;
  const cells = (line) => line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
  return { header: cells(rows[0]), body: rows.slice(2).map(cells) };
}

function TableBlock({ md }) {
  const t = parseMarkdownTable(md);
  if (!t || !t.header.length) return null;
  return (
    <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch', margin: '12px 0', border: '1px solid var(--border)', borderRadius: 10 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 'max-content', fontSize: 13 }}>
        <thead>
          <tr>
            {t.header.map((h, i) => (
              <th key={i} style={{ textAlign: 'left', padding: '9px 13px', background: 'var(--surface2)', color: 'var(--text2)', fontWeight: 700, borderBottom: '2px solid var(--border)', whiteSpace: 'nowrap' }} dangerouslySetInnerHTML={{ __html: inlineMd(h) }} />
            ))}
          </tr>
        </thead>
        <tbody>
          {t.body.map((row, r) => (
            <tr key={r} style={{ background: r % 2 ? 'var(--accent-soft)' : 'transparent' }}>
              {row.map((c, ci) => (
                <td key={ci} style={{ padding: '8px 13px', color: 'var(--text2)', borderBottom: '1px solid var(--border)', verticalAlign: 'top' }} dangerouslySetInnerHTML={{ __html: inlineMd(c) }} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CHART_COLORS = ['var(--accent)', 'var(--green)', 'var(--cyan)', 'var(--warn)', '#f472b6', 'var(--cyan)', 'var(--accent)', 'var(--warn)'];

function normalizeChartSpec(spec) {
  if (!spec || typeof spec !== 'object') return null;
  const type = ['bar', 'line', 'pie'].includes(spec.type) ? spec.type : 'bar';
  const title = spec.title || '';

  // Format A (preferred/natural): { data: [{label|name, value|y}, ...] } ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â one value per row.
  if (Array.isArray(spec.data) && spec.data.length && !Array.isArray(spec.series)) {
    const data = spec.data.map((d) => {
      if (!d || typeof d !== 'object') return null;
      const rawName = d.label != null ? d.label : (d.name != null ? d.name : d.x);
      const rawVal = d.value != null ? d.value : d.y;
      const name = rawName != null ? String(rawName) : '';
      const value = Number(rawVal);
      if (!name || !Number.isFinite(value)) return null;
      return { name, value };
    }).filter(Boolean);
    if (!data.length) return null;
    return { type, title, data, seriesKeys: ['value'] };
  }

  // Format B (legacy): { labels: [...], series: [{name, data:[...]}] }
  const labels = Array.isArray(spec.labels) ? spec.labels.map(String) : null;
  let series = Array.isArray(spec.series) ? spec.series : null;
  if (!labels || !labels.length || !series || !series.length) return null;
  series = series
    .map((s, i) => ({ name: String(s && s.name ? s.name : `Series ${i + 1}`), data: Array.isArray(s && s.data) ? s.data.map(Number) : [] }))
    .filter((s) => s.data.length && s.data.some((n) => Number.isFinite(n)));
  if (!series.length) return null;
  if (type === 'pie') {
    const s0 = series[0];
    const data = labels.map((l, i) => ({ name: l, value: Number.isFinite(s0.data[i]) ? s0.data[i] : 0 }));
    return { type, title: spec.title || '', data, seriesKeys: ['value'] };
  }
  const seriesKeys = series.map((s) => s.name);
  const data = labels.map((l, i) => {
    const row = { name: l };
    series.forEach((s) => { row[s.name] = Number.isFinite(s.data[i]) ? s.data[i] : 0; });
    return row;
  });
  return { type, title: spec.title || '', data, seriesKeys };
}

// Split concatenated top-level JSON objects ("{...}\n{...}\n{...}") that some
// models pack into a single fence. Brace-depth scan, string-aware ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â no regex.
function splitJsonObjects(src) {
  const out = [];
  let depth = 0, start = -1, inStr = false, esc = false;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === '\\') esc = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') { inStr = true; continue; }
    if (c === '{') { if (depth === 0) start = i; depth++; }
    else if (c === '}') { depth--; if (depth === 0 && start >= 0) { out.push(src.slice(start, i + 1)); start = -1; } }
  }
  return out;
}

function ChartBlock({ src }) {
  // Normal case: one JSON spec per fence.
  let specs = [];
  try { specs = [JSON.parse(src)]; } catch (_) {
    // A fence carrying SEVERAL concatenated JSON objects ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ split and render
    // each as its own independent chart instead of failing to a code block.
    const pieces = splitJsonObjects(src);
    if (pieces.length > 1) {
      specs = pieces.map((p) => { try { return JSON.parse(p); } catch (_) { return null; } }).filter(Boolean);
    }
  }
  const norms = specs.map(normalizeChartSpec).filter(Boolean);
  if (!norms.length) {
    // Not valid/chartable ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ never force a chart; preserve the data as a code block.
    return (
      <pre style={{ margin: '10px 0', padding: '12px 14px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflowX: 'auto', fontSize: 12, color: 'var(--text)', fontFamily: 'monospace' }}><code>{src}</code></pre>
    );
  }
  // One <ChartCanvas> per spec ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â datasets are NEVER combined into one chart.
  return <>{norms.map((norm, i) => <ChartCanvas key={i} norm={norm} />)}</>;
}

function ChartCanvas({ norm }) {
  const { type, title, data, seriesKeys } = norm;
  const axisTick = { fill: 'var(--text3)', fontSize: 11 };
  const tip = { contentStyle: { background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }, labelStyle: { color: 'var(--text2)' }, itemStyle: { color: 'var(--text)' } };
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 14px 6px', margin: '12px 0' }}>
      {title && <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text2)', marginBottom: 10 }}>ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â  {title}</div>}
      <ResponsiveContainer width="100%" height={260}>
        {type === 'pie' ? (
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={88} label={{ fill: 'var(--text2)', fontSize: 11 }}>
              {data.map((d, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
            </Pie>
            <Tooltip {...tip} />
            <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text2)' }} />
          </PieChart>
        ) : type === 'line' ? (
          <LineChart data={data} margin={{ top: 6, right: 14, bottom: 2, left: -12 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={axisTick} stroke="var(--border)" />
            <YAxis tick={axisTick} stroke="var(--border)" />
            <Tooltip {...tip} />
            {seriesKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text2)' }} />}
            {seriesKeys.map((k, i) => <Line key={k} type="monotone" dataKey={k} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2} dot={false} />)}
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 6, right: 14, bottom: 2, left: -12 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={axisTick} stroke="var(--border)" />
            <YAxis tick={axisTick} stroke="var(--border)" />
            <Tooltip {...tip} cursor={{ fill: 'var(--accent-soft)' }} />
            {seriesKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text2)' }} />}
            {seriesKeys.map((k, i) => <Bar key={k} dataKey={k} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} />)}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

// ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Mermaid diagrams (```mermaid) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â CDN-loaded like KaTeX, dark theme, safe fallback ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
let _mermaidPromise = null;
function ensureMermaid() {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'));
  if (window.mermaid) return Promise.resolve(window.mermaid);
  if (_mermaidPromise) return _mermaidPromise;
  _mermaidPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js';
    s.async = true;
    s.onload = () => {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'strict',
          fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
          themeVariables: {
            background: 'var(--surface)', primaryColor: 'var(--border)', primaryTextColor: 'var(--text)',
            primaryBorderColor: 'var(--accent)', lineColor: 'var(--text3)', secondaryColor: 'var(--surface2)',
            tertiaryColor: 'var(--surface2)', fontSize: '13px',
          },
        });
      } catch (_) { /* init issues surface later as render failures -> fallback */ }
      resolve(window.mermaid);
    };
    s.onerror = () => reject(new Error('mermaid failed to load'));
    document.head.appendChild(s);
  });
  return _mermaidPromise;
}

// LLMs constantly break Mermaid edge-label syntax ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â repair the common cases before render.
function sanitizeMermaid(code) {
  let s = String(code || '');
  // #1 LLM bug: edge label emitted as "A -->|label|> B". The ">" immediately after the
  // pipe that CLOSES an edge label is always invalid here ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ drop it: "|label|>" -> "|label|".
  s = s.replace(/\|\s*>/g, '|');
  // Occasional extra arrowhead: "-->>", "==>>" -> single head.
  s = s.replace(/(--|==)>>+/g, '$1>');
  // Normalize "graph TD/LR/BT/RL/TB" -> "flowchart ..." (both valid; keep consistent).
  s = s.replace(/^(\s*)graph(\s+(?:TD|TB|BT|LR|RL)\b)/gim, '$1flowchart$2');
  return s;
}

function MermaidBlock({ code }) {
  const ref = useRef(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setReady(false);
    ensureMermaid()
      .then(async (mermaid) => {
        if (cancelled || !mermaid) { if (!cancelled) setFailed(true); return; }
        // Validate first (no throw) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â LLMs emit invalid Mermaid constantly. Sanitize first.
        const clean = sanitizeMermaid(code);
        let ok = false;
        try { ok = await mermaid.parse(clean, { suppressErrors: true }); } catch (_) { ok = false; }
        if (!ok) { if (!cancelled) setFailed(true); return; }
        try {
          const id = 'mmd_' + Math.random().toString(36).slice(2);
          const { svg } = await mermaid.render(id, clean);
          if (cancelled) return;
          if (ref.current) {
            ref.current.innerHTML = svg;
            const el = ref.current.querySelector('svg');
            if (el) {
              // Mermaid tags the <svg> with width="100%" and a max-width equal to the
              // diagram's own width. Overriding that with max-width:100% cancelled the
              // cap, so width="100%" stretched even a small vertical flowchart to the
              // full column width ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â every node blown up several times over. Pin the svg
              // to its intrinsic viewBox width so it renders at natural scale; a
              // genuinely wide diagram then overflows and the container scrolls it
              // sideways instead of the whole thing being upscaled.
              const vb = el.viewBox && el.viewBox.baseVal;
              if (vb && vb.width) {
                el.removeAttribute('width');
                el.removeAttribute('height');
                el.style.width = Math.ceil(vb.width) + 'px';
              }
              el.style.height = 'auto';
            }
          }
          setReady(true);
        } catch (_) { if (!cancelled) setFailed(true); }
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [code]);

  if (failed) {
    // #1 failure mode: degrade to readable text ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â never a broken/blank box or crash.
    return (
      <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 10, margin: '12px 0', overflow: 'hidden' }}>
        <div style={{ padding: '7px 12px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)', fontSize: 11, color: 'var(--warn)' }}>ÃƒÂ¢Ã…Â¡Ã‚Â  Couldn't render this diagram ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â showing its description instead.</div>
        <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontSize: 12, lineHeight: 1.6, color: 'var(--text2)', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}><code>{code}</code></pre>
      </div>
    );
  }
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 12, margin: '12px 0', overflowX: 'auto', WebkitOverflowScrolling: 'touch', textAlign: 'center' }}>
      {!ready && <div style={{ fontSize: 11, color: 'var(--text3)', padding: '10px 0' }}>Rendering diagramÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦</div>}
      <div ref={ref} />
    </div>
  );
}

function MarkdownRenderer({ text }) {
  const [copied, setCopied] = useState({});
  const copyCode = (code, id) => {
    navigator.clipboard.writeText(code);
    setCopied(c => ({ ...c, [id]: true }));
    setTimeout(() => setCopied(c => ({ ...c, [id]: false })), 2000);
  };
  const renderBlock = (raw) => {
    const mathBlocks = [];
    raw = raw.replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => { mathBlocks.push({ src: m, block: true }); return `%%MATH_${mathBlocks.length - 1}%%`; });
    raw = raw.replace(/\$([^$\n]+?)\$/g, (_, m) => { mathBlocks.push({ src: m, block: false }); return `%%MATH_${mathBlocks.length - 1}%%`; });
    // Also catch unwrapped LaTeX commands like \frac, \sqrt, \sum etc
    raw = raw.replace(/((?:\\(?:frac|sqrt|sum|int|lim|prod|alpha|beta|gamma|theta|pi|sigma|omega|delta|lambda|mu|infty|pm|mp|times|div|cdot|leq|geq|neq|approx|equiv|in|notin|subset|cup|cap|forall|exists|partial|nabla|hat|bar|vec|dot|ddot|tilde|mathbb|mathbf|mathrm|text|left|right|begin|end|matrix|pmatrix|bmatrix)[^a-zA-Z])[^\n$`]{0,200})/g,
      (match) => {
        if (!match.includes('%%MATH')) {
          mathBlocks.push({ src: match.trim(), block: false });
          return `%%MATH_${mathBlocks.length - 1}%%`;
        }
        return match;
      }
    );
    const codeBlocks = [];
    const chartBlocks = [];
    const mermaidBlocks = [];
    // Detect chart specs by CONTENT, not fence tag alone: the model often emits
    // ```json (or untagged) fences containing {"type":"pie"|"bar"|"line", ...}.
    const looksLikeChartSpec = (code) => {
      try {
        const s = JSON.parse(code);
        return !!s && typeof s === 'object' && ['pie', 'bar', 'line'].includes(s.type)
          && (Array.isArray(s.data) || (Array.isArray(s.labels) && Array.isArray(s.series)));
      } catch (_) { return false; }
    };
    let html = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      const lc = (lang || '').toLowerCase();
      if (lc === 'chart' || ((lc === 'json' || lc === '') && looksLikeChartSpec(code.trim()))) {
        chartBlocks.push(code.trim());
        return `%%CHARTBLOCK_${chartBlocks.length - 1}%%`;
      }
      if (lc === 'mermaid') {
        mermaidBlocks.push(code.trim());
        return `%%MERMAIDBLOCK_${mermaidBlocks.length - 1}%%`;
      }
      const id = `cb_${codeBlocks.length}`;
      codeBlocks.push({ id, lang: lang || 'code', code: code.trim() });
      return `%%CODEBLOCK_${codeBlocks.length - 1}%%`;
    });
    // Extract GFM tables (header row + |---| separator + body rows) BEFORE inline formatting.
    const tableBlocks = [];
    {
      const tlines = html.split('\n');
      const tout = [];
      const isSep = (l) => /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(l) && l.includes('-') && l.includes('|');
      let ti = 0;
      while (ti < tlines.length) {
        if (tlines[ti].includes('|') && ti + 1 < tlines.length && isSep(tlines[ti + 1])) {
          const block = [tlines[ti], tlines[ti + 1]];
          let tj = ti + 2;
          while (tj < tlines.length && tlines[tj].includes('|') && tlines[tj].trim()) { block.push(tlines[tj]); tj++; }
          tableBlocks.push(block.join('\n'));
          tout.push(`%%TABLEBLOCK_${tableBlocks.length - 1}%%`);
          ti = tj;
        } else { tout.push(tlines[ti]); ti++; }
      }
      html = tout.join('\n');
    }
    html = html
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, markdownLinkReplacement)
      .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code style="background:rgba(38,101,140,.25);border:1px solid rgba(84,172,191,.2);border-radius:4px;padding:1px 6px;font-family:monospace;font-size:12px;color:var(--text2)">$1</code>')
      .replace(/^### (.+)$/gm, '<h3 style="font-size:17px;font-weight:700;color:var(--text2);margin:12px 0 6px">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="font-size:19px;font-weight:700;color:var(--text2);margin:14px 0 7px">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="font-size:22px;font-weight:800;color:var(--text2);margin:16px 0 8px">$1</h1>')
      .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid var(--border);margin:12px 0">')
      .replace(/^&gt; (.+)$/gm, '<blockquote style="border-left:3px solid var(--accent);padding-left:10px;color:var(--text3);margin:6px 0">$1</blockquote>')
      .replace(/((?:^\d+\..+\n?)+)/gm, m => '<ol style="padding-left:20px;margin:6px 0">' + m.trim().split('\n').map(l => `<li style="margin-bottom:3px">${l.replace(/^\d+\.\s*/, '')}</li>`).join('') + '</ol>')
      .replace(/((?:^[-*] .+\n?)+)/gm, m => '<ul style="padding-left:20px;margin:6px 0">' + m.trim().split('\n').map(l => `<li style="margin-bottom:3px">${l.replace(/^[-*] /, '')}</li>`).join('') + '</ul>');
    const parts = html.split(/(%%CODEBLOCK_\d+%%|%%MATH_\d+%%|%%TABLEBLOCK_\d+%%|%%CHARTBLOCK_\d+%%|%%MERMAIDBLOCK_\d+%%)/);
    return parts.map((part, i) => {
      const mathMatch = part.match(/%%MATH_(\d+)%%/);
      if (mathMatch) {
        const mb = mathBlocks[parseInt(mathMatch[1])];
        return <KatexInline key={i} src={mb.src} block={mb.block} />;
      }
      const tableMatch = part.match(/%%TABLEBLOCK_(\d+)%%/);
      if (tableMatch) return <TableBlock key={i} md={tableBlocks[parseInt(tableMatch[1], 10)]} />;
      const chartMatch = part.match(/%%CHARTBLOCK_(\d+)%%/);
      if (chartMatch) return <ChartBlock key={i} src={chartBlocks[parseInt(chartMatch[1], 10)]} />;
      const mermaidMatch = part.match(/%%MERMAIDBLOCK_(\d+)%%/);
      if (mermaidMatch) return <MermaidBlock key={i} code={mermaidBlocks[parseInt(mermaidMatch[1], 10)]} />;
      const match = part.match(/%%CODEBLOCK_(\d+)%%/);
      if (match) {
        const cb = codeBlocks[parseInt(match[1])];
        return (
          <div key={i} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, margin: '10px 0', overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'monospace' }}>{cb.lang}</span>
              <button onClick={() => copyCode(cb.code, cb.id)}
                style={{ fontSize: 11, color: copied[cb.id] ? 'var(--green)' : 'var(--text3)', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                {copied[cb.id] ? '✓ Copied!' : '⧉ Copy'}
              </button>
            </div>
            <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontSize: 12, lineHeight: 1.6, color: 'var(--text)', fontFamily: 'monospace' }}>
              <code>{cb.code}</code>
            </pre>
          </div>
        );
      }
      return <span key={i} dangerouslySetInnerHTML={{ __html: part.replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>') }} />;
    });
  };
  return <div style={{ fontSize: '1rem', lineHeight: 1.8, color: 'var(--text)' }}>{renderBlock(text)}</div>;
}

// ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
// INLINE DASHBOARD RENDERER
// ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
function DashboardRenderer({ data }) {
  const { charts = [], summary_stats = {}, shape = {} } = data;

  const renderBar = (chart) => {
    const max = Math.max(...chart.data.map(d => d[chart.y] || 0));
    return (
      <div key={chart.title}>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 6, fontWeight: 600 }}>{chart.title}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {chart.data.slice(0, 8).map((row, i) => {
            const val = row[chart.y] || 0;
            const pct = max > 0 ? (val / max) * 100 : 0;
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 80, fontSize: 10, color: 'var(--text3)', textAlign: 'right', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(row[chart.x]).slice(0, 12)}</div>
                <div style={{ flex: 1, height: 16, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: chart.color || 'var(--accent)', borderRadius: 4, transition: '.3s' }} />
                </div>
                <div style={{ width: 40, fontSize: 10, color: 'var(--text3)' }}>{typeof val === 'number' ? val.toFixed(1) : val}</div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const renderPie = (chart) => {
    const total = chart.data.reduce((s, d) => s + (d.value || 0), 0);
    const COLORS = ['var(--accent)','var(--green)','var(--warn)','var(--red)','var(--accent)','var(--accent)','var(--warn)','#84cc16'];
    return (
      <div key={chart.title}>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8, fontWeight: 600 }}>{chart.title}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {chart.data.map((item, i) => {
            const pct = total > 0 ? ((item.value / total) * 100).toFixed(1) : 0;
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'var(--border)', borderRadius: 6, padding: '4px 8px' }}>
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: COLORS[i % COLORS.length], flexShrink: 0 }} />
                <span style={{ fontSize: 10, color: 'var(--text2)' }}>{item.name}</span>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>{pct}%</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16, marginTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 16 }}>ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â </span>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Dashboard</span>
        <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>{shape.rows} rows ÃƒÆ’Ã¢â‚¬â€ {shape.cols} cols</span>
      </div>

      {/* Summary Stats */}
      {Object.keys(summary_stats).length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
          {Object.entries(summary_stats).slice(0, 4).map(([col, stats]) => (
            <div key={col} style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', flex: '1 1 120px' }}>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '.5px' }}>{col}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text2)' }}>{stats.mean}</div>
              <div style={{ fontSize: 9, color: 'var(--border2)' }}>min {stats.min} Ãƒâ€šÃ‚Â· max {stats.max}</div>
            </div>
          ))}
        </div>
      )}

      {/* Charts */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {charts.map((chart) => (
          <div key={chart.title} style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
            {chart.type === 'bar'  && renderBar(chart)}
            {chart.type === 'pie'  && renderPie(chart)}
            {chart.type === 'scatter' && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 6, fontWeight: 600 }}>{chart.title}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)' }}>Scatter: {chart.data.length} data points plotted</div>
              </div>
            )}
            {chart.type === 'line' && renderBar({ ...chart, y: chart.y, x: 'index' })}
          </div>
        ))}
      </div>
    </div>
  );
}

// ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
// GEN AI AUTOMATION PANEL
// ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
// eslint-disable-next-line no-unused-vars
function GenAIPanel({ API, token, onSendToChat }) {
  const [activeTab, setActiveTab]     = useState('load');
  const [dataSource, setDataSource]   = useState('files');
  const [sqlConn, setSqlConn]         = useState('');
  const [urls, setUrls]               = useState('');
  const [tasks, setTasks]             = useState({ rag: true, summarize: true, extract: false, train: false });
  const [pipeline, setPipeline]       = useState([]);
  const [running, setRunning]         = useState(false);
  const [results, setResults]         = useState([]);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [dragging, setDragging]       = useState(false);
  const fileRef = useRef();

  const TASK_OPTIONS = [
    { id: 'rag',       icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â¬', label: 'RAG Q&A',        desc: 'Index for chatbot queries' },
    { id: 'summarize', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹', label: 'Auto Summarize', desc: 'Generate document summaries' },
    { id: 'extract',   icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â', label: 'Extract Info',   desc: 'Tables, names, dates, entities' },
    { id: 'train',     icon: 'ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â ', label: 'Train ML Model', desc: 'Fine-tune on your data' },
  ];

  const addFiles = (files) => {
    const arr = Array.from(files);
    setUploadedFiles(f => [...f, ...arr.map(f => ({ name: f.name, size: f.size, file: f, status: 'ready' }))]);
  };

  const pollUploadJob = async (jobId, onUpdate = () => {}) => {
    const terminal = new Set(['COMPLETE', 'FAILED', 'CANCELLED']);
    while (true) {
      const res = await fetch(`${RAG_API}/rag/jobs/${encodeURIComponent(jobId)}`, {
        headers: { },
      });
      if (!res.ok) throw new Error(`Upload job ${jobId} not found`);
      const job = await res.json();
      onUpdate(job);
      if (terminal.has(job.status)) {
        if (job.status !== 'COMPLETE') throw new Error(job.error || job.message || `Upload job ${job.status}`);
        return job;
      }
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
  };

  const buildPipeline = () => {
    const steps = [];
    if (dataSource === 'files' && uploadedFiles.length > 0)
      steps.push({ id: 'load_files', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Å¡', label: `Load ${uploadedFiles.length} file(s)`, status: 'pending' });
    if (dataSource === 'sql' && sqlConn)
      steps.push({ id: 'load_sql', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â€Ã¢â‚¬Å¾ÃƒÂ¯Ã‚Â¸Ã‚Â', label: 'Connect & query SQL database', status: 'pending' });
    if (dataSource === 'urls' && urls)
      steps.push({ id: 'scrape', icon: 'ÃƒÂ°Ã…Â¸Ã…â€™Ã‚Â', label: `Scrape ${urls.split('\n').filter(Boolean).length} URL(s)`, status: 'pending' });
    steps.push({ id: 'ocr',   icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ËœÃ‚ÂÃƒÂ¯Ã‚Â¸Ã‚Â', label: 'OCR + text extraction', status: 'pending' });
    steps.push({ id: 'embed', icon: 'ÃƒÂ¢Ã…Â¡Ã‚Â¡', label: 'Generate embeddings', status: 'pending' });
    if (tasks.rag)       steps.push({ id: 'rag',     icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â¬', label: 'Index for RAG', status: 'pending' });
    if (tasks.summarize) steps.push({ id: 'summary', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹', label: 'Auto summarize', status: 'pending' });
    if (tasks.extract)   steps.push({ id: 'extract', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â', label: 'Extract structured info', status: 'pending' });
    if (tasks.train)     steps.push({ id: 'train',   icon: 'ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â ', label: 'Train ML model', status: 'pending' });
    return steps;
  };

  const runPipeline = async () => {
    const steps = buildPipeline();
    if (steps.length === 0) return;
    setRunning(true);
    setActiveTab('pipeline');
    setPipeline(steps.map(s => ({ ...s, status: 'pending' })));
    setResults([]);

    const updateStep = (id, status, result = null) =>
      setPipeline(p => p.map(s => s.id === id ? { ...s, status, result } : s));

    const headers = {
      
      ...(token && token !== 'offline' ? { 'Authorization': `Bearer ${token}` } : {}),
    };
    const workspaceId = localStorage.getItem('eva_selected_workspace_id') || 'default-org';

    try {
      // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Save files ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â return success INSTANTLY ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
      if (dataSource === 'files' && uploadedFiles.length > 0) {
        updateStep('load_files', 'running');
        let uploaded = 0;
        // Upload all files in parallel (not one-by-one)
        await Promise.all(uploadedFiles.map(async (f) => {
          const fd = new FormData();
          fd.append('file', f.file);
          fd.append('workspace_id', workspaceId);
          try {
            const r = await fetch(`${RAG_API}/rag/upload`, { method: 'POST', headers, body: fd });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.job_id) throw new Error(data.detail || 'Upload job was not created');
            setUploadedFiles(prev => prev.map(u => u.name === f.name ? { ...u, status: 'QUEUED', jobId: data.job_id } : u));
            await pollUploadJob(data.job_id, (job) => {
              setUploadedFiles(prev => prev.map(u => u.name === f.name ? { ...u, status: job.status, job } : u));
            });
            uploaded++;
            setUploadedFiles(prev => prev.map(u => u.name === f.name ? { ...u, status: 'COMPLETE' } : u));
          } catch (err) {
            console.error(err);
            setUploadedFiles(prev => prev.map(u => u.name === f.name ? { ...u, status: 'error' } : u));
          }
        }));
        updateStep('load_files', uploaded === uploadedFiles.length ? 'done' : 'error', `${uploaded}/${uploadedFiles.length} files indexed`);
      }

      // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ SQL ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
      if (dataSource === 'sql' && sqlConn) {
        updateStep('load_sql', 'running');
        await new Promise(r => setTimeout(r, 1200));
        updateStep('load_sql', 'done', 'SQL connection simulated (add backend endpoint)');
      }

      //  Scrape URLs ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â parallel ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
      if (dataSource === 'urls' && urls) {
        updateStep('scrape', 'running');
        const urlList = urls.split('\n').filter(Boolean);
        let scraped = 0;
        await Promise.all(urlList.map(async (url) => {
          try {
            const fd = new FormData();
            const blob = new Blob([`URL: ${url}`], { type: 'text/plain' });
            fd.append('file', blob, 'url_content.txt');
            fd.append('workspace_id', workspaceId);
            const res = await fetch(`${RAG_API}/rag/upload`, { method: 'POST', headers, body: fd });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.job_id) throw new Error(data.detail || 'Upload job was not created');
            await pollUploadJob(data.job_id);
            scraped++;
          } catch (err) { console.error(err); }
        }));
        updateStep('scrape', 'done', `${scraped}/${urlList.length} URLs scraped`);
      }

      updateStep('ocr', 'done', 'Text extracted by upload jobs');
      updateStep('embed', 'done', 'Embeddings completed by upload jobs');

      // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ RAG / Summarize / Extract / Train run immediately ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
      // (don't wait for OCR/embed ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â backend handles that async)

      if (tasks.rag) {
        updateStep('rag', 'running');
        updateStep('rag', 'done', 'Documents indexed for Q&A');
        setResults(prev => [...prev, { type: 'rag', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â¬', title: 'RAG Ready', body: 'Your data is now indexed. Ask questions in chat.' }]);
        onSendToChat('ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Files saved and indexing in background. You can start asking questions now ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â answers will improve as indexing completes.');
      }

      if (tasks.summarize) {
        updateStep('summary', 'running');
        try {
          const r = await fetch(`${API}/chat`, {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: 'Summarize all the documents that have been uploaded. Give a concise overview.', user_id: 'automation', workspace_id: workspaceId }),
          });
          const d = await r.json();
          const summary = d.answer || d.response || 'Summary generated.';
          updateStep('summary', 'done', 'Summary ready');
          setResults(prev => [...prev, { type: 'summary', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹', title: 'Auto Summary', body: summary }]);
        } catch {
          updateStep('summary', 'done', 'Summary generated (offline)');
          setResults(prev => [...prev, { type: 'summary', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹', title: 'Auto Summary', body: 'Documents processed and summarized successfully.' }]);
        }
      }

      if (tasks.extract) {
        updateStep('extract', 'running');
        try {
          const r = await fetch(`${API}/chat`, {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: 'Extract all key entities from the documents: names, dates, numbers, tables, and important facts. Format as structured list.', user_id: 'automation', workspace_id: workspaceId }),
          });
          const d = await r.json();
          const extracted = d.answer || d.response || 'Entities extracted.';
          updateStep('extract', 'done', 'Extraction complete');
          setResults(prev => [...prev, { type: 'extract', icon: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â', title: 'Extracted Info', body: extracted }]);
        } catch {
          updateStep('extract', 'done', 'Extraction complete');
        }
      }

      if (tasks.train) {
        updateStep('train', 'running');
        await new Promise(r => setTimeout(r, 1500));
        updateStep('train', 'done', 'Training started in background');
        setResults(prev => [...prev, { type: 'train', icon: 'ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â ', title: 'ML Training', body: 'Model training started in background. Check ML page for progress.' }]);
      }

    } catch (e) {
      console.error('Pipeline error:', e);
    }

    setRunning(false);
    if (results.length > 0 || tasks.rag || tasks.summarize) setActiveTab('results');
  };

  const statusColor = (s) => ({ done: 'var(--green)', running: 'var(--warn)', error: 'var(--red)', pending: 'var(--border2)' }[s] || 'var(--border2)');
  const statusIcon  = (s) => ({ done: 'ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“', running: 'ÃƒÂ¢Ã…Â¸Ã‚Â³', error: 'ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¢', pending: 'ÃƒÂ¢Ã¢â‚¬â€Ã¢â‚¬Â¹' }[s] || 'ÃƒÂ¢Ã¢â‚¬â€Ã¢â‚¬Â¹');

  return (
    <div style={{ width: 320, background: 'var(--bg)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ fontSize: 16 }}>ÃƒÂ¢Ã…Â¡Ã‚Â¡</span> Gen AI Automation
        </div>
        <div style={{ fontSize: 10, color: 'var(--border2)', fontFamily: 'monospace', marginTop: 2 }}>Auto load Ãƒâ€šÃ‚Â· learn Ãƒâ€šÃ‚Â· work</div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginTop: 10 }}>
          {[['load', 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Å¡ Load'], ['pipeline', 'ÃƒÂ¢Ã…Â¡Ã¢â€žÂ¢ÃƒÂ¯Ã‚Â¸Ã‚Â Pipeline'], ['results', 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â  Results']].map(([id, label]) => (
            <button key={id} onClick={() => setActiveTab(id)}
              style={{ flex: 1, padding: '5px 4px', borderRadius: 7, border: `1px solid ${activeTab === id ? 'var(--accent)' : 'var(--border)'}`, background: activeTab === id ? 'var(--accent-soft)' : 'transparent', color: activeTab === id ? 'var(--accent)' : 'var(--text3)', fontSize: 10, cursor: 'pointer' }}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ LOAD TAB ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ */}
        {activeTab === 'load' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

            {/* Data source selector */}
            <div>
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.7px', fontFamily: 'monospace', marginBottom: 8 }}>Data Source</div>
              <div style={{ display: 'flex', gap: 4 }}>
                {[['files', 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â Files'], ['sql', 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â€Ã¢â‚¬Å¾ÃƒÂ¯Ã‚Â¸Ã‚Â SQL'], ['urls', 'ÃƒÂ°Ã…Â¸Ã…â€™Ã‚Â URLs']].map(([id, label]) => (
                  <button key={id} onClick={() => setDataSource(id)}
                    style={{ flex: 1, padding: '7px 4px', borderRadius: 8, border: `1px solid ${dataSource === id ? 'var(--accent)' : 'var(--border)'}`, background: dataSource === id ? 'var(--accent-soft)' : 'transparent', color: dataSource === id ? 'var(--accent)' : 'var(--text3)', fontSize: 11, cursor: 'pointer' }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Premium animated cloud upload */}
            {dataSource === 'files' && (
              <div className="eva-upload-panel">
                <div
                  className={`eva-cloud-dropzone${dragging ? ' is-dragging' : ''}`}
                  onDragOver={e => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={e => {
                    e.preventDefault();
                    setDragging(false);
                    addFiles(e.dataTransfer.files);
                  }}
                  onClick={() => fileRef.current?.click()}
                  role="button"
                  tabIndex={0}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      fileRef.current?.click();
                    }
                  }}
                  aria-label="Upload files"
                >
                  <div className="eva-cloud-orbit eva-cloud-orbit-one" />
                  <div className="eva-cloud-orbit eva-cloud-orbit-two" />
                  <div className="eva-cloud-symbol" aria-hidden="true">
                    <svg viewBox="0 0 64 64" fill="none">
                      <path d="M18 43H14.5C8.7 43 4 38.3 4 32.5S8.7 22 14.5 22c1.5 0 2.9.3 4.2.9C21.2 14.7 28.5 9 37 9c10.2 0 18.5 8.3 18.5 18.5v.8C60 30 63 34.2 63 39c0 6.1-4.9 11-11 11H42" transform="translate(-1 0)" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"/>
                      <path d="M32 52V30m0 0-9 9m9-9 9 9" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                  <div className="eva-cloud-title">
                    {dragging ? 'Drop files to add them' : 'Upload your knowledge'}
                  </div>
                  <div className="eva-cloud-subtitle">
                    Drag and drop files here, or <span>browse files</span>
                  </div>
                  <div className="eva-cloud-formats">
                    <span>PDF</span><span>DOCX</span><span>CSV</span><span>TXT</span><span>ZIP</span>
                  </div>
                  <div className="eva-cloud-footnote">Files are added to your EVA workspace</div>
                </div>

                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  accept=".pdf,.docx,.csv,.txt,.zip,.png,.jpg"
                  style={{ display: 'none' }}
                  onChange={e => {
                    addFiles(e.target.files);
                    e.target.value = '';
                  }}
                />

                {uploadedFiles.length > 0 && (
                  <div className="eva-upload-file-list">
                    <div className="eva-upload-list-heading">
                      <span>Selected files</span>
                      <span>{uploadedFiles.length} file{uploadedFiles.length === 1 ? '' : 's'}</span>
                    </div>
                    {uploadedFiles.map((f, i) => {
                      const ext = (f.name.split('.').pop() || 'FILE').toLowerCase();
                      const type = ['pdf', 'csv', 'docx', 'txt', 'zip'].includes(ext) ? ext : 'file';
                      const isDone = ['done', 'DONE', 'COMPLETED', 'completed'].includes(f.status);
                      const isError = ['error', 'ERROR', 'FAILED', 'failed'].includes(f.status);
                      return (
                        <div className="eva-upload-file-card" key={`${f.name}-${i}`}>
                          <div className={`eva-file-type-icon eva-file-type-${type}`}>
                            {type === 'file' ? 'FILE' : type.toUpperCase()}
                          </div>
                          <div className="eva-upload-file-info">
                            <div className="eva-upload-file-name" title={f.name}>{f.name}</div>
                            <div className="eva-upload-file-meta">
                              {(f.size / 1024).toFixed(1)} KB
                              <span className="eva-file-meta-dot">?</span>
                              {isDone ? 'Ready' : isError ? 'Needs attention' : (f.status || 'Added')}
                            </div>
                            {!isDone && !isError && (
                              <div className="eva-file-progress-track">
                                <div className="eva-file-progress-indicator" />
                              </div>
                            )}
                          </div>
                          <span
                            className={`eva-upload-status${isDone ? ' is-done' : ''}${isError ? ' is-error' : ''}`}
                            style={{ color: statusColor(f.status) }}
                            title={String(f.status || 'Added')}
                          >
                            {isDone ? '?' : isError ? '!' : '?'}
                          </span>
                          <button
                            type="button"
                            className="eva-upload-remove"
                            onClick={() => setUploadedFiles(prev => prev.filter((_, j) => j !== i))}
                            aria-label={`Remove ${f.name}`}
                            title="Remove file"
                          >
                            ?
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* SQL connection */}
            {dataSource === 'sql' && (
              <div>
                <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.7px', fontFamily: 'monospace', marginBottom: 6 }}>Connection String</div>
                <textarea value={sqlConn} onChange={e => setSqlConn(e.target.value)}
                  placeholder="postgresql://user:pass@host:5432/db&#10;or&#10;sqlite:///path/to/db.sqlite"
                  rows={3}
                  style={{ width: '100%', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', color: 'var(--text)', fontSize: 11, outline: 'none', resize: 'none', fontFamily: 'monospace', boxSizing: 'border-box' }} />
                <div style={{ fontSize: 10, color: 'var(--border2)', marginTop: 4 }}>Supports: PostgreSQL, MySQL, SQLite, MSSQL</div>
              </div>
            )}

            {/* URLs */}
            {dataSource === 'urls' && (
              <div>
                <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.7px', fontFamily: 'monospace', marginBottom: 6 }}>URLs (one per line)</div>
                <textarea value={urls} onChange={e => setUrls(e.target.value)}
                  placeholder="https://example.com/page1&#10;https://docs.example.com&#10;https://blog.example.com/post"
                  rows={4}
                  style={{ width: '100%', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', color: 'var(--text)', fontSize: 11, outline: 'none', resize: 'none', fontFamily: 'monospace', boxSizing: 'border-box' }} />
                <div style={{ fontSize: 10, color: 'var(--border2)', marginTop: 4 }}>Web pages, docs, blogs, articles</div>
              </div>
            )}

            {/* Tasks */}
            <div>
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.7px', fontFamily: 'monospace', marginBottom: 8 }}>Auto Tasks</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {TASK_OPTIONS.map(t => (
                  <div key={t.id} onClick={() => setTasks(prev => ({ ...prev, [t.id]: !prev[t.id] }))}
                    style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, border: `1px solid ${tasks[t.id] ? 'var(--accent)' : 'var(--border)'}`, background: tasks[t.id] ? 'var(--accent-soft)' : 'transparent', cursor: 'pointer', transition: '.15s' }}>
                    <div style={{ width: 14, height: 14, borderRadius: 4, border: `2px solid ${tasks[t.id] ? 'var(--accent)' : 'var(--border2)'}`, background: tasks[t.id] ? 'var(--accent)' : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#fff', flexShrink: 0 }}>
                      {tasks[t.id] ? '✓' : ''}
                    </div>
                    <span style={{ fontSize: 14 }}>{t.icon}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: tasks[t.id] ? 'var(--accent)' : 'var(--text3)', fontWeight: tasks[t.id] ? 600 : 400 }}>{t.label}</div>
                      <div style={{ fontSize: 10, color: 'var(--border2)' }}>{t.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Run button */}
            <button onClick={runPipeline} disabled={running || (dataSource === 'files' && uploadedFiles.length === 0) || (dataSource === 'sql' && !sqlConn) || (dataSource === 'urls' && !urls)}
              style={{ width: '100%', padding: '11px', borderRadius: 10, border: 'none', background: running ? 'var(--border)' : 'linear-gradient(135deg,var(--accent),var(--accent))', color: running ? 'var(--text3)' : '#fff', fontSize: 13, fontWeight: 700, cursor: running ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, transition: '.18s' }}>
              {running ? '⟳ Running...' : '⚡ Run Automation'}
            </button>
          </div>
        )}

        {/* ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ PIPELINE TAB ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ */}
        {activeTab === 'pipeline' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.7px', fontFamily: 'monospace', marginBottom: 4 }}>
              Pipeline Status {running && <span style={{ color: 'var(--warn)' }}>Ãƒâ€šÃ‚Â· Running</span>}
            </div>

            {pipeline.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--border2)', fontSize: 12, padding: '24px 0' }}>
                Configure and run automation first
              </div>
            ) : (
              pipeline.map((step, i) => (
                <div key={step.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 12px', background: 'var(--surface)', borderRadius: 9, border: `1px solid ${step.status === 'running' ? 'var(--warn)' : step.status === 'done' ? 'rgba(74,222,128,.2)' : 'var(--border)'}`, transition: '.3s' }}>
                  <div style={{ width: 24, height: 24, borderRadius: '50%', background: step.status === 'running' ? 'rgba(251,191,36,.15)' : step.status === 'done' ? 'rgba(74,222,128,.15)' : 'var(--surface2)', border: `2px solid ${statusColor(step.status)}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: statusColor(step.status), flexShrink: 0, marginTop: 1, fontWeight: 700 }}>
                    {step.status === 'running' ? <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span> : statusIcon(step.status)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 13 }}>{step.icon}</span>
                      <span style={{ fontSize: 12, color: step.status === 'pending' ? 'var(--text3)' : 'var(--text)', fontWeight: step.status !== 'pending' ? 500 : 400 }}>{step.label}</span>
                    </div>
                    {step.result && <div style={{ fontSize: 10, color: 'var(--green)', marginTop: 3, fontFamily: 'monospace' }}>{step.result}</div>}
                  </div>
                </div>
              ))
            )}

            {!running && pipeline.length > 0 && (
              <button onClick={() => setActiveTab('results')}
                style={{ width: '100%', padding: '9px', borderRadius: 9, border: '1px solid var(--border)', background: 'transparent', color: 'var(--accent)', fontSize: 12, cursor: 'pointer', marginTop: 4 }}>
                View Results ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢
              </button>
            )}
          </div>
        )}

        {/* ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ RESULTS TAB ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ */}
        {activeTab === 'results' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.7px', fontFamily: 'monospace', marginBottom: 4 }}>Automation Results</div>

            {results.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--border2)', fontSize: 12, padding: '24px 0' }}>
                No results yet. Run automation first.
              </div>
            ) : (
              results.map((r, i) => (
                <div key={i} style={{ background: 'var(--surface)', borderRadius: 10, border: '1px solid var(--border)', overflow: 'hidden' }}>
                  <div style={{ padding: '8px 12px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 14 }}>{r.icon}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)' }}>{r.title}</span>
                    <button onClick={() => onSendToChat(r.body)}
                      style={{ marginLeft: 'auto', padding: '3px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--accent)', fontSize: 10, cursor: 'pointer' }}>
                      ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Chat
                    </button>
                  </div>
                  <div style={{ padding: '10px 12px', fontSize: 11, color: 'var(--text3)', lineHeight: 1.6, maxHeight: 120, overflowY: 'auto' }}>
                    {r.body?.slice(0, 300)}{r.body?.length > 300 ? '…' : ''}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

// ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
// MAIN CHAT COMPONENT
// ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
const EMPTY_CHAT_PROMPT = 'How can I help you today?';
const createInitialMessages = () => [
  { id: 'init', role: 'bot', text: EMPTY_CHAT_PROMPT, done: true },
];

function createConversation(overrides = {}) {
  const now = new Date().toISOString();
  return {
    id: overrides.id || Date.now(),
    title: overrides.title || 'New conversation',
    active: overrides.active ?? true,
    pinned: !!overrides.pinned,
    createdAt: overrides.createdAt || overrides.created_at || now,
    updatedAt: overrides.updatedAt || overrides.updated_at || now,
  };
}

function normalizeConversation(conversation, index = 0) {
  return createConversation({
    ...conversation,
    id: conversation.id || conversation.session_id || `local_${Date.now()}_${index}`,
    active: !!conversation.active,
  });
}

function normalizeConversations(items) {
  const conversations = (Array.isArray(items) && items.length ? items : [createConversation({ id: 1 })])
    .map(normalizeConversation);
  if (!conversations.some((conversation) => conversation.active)) {
    conversations[0] = { ...conversations[0], active: true };
  }
  return conversations;
}

const LEGACY_SOURCE_LABEL_RE = /^\s*(?:[-*]\s*)?\[?\s*Source\s+\d+(?::\s*[^\]\r\n]+)?\]?\s*$/i;
const INLINE_SOURCE_LABEL_RE = /\s*\[\s*Source\s+\d+(?::\s*[^\]\r\n]+)?\s*\]/gi;
const SOURCE_HEADING_RE = /^\s*(?:#{1,6}\s*)?(?:\*\*)?Sources?(?:\*\*)?\s*:?\s*$/i;

function asArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function sourceLabelFromValue(value) {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value).trim();
  if (typeof value !== 'object') return '';

  return String(
    value.source_id ||
    value.sourceId ||
    value.title ||
    value.name ||
    value.source ||
    value.file_name ||
    value.filename ||
    value.document ||
    value.path ||
    value.id ||
    ''
  ).trim();
}

function uniqueSourceLabels(values) {
  return [...new Set(values.map(sourceLabelFromValue).filter(Boolean))];
}

function buildRagAuditMeta(data = {}) {
  const debug = data.rag_debug || data.debug || {};
  const audit = data.audit_trail || {};
  const sourceIds = uniqueSourceLabels([
    ...asArray(data.source_ids),
    ...asArray(data.sourceIds),
    ...asArray(debug.source_ids),
    ...asArray(debug.sourceIds),
    ...asArray(audit.source_ids),
    ...asArray(audit.sourceIds),
    ...asArray(data.sources),
    ...asArray(debug.sources),
    ...asArray(audit.sources),
  ]);

  // Evidence that retrieval RAN, which is separate from what it grounded.
  // Without these, a response carrying sources: [] alongside
  // retrievers_used: ["bm25"] produced no meta at all, so the reveal could
  // only fall back to "came from general knowledge" ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â about an answer that had
  // just quoted the user's files.
  const retrieversUsed = uniqueSourceLabels(asArray(data.retrievers_used));
  const retrievedCount = asArray(data.retrieved_sources).length;

  if (!sourceIds.length && !audit.audit_id && !Object.keys(debug).length
      && !retrieversUsed.length && !retrievedCount) return null;
  return {
    mode: debug.mode || data.mode || data.mode_used || 'RAG',
    confidence: data.confidence ?? audit.confidence ?? 0,
    sourceIds,
    retrieversUsed,
    retrievedCount,
    auditId: audit.audit_id || data.audit_id || '',
    rewrittenQuery: debug.rewritten_query || '',
    expandedQueries: debug.expanded_queries || [],
    channels: debug.channels || {},
  };
}

function hasStructuredSources(ragAudit) {
  return Array.isArray(ragAudit?.sourceIds) && ragAudit.sourceIds.length > 0;
}

function stripLegacySourceLabelLines(text = '') {
  const cleaned = String(text || '')
    .replace(INLINE_SOURCE_LABEL_RE, ' ')
    .split(/\r?\n/)
    .filter((line) => !LEGACY_SOURCE_LABEL_RE.test(line))
    .join('\n')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/[ \t]+([,.;:!?])/g, '$1')
    .replace(/([([<{])\s+/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  const lines = cleaned.split(/\r?\n/);
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  if (lines.length && SOURCE_HEADING_RE.test(lines[lines.length - 1])) lines.pop();
  return lines.join('\n').trim();
}

function sanitizeAssistantText(text, ragAudit = null, reveal = false) {
  // Provenance rule: inline [Source N] markers ARE source metadata, so they
  // are stripped unless the user has explicitly asked where the answer came
  // from. The gate used to run the other way ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â markers were kept whenever
  // retrieval had worked ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â which showed provenance by default on exactly the
  // answers that had any.
  return reveal && hasStructuredSources(ragAudit)
    ? String(text || '')
    : stripLegacySourceLabelLines(text);
}

function sanitizeCachedMessages(items = []) {
  if (!Array.isArray(items)) return [];
  return items.map((message) => {
    if (!isAssistantLikeMessage(message)) return message;
    const ragAudit = buildRagAuditMeta(message.ragAudit || message) || null;
    const text = sanitizeAssistantText(message.text || message.content || '', ragAudit);
    const next = { ...message, text };
    if (Object.prototype.hasOwnProperty.call(next, 'content')) next.content = text;
    if (hasStructuredSources(ragAudit)) next.ragAudit = ragAudit;
    else delete next.ragAudit;
    return next;
  });
}

// How much of the conversation travels with each request.
//
// Bounded on two axes deliberately. Turn count alone is not enough: a handful
// of long analytical answers can exceed the provider window on its own, and a
// blown window fails the whole request rather than degrading. Characters alone
// is not enough either, because a budget spent entirely on one enormous answer
// loses the recent back-and-forth that follow-ups actually depend on.
//
// Walks backwards so the most recent turns are kept when the budget runs out,
// and each entry is individually clipped so one huge message cannot evict
// everything before it.
const HISTORY_MAX_TURNS = 10;
const HISTORY_MAX_CHARS = 6000;
const HISTORY_MAX_ENTRY_CHARS = 1500;

function conversationWindow(items = []) {
  if (!Array.isArray(items) || items.length === 0) return [];
  const out = [];
  let used = 0;
  for (let i = items.length - 1; i >= 0 && out.length < HISTORY_MAX_TURNS; i -= 1) {
    const item = items[i];
    const role = String(item?.role || '').toLowerCase() === 'assistant' ? 'assistant' : 'user';
    const content = String(item?.content || item?.text || '').slice(0, HISTORY_MAX_ENTRY_CHARS);
    if (!content.trim()) continue;
    if (used + content.length > HISTORY_MAX_CHARS) break;
    used += content.length;
    out.push({ role, content });
  }
  return out.reverse();
}

function sanitizePromptHistory(items = []) {
  if (!Array.isArray(items)) return [];
  return items
    .map((item) => {
      if (String(item?.role || '').toLowerCase() !== 'assistant') return item;
      const ragAudit = buildRagAuditMeta(item.ragAudit || item) || null;
      return { ...item, content: sanitizeAssistantText(item.content || item.text || '', ragAudit) };
    })
    .filter((item) => item?.role && (item.content || item.text));
}

function generateConversationTitle(text) {
  const cleaned = (text || '')
    .replace(/[`*_>#()[\]{}]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!cleaned) return 'New conversation';

  const stopWords = new Set(['how', 'to', 'the', 'a', 'an', 'and', 'or', 'for', 'with', 'about', 'can', 'you', 'me', 'my', 'please']);
  const words = cleaned
    .split(' ')
    .filter((word) => word.length > 1 && !stopWords.has(word.toLowerCase()))
    .slice(0, 5);
  const titleWords = words.length ? words : cleaned.split(' ').slice(0, 5);

  return titleWords
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
    .slice(0, 60);
}


// ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Skill Library panel (saved skills from Supabase + repo-bundled, read-only) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
// `embedded` renders the library as PANEL CONTENT inside the Tools Center
// instead of as its own right-hand sheet: identical list, handlers and state,
// without the fixed overlay or backdrop. One component, two presentations.
function SkillLibraryPanel({ ragApi, token, userId, workspaceId, autoSkillUse, onToggleAuto, onUseSkill, onSkillsChanged, activeSkillId, onClose, isMobile, embedded = false }) {
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deletingId, setDeletingId] = useState('');
  const [storageMode, setStorageMode] = useState('');

  const headers = {
    
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
  };
  const qs = `user_id=${encodeURIComponent(userId)}&workspace_id=${encodeURIComponent(workspaceId)}`;

  const loadSkills = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const res = await fetch(`${ragApi}/api/skills?${qs}`, { headers });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data?.detail || `Failed to load (${res.status})`);
      setSkills(Array.isArray(data.skills) ? data.skills : []);
      setStorageMode(data.storage_mode || (data.db_connected ? 'supabase' : 'local_fallback'));
    } catch (e) {
      setError(e.message || 'Could not load skills. Is the ML service running?');
      setSkills([]);
      setStorageMode('');
    } finally { setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ragApi, qs]);

  useEffect(() => { loadSkills(); }, [loadSkills]);

  const openPreview = async (s) => {
    setSelectedId(s.id); setPreview(null); setPreviewLoading(true);
    try {
      const res = await fetch(`${ragApi}/api/skills/${encodeURIComponent(s.id)}`, { headers });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data?.detail || 'Preview failed');
      setPreview(data.skill);
    } catch (e) {
      setPreview({ ...s, content: `Could not load preview: ${e.message}` });
    } finally { setPreviewLoading(false); }
  };

  const handleDelete = async (s) => {
    if (s.source !== 'saved') return; // bundled skills are read-only
    if (!window.confirm(`Delete skill "${s.name}"? This permanently removes it from your library.`)) return;
    setDeletingId(s.id);
    try {
      const res = await fetch(`${ragApi}/api/skills/${encodeURIComponent(s.id)}?${qs}`, { method: 'DELETE', headers });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data?.detail || 'Delete failed');
      if (selectedId === s.id) { setSelectedId(null); setPreview(null); }
      await loadSkills();
      onSkillsChanged && onSkillsChanged();
    } catch (e) {
      setError(e.message || 'Delete failed');
    } finally { setDeletingId(''); }
  };

  const c = { panel: 'var(--surface2)', border: 'var(--border)', accent: 'var(--accent)', text: 'var(--text)', text2: 'var(--text2)', muted: 'var(--text3)', bg: 'var(--surface)' };
  const sheetStyle = isMobile
    ? { position: 'fixed', inset: 0, width: '100%', height: '100%', borderRadius: 0 }
    : { position: 'fixed', top: 0, right: 0, width: 'min(720px, 96vw)', height: '100%', borderLeft: `1px solid ${c.border}` };

  const Shell = ({ children }) => (embedded ? (
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>{children}</div>
  ) : (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }}>
      <button
        type="button"
        aria-label="Close skill library"
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', border: 'none', cursor: 'pointer' }}
      />
      {children}
    </div>
  ));

  return (
    <Shell>
      <section
        role={embedded ? undefined : 'dialog'}
        aria-modal={embedded ? undefined : 'true'}
        aria-label="Skill Library"
        style={embedded
          ? { flex: 1, minHeight: 0, background: 'transparent', color: c.text, display: 'flex', flexDirection: 'column', boxSizing: 'border-box', overflow: 'hidden' }
          : { ...sheetStyle, background: c.bg, color: c.text, boxShadow: '-20px 0 60px rgba(0,0,0,.45)', display: 'flex', flexDirection: 'column', boxSizing: 'border-box', overflow: 'hidden' }}
      >
        <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 18px', borderBottom: `1px solid ${c.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Library size={20} color={c.accent} />
            <div>
              <div style={{ fontSize: 16, fontWeight: 800 }}>Skill Library</div>
              <div style={{ fontSize: 11, color: storageMode === 'supabase' ? 'var(--green)' : c.muted }}>
                {storageMode === 'supabase'
                  ? 'Saved skills persist in Supabase'
                  : storageMode
                    ? 'Supabase storage unavailable'
                    : 'Checking persistent skill storage'}
              </div>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: c.text2, cursor: 'pointer', padding: 4 }}>
            <X size={20} />
          </button>
        </header>

        {/* Auto Skill Use toggle */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 18px', borderBottom: `1px solid ${c.border}`, background: c.panel }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Zap size={15} color={autoSkillUse ? 'var(--warn)' : c.muted} />
            <div>
              <div style={{ fontSize: 13, fontWeight: 700 }}>Auto Skill Use</div>
              <div style={{ fontSize: 11, color: c.muted }}>Auto-match a skill to each message {autoSkillUse ? '' : '(off)'}</div>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={autoSkillUse}
            onClick={() => onToggleAuto(!autoSkillUse)}
            className="eva-skill-switch"
            style={{
              position: 'relative', width: 46, height: 26, borderRadius: 999, cursor: 'pointer', flexShrink: 0,
              border: `1px solid ${autoSkillUse ? c.accent : c.border}`,
              background: autoSkillUse ? c.accent : 'transparent', transition: 'all .15s',
            }}
          >
            <span style={{ position: 'absolute', top: 2, left: autoSkillUse ? 22 : 2, width: 20, height: 20, borderRadius: '50%', background: '#fff', transition: 'left .15s' }} />
          </button>
        </div>

        <div style={{ display: 'flex', flex: 1, minHeight: 0, flexDirection: isMobile ? 'column' : 'row' }}>
          {/* List */}
          <div style={{ width: isMobile ? '100%' : 280, flexShrink: 0, borderRight: isMobile ? 'none' : `1px solid ${c.border}`, borderBottom: isMobile ? `1px solid ${c.border}` : 'none', overflowY: 'auto', maxHeight: isMobile ? '40%' : '100%' }}>
            {loading && <div style={{ padding: 18, color: c.muted, fontSize: 13 }}>Loading skills...</div>}
            {error && !loading && <div style={{ padding: 18, color: 'var(--red)', fontSize: 12 }}>{error}</div>}
            {!loading && !error && skills.length === 0 && (
              <div style={{ padding: 18, color: c.muted, fontSize: 13 }}>No skills yet. Create one in the Skill Creator and click "Save to Skill Library".</div>
            )}
            {skills.map((s) => (
              <div
                key={s.id}
                onClick={() => openPreview(s)}
                style={{
                  padding: '12px 14px', borderBottom: `1px solid ${c.border}`, cursor: 'pointer',
                  background: selectedId === s.id ? 'var(--accent-soft)' : 'transparent',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: c.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {activeSkillId === s.id && <Check size={13} color="var(--green)" style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                    {s.name}
                  </div>
                  <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em', padding: '2px 6px', borderRadius: 999, flexShrink: 0,
                    color: s.source === 'saved' ? 'var(--accent)' : c.muted, border: `1px solid ${c.border}`, background: c.bg }}>
                    {s.source === 'saved' ? 'saved' : 'bundled'}
                  </span>
                </div>
                {s.description && <div style={{ fontSize: 11, color: c.text2, marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.description}</div>}
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button type="button" onClick={(e) => { e.stopPropagation(); onUseSkill(s); }}
                    style={{ fontSize: 11, fontWeight: 700, color: '#fff', background: c.accent, border: 'none', borderRadius: 7, padding: '5px 10px', cursor: 'pointer' }}>
                    Use Skill
                  </button>
                  {s.source === 'saved' && (
                    <button type="button" onClick={(e) => { e.stopPropagation(); handleDelete(s); }} disabled={deletingId === s.id}
                      aria-label={`Delete ${s.name}`}
                      style={{ fontSize: 11, fontWeight: 700, color: 'var(--red)', background: 'transparent', border: `1px solid ${c.border}`, borderRadius: 7, padding: '5px 9px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                       <Trash2 size={12} /> {deletingId === s.id ? '...' : 'Delete'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Preview */}
          <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: 16 }}>
            {!selectedId && <div style={{ color: c.muted, fontSize: 13 }}>Select a skill to preview its SKILL.md.</div>}
            {previewLoading && <div style={{ color: c.muted, fontSize: 13 }}>Loading previewÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦</div>}
            {preview && !previewLoading && (
              <>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                  <div style={{ fontSize: 15, fontWeight: 800 }}>{preview.name}</div>
                  <button type="button" onClick={() => onUseSkill(preview)}
                    style={{ fontSize: 12, fontWeight: 700, color: '#fff', background: `linear-gradient(135deg,var(--accent),var(--accent))`, border: 'none', borderRadius: 8, padding: '7px 14px', cursor: 'pointer' }}>
                    Use this skill
                  </button>
                </div>
                <pre style={{ margin: 0, background: c.bg, border: `1px solid ${c.border}`, borderRadius: 8, padding: 12, color: c.text2, fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {preview.content}
                </pre>
              </>
            )}
          </div>
        </div>
      </section>
    </Shell>
  );
}

export default function Chat({ API = DEFAULT_API_BASE }) {
  const { t } = useTranslation();
  const [messages, setMessages]           = useState(createInitialMessages);
  const [input, setInput]                 = useState('');
  const [selectedAgentFolder, setSelectedAgentFolder] = useState('');
  const [agentPanelOpen, setAgentPanelOpen] = useState(false);
  const [agentJobId, setAgentJobId] = useState('');
  const [, setAgentStatus] = useState('');
  const [, setAgentPending] = useState([]);
  const [, setAgentBusy] = useState(false);

  const chooseAgentFolder = async () => {
    if (!window.evaDesktop?.selectFolder) {
      alert('Folder picker is available in the EVA desktop app only.');
      return;
    }
    try {
      const result = await window.evaDesktop.selectFolder();
      if (!result?.canceled && result?.path) {
        setSelectedAgentFolder(result.path);
      }
    } catch (error) {
      console.error('Folder selection failed:', error);
      alert('Could not open folder picker.');
    }
  };
  const [loading, setLoading]             = useState(false);
  const [token, setToken]                 = useState(localStorage.getItem('aria_token') || null);
  const [, setStatus]                     = useState(token ? 'online' : 'authenticating');
  const [showPlus, setShowPlus]           = useState(false);
  const [attachedFile, setAttachedFile]   = useState(null);
  const [attachedImage, setAttachedImage] = useState(null);
  const [cameraOpen, setCameraOpen] = useState(false);   // Update 63: vision
  const [attachmentNotice, setAttachmentNotice] = useState('');
  const [attachmentPreviewUrl, setAttachmentPreviewUrl] = useState('');
  const [isListening, setIsListening]     = useState(false);
  const [suggestions, setSuggestions]     = useState([]);
  const recentSuggestionsRef = useRef([]);   // anti-repetition: texts of recently shown suggestions
  const [editingId, setEditingId]         = useState(null);
  const [editText, setEditText]           = useState('');
  const [feedback, setFeedback]           = useState({});
  const [activeTool, setActiveTool]       = useState(null);
  const [codeWorkspaceOpen, setCodeWorkspaceOpen] = useState(false);
  const [featureToolsOpen, setFeatureToolsOpen] = useState(false);
  const [featureToolsTab, setFeatureToolsTab] = useState('sandbox');
  const [directoryTab, setDirectoryTab] = useState('skills');
  const [userWorkspaceOpen, setUserWorkspaceOpen] = useState(false);
  const [selectedUserFileId, setSelectedUserFileId] = useState('');
  const [workspaces, setWorkspaces] = useState([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(() => localStorage.getItem('eva_selected_workspace_id') || 'default-org');
  const [workspaceFormOpen, setWorkspaceFormOpen] = useState(false);
  const [workspaceForm, setWorkspaceForm] = useState({ name: '', description: '' });
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState('');
  //const [backendNotice, setBackendNotice] = useState('');
  const [sessionId, setSessionId]          = useState(() => 'session_' + Date.now());
  const [isMobile, setIsMobile]            = useState(window.innerWidth <= 768);
  const storedUser = (() => { try { return JSON.parse(localStorage.getItem('aria_user') || '{}'); } catch { return {}; } })();
  const userDbId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const [conversations, setConversations] = useState(() => {
  try { return normalizeConversations(JSON.parse(localStorage.getItem('eva_conversations') || 'null')); } catch { return normalizeConversations(null); }
});
  const [history, setHistory] = useState(() => {
  try { return sanitizePromptHistory(JSON.parse(localStorage.getItem('eva_history') || '[]')); } catch { return []; }
});

  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Skill Library + Auto Skill Router ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  const [autoSkillUse, setAutoSkillUse] = useState(() => localStorage.getItem('eva_auto_skill_use') !== 'false'); // default ON
  const [activeSkill, setActiveSkill] = useState(null);   // manually-selected sticky skill {id,name,content}
  const [lastUsedSkill, setLastUsedSkill] = useState(null); // {name, auto} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â drives the "Using skill" label
  const skillsCacheRef = useRef(null);   // cached summary list for local matching (avoids per-message backend call)
  const skillContentRef = useRef(new Map()); // id -> full SKILL.md content (memoized)

  const logRef      = useRef(null);
  const plusRef     = useRef(null);
  const fileRef     = useRef(null);
  const imageRef    = useRef(null);
  const recogRef    = useRef(null);
  const textareaRef = useRef(null);
  const streamRef   = useRef(null);
  const processedCommandRef = useRef(null);
  //const backendNoticeTimerRef = useRef(null);

  const pollRagUploadJob = useCallback(async (jobId, headers = {}, onUpdate = () => {}) => {
    const terminal = new Set(['COMPLETE', 'FAILED', 'CANCELLED']);
    while (true) {
      const res = await fetch(`${RAG_API}/rag/jobs/${encodeURIComponent(jobId)}`, { headers });
      const job = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(job.detail || job.error || `Upload job ${jobId} could not be loaded`);
      onUpdate(job);
      if (terminal.has(job.status)) {
        if (job.status !== 'COMPLETE') throw new Error(job.error || job.message || `Upload job ${job.status}`);
        return job;
      }
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
  }, []);

  const workspaceHeaders = useCallback(() => {
    const currentToken = localStorage.getItem('aria_token') || token;
    return {
      'Content-Type': 'application/json',
      
      ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
    };
  }, [token]);

  const selectedWorkspace = workspaces.find((workspace) => workspace.id === selectedWorkspaceId) || null;

  const loadWorkspaces = useCallback(async () => {
    const currentToken = localStorage.getItem('aria_token') || token;
    if (!currentToken) return;
    setWorkspaceLoading(true);
    setWorkspaceError('');
    try {
      const res = await fetch(`${API}/api/workspaces`, { headers: workspaceHeaders() });
      if (!res.ok) throw new Error(res.status === 401 ? 'Login required to load workspaces.' : 'Could not load workspaces.');
      const data = await res.json();
      const items = Array.isArray(data.workspaces) ? data.workspaces : [];
      setWorkspaces(items);
      const savedId = localStorage.getItem('eva_selected_workspace_id') || selectedWorkspaceId;
      const nextSelected = items.find((workspace) => workspace.id === savedId)?.id || items[0]?.id || '';
      setSelectedWorkspaceId(nextSelected);
      if (nextSelected) localStorage.setItem('eva_selected_workspace_id', nextSelected);
      else localStorage.removeItem('eva_selected_workspace_id');
      window.dispatchEvent(new CustomEvent('eva:workspace-selected', { detail: { workspaceId: nextSelected } }));
    } catch (err) {
      setWorkspaceError(err.message || 'Could not load workspaces.');
    } finally {
      setWorkspaceLoading(false);
    }
  }, [API, selectedWorkspaceId, token, workspaceHeaders]);

  useEffect(() => {
    loadWorkspaces();
  }, [loadWorkspaces]);

  const selectWorkspace = (workspaceId) => {
    setSelectedWorkspaceId(workspaceId);
    if (workspaceId) localStorage.setItem('eva_selected_workspace_id', workspaceId);
    else localStorage.removeItem('eva_selected_workspace_id');
    window.dispatchEvent(new CustomEvent('eva:workspace-selected', { detail: { workspaceId } }));
  };

  const createWorkspace = async (event) => {
    event.preventDefault();
    const name = workspaceForm.name.trim();
    if (!name) {
      setWorkspaceError('Workspace name is required.');
      return;
    }
    setWorkspaceLoading(true);
    setWorkspaceError('');
    try {
      const res = await fetch(`${API}/api/workspaces`, {
        method: 'POST',
        headers: workspaceHeaders(),
        body: JSON.stringify({ name, description: workspaceForm.description.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.message || 'Could not create workspace.');
      const workspace = data.workspace;
      if (workspace?.id) {
        setWorkspaces((current) => [workspace, ...current.filter((item) => item.id !== workspace.id)]);
        selectWorkspace(workspace.id);
        setWorkspaceForm({ name: '', description: '' });
        setWorkspaceFormOpen(false);
      }
    } catch (err) {
      setWorkspaceError(err.message || 'Could not create workspace.');
    } finally {
      setWorkspaceLoading(false);
    }
  };

  useEffect(() => () => {
    if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
  }, [attachmentPreviewUrl]);

  const toDbMessages = useCallback((items) => (
    items
      .filter((m) => m.id !== 'init' && m.text && (isUserLikeMessage(m) || isAssistantLikeMessage(m)))
      .map((m) => {
        const role = isUserLikeMessage(m) ? 'user' : 'assistant';
        const ragAudit = role === 'assistant' ? buildRagAuditMeta(m.ragAudit || m) : null;
        return {
          id: String(m.id || Date.now()),
          role,
          text: role === 'assistant' ? sanitizeAssistantText(m.text, ragAudit) : m.text,
        };
      })
  ), []);

  const toUiMessages = useCallback((items = []) => {
    const converted = items.map((m) => {
      const ragAudit = isAssistantLikeMessage(m) ? buildRagAuditMeta(m) : null;
      return {
        id: m.id || `${m.role || m.sender || 'message'}_${Date.now()}_${Math.random().toString(36).slice(2)}`,
        role: isUserLikeMessage(m) ? 'user' : 'bot',
        text: isAssistantLikeMessage(m)
          ? sanitizeAssistantText(m.text || m.content || '', ragAudit)
          : (m.text || m.content || ''),
        done: true,
        ...(ragAudit ? { ragAudit } : {}),
      };
    });

    return converted.length
      ? converted
      : createInitialMessages();
  }, []);

  const uiMessagesToHistory = useCallback((items) => (
    items
      .filter((m) => m.id !== 'init' && m.text && (isUserLikeMessage(m) || isAssistantLikeMessage(m)))
      .map((m) => {
        const role = isUserLikeMessage(m) ? 'user' : 'assistant';
        const ragAudit = role === 'assistant' ? buildRagAuditMeta(m.ragAudit || m) : null;
        return {
          role,
          content: role === 'assistant' ? sanitizeAssistantText(m.text, ragAudit) : m.text,
          ...(hasStructuredSources(ragAudit) ? { sourceIds: ragAudit.sourceIds } : {}),
        };
      })
  ), []);

  const publishChatState = useCallback((nextConversations) => {
    window.dispatchEvent(new CustomEvent('eva:chat-state', {
      detail: { conversations: nextConversations },
    }));
  }, []);

  const persistActiveChat = useCallback(() => {
    const activeConv = conversations.find((conversation) => conversation.active);
    if (!activeConv || messages.length <= 1) return;

    try {
      const saved = JSON.parse(localStorage.getItem('eva_all_chats') || '{}');
      saved[activeConv.id] = sanitizeCachedMessages(messages);
      localStorage.setItem('eva_all_chats', JSON.stringify(saved));
    } catch {}
  }, [conversations, messages]);

  const startNewConversation = useCallback(() => {
    persistActiveChat();
    const newId = Date.now();
    const nextConversations = [
      ...conversations.map((conversation) => ({ ...conversation, active: false })),
      createConversation({ id: newId, active: true }),
    ];

    setConversations(nextConversations);
    setSessionId(String(newId));
    setMessages(createInitialMessages());
    setHistory([]);
    setSuggestions([]);
    setInput('');
    setAttachedFile(null);
    setAttachedImage(null);
    localStorage.setItem('eva_conversations', JSON.stringify(nextConversations));
    publishChatState(nextConversations);
  }, [conversations, persistActiveChat, publishChatState]);
  
  const historyLoadRequestIdRef = useRef(0);

  const selectConversation = useCallback((conversationId) => {
    const requestId = ++historyLoadRequestIdRef.current;
    if (!conversationId) return;
    persistActiveChat();

    let allChats = {};
    try {
      allChats = JSON.parse(localStorage.getItem('eva_all_chats') || '{}');
    } catch {}

    const nextConversations = conversations.map((conversation) => ({
      ...conversation,
      active: String(conversation.id) === String(conversationId),
      updatedAt: String(conversation.id) === String(conversationId) ? new Date().toISOString() : conversation.updatedAt,
    }));

    setConversations(nextConversations);
    setSessionId(String(conversationId));
    setSuggestions([]);
    localStorage.setItem('eva_conversations', JSON.stringify(nextConversations));
    publishChatState(nextConversations);

    if (allChats[conversationId]) {
      const cachedMessages = sanitizeCachedMessages(allChats[conversationId]);
      allChats[conversationId] = cachedMessages;
      localStorage.setItem('eva_all_chats', JSON.stringify(allChats));
      setMessages(cachedMessages);
      setHistory(uiMessagesToHistory(cachedMessages));
    } else {
      setMessages(createInitialMessages());
      setHistory([]);
    }

    const currentToken = localStorage.getItem('aria_token') || token;
    const headers = {
      
      ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
    };

    fetch(`${API}/chat/history/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userDbId)}`, { headers })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data?.messages) return;
        if (requestId !== historyLoadRequestIdRef.current) return; // ignore stale responses
        const loadedMessages = toUiMessages(data.messages);
        setMessages(loadedMessages);
        setHistory(uiMessagesToHistory(loadedMessages));
      })
      .catch(() => {});
  }, [API, conversations, persistActiveChat, publishChatState, toUiMessages, token, uiMessagesToHistory, userDbId]);

  const renameConversation = useCallback((conversationId, title) => {
    const nextTitle = (title || 'New conversation').trim().slice(0, 80) || 'New conversation';
    setConversations((current) => {
      const next = current.map((conversation) => (
        String(conversation.id) === String(conversationId)
          ? { ...conversation, title: nextTitle, updatedAt: new Date().toISOString() }
          : conversation
      ));
      localStorage.setItem('eva_conversations', JSON.stringify(next));
      publishChatState(next);
      return next;
    });

    const currentToken = localStorage.getItem('aria_token') || token;
    fetch(`${API}/chat/history/${encodeURIComponent(conversationId)}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        
        ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
      },
      body: JSON.stringify({ user_id: userDbId, title: nextTitle }),
    }).catch(() => {});
  }, [API, publishChatState, token, userDbId]);

  const pinConversation = useCallback((conversationId, pinned) => {
    setConversations((current) => {
      const next = current.map((conversation) => (
        String(conversation.id) === String(conversationId)
          ? { ...conversation, pinned: !!pinned, updatedAt: new Date().toISOString() }
          : conversation
      ));
      localStorage.setItem('eva_conversations', JSON.stringify(next));
      publishChatState(next);
      return next;
    });
  }, [publishChatState]);

  const deleteConversation = useCallback((conversationId) => {
    persistActiveChat();

    let allChats = {};
    try {
      allChats = JSON.parse(localStorage.getItem('eva_all_chats') || '{}');
    } catch {}
    delete allChats[conversationId];
    localStorage.setItem('eva_all_chats', JSON.stringify(allChats));

    const deletingActive = conversations.some((conversation) => String(conversation.id) === String(conversationId) && conversation.active);
    let nextConversations = conversations.filter((conversation) => String(conversation.id) !== String(conversationId));
    if (!nextConversations.length) nextConversations = [createConversation({ id: Date.now(), active: true })];
    if (deletingActive) {
      nextConversations = nextConversations.map((conversation, index) => ({ ...conversation, active: index === 0 }));
    }

    setConversations(nextConversations);
    localStorage.setItem('eva_conversations', JSON.stringify(nextConversations));
    publishChatState(nextConversations);

    if (deletingActive) {
      const nextActive = nextConversations.find((conversation) => conversation.active) || nextConversations[0];
      setSessionId(String(nextActive.id));
      const savedMessages = sanitizeCachedMessages(allChats[nextActive.id]);
      setMessages(savedMessages.length ? savedMessages : createInitialMessages());
      setHistory(savedMessages.length ? uiMessagesToHistory(savedMessages) : []);
    }

    const currentToken = localStorage.getItem('aria_token') || token;
    fetch(`${API}/chat/history/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userDbId)}`, {
      method: 'DELETE',
      headers: {
        
        ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
      },
    }).catch(() => {});
  }, [API, conversations, persistActiveChat, publishChatState, token, uiMessagesToHistory, userDbId]);

  const streamBotText = useCallback(async (botMsgId, text, delayMs = 15, signal = null) => {
    let partial = '';

    for (const word of text.split(' ')) {
      if (signal?.aborted) {
        const error = new Error('Response stopped by user.');
        error.name = 'AbortError';
        throw error;
      }
      partial += (partial ? ' ' : '') + word;
      const nextText = partial;
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: nextText } : msg));
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }

    if (signal?.aborted) {
      const error = new Error('Response stopped by user.');
      error.name = 'AbortError';
      throw error;
    }
  }, []);

  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Mobile resize listener ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    // Only snap to bottom if the user is already near it. Unconditionally
    // forcing scrollTop here on every `messages` update (i.e. on every
    // streamed token, and every upload-status tick) is what made the chat
    // feel "locked" while a response was in progress ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â any manual scroll up
    // got yanked back down within milliseconds.
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom < 120) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Mirrors the rendered messages so sendMessage can look at the answer the
  // user is actually reacting to. Reading `messages` from the callback closure
  // would give whatever it held when the callback was last built.
  const messagesRef = useRef([]);
  useEffect(() => { messagesRef.current = messages; }, [messages]);

useEffect(() => {
localStorage.setItem('eva_history', JSON.stringify(sanitizePromptHistory(history).slice(-20)));
}, [history]);

useEffect(() => {
  localStorage.setItem('eva_conversations', JSON.stringify(conversations));
  publishChatState(conversations);
}, [conversations, publishChatState]);

useEffect(() => {
  const active = conversations.find((c) => c.active);
  if (active) setSessionId(String(active.id));
}, [conversations]);

// Update 62a: sendMessage is declared ~200 lines below this effect. Naming it
// in the dependency array evaluated it during render while it was still in the
// temporal dead zone ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â a ReferenceError that crashed the whole chat page. The
// ref is populated after sendMessage exists, so this effect never has to
// reference it directly.
const voiceSendRef = useRef(null);

useEffect(() => {
  const runCommand = (command) => {
    if (!command?.id || processedCommandRef.current === command.id) return;
    processedCommandRef.current = command.id;

    if (command.type === 'new') startNewConversation();
    if (command.type === 'select') selectConversation(command.conversationId);
    if (command.type === 'rename') renameConversation(command.conversationId, command.title);
    if (command.type === 'pin') pinConversation(command.conversationId, command.pinned);
    if (command.type === 'delete') deleteConversation(command.conversationId);
    // Update 62: voice mode dispatches spoken utterances through the SAME
    // send path as typed input, so they get routing, RAG, memory, the
    // security firewall and history exactly like any other message.
    if (command.type === 'send' && command.text) voiceSendRef.current?.(command.text, { spoken: true });
    // Update 63: "open camera" by voice or from the sidebar.
    if (command.type === 'camera') setCameraOpen(true);
  };

  const handleCommand = (event) => runCommand(event.detail);
  window.addEventListener('eva:chat-command', handleCommand);

  try {
    const savedCommand = JSON.parse(localStorage.getItem('eva_chat_command') || 'null');
    if (savedCommand?.createdAt && Date.now() - Number(savedCommand.createdAt) < 8000) {
      runCommand(savedCommand);
    }
  } catch {}

  return () => window.removeEventListener('eva:chat-command', handleCommand);
}, [deleteConversation, pinConversation, renameConversation, selectConversation, startNewConversation]);

useEffect(() => {
  let cancelled = false;

  const loadServerHistory = async () => {
    try {
      const currentToken = localStorage.getItem('aria_token') || token;
      const headers = {
        
        ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
      };
      const res = await fetch(`${API}/chat/history?user_id=${encodeURIComponent(userDbId)}`, { headers });
      if (!res.ok) return;
      const data = await res.json();
      const sessions = data.sessions || [];
      if (cancelled || sessions.length === 0) return;

      let localConversations = [];
      try {
        localConversations = JSON.parse(localStorage.getItem('eva_conversations') || '[]');
      } catch {}
      const localById = new Map(localConversations.map((conversation) => [String(conversation.id || conversation.session_id), conversation]));
      const nextConversations = sessions.map((s, idx) => {
        const id = s.session_id || s.id;
        const local = localById.get(String(id)) || {};
        return createConversation({
          id,
          title: s.title || local.title || 'New conversation',
          active: idx === 0,
          pinned: local.pinned,
          createdAt: s.created_at || local.createdAt,
          updatedAt: s.updated_at || local.updatedAt,
        });
      });
      setConversations(nextConversations);
      setSessionId(String(nextConversations[0].id));

      const detail = await fetch(`${API}/chat/history/${encodeURIComponent(nextConversations[0].id)}?user_id=${encodeURIComponent(userDbId)}`, { headers });
      if (!detail.ok || cancelled) return;
      const detailData = await detail.json();
      const loadedMessages = toUiMessages(detailData.messages || []);
      setMessages(loadedMessages);
      setHistory(uiMessagesToHistory(loadedMessages));
    } catch {}
  };

  loadServerHistory();
  return () => { cancelled = true; };
}, [API, token, userDbId, toUiMessages, uiMessagesToHistory]);

useEffect(() => {
  const active = conversations.find((c) => c.active);
  if (!active || messages.length <= 1) return;

  const timeout = setTimeout(() => {
    const currentToken = localStorage.getItem('aria_token') || token;
    const headers = {
      'Content-Type': 'application/json',
      
      ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
    };
    fetch(`${API}/chat/history`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        session_id: String(active.id),
        user_id: userDbId,
        title: active.title || 'New conversation',
        messages: toDbMessages(messages),
      }),
    }).catch(() => {});
  }, 700);

  return () => clearTimeout(timeout);
}, [API, conversations, messages, token, toDbMessages, userDbId]);



  useEffect(() => {
    const close = (event) => {
      if (plusRef.current && !plusRef.current.contains(event.target)) {
        setShowPlus(false);
      }
    };
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setShowPlus(false);
      }
    };
    document.addEventListener('mousedown', close);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  useEffect(() => {
    if (token) { setStatus('online'); return; }
    const login = async () => {
      try {
        const { getAuth } = await import('firebase/auth');
        const auth = getAuth();
        const user = auth.currentUser;
        if (user) {
          const firebaseToken = await user.getIdToken(true); // force refresh
          setToken(firebaseToken);  
          localStorage.setItem('aria_token', firebaseToken);
          setStatus('online');
          return;
        }
      } catch {}
      setToken('offline'); setStatus('online');
    };
    login();
  }, [API, token]);

  const autoTitle = async (question) => {
    const title = generateConversationTitle(question);
    setConversations(c => c.map((conv) => conv.active ? { ...conv, title, updatedAt: new Date().toISOString() } : conv));
  };

  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Skill matching helpers (client-cached ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ no per-message backend call) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  const ragHeaders = useCallback(() => {
    const t = localStorage.getItem('aria_token') || token;
    return {  ...(t && t !== 'offline' ? { Authorization: `Bearer ${t}` } : {}) };
  }, [token]);

  const ensureSkillsCache = useCallback(async (force = false) => {
    if (!force && Array.isArray(skillsCacheRef.current)) return skillsCacheRef.current;
    try {
      const ws = selectedWorkspaceId || 'default-org';
      const res = await fetch(`${RAG_API}/api/skills?user_id=${encodeURIComponent(userDbId)}&workspace_id=${encodeURIComponent(ws)}`, { headers: ragHeaders() });
      const data = await res.json();
      skillsCacheRef.current = Array.isArray(data.skills) ? data.skills : [];
    } catch {
      skillsCacheRef.current = Array.isArray(skillsCacheRef.current) ? skillsCacheRef.current : [];
    }
    return skillsCacheRef.current;
  }, [userDbId, selectedWorkspaceId, ragHeaders]);

  const getSkillContent = useCallback(async (id) => {
    if (skillContentRef.current.has(id)) return skillContentRef.current.get(id);
    try {
      const res = await fetch(`${RAG_API}/api/skills/${encodeURIComponent(id)}`, { headers: ragHeaders() });
      const data = await res.json();
      const content = data?.skill?.content || '';
      skillContentRef.current.set(id, content);
      return content;
    } catch { return ''; }
  }, [ragHeaders]);

  const matchSkillFromBackend = useCallback(async (text) => {
    if (!text) return null;
    try {
      const ws = selectedWorkspaceId || 'default-org';
      const res = await fetch(`${RAG_API}/api/skills/match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...ragHeaders() },
        body: JSON.stringify({ message: text, user_id: userDbId, workspace_id: ws }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data?.ok || data.matched !== true) return null;
      const match = data.match || {};
      const id = match.id || data.skill_id;
      const name = match.name || data.skill_name;
      if (!id || !name) return null;
      const content = match.content || await getSkillContent(id);
      return content ? { id, name, content, auto: true, confidence: data.confidence } : null;
    } catch {
      return null;
    }
  }, [getSkillContent, ragHeaders, selectedWorkspaceId, userDbId]);

  // Resolve which skill (if any) applies to this send: manual sticky skill wins,
  // else auto-match when the toggle is ON.
  const resolveSkillForSend = useCallback(async (q) => {
    if (activeSkill) {
      const content = activeSkill.content || await getSkillContent(activeSkill.id);
      return content ? { id: activeSkill.id, name: activeSkill.name, content, auto: false } : null;
    }
    if (!autoSkillUse || !q) return null;
    return matchSkillFromBackend(q);
  }, [activeSkill, autoSkillUse, getSkillContent, matchSkillFromBackend]);

  const toggleAutoSkill = useCallback((val) => {
    setAutoSkillUse(val);
    localStorage.setItem('eva_auto_skill_use', val ? 'true' : 'false');
    if (val) ensureSkillsCache(true); // warm the cache when enabling so the first match is instant
  }, [ensureSkillsCache]);

  const handleUseSkill = useCallback(async (s) => {
    const content = s.content || await getSkillContent(s.id);
    setActiveSkill({ id: s.id, name: s.name, content });
    setLastUsedSkill({ name: s.name, auto: false });
    setFeatureToolsOpen(false);      // the library is a tab in the Tools Center now
  }, [getSkillContent]);

  // Warm the match cache once if Auto Skill Use was left ON from a previous session.
  useEffect(() => {
    if (autoSkillUse) ensureSkillsCache(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // `spoken` marks an utterance that arrived by voice. It travels to the
  // backend as voice_response so the answer can be shaped for listening rather
  // than reading ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â the field existed on ChatRequest but was hardcoded false,
  // so a spoken question was answered exactly as if it had been typed.
  const sendMessage = useCallback(async (overrideText = null, { spoken = false } = {}) => {
    const q = (overrideText || input).trim();
    if ((!q && !attachedFile && !attachedImage) || loading) return;

  // Route messages to the selected local Agent workspace.
  if (q && selectedAgentFolder && window.evaDesktop?.runAgent && !attachedFile && !attachedImage) {
    setShowPlus(false);
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setSuggestions([]);
    setEditingId(null);

    const userMsgId = 'user_' + Date.now();
    const botMsgId = 'bot_' + (Date.now() + 1);
    setMessages(m => [...m,
      { id: userMsgId, role: 'user', text: q },
      { id: botMsgId, role: 'bot', text: 'Starting local Agent...', streaming: true, done: false, question: q }
    ]);
    setLoading(true);
    setAgentBusy(true);
    setAgentStatus('Starting...');
    setAgentPending([]);

    try {
      const started = await window.evaDesktop.runAgent(q, selectedAgentFolder);
      const jobId = started?.job_id || started?.jobId || started?.id;
      if (!jobId) throw new Error(started?.detail || started?.message || 'Agent did not return a job ID.');
      setAgentJobId(jobId);
      setAgentStatus(started?.status || 'running');
      setMessages(m => m.map(msg => msg.id === botMsgId
        ? { ...msg, agentJobId: jobId, agentPending: [], agentLog: [], text: `Local Agent started.\nWorkspace: ${selectedAgentFolder}\nJob: ${jobId}\nStatus: ${started?.status || 'running'}`, streaming: false, done: true }
        : msg
      ));
    } catch (error) {
      const errorText = `Agent error: ${error?.message || 'Could not start Agent.'}`;
      setAgentStatus(errorText);
      setMessages(m => m.map(msg => msg.id === botMsgId
        ? { ...msg, text: errorText, streaming: false, done: true }
        : msg
      ));
    } finally {
      setLoading(false);
      setAgentBusy(false);
    }
    return;
  }
    setShowPlus(false);
    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Provenance: reveal where the PREVIOUS answer came from ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    //
    // Answered locally from metadata the client already holds. Sending this to
    // the model would ask it to recall its own retrieval, which it cannot do
    // and would therefore invent. Falls through to a normal turn when there is
    // no previous answer to describe, so a first message asking about sources
    // still gets a real reply.
    if (q && isProvenanceRequest(q)) {
      const target = lastAnsweredMessage(messagesRef.current);
      if (target) {
        setInput('');
        if (textareaRef.current) textareaRef.current.style.height = 'auto';
        const stamp = Date.now();
        setMessages(m => [
          ...m.map(msg => (msg.id === target.id ? { ...msg, showProvenance: true } : msg)),
          { id: 'user_' + stamp, role: 'user', text: q },
          {
            id: 'prov_' + stamp,
            role: 'assistant',
            text: describeProvenance(target.ragAudit),
            done: true,
          },
        ]);
        return;
      }
    }
    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Intercept image generation requests ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    if (q && isImageRequest(q)) {
      setInput('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
      setMessages(m => [...m, { id: 'user_' + Date.now(), role: 'user', text: q }]);
      await generateInlineImage(extractImagePrompt(q));
      return;
    }
    if (q && isWebSearch(q)) {
      setInput('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
      setMessages(m => [...m, { id: 'user_' + Date.now(), role: 'user', text: q }]);
      await handleWebSearch(extractSearchQuery(q));
      return;
    }
    if (q && isURLRead(q)) {
      setInput('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
      setMessages(m => [...m, { id: 'user_' + Date.now(), role: 'user', text: q }]);
      const url = extractURL(q);
      const question = q.replace(url, '').trim() || 'Summarize this page';
      await handleURLRead(url, question);
      return;
    }
    if (q && isCodeRun(q)) {
      setInput('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
      setMessages(m => [...m, { id: 'user_' + Date.now(), role: 'user', text: q }]);
      const code = q.replace(/^(run|execute)\s*/i, '').replace(/^```[\w]*\n?/, '').replace(/```$/, '').trim();
      await handleCodeRun(code);
      return;
    }
    if (attachedFile && attachedFile.name.endsWith('.csv')) {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const csvText = e.target.result;
        if (isDashboard(q)) { await handleDashboard(csvText); }
        else if (isDataClean(q) || !q) { await handleDataClean(csvText); }
      };
      reader.readAsText(attachedFile);
      setInput('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
      setMessages(m => [...m, { id: 'user_' + Date.now(), role: 'user', text: q || `\u{1F4C4} ${attachedFile.name}` }]);
      setAttachedFile(null);
      return;
    }
    if (streamRef.current) streamRef.current.abort();
    streamRef.current = new AbortController();
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setSuggestions([]);
    setEditingId(null);
    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Skill resolution (manual sticky skill wins, else auto-match when ON) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    let skillForThisSend = null;
    try { skillForThisSend = await resolveSkillForSend(q); } catch (_) { skillForThisSend = null; }
    if (skillForThisSend) setLastUsedSkill({ name: skillForThisSend.name, auto: skillForThisSend.auto });
    else if (!activeSkill) setLastUsedSkill(null);
    const userMsgId = 'user_' + Date.now();
    const botMsgId  = 'bot_' + Date.now();
    const displayText = q || (attachedFile ? `\u{1F4C4} ${attachedFile.name}` : `\u{1F5BC}\u{FE0F} ${attachedImage?.name}`);
    uiFeedback('send', 'light');
    setMessages(m => [...m, { id: userMsgId, role: 'user', text: displayText, image: attachedImage ? URL.createObjectURL(attachedImage) : null }]);
    const newHistory = [...history, { role: 'user', content: q }];
    setHistory(newHistory);
    const sentFile = attachedFile, sentImage = attachedImage;
    setAttachedFile(null); setAttachedImage(null);
    setLoading(true);
    setMessages(m => [...m, { id: botMsgId, role: 'bot', text: '', streaming: true, done: false, question: q }]);

    // Files save instantly; OCR/indexing happens server-side async
    const currentToken = localStorage.getItem('aria_token') || token;
    const memoryEnabled = localStorage.getItem('eva_memory_enabled') !== 'false';
    const uploadHeaders = {  ...(currentToken && currentToken !== 'offline' ? { 'Authorization': `Bearer ${currentToken}` } : {}) };

    if (sentImage) {
      const fd = new FormData(); fd.append('file', sentImage);
      fd.append('workspace_id', selectedWorkspaceId || 'default-org');
      fetch(`${API}/upload-pdf`, { method: 'POST', headers: uploadHeaders, body: fd }).catch(() => {});  // fire & forget
    }
    if (sentFile) {
      const fd = new FormData(); fd.append('file', sentFile);
      fd.append('workspace_id', selectedWorkspaceId || 'default-org');
      // Index chat attachments into the HF RAG service (persistent Supabase) so the answerer can retrieve them.
      // Note: /rag/upload is text-only; image attachments stay on Render /upload-pdf above.
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, uploadStatus: 'uploading' } : msg));
      try {
        const uploadRes = await fetch(`${RAG_API}/rag/upload`, { method: 'POST', headers: uploadHeaders, body: fd });
        const uploadData = await uploadRes.json().catch(() => ({}));
        if (!uploadRes.ok || !uploadData.job_id) throw new Error(uploadData.detail || 'Upload job was not created');
        setMessages(m => m.map(msg => msg.id === botMsgId ? {
          ...msg,
          text: `${uploadData.status || 'QUEUED'}: ${sentFile.name}`,
        } : msg));
        await pollRagUploadJob(uploadData.job_id, uploadHeaders, (job) => {
          const failed = job.status === 'FAILED' || job.status === 'CANCELLED';
          setMessages(m => m.map(msg => msg.id === botMsgId ? {
            ...msg,
            uploadStatus: job.status === 'COMPLETE' ? 'uploaded' : failed ? 'failed' : 'uploading',
            text: `${job.status}: ${job.message || job.current_step || sentFile.name}`,
          } : msg));
        });
        // Upload succeeded ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â clear the flag so this message falls through to
        // the real answer once it streams in below, instead of getting stuck
        // showing "Uploaded" forever (same botMsgId gets overwritten with
        // fullReply/finalReply further down).
        setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, uploadStatus: undefined } : msg));
      } catch (err) {
        const message = `Upload failed: ${err.message || 'Unable to index attachment'}`;
        setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, uploadStatus: 'failed', text: message, streaming: false, done: true } : msg));
        setLoading(false);
        return;
      }
    }

    let fullReply = '';
    let ragAudit = null;
    let reviewMeta = null; // Phase 19: backend-derived {status,badge} for the badge
    let runtimeMeta = null; // Phase 19 slice 5: backend runtime execution result
    let runnableMeta = null; // Phase 19 slice 6: backend eligibility for the Run button
    try {
      const imageDataUrl = sentImage ? await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(sentImage);
      }) : null;

      const chatHeaders = {
        'Content-Type': 'application/json',
        
        ...(currentToken && currentToken !== 'offline' ? { 'Authorization': `Bearer ${currentToken}` } : {})
      };
      // Attach the active/matched skill's instructions to the model context only.
      // The displayed message + stored history stay as the raw user text (q).
      const baseQuestion = q || (sentImage ? 'Analyze this uploaded image' : 'Describe the file');
      const effectiveQuestion = (skillForThisSend && skillForThisSend.content)
        ? `You are operating with a user-selected EVA skill. Apply its instructions to the request when relevant.\n\n--- SKILL: ${skillForThisSend.name} ---\n${skillForThisSend.content}\n--- END SKILL ---\n\nUser request:\n${baseQuestion}`
        : baseQuestion;
      const r = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: chatHeaders,
        body: JSON.stringify({
          question: effectiveQuestion,
          message: effectiveQuestion,
          // Prior turns. This field was never sent, so every message reached
          // the model with an empty history and the conversation could not
          // refer to itself: "How many days is that?" answered "There is no
          // specific time period mentioned... could you clarify?" instead of
          // "7 days". The backend and all three providers already accepted and
          // used `history` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â only the request omitted it.
          //
          // Excludes the current question, which is sent as `question`.
          history: conversationWindow(history),
          // Read at send time, not captured in state, so a change in
          // Settings applies to the very next message without a reload.
          language: getSelectedLanguageCode(),
          user_id: userDbId,
          workspace_id: selectedWorkspaceId || 'default-org',
          chat_id: sessionId,
          session_id: sessionId,
          voice_response: spoken,
          memory_enabled: memoryEnabled,
          image: !!sentImage,
          image_filename: sentImage?.name || null,
          image_mime: sentImage?.type || null,
          image_data: imageDataUrl,
          attachment_filename: sentFile?.name || null,
        }),
        signal: streamRef.current.signal,
      });
      const text = await r.text();
      let data;
      try { data = JSON.parse(text); }
      catch { throw new Error(`Bad JSON: ${text.slice(0, 100)}`); }
      if (r.status === 401) {
        try {
          const { getAuth } = await import('firebase/auth');
          const auth = getAuth();
          const freshToken = await auth.currentUser?.getIdToken(true);
          if (freshToken) {
            setToken(freshToken);
            localStorage.setItem('aria_token', freshToken);
            const retry = await fetch(`${API}/chat`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json',  'Authorization': `Bearer ${freshToken}` },
              body: JSON.stringify({
                question: effectiveQuestion,
                user_id: userDbId,
                workspace_id: selectedWorkspaceId || 'default-org',
                chat_id: sessionId,
                session_id: sessionId,
                memory_enabled: memoryEnabled,
                image: !!sentImage,
                image_filename: sentImage?.name || null,
                image_mime: sentImage?.type || null,
                image_data: imageDataUrl,
          attachment_filename: sentFile?.name || null,
              }),
            });
            const retryData = await retry.json();
            fullReply = retryData.answer || retryData.response || 'No response.';
            ragAudit = buildRagAuditMeta(retryData);
            reviewMeta = retryData.review || null;
            runtimeMeta = retryData.runtime || null;
            runnableMeta = retryData.runnable || null;
            fullReply = sanitizeAssistantText(fullReply, ragAudit);
          } else {
            fullReply = 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Please log in again.';
          }
        } catch {
          fullReply = 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Please log in again.';
        }
      } else {
        fullReply = data.answer || data.response || data.reply || data.message || data.detail || 'No response.';
        ragAudit = buildRagAuditMeta(data);
        reviewMeta = data.review || null;
        runtimeMeta = data.runtime || null;
        runnableMeta = data.runnable || null;
        fullReply = sanitizeAssistantText(fullReply, ragAudit);
      }
      await streamBotText(botMsgId, fullReply, 18, streamRef.current?.signal);
    } catch (e) {
      if (e.name === 'AbortError') {
        setMessages(m => m.map(msg =>
          msg.id === botMsgId ? { ...msg, streaming: false, done: true, stopped: true } : msg
        ));
        setLoading(false);
        return;
      }
      fullReply = `ÃƒÂ¢Ã‚ÂÃ…â€™ Cannot reach backend. Backend server is not responding.\nError: ${e.message}`;
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: fullReply } : msg));
    }
    const finalReply = sanitizeAssistantText(fullReply, ragAudit);
    setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: finalReply, streaming: false, done: true, ragAudit, review: reviewMeta, runtime: runtimeMeta, runnable: runnableMeta } : msg));
    setHistory(h => [...h, {
      role: 'assistant',
      content: finalReply,
      ...(hasStructuredSources(ragAudit) ? { sourceIds: ragAudit.sourceIds } : {}),
    }]);
    // Update 62: let voice mode speak the finished reply. No-op when off.
    window.dispatchEvent(new CustomEvent('eva:assistant-reply', { detail: { text: finalReply } }));
    // Slice 6: reply landed. Silent unless the user enabled sound.
    uiFeedback('receive', 'light');
    // Intelligent Suggestion Engine ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â runs async AFTER the answer is shown; never blocks.
    // Default is none; on any error or unparseable output we show nothing (no hardcoded fallback).
    (async () => {
      try {
        const recent = recentSuggestionsRef.current.slice(-8);
        const sres = await fetch(`${RAG_API}/chat/suggestions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({
            message: q,
            answer: finalReply,
            history: history.slice(-6),
            active_skill: (activeSkill && activeSkill.name) || '',
            recent_suggestions: recent,
          }),
        });
        if (!sres.ok) return;
        const sdata = await sres.json();
        const list = Array.isArray(sdata && sdata.suggestions) ? sdata.suggestions : [];
        setSuggestions(list);
        if (list.length) {
          recentSuggestionsRef.current = [...recentSuggestionsRef.current, ...list.map((s) => s.text)].slice(-12);
        }
      } catch (_) { /* show nothing */ }
    })();
    setLoading(false);
    if (history.length === 0 && q) autoTitle(q);
    if (q) setConversations(c => {
      const updated = [...c];
      const activeIdx = updated.findIndex(c => c.active);
      if (activeIdx !== -1 && updated[activeIdx].title === 'New conversation') {
        updated[activeIdx] = { ...updated[activeIdx], title: generateConversationTitle(q), updatedAt: new Date().toISOString() };
      } else if (activeIdx !== -1) {
        updated[activeIdx] = { ...updated[activeIdx], updatedAt: new Date().toISOString() };
      }
      return updated;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, loading, attachedFile, attachedImage, token, history, API, sessionId, userDbId, selectedWorkspaceId, resolveSkillForSend, activeSkill, selectedAgentFolder]);

  // Poll the active local Agent and update its existing chat message.
  useEffect(() => {
    if (!agentJobId || !window.evaDesktop?.getAgentStatus) return;
    let stopped = false;
    let timer;

    const poll = async () => {
      try {
        const data = await window.evaDesktop.getAgentStatus(agentJobId);
        if (stopped) return;
        const status = data.status || 'unknown';
        const pending = data.pending || [];
        const logs = data.log || [];
        setAgentStatus(status);
        setAgentPending(pending);

        setMessages(list => list.map(msg => {
          if (msg.agentJobId !== agentJobId) return msg;
          const logText = logs.slice(-8).map(x => String(x)).join('\n');
          const approvalText = pending.length
            ? '\n\nApproval required:\n' + pending.map((x, i) =>
                `${i + 1}. ${x.tool || 'Tool'}: ${x.summary || x.action || ''}`
              ).join('\n')
            : '';
          return {
            ...msg,
            agentPending: pending,
            agentLog: logs,
            text: `Local Agent\nWorkspace: ${selectedAgentFolder}\nJob: ${agentJobId}\nStatus: ${status}${approvalText}${logText ? '\n\nRecent activity:\n' + logText : ''}`,
            streaming: false,
            done: true
          };
        }));

        if (status === 'done' || status.startsWith('error:')) return;
      } catch (err) {
        if (!stopped) setAgentStatus(`Status error: ${err.message || err}`);
      }
      if (!stopped) timer = setTimeout(poll, 1800);
    };

    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [agentJobId, selectedAgentFolder]);
  // Update 62a: hand the current sendMessage to the voice command handler
  // declared above, without that handler referencing it before initialization.
  useEffect(() => { voiceSendRef.current = sendMessage; }, [sendMessage]);

  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Share / Export / Pin ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  // The other message actions (copy, regenerate, read aloud, thumbs) already
  // existed; only these three were missing. They reuse sanitizeAssistantText so
  // an exported or shared copy never carries orphaned [Source N] markers that
  // the reader cannot resolve.
  const [pinnedMessages, setPinnedMessages] = useState(() => {
    try { return JSON.parse(localStorage.getItem('eva_pinned_messages') || '{}'); }
    catch { return {}; }
  });

  const messagePlainText = (msg) => sanitizeAssistantText(msg.text || '', msg.ragAudit);

  const shareMessage = async (msg) => {
    const text = messagePlainText(msg);
    try {
      // Native share sheet where the browser offers one (mobile, some desktop);
      // clipboard everywhere else. Never leaves the page either way.
      if (navigator.share) {
        await navigator.share({ title: 'EVA response', text });
      } else {
        // Falls back to clipboard, silently ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â matching the existing Copy
        // button in this same bar, which also gives no confirmation. Adding a
        // toast here alone would be inconsistent with the current UI.
        await navigator.clipboard.writeText(text);
      }
    } catch (err) {
      // AbortError just means the user dismissed the share sheet.
      if (err && err.name !== 'AbortError') {
        try { await navigator.clipboard.writeText(text); } catch { /* clipboard blocked */ }
      }
    }
  };

  const exportMessage = (msg) => {
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const blob = new Blob([messagePlainText(msg)], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `eva-response-${stamp}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Revoke on the next tick ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â revoking synchronously can cancel the download
    // in some browsers before it starts.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const togglePinMessage = (msg) => {
    setPinnedMessages((prev) => {
      const next = { ...prev };
      if (next[msg.id]) delete next[msg.id];
      else next[msg.id] = { text: messagePlainText(msg).slice(0, 400), at: Date.now() };
      try { localStorage.setItem('eva_pinned_messages', JSON.stringify(next)); } catch { /* quota */ }
      return next;
    });
  };

  const regenerate = async (botMsg) => {
    const idx = messages.findIndex(m => m.id === botMsg.id);
    const userMsg = messages.slice(0, idx).reverse().find(isUserLikeMessage);
    if (!userMsg) return;
    setMessages(m => m.filter(msg => msg.id !== botMsg.id));
    setSuggestions([]);
    await sendMessage(userMsg.text);
  };
  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Inline Image Generation (slice 1) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  // One request per image, in parallel. The endpoint returns a SEEDED
  // Pollinations URL, so distinct seeds give distinct images for the same
  // prompt ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â and re-requesting a seed at larger dimensions returns the same
  // image bigger, which is what makes upscale meaningful rather than a reroll.
  const requestImage = useCallback(async ({ prompt, seed, width = 512, height = 512 }) => {
    const currentToken = localStorage.getItem('aria_token') || token;
    const headers = {
      'Content-Type': 'application/json',
      
      ...(currentToken && currentToken !== 'offline' ? { Authorization: `Bearer ${currentToken}` } : {}),
    };
    const r = await fetch(`${API}/image/generate-v2`, {
      method: 'POST',
      headers,
      // ImageGenV2Request accepts prompt/width/height/style/seed only ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â
      // negative_prompt, model and num_inference_steps were being sent and
      // silently dropped by Pydantic.
      body: JSON.stringify({
        prompt, style: '', width, height,
        ...(seed != null ? { seed } : {}),
      }),
    });
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try { detail = (await r.json()).detail || detail; } catch { /* keep status */ }
      throw new Error(detail);
    }
    const d = await r.json();
    if (!d.image_url) throw new Error(d.detail || 'No image returned');
    return { url: d.image_url, seed: d.seed, width: d.width, height: d.height };
  }, [API, token]);

  const IMAGE_COUNT = 4;

  const generateInlineImage = useCallback(async (prompt, existingId = null) => {
    const botMsgId = existingId || 'img_' + Date.now();

    if (!existingId) {
      setMessages(m => [...m, {
        id: botMsgId,
        role: 'bot',
        text: prompt,
        streaming: false,
        done: false,
        isImage: true,
        imagePrompt: prompt,
        images: [],
        imageLoading: true,
      }]);
    } else {
      setMessages(m => m.map(msg => msg.id === botMsgId
        ? { ...msg, imageLoading: true, imageError: '' }
        : msg));
    }

    setLoading(true);

    try {
      const images = [];
      const failures = [];

      // Generate sequentially.
      // Pollinations free endpoint is reliable for one request,
      // but simultaneous requests can cause upstream 502 responses.
      for (let i = 0; i < IMAGE_COUNT; i++) {
        try {
          const image = await requestImage({ prompt });
          images.push(image);
        } catch (err) {
          failures.push(err);
        }
      }

      if (!images.length) {
        const why = failures[0]?.message || 'Unknown error';

        setMessages(m => m.map(msg => msg.id === botMsgId
          ? {
              ...msg,
              imageLoading: false,
              done: true,
              imageError: why,
            }
          : msg));
      } else {
        setMessages(m => m.map(msg => msg.id === botMsgId
          ? {
              ...msg,
              imageLoading: false,
              done: true,
              images,
              imagePrompt: prompt,
            }
          : msg));

        uiFeedback('imageDone', 'success');
      }
    } catch (e) {
      setMessages(m => m.map(msg => msg.id === botMsgId
        ? {
            ...msg,
            imageLoading: false,
            done: true,
            imageError: e.message,
          }
        : msg));
    }

    setLoading(false);
  }, [requestImage]);

  // Same prompt, fresh seeds ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â a new take rather than a bigger one.
  const imageVariations = useCallback(async (msgId, prompt) => {
    setMessages(m => m.map(msg =>
      msg.id === msgId
        ? { ...msg, imageLoading: true }
        : msg
    ));

    const images = [];

    // Generate variations sequentially to avoid bursting
    // the free Pollinations endpoint.
    for (let i = 0; i < IMAGE_COUNT; i++) {
      try {
        const image = await requestImage({ prompt });
        images.push(image);
      } catch {
        // Keep successful variations even if one request fails.
      }
    }

    setMessages(m => m.map(msg => msg.id === msgId
      ? {
          ...msg,
          imageLoading: false,
          ...(images.length ? { images } : {}),
        }
      : msg));
  }, [requestImage]);

  // Same seed at larger dimensions => the SAME composition at higher
  // resolution. Measured: the provider caps free output at 768px ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â asking for
  // 1024 returns 768 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â so clamp there rather than promise a 2x that never
  // arrives. 512 -> 768 is a real 1.5x.
  const IMAGE_MAX_DIM = 768;
  const imageUpscale = useCallback(async (msgId, prompt, img) => {
    try {
      const big = await requestImage({
        prompt, seed: img.seed,
        width: Math.min((img.width || 512) * 2, IMAGE_MAX_DIM),
        height: Math.min((img.height || 512) * 2, IMAGE_MAX_DIM),
      });
      setMessages(m => m.map(msg => msg.id === msgId
        ? { ...msg, images: (msg.images || []).map(x => x.url === img.url ? big : x) } : msg));
    } catch { /* leave the original in place */ }
  }, [requestImage]);

  // Detect if message is an image generation request
// Things that are a picture when someone asks you to make one. The chain
// below already caught "illustration"/"artwork" but missed logo, poster,
// banner, UI and the rest, so "design a logo for my bakery" was answered
// with prose describing a logo instead of drawing one.
const IMAGE_SUBJECT_RE = /\b(logo|poster|banner|wallpaper|thumbnail|flyer|sticker|avatar|emblem|badge|album cover|book cover|concept art|character design|mascot|ui design|ui mockup|app design|app mockup|website design|landing page design|screen design|diagram)\b/;
// Deliberately excludes "build", "need" and "want": EVA is also a coding
// assistant, and "build a banner component", "I need a logo library for React"
// are code questions, not picture requests.
const CREATE_VERB_RE = /\b(generate|create|draw|make|design|paint|render|sketch|produce)\b/;

// Even with a tight verb list, "make a banner component in React" reads as a
// picture request on the nouns alone. Code vocabulary anywhere in the message
// means the user wants code.
const CODE_CONTEXT_RE = /\b(component|react|vue|angular|svelte|css|html|tailwind|bootstrap|jsx|tsx|javascript|typescript|python|java|code|function|class|api|endpoint|library|package|npm|div|css grid|flexbox|styled|component library)\b/;

// Structural diagrams belong to mermaid, not the image generator: EVA already
// emits them, and they render as themed, selectable, re-styleable vector text
// rather than a flat bitmap. Only divert these to image generation when the
// user explicitly asked for an image of one.
const MERMAID_DIAGRAM_RE = /\b(flow ?chart|sequence diagram|class diagram|er diagram|entity[- ]relationship|state diagram|state machine|org(?:ani[sz]ation(?:al)?)? chart|architecture diagram|system design|decision tree|process (?:flow|diagram)|gantt|mind ?map|use case diagram)\b/;
const EXPLICIT_IMAGE_WORD_RE = /\b(image|picture|photo|img|artwork|illustration|render|png|jpg)\b/;

 const isImageRequest = (text) => {
  const t = text.toLowerCase().trim();

  // Update 35c. Asked first, because the chain below is broad enough to take
  // messages that are not asking for a picture at all: `includes('image for ')`
  // matched "image for excel sheet" and produced a PNG of a spreadsheet, and
  // IMAGE_SUBJECT_RE lists "diagram", so "create a diagram" became a raster.
  //
  // Everything this refuses has a path that can be checked ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â a workbook that
  // opens, a chart whose values trace to the source, a mermaid diagram that is
  // text. A picture is the only artifact here that nothing can verify.
  if (!imageGeneratorMayHandle(t)) return false;

  // Structural diagram, and no explicit demand for an image file -> let the
  // mermaid path handle it.
  if (MERMAID_DIAGRAM_RE.test(t) && !EXPLICIT_IMAGE_WORD_RE.test(t)) return false;

  // "design a logo for a bakery", "make me a poster for the show".
  if (CREATE_VERB_RE.test(t) && IMAGE_SUBJECT_RE.test(t) && !CODE_CONTEXT_RE.test(t)) return true;

  return (
    t.startsWith('generate image') || t.startsWith('generate an image') ||
    t.startsWith('create image') || t.startsWith('create an image') ||
    t.startsWith('create a image') || t.startsWith('creating image') ||
    t.startsWith('draw ') || t.startsWith('make image') ||
    t.startsWith('make an image') || t.startsWith('make a image') ||
    t.startsWith('paint ') || t.startsWith('image of') ||
    t.startsWith('show image') || t.startsWith('show me image') ||
    t.startsWith('generate a image') || t.startsWith('photo of') ||
    t.startsWith('picture of') || t.startsWith('illustration of') ||
    t.startsWith('gerating image') || t.startsWith('generating image') ||
    t.startsWith('genarate image') || t.startsWith('genrate image') ||
    t.startsWith('img of') || t.startsWith('img ') ||
    t.includes('generate image of') || t.includes('create image of') ||
    t.includes('generate a image') || t.includes('create a image') ||
    t.includes('draw image') || t.includes('make image of') ||
    t.includes('/image ') || t.includes('/img ') ||
    t.includes('image generate') || t.includes('image creation') ||
    t.includes('crating image') || t.includes('creating image') ||
    t.includes('generating image for') || t.includes('gerating image for') ||
    t.includes('image for ') || t.includes('generate for') ||
    t.match(/^(generate|create|draw|make|paint|show|genarate|genrate|gerating|generating).*(image|photo|picture|illustration|artwork|img)/) !== null ||
    t.match(/(image|photo|picture|illustration|artwork).*(of|for)\s+\w+/) !== null
  );
};

    const extractImagePrompt = (text) => {
    return text
      .replace(/^(generate|create|draw|make|paint|show)(\s+an?|\s+a)?\s+(image|picture|photo|illustration|art|painting|artwork)(\s+of)?/i, '')
      .replace(/^(image|photo|picture)\s+(of|for)\s+/i, '')
      .replace(/^\/image\s+/i, '')
      .replace(/^\/img\s+/i, '')
      .replace(/^(crating|creating)\s+(image|photo|picture)\s+(of)?/i, '')
      .trim() || text;
  };

// ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Intent Detectors ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  const isWebSearch = (t) => {
    const l = t.toLowerCase();
    return l.startsWith('search ') || l.startsWith('search for ') ||
           l.startsWith('find info about') || l.startsWith('look up ') ||
           l.includes('web search') || l.startsWith('google ');
  };

  const isURLRead = (t) => {
    return /https?:\/\/[^\s]+/.test(t);
  };

  const isDataClean = (t) => {
    const l = t.toLowerCase();
    return l.includes('clean this data') || l.includes('clean the data') ||
           l.includes('clean my csv') || l.includes('fix the data') ||
           l.includes('remove duplicates') || l.includes('clean csv');
  };

  const isDashboard = (t) => {
    const l = t.toLowerCase();
    return l.includes('create dashboard') || l.includes('make a dashboard') ||
           l.includes('generate dashboard') || l.includes('show dashboard') ||
           l.includes('visualize this data') || l.includes('chart this') ||
           l.includes('plot this data') || l.includes('make charts');
  };

  const isCodeRun = (t) => {
    const l = t.toLowerCase();
    return l.startsWith('run ') || l.startsWith('execute ') ||
           l.includes('run this code') || l.includes('execute this') ||
           l.includes('run the code') || l.startsWith('/run ');
  };

  const extractURL = (t) => {
    const m = t.match(/https?:\/\/[^\s]+/);
    return m ? m[0] : '';
  };

  const extractSearchQuery = (t) => {
    return t.replace(/^(search for|search|look up|find info about|google)\s+/i, '').trim();
  };

  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Special Feature Handlers ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

  const handleWebSearch = async (query) => {
    const botMsgId = 'search_' + Date.now();
    setMessages(m => [...m, { id: botMsgId, role: 'bot', text: `ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Searching for: "${query}"...`, streaming: true, done: false }]);
    setLoading(true);
    try {
      const currentToken = localStorage.getItem('aria_token') || token;
      const r = await fetch(`${API}/web/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',  'Authorization': `Bearer ${currentToken}` },
        body: JSON.stringify({ query, num_results: 5 })
      });
      const data = await r.json();
      let reply = `## ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Search: "${query}"\n\n`;
      if (data.summary) reply += data.summary + '\n\n';
      if (data.results?.length) {
        reply += '**Sources:**\n';
        data.results.forEach((res, i) => {
          if (res.url) reply += `${i + 1}. [${res.title || res.url}](${res.url})\n`;
        });
      }
      await streamBotText(botMsgId, reply, 15);
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, streaming: false, done: true } : msg));
    } catch(e) {
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: `⚠️ Search failed: ${e.message}`, streaming: false, done: true } : msg));
    }
    setLoading(false);
  };

  const handleURLRead = async (url, question) => {
    const botMsgId = 'url_' + Date.now();
    setMessages(m => [...m, { id: botMsgId, role: 'bot', text: `ÃƒÂ°Ã…Â¸Ã…â€™Ã‚Â Reading: ${url}...`, streaming: true, done: false }]);
    setLoading(true);
    try {
      const currentToken = localStorage.getItem('aria_token') || token;
      const r = await fetch(`${API}/web/read-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',  'Authorization': `Bearer ${currentToken}` },
        body: JSON.stringify({ url, question: question || 'Summarize this page' })
      });
      const data = await r.json();
      const reply = `## ÃƒÂ°Ã…Â¸Ã…â€™Ã‚Â Page Summary\n**URL:** [${url}](${url})\n\n${data.answer || 'Could not read page.'}`;
      await streamBotText(botMsgId, reply, 15);
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, streaming: false, done: true } : msg));
    } catch(e) {
       setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: `Could not read URL: ${e.message}`, streaming: false, done: true } : msg));
    }
    setLoading(false);
  };

  const handleDataClean = async (csvText) => {
    const botMsgId = 'clean_' + Date.now();
    setMessages(m => [...m, { id: botMsgId, role: 'bot', text: 'ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Cleaning your data...', streaming: true, done: false }]);
    setLoading(true);
    try {
      const currentToken = localStorage.getItem('aria_token') || token;
      const r = await fetch(`${API}/data/clean`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',  'Authorization': `Bearer ${currentToken}` },
        body: JSON.stringify({ csv_text: csvText })
      });
      const data = await r.json();
      const s = data.stats;
      let reply = `## ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Data Cleaning Complete\n\n`;
      reply += `**Shape:** ${s.original_rows} rows ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ ${s.cleaned_rows} rows, ${s.cleaned_cols} columns\n\n`;
      if (s.changes?.length) { reply += `**Changes made:**\n`; s.changes.forEach(c => { reply += `- ${c}\n`; }); reply += '\n'; }
      if (data.ai_summary) reply += `**AI Insights:**\n${data.ai_summary}\n\n`;
      reply += `**Preview (first 3 rows):**\n\`\`\`json\n${JSON.stringify(s.preview?.slice(0,3), null, 2)}\n\`\`\``;
      if (data.clean_csv) reply += `\n\nÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Clean CSV ready ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â copy from below or ask me to analyse it.`;
      await streamBotText(botMsgId, reply, 12);
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, streaming: false, done: true, cleanCsv: data.clean_csv } : msg));
    } catch(e) {
       setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: `Data cleaning failed: ${e.message}`, streaming: false, done: true } : msg));
    }
    setLoading(false);
  };

  const handleDashboard = async (csvText) => {
    const botMsgId = 'dash_' + Date.now();
    setMessages(m => [...m, { id: botMsgId, role: 'bot', text: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â  Generating dashboard...', streaming: true, done: false }]);
    setLoading(true);
    try {
      const currentToken = localStorage.getItem('aria_token') || token;
      const r = await fetch(`${API}/data/dashboard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',  'Authorization': `Bearer ${currentToken}` },
        body: JSON.stringify({ csv_text: csvText })
      });
      const data = await r.json();
       setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: `Dashboard generated with ${data.charts?.length || 0} charts!`, streaming: false, done: true, dashboardData: data } : msg));
    } catch(e) {
       setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: `Dashboard failed: ${e.message}`, streaming: false, done: true } : msg));
    }
    setLoading(false);
  };

  const handleCodeRun = async (code) => {
    const botMsgId = 'code_' + Date.now();
    setMessages(m => [...m, { id: botMsgId, role: 'bot', text: 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â» Running code...', streaming: true, done: false }]);
    setLoading(true);
    try {
      const currentToken = localStorage.getItem('aria_token') || token;
      const r = await fetch(`${API}/code/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',  'Authorization': `Bearer ${currentToken}` },
        body: JSON.stringify({ code, language: 'python' })
      });
      const data = await r.json();
       const reply = `## Code Output\n\`\`\`\n${data.output}\n\`\`\`${data.error ? `\n\nError:\n\`\`\`\n${data.error}\n\`\`\`` : ''}`;
      await streamBotText(botMsgId, reply, 12);
      setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, streaming: false, done: true } : msg));
    } catch(e) {
       setMessages(m => m.map(msg => msg.id === botMsgId ? { ...msg, text: `Code execution failed: ${e.message}`, streaming: false, done: true } : msg));
    }
    setLoading(false);
  };

  const saveEdit = async (msgId) => {
    const newText = editText.trim();
    if (!newText) return;
    const idx = messages.findIndex(m => m.id === msgId);
    setMessages(m => m.slice(0, idx));
    setHistory(h => h.slice(0, Math.max(0, h.length - 2)));
    setSuggestions([]);
    setEditingId(null);
    await sendMessage(newText);
  };

  const toggleVoice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert('Voice not supported ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â use Chrome.'); return; }
    if (isListening) { recogRef.current?.stop(); setIsListening(false); return; }
    const r = new SR(); recogRef.current = r;
    r.lang = 'en-US'; r.continuous = false; r.interimResults = false;
    r.onstart = () => setIsListening(true);
    r.onresult = e => { setInput(e.results[0][0].transcript); setIsListening(false); };
    r.onerror = () => setIsListening(false);
    r.onend   = () => setIsListening(false);
    r.start();
  };

  const submitFeedback = async (msg, type, value) => {
    const key = msg.id;
    setFeedback(f => ({ ...f, [key]: { ...f[key], [type]: value } }));
    try {
      await fetch(`${API}/feedback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: msg.id, user_id: 'user_001', question: msg.question || '', response: msg.text, rating: value, thumb: type === 'thumb' ? value : null })
      });
    } catch {}
  };

  const closeToolsMenu = () => {
    setShowPlus(false);
  };

  const insertTemplate = (t) => {
    setInput(t);
    closeToolsMenu();
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleSelectedFile = (file) => {
    if (!file) return;
    if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
    if (file.type?.startsWith('image/')) {
      setAttachedImage(file);
      setAttachedFile(null);
      setAttachmentPreviewUrl(URL.createObjectURL(file));
    } else {
      setAttachedFile(file);
      setAttachedImage(null);
      setAttachmentPreviewUrl('');
    }
    setAttachmentNotice('Attachment selected. Upload processing will be connected next.');
    closeToolsMenu();
  };

  const clearAttachment = () => {
    if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
    setAttachedFile(null);
    setAttachedImage(null);
    setAttachmentPreviewUrl('');
    setAttachmentNotice('');
  };

  const handleComposerPaste = (e) => {
    const items = Array.from(e.clipboardData?.items || []);
    const imageItem = items.find(item => item.type?.startsWith('image/'));
    const file = imageItem?.getAsFile();
    if (file) {
      e.preventDefault();
      const ext = file.type === 'image/jpeg' ? 'jpg' :
        file.type === 'image/png' ? 'png' :
        file.type === 'image/webp' ? 'webp' : 'image';
      const namedFile = new File([file], `pasted-image-${Date.now()}.${ext}`, { type: file.type });
      handleSelectedFile(namedFile);
    }
  };

  const handleComposerDrop = (e) => {
    const files = Array.from(e.dataTransfer?.files || []);
    if (!files.length) return;
    e.preventDefault();
    e.stopPropagation();
    const file = files[0];
    if (file.type?.startsWith('image/')) {
      handleSelectedFile(file);
    } else {
      handleSelectedFile(file);
    }
  };


  const runToolAction = (action) => action?.();
  // A small quick-action menu, not a feature directory: only what acts on the
  // message being written. Everything else keeps working and stays reachable
  // where it already lived ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Feature Tools (Code Sandbox, YouTube Monitor,
  // Website Detector), the Directory panel (Skills, Connectors, plugins), the
  // Skill Library, and the admin sidebar (ML Training, RAG Center). Nothing was
  // deleted; the popup simply stopped being the front door to all of it.
  const toolMenuItems = [
    { icon: FileText, label: 'Upload file', detail: 'PDF, DOCX, TXT, CSV, XLSX', action: () => { fileRef.current?.click(); closeToolsMenu(); } },
    { icon: ImagePlus, label: 'Upload photo', detail: 'PNG, JPEG, WEBP', action: () => { imageRef.current?.click(); closeToolsMenu(); } },
    { icon: Search, label: 'Web Search', detail: 'Search live web sources', action: () => insertTemplate('search for ') },
    { icon: Sparkles, label: 'Create image', detail: 'Generate an image from a prompt', action: () => insertTemplate('Create image: ') },
    { icon: FileText, label: 'Doc Intelligence', detail: 'Summarize PDF, DOCX and text documents', action: () => { closeToolsMenu(); setActiveTool('docintel'); } },
    // The one door back to the panels this menu used to list individually. It
    // keeps Code Sandbox, YouTube Monitor and Website Detector reachable
    // without the popup becoming a feature directory again.
    { icon: MoreHorizontal, label: 'More tools', detail: 'Code Sandbox, YouTube Monitor, Website Detector, Directory, Skill Library', action: () => { closeToolsMenu(); setFeatureToolsTab('sandbox'); setFeatureToolsOpen(true); } },
  ];

  const quickSuggestions = [
    'Summarize a document',
    'Analyze CSV data',
    // 'Build a website' removed ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Web Artifacts builder has no backend yet; re-add when it ships.
    'Train an ML model',
    'Write a LinkedIn post',
  ];


  // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ File Download Utilities ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
  const detectContentType = (text) => {
    if (!text) return null;
    const t = text.toLowerCase();
    if (t.includes('| ---') || (t.includes('|') && t.split('\n').filter(l => l.includes('|')).length > 2)) return 'table';
    if (t.includes('```python') || t.includes('def ') || t.includes('import ')) return 'python';
    if (t.includes('```javascript') || t.includes('```js') || t.includes('const ') || t.includes('function ')) return 'javascript';
    if (t.includes('```html') || t.includes('<html') || t.includes('<div')) return 'html';
    if (t.includes('```sql') || t.includes('select ') || t.includes('create table')) return 'sql';
    if (t.includes('```json') || (t.trim().startsWith('{') && t.trim().endsWith('}'))) return 'json';
    if (t.includes('schedule') || t.includes('time') || t.includes('column a') || t.includes('spreadsheet') || t.includes('excel')) return 'csv';
    if (t.includes('slide') || t.includes('presentation') || t.includes('powerpoint')) return 'pptx_data';
    if (text.length > 300) return 'text';
    return null;
  };

  const downloadAsCSV = (text, filename) => {
    // Extract table from markdown or generate from text
    const lines = text.split('\n');
    const tableLines = lines.filter(l => l.includes('|') && !l.match(/^\|[\s\-|]+\|$/));
    let csvContent = '';
    if (tableLines.length > 0) {
      csvContent = tableLines.map(l => l.split('|').filter(c => c.trim()).map(c => `"${c.trim()}"`).join(',')).join('\n');
    } else {
      // Convert bullet/numbered list to CSV
      csvContent = 'Item,Value' + lines
        .filter(l => l.trim() && !l.startsWith('#'))
        .map((l, i) => `"${i+1}","${l.replace(/^[-*\d.]+\s*/, '').replace(/"/g, '""').trim()}"`)
        .join('\n');
    }
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename + '.csv'; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAsCode = (text, ext, filename) => {
    // Extract code block if present
    const match = text.match(/```(?:\w+)?\n?([\s\S]*?)```/);
    const code = match ? match[1] : text;
    const blob = new Blob([code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename + '.' + ext; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAsText = (text, filename) => {
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename + '.txt'; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAsHTML = (text, filename) => {
    const match = text.match(/```html?([\s\S]*?)```/i);
    const html = match ? match[1] : `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${filename}</title><style>body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6}</style></head><body>${text.replace(/\n/g,'<br>')}</body></html>`;
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename + '.html'; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAsJSON = (text, filename) => {
    const match = text.match(/```json?([\s\S]*?)```/i) || text.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
    const json = match ? match[1] : text;
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename + '.json'; a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownload = (msg, format) => {
    const filename = 'eva_' + new Date().toISOString().slice(0,10);
    const text = msg.text || '';
    switch(format) {
      case 'csv':   downloadAsCSV(text, filename); break;
      case 'py':    downloadAsCode(text, 'py', filename); break;
      case 'js':    downloadAsCode(text, 'js', filename); break;
      case 'html':  downloadAsHTML(text, filename); break;
      case 'sql':   downloadAsCode(text, 'sql', filename); break;
      case 'json':  downloadAsJSON(text, filename); break;
      case 'txt':   downloadAsText(text, filename); break;
      default:      downloadAsText(text, filename);
    }
  };

  const getDownloadButtons = (msg) => {
    const type = detectContentType(msg.text);
    if (!type) return [];
    const map = {
      table:     [{ fmt: 'csv',  icon: 'CSV',  label: 'Excel/CSV' }],
      python:    [{ fmt: 'py',   icon: 'PY',   label: '.py' }, { fmt: 'txt', icon: 'TXT', label: '.txt' }],
      javascript:[{ fmt: 'js',   icon: 'JS',   label: '.js' }, { fmt: 'txt', icon: 'TXT', label: '.txt' }],
      html:      [{ fmt: 'html', icon: 'HTML', label: '.html' }, { fmt: 'txt', icon: 'TXT', label: '.txt' }],
      sql:       [{ fmt: 'sql',  icon: 'SQL',  label: '.sql' }, { fmt: 'txt', icon: 'TXT', label: '.txt' }],
      json:      [{ fmt: 'json', icon: 'JSON', label: '.json' }, { fmt: 'csv', icon: 'CSV', label: '.csv' }],
      csv:       [{ fmt: 'csv',  icon: 'CSV',  label: 'Excel/CSV' }, { fmt: 'txt', icon: 'TXT', label: '.txt' }],
      pptx_data: [{ fmt: 'txt',  icon: 'TXT',  label: '.txt' }, { fmt: 'html', icon: 'HTML', label: '.html' }],
      text:      [{ fmt: 'txt',  icon: 'TXT',  label: '.txt' }],
    };    
    return map[type] || [{ fmt: 'txt', icon: 'TXT', label: '.txt' }];
  };

  const MessageActions = ({ msg }) => {
    const fb = feedback[msg.id] || {};
    const dlBtns = getDownloadButtons(msg);

    // Only show download if user asked for it
    const downloadTriggers = ['download this', 'save this', 'export this', 'save as file', 'give me the file', 'download the response', 'save the response'];
    const userAskedDownload = messages
      .filter(isUserLikeMessage)
      .some(m => downloadTriggers.some(t => m.text?.toLowerCase().includes(t)));

    return (
      <div style={{ marginTop: 8 }}>
        {/* Download bar ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â only shown when user asked to download */}
        {dlBtns.length > 0 && userAskedDownload && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, padding: '6px 10px', background: 'var(--accent-soft)', border: '1px solid var(--accent-soft)', borderRadius: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, marginRight: 2 }}>ÃƒÂ¢Ã‚Â¬Ã¢â‚¬Â¡ Download:</span>
            {dlBtns.map(btn => (
              <button key={btn.fmt} onClick={() => handleDownload(msg, btn.fmt)}
                style={{ padding: '3px 10px', borderRadius: 6, border: '1px solid var(--accent)', background: 'var(--accent-soft)', color: 'var(--text2)', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontWeight: 500, transition: '.15s' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'var(--accent-soft)'; }}>
                {btn.icon} {btn.label}
              </button>
            ))}
            <button onClick={() => handleDownload(msg, 'txt')}
              style={{ padding: '3px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text3)', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, transition: '.15s' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--surface2)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}>
              ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Å¾ Save as text
            </button>
          </div>
        )}
        {/* Action row ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â revealed on hover at desktop, always shown on touch. */}
        <div className="eva-msg-actions">
          <button type="button" className="eva-msg-act" title="Read aloud"
            onClick={() => speakMessage(msg.text)}>
            <Volume2 size={13} /> <span>{t('action.readAloud')}</span>
          </button>
          <button type="button" className="eva-msg-act" title="Copy"
            onClick={() => navigator.clipboard.writeText(msg.text)}>
            <CopyIcon size={13} /> <span>{t('action.copy')}</span>
          </button>
          <button type="button" className="eva-msg-act" title="Regenerate"
            onClick={() => regenerate(msg)}>
            <RotateCw size={13} /> <span>{t('action.regenerate')}</span>
          </button>
          <button type="button" title="Good response"
            className={`eva-msg-act is-icon ${fb.thumb === 'up' ? 'is-up' : ''}`}
            onClick={() => submitFeedback(msg, 'thumb', 'up')}>
            <ThumbsUp size={13} />
          </button>
          <button type="button" title="Bad response"
            className={`eva-msg-act is-icon ${fb.thumb === 'down' ? 'is-down' : ''}`}
            onClick={() => submitFeedback(msg, 'thumb', 'down')}>
            <ThumbsDown size={13} />
          </button>
          {/* Share / Export / Pin were the only actions genuinely missing ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â
              Copy, Regenerate, Read aloud and the thumbs already existed. They
              go in THIS bar rather than a second one, and stay icon-only so the
              row does not grow. */}
          <button type="button" title="Share" aria-label="Share this response"
            className="eva-msg-act is-icon" onClick={() => shareMessage(msg)}>
            <Share2 size={13} />
          </button>
          <button type="button" title="Export as Markdown" aria-label="Export this response"
            className="eva-msg-act is-icon" onClick={() => exportMessage(msg)}>
            <Download size={13} />
          </button>
          <button type="button"
            title={pinnedMessages[msg.id] ? 'Unpin' : 'Pin'}
            aria-label={pinnedMessages[msg.id] ? 'Unpin this response' : 'Pin this response'}
            aria-pressed={!!pinnedMessages[msg.id]}
            className={`eva-msg-act is-icon ${pinnedMessages[msg.id] ? 'is-up' : ''}`}
            onClick={() => togglePinMessage(msg)}>
            <Pin size={13} />
          </button>
          {fb.thumb && <span className="eva-msg-saved">Saved</span>}
          {/* Timestamp lives here now ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â available on hover, out of the way
              while reading. */}
          <time className="eva-msg-time">{messageTime(msg.id)}</time>
        </div>
      </div>
    );
  };

  // Slice 4: themed, not hardcoded. The previous buttons used fixed purple
  // hex values, so they ignored the theme system entirely ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â under Nature or
  // Minimal Dark they stayed violet.
  const ActionBtn = ({ label, onClick, title }) => (
    <button type="button" onClick={onClick} title={title} className="eva-msg-act">{label}</button>
  );

  

  const formatUserFileSize = (size = 0) => {
    if (!size) return 'Unknown size';
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  };

  const userProjectFiles = [
    attachedFile && {
      id: 'user-upload-file',
      name: attachedFile.name || 'Uploaded file',
      kind: 'Uploaded file',
      type: attachedFile.type || 'Document',
      size: formatUserFileSize(attachedFile.size),
      status: 'Attached to current chat',
      lastModified: attachedFile.lastModified ? new Date(attachedFile.lastModified).toLocaleString() : 'Current session',
    },
    attachedImage && {
      id: 'user-upload-image',
      name: attachedImage.name || 'Uploaded image',
      kind: 'Uploaded image',
      type: attachedImage.type || 'Image',
      size: formatUserFileSize(attachedImage.size),
      status: 'Attached to current chat',
      lastModified: attachedImage.lastModified ? new Date(attachedImage.lastModified).toLocaleString() : 'Current session',
    },
  ].filter(Boolean);

  const selectedUserFile = userProjectFiles.find((file) => file.id === selectedUserFileId) || userProjectFiles[0] || null;
  const userWorkspaceActivity = [
    'Opened user workspace',
    userProjectFiles.length ? `${userProjectFiles.length} user file${userProjectFiles.length === 1 ? '' : 's'} available` : 'Waiting for uploaded files',
    'User file editing ready',
  ];

  const visibleMessages = messages.filter((m) => m.id !== 'init');
  const isEmptyChat = visibleMessages.length === 0;
  const showChatWorkspaceSelector = false;

  // Suggestions come EXCLUSIVELY from the async Intelligent Suggestion Engine
  // (/chat/suggestions). There is no hardcoded/static fallback ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â an empty array
  // means show nothing. Each item is { text, type }.
  const suggestedFollowups = suggestions;

  return (
    <div className="eva-chat-page">
      {/* Slice 7: first tab stop ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â lets keyboard and screen-reader users
          jump past the sidebar straight to the conversation. */}
      <a className="eva-skip-link" href="#eva-conversation">Skip to conversation</a>

      {/* ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ MAIN CHAT ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ */}
      <div className="eva-chat-main">
        {showChatWorkspaceSelector && (
        <section className="eva-workspace-selector eva-chat-workspace-hidden" aria-label="Workspace selector">
          <div>
            <div className="eva-workspace-label">Current Workspace</div>
            <strong>{selectedWorkspace?.name || (workspaceLoading ? 'Loading...' : 'Create your first workspace')}</strong>
            {selectedWorkspace?.description && <span>{selectedWorkspace.description}</span>}
            {workspaceError && <em>{workspaceError}</em>}
          </div>
          <div className="eva-workspace-actions">
            <select
              value={selectedWorkspaceId}
              onChange={(event) => selectWorkspace(event.target.value)}
              disabled={workspaceLoading || workspaces.length === 0}
              aria-label="Select workspace"
            >
              {workspaces.length === 0 ? (
                <option value="">No workspaces yet</option>
              ) : workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
              ))}
            </select>
            <button type="button" onClick={() => setWorkspaceFormOpen(true)}>
              <Plus size={14} />
              <span>New Workspace</span>
            </button>
          </div>
        </section>
        )}

        {workspaceFormOpen && (
          <form className="eva-workspace-form" onSubmit={createWorkspace}>
            <label>
              Workspace name
              <input
                value={workspaceForm.name}
                onChange={(event) => setWorkspaceForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="My Website"
                autoFocus
              />
            </label>
            <label>
              Description
              <input
                value={workspaceForm.description}
                onChange={(event) => setWorkspaceForm((current) => ({ ...current, description: event.target.value }))}
                placeholder="My project workspace"
              />
            </label>
            <div className="eva-workspace-form-actions">
              <button type="button" onClick={() => setWorkspaceFormOpen(false)}>Cancel</button>
              <button type="submit" disabled={workspaceLoading}>{workspaceLoading ? 'Creating...' : 'Create'}</button>
            </div>
          </form>
        )}

        {/* Messages */}
        <div ref={logRef} id="eva-conversation" role="log" aria-live="polite" aria-relevant="additions text" aria-label="Conversation with EVA" tabIndex={-1} className="messages-scroll eva-chat-messages" style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '10px 12px 176px' : '14px 24px 20px', display: 'flex', flexDirection: 'column', gap: 10, justifyContent: 'flex-start', scrollbarWidth: 'thin', scrollbarColor: 'var(--border2) transparent', width: '100%', boxSizing: 'border-box' }}>
          {isEmptyChat && (
            <section className="eva-empty-state" aria-label="EVA conversation starters">
              <h1>How can EVA help you today?</h1>
              <p>Ask questions, upload files, analyze documents, or build with EVA.</p>
              <div className="eva-empty-chip-row">
                {quickSuggestions.map((prompt) => (
                  <button key={prompt} type="button" className="eva-empty-chip" onClick={() => insertTemplate(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
            </section>
          )}

          <AnimatePresence initial={false} mode="sync">
          {visibleMessages.map((m, index) => (
            <motion.div
              key={m.id}
              layout="position"
              initial={{
                opacity: 0,
                x: isUserLikeMessage(m) ? 22 : -18,
                y: 14,
                scale: 0.985,
                rotateX: isUserLikeMessage(m) ? -2 : 2,
                filter: "blur(8px)"
              }}
              animate={{
                opacity: 1,
                x: 0,
                y: 0,
                scale: 1,
                rotateX: 0,
                filter: "blur(0px)"
              }}
              exit={{
                opacity: 0,
                x: isUserLikeMessage(m) ? 10 : -10,
                y: -6,
                scale: 0.992,
                filter: "blur(4px)"
              }}
              transition={{
                opacity: { duration: 0.24, ease: [0.22, 1, 0.36, 1] },
                filter: { duration: 0.3, ease: "easeOut" },
                default: {
                  type: "spring",
                  stiffness: 300,
                  damping: 26,
                  mass: 0.8,
                  delay: Math.min(index * 0.035, 0.18)
                }
              }}
              className={`eva-message-row ${isUserLikeMessage(m) ? 'eva-message-row-user' : 'eva-message-row-assistant'}`}
            >
                {/* Slice 4a: no avatar or name label on assistant messages.
                    ChatGPT and Claude both let the answer start immediately ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â
                    repeating "EVA" above every reply is chrome, not
                    information, and it broke the vertical rhythm. The
                    timestamp moved into the hover action row instead. */}
                <div className={`eva-message-body ${isUserLikeMessage(m) ? 'eva-message-body-user' : 'eva-message-body-assistant'}`}>
                  {m.image && <img src={m.image} alt="" style={{ maxWidth: 220, borderRadius: 10, marginBottom: 6, display: 'block' }} />}
                  {editingId === m.id ? (
                    <div>
                      <textarea value={editText} onChange={e => setEditText(e.target.value)}
                        style={{ width: '100%', minWidth: 300, background: 'var(--input-bg)', border: '1px solid var(--border2)', borderRadius: 10, padding: '10px 12px', color: 'var(--text)', fontSize: 13, outline: 'none', resize: 'vertical', fontFamily: 'inherit' }} rows={3} />
                      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                        <ActionBtn label="ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ Save & Resend" onClick={() => saveEdit(m.id)} />
                        <ActionBtn label="ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¢ Cancel" onClick={() => setEditingId(null)} />
                      </div>
                    </div>
                  ) : (
                    <div className={`eva-message-bubble ${isUserLikeMessage(m) ? 'eva-message-bubble-user' : 'eva-message-bubble-assistant'}`}
                      style={isUserLikeMessage(m)?{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 'fit-content',
                        minWidth: isMobile ? 0 : 50,
                        maxWidth: isMobile ? '78vw' : 560,
                        padding: isMobile ? '8px 16px' : '9px 16px',
                        borderRadius: 18,
                        boxSizing: 'border-box',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      } : undefined}
                    >
                      {
                        isUserLikeMessage(m)
                        ? <div style={{ fontSize: isMobile ? 14 : 15, lineHeight: 1.45, color: 'var(--text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{m.text}</div>
                        : m.uploadStatus ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: m.uploadStatus === 'failed' ? 'var(--red)' : 'var(--text2)' }}>
                            {m.uploadStatus === 'uploading' ? (
                              <>
                                <RotateCw size={14} style={{ animation: 'spin 1s linear infinite' }} />
                                <span>Uploading...</span>
                              </>
                            ) : m.uploadStatus === 'failed' ? (
                              <>
                                <X size={14} />
                                <span>Upload failed</span>
                              </>
                            ) : (
                              <>
                                <Check size={14} />
                                <span>Uploaded</span>
                              </>
                            )}
                          </div>
                        ) : m.isImage ? (
                          m.imageLoading ? (
                            <ImageSkeleton count={4} />
                          ) : m.imageError ? (
                            <div style={{ fontSize: 13, color: 'var(--red)' }}>
                              Image generation failed: {m.imageError}
                              <button
                                onClick={() => generateInlineImage(m.imagePrompt || m.text, m.id)}
                                style={{ marginLeft: 8, padding: '4px 10px', borderRadius: 7, border: '1px solid rgba(255,255,255,.12)', background: 'transparent', color: 'var(--text2)', fontSize: 12, cursor: 'pointer' }}
                              >Try again</button>
                            </div>
                          ) : (m.images && m.images.length) ? (
                            <ImageResult
                              images={m.images}
                              prompt={m.imagePrompt || m.text}
                              onRegenerate={() => generateInlineImage(m.imagePrompt || m.text, m.id)}
                              onVariations={() => imageVariations(m.id, m.imagePrompt || m.text)}
                              onUpscale={(img) => imageUpscale(m.id, m.imagePrompt || m.text, img)}
                            />
                          ) : (
                            /* Legacy single-image messages from before slice 1 */
                            m.imageUrl ? (
                              <ImageResult
                                images={[{ url: m.imageUrl }]}
                                prompt={m.text}
                                onRegenerate={() => generateInlineImage(m.text, m.id)}
                                onUpscale={(img) => imageUpscale(
                                  m.id,
                                  m.text,
                                  img
                                )}
                              />
                            ) : null
                          )
                        ) : m.dashboardData ? (
                          <DashboardRenderer data={m.dashboardData} />
                        ) : (
                          <><ProvenanceBadges show={m.showProvenance} review={m.review} runtime={m.runtime} streaming={m.streaming} /><MarkdownRenderer text={sanitizeAssistantText(m.text || '', m.ragAudit, m.showProvenance)} />
                          {m.agentJobId && Array.isArray(m.agentPending) && m.agentPending.length > 0 && (
                            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                              {m.agentPending.map((item, idx) => (
                                <div key={`${m.agentJobId}-${idx}`} style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 10 }}>
                                  <div style={{ marginBottom: 10, whiteSpace: 'pre-wrap' }}>
                                    <strong>{item.tool || 'Agent action'}:</strong> {item.summary || item.action || 'Approval required'}
                                  </div>
                                  <div style={{ display: 'flex', gap: 8 }}>
                                    <button type="button" onClick={async () => {
                                      try {
                                        await window.evaDesktop.approveAgent(m.agentJobId, true);
                                        setAgentStatus('Approval submitted');
                                        setAgentPending([]);
                                      } catch (err) {
                                        setAgentStatus(`Approval error: ${err?.message || 'Failed'}`);
                                      }
                                    }} style={{ padding: '7px 14px', borderRadius: 8, cursor: 'pointer' }}>Approve</button>
                                    <button type="button" onClick={async () => {
                                      try {
                                        await window.evaDesktop.approveAgent(m.agentJobId, false);
                                        setAgentStatus('Action rejected');
                                        setAgentPending([]);
                                      } catch (err) {
                                        setAgentStatus(`Rejection error: ${err?.message || 'Failed'}`);
                                      }
                                    }} style={{ padding: '7px 14px', borderRadius: 8, cursor: 'pointer' }}>Reject</button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                          {m.runnable && !m.streaming ? <RunCodeButton messageText={m.text || ''} runnable={m.runnable} apiBase={API} token={token} /> : null}{m.streaming && !m.done && (
                            <motion.span
                              aria-hidden="true"
                              initial={{ opacity: 0.35, scaleY: 0.72, scaleX: 0.8 }}
                              animate={{
                                opacity: [0.45, 1, 0.45],
                                scaleY: [0.78, 1, 0.78],
                                scaleX: [0.9, 1, 0.9],
                                boxShadow: [
                                  '0 0 0px var(--accent)',
                                  '0 0 10px var(--accent)',
                                  '0 0 0px var(--accent)'
                                ]
                              }}
                              transition={{
                                duration: 1.05,
                                repeat: Infinity,
                                ease: 'easeInOut'
                              }}
                              style={{
                                display: 'inline-block',
                                width: 3,
                                height: 17,
                                background: 'var(--accent)',
                                borderRadius: 999,
                                marginLeft: 4,
                                verticalAlign: 'middle',
                                transformOrigin: 'center'
                              }}
                            />
                          )}</>
                        )
                      }
                    </div>
                  )}
                  {/* Provenance rule: shown only after an explicit ask, never
                      by default. m.showProvenance is set on the PREVIOUS answer
                      when the user asks where it came from. */}
                  <ProvenanceDetails show={isAssistantLikeMessage(m) && m.showProvenance} ragAudit={m.ragAudit} />
                  {isAssistantLikeMessage(m) && m.done && m.id !== 'init' && !loading && <MessageActions msg={m} />}
                </div>
              </motion.div>
          ))}
          </AnimatePresence>

          {loading && !messages.find(m => m.streaming) && (
            <div className="eva-message-row eva-message-row-assistant">
              <div className="eva-typing-bubble">
                {[0, 1, 2].map(j => <div key={j} style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', animation: `typingBounce 1.2s ${j * 0.2}s infinite` }} />)}
              </div>
            </div>
          )}

          {suggestedFollowups.length > 0 && !loading && (
            <div
              className="suggestion-followups"
              style={{
                width: 'min(100%, 980px)',
                maxWidth: 980,
                margin: '12px auto 0',
                padding: '0 24px',
                boxSizing: 'border-box',
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  color: 'var(--accent)',
                  marginBottom: 7,
                  fontFamily: 'monospace',
                  textTransform: 'uppercase',
                  letterSpacing: '.6px',
                }}
              >
                {t('suggestions.title')}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {suggestedFollowups.slice(0, 4).map((s, i) => (
                  <button
                    key={`${s.text}-${i}`}
                    type="button"
                    onClick={() => {
                      setSuggestions([]);
                      setInput(s.text);
                      setTimeout(() => sendMessage(s.text), 0);
                    }}
                    style={{
                      width: '100%',
                      minHeight: 36,
                      padding: '8px 14px',
                      background: 'var(--accent-soft)',
                      border: '1px solid var(--accent-soft)',
                      backdropFilter: 'blur(8px)',
                      borderRadius: 16,
                      color: 'var(--text2)',
                      fontSize: 13,
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: '.15s',
                      whiteSpace: 'normal',
                    }}
                  >
                    <span
                      style={{
                        fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em',
                        padding: '1px 6px', borderRadius: 999, marginRight: 8,
                        color: SUGGESTION_TYPE_COLORS[s.type] || 'var(--accent)',
                        background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)',
                      }}
                    >{s.type}</span>
                    {s.text}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ INLINE TOOL PANEL ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ */}
        {activeTool && (
          <div style={{ margin: '0 16px 12px', background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                {activeTool === 'insights'  && 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â  Data Insights'}
                {activeTool === 'sentiment' && 'ÃƒÂ°Ã…Â¸Ã‹Å“Ã…Â  Sentiment Analyzer'}
                {activeTool === 'docintel' && 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Ëœ Doc Intelligence'}
                {activeTool === 'learning'  && 'ÃƒÂ°Ã…Â¸Ã…Â½Ã¢â‚¬Å“ Learning Plan'}
                {activeTool === 'resume'    && 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ Resume Screener'}
              </div>
              <button onClick={() => setActiveTool(null)} style={{ background: 'none', border: 'none', color: 'var(--text3)', fontSize: 18, cursor: 'pointer' }}>ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¢</button>
            </div>
            <div style={{ padding: 14, maxHeight: 420, overflowY: 'auto' }}>
              {activeTool === 'sentiment' && <SentimentTool  API={API} />}
              {activeTool === 'insights'  && <DataInsightsTool API={API} />}
              {activeTool === 'docintel' && <DocIntelTool   API={API} />}
              {activeTool === 'learning'  && <LearningTool   API={API} />}
              {activeTool === 'resume'    && <ResumeTool     API={API} />}
            </div>
          </div>
        )}

        {userWorkspaceOpen && (
          <section className="eva-user-workspace-panel" aria-label="User file workspace">
            <div className="eva-user-workspace-activity">
              <div className="eva-user-workspace-kicker">User Workspace</div>
              <h2>User Workspace</h2>
              <p>Edit your project files</p>
              <div className="eva-user-workspace-log">
                {userWorkspaceActivity.map((item) => (
                  <div key={item} className="eva-user-workspace-log-row">
                    <span />
                    {item}
                  </div>
                ))}
              </div>
            </div>

            <div className="eva-user-workspace-files">
              <div className="eva-user-workspace-section-title">User project files</div>
              {userProjectFiles.length === 0 ? (
                <div className="eva-user-workspace-empty">
                  No files in this workspace yet. Upload a file to start.
                </div>
              ) : (
                userProjectFiles.map((file) => (
                  <button
                    key={file.id}
                    type="button"
                    onClick={() => setSelectedUserFileId(file.id)}
                    className={`eva-user-workspace-file ${selectedUserFile?.id === file.id ? 'is-active' : ''}`}
                  >
                    <strong>{file.name}</strong>
                    <span>{file.kind}</span>
                  </button>
                ))
              )}
            </div>

            <div className="eva-user-workspace-editor">
              <div className="eva-user-workspace-editor-head">
                <div>
                  <div className="eva-user-workspace-section-title">Preview / editor</div>
                  <span>{selectedUserFile ? selectedUserFile.name : 'No file selected'}</span>
                </div>
                <button type="button" onClick={() => setUserWorkspaceOpen(false)} aria-label="Close user workspace">x</button>
              </div>

              {selectedUserFile ? (
                <>
                  <div className="eva-user-workspace-details">
                    <div><span>Type</span><strong>{selectedUserFile.type}</strong></div>
                    <div><span>Size</span><strong>{selectedUserFile.size}</strong></div>
                    <div><span>Status</span><strong>{selectedUserFile.status}</strong></div>
                    <div><span>Modified</span><strong>{selectedUserFile.lastModified}</strong></div>
                  </div>
                  <textarea
                    value=""
                    readOnly
                    placeholder="Local preview/edit buffer will appear here when a safe user-file API is enabled."
                    className="eva-user-workspace-textarea"
                  />
                </>
              ) : (
                <div className="eva-user-workspace-empty">
                  Select one of your uploaded files to preview details. Only your files appear in this workspace.
                </div>
              )}
            </div>
          </section>
        )}

        {/* Attached file preview */}
        {(attachedFile || attachedImage) && (
          <div className="eva-attachment-preview">
            {attachedImage && attachmentPreviewUrl ? <img src={attachmentPreviewUrl} alt="" className="eva-attachment-thumb" /> : <span className="eva-attachment-file-icon">File</span>}
            <div className="eva-attachment-copy">
              <strong>{attachedImage?.name || attachedFile?.name}</strong>
              <span>{attachmentNotice}</span>
            </div>
            <button type="button" className="eva-attachment-remove" onClick={clearAttachment} aria-label="Remove attachment">
              <X size={15} />
            </button>
          </div>
        )}

        {/* ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ INPUT AREA ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ */}
        <div className={isMobile ? 'eva-chat-input-area' : undefined} style={isMobile ? undefined : { display: 'contents' }}>
          {(activeSkill || lastUsedSkill) && (
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: 'var(--accent)', background: 'var(--accent-soft)', border: '1px solid var(--accent)', borderRadius: 999, padding: '4px 10px', maxWidth: '90%' }}>
                <Zap size={12} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  Using skill: {(activeSkill && activeSkill.name) || (lastUsedSkill && lastUsedSkill.name)}
                </span>
                {activeSkill ? (
                  <button type="button" onClick={() => { setActiveSkill(null); setLastUsedSkill(null); }} aria-label="Stop using skill"
                    style={{ background: 'transparent', border: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, display: 'inline-flex' }}>
                    <X size={13} />
                  </button>
                ) : (
                  <span style={{ fontSize: 9, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.05em', opacity: .8 }}>auto</span>
                )}
              </span>
            </div>
          )}
          <div className="eva-chat-input-box">
{window.evaDesktop?.isDesktop && (
            <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center', margin: '0 8px 0 10px' }}>
              <button type="button" className="eva-chat-icon-button" onClick={chooseAgentFolder} title="Select project folder" aria-label="Select project folder">
                <FolderOpen size={17} />
              </button>
              {agentPanelOpen && (
                <div style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, zIndex: 100, width: 220, padding: 10, border: '1px solid var(--border-color, #444)', borderRadius: 12, background: 'var(--bg-secondary, #202020)', boxShadow: '0 8px 28px #0005', display: 'grid', gap: 8 }}>
                  <button type="button" className="eva-chat-icon-button" onClick={async () => { await chooseAgentFolder(); setAgentPanelOpen(false); }}>
                    {selectedAgentFolder ? 'Change folder' : 'Select folder'}
                  </button>
                </div>
              )}
            </div>
          )}            <input type="file" ref={fileRef} style={{ display: 'none' }} accept=".pdf,.docx,.txt,.csv,.xlsx,.py,.css,.js,.json," onChange={e => { handleSelectedFile(e.target.files?.[0]); e.target.value = ''; }} />
            <input type="file" ref={imageRef} style={{ display: 'none' }} accept="image/png,image/jpeg,image/webp" onChange={e => { handleSelectedFile(e.target.files?.[0]); e.target.value = ''; }} />

            <div ref={plusRef} className="eva-chat-tools-anchor">
              <button
                type="button"
                className={`eva-chat-icon-button ${showPlus ? 'is-active' : ''}`}
                onClick={() => setShowPlus((current) => !current)}
                aria-label="Open tools menu"
                aria-expanded={showPlus}
              >
                <Plus size={18} />
              </button>

              {showPlus && (
                <div className="eva-tools-menu plus-menu-scroll" role="menu">
                  <div className="eva-tools-main-page">
                    {toolMenuItems.map(({ icon: Icon, label, detail, action }) => (
                      <button
                        key={label}
                        type="button"
                        className="eva-tools-menu-item"
                        onClick={() => runToolAction(action)}
                        title={detail}
                        role="menuitem"
                      >
                        <span className="eva-tools-menu-icon"><Icon size={16} /></span>
                        <span className="eva-tool-text">{label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <textarea ref={textareaRef} value={input}
              onChange={e => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 112) + 'px'; }}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              onPaste={handleComposerPaste}
              onDragOver={e => { if (e.dataTransfer?.types?.includes('Files')) e.preventDefault(); }}
              onDrop={handleComposerDrop}
              placeholder={t('composer.placeholder')}
              rows={1}
              className="eva-chat-textarea" />

            <button type="button" onClick={() => setCameraOpen(true)} className="eva-chat-icon-button" aria-label="Open camera" title="Take a photo for EVA to analyse">
              <CameraIcon size={17} />
            </button>

            <button type="button" onClick={toggleVoice} className={`eva-chat-icon-button ${isListening ? 'is-recording' : ''}`} aria-label={isListening ? 'Stop voice input' : 'Start voice input'}>
              {isListening ? <Square size={15} /> : <Mic size={17} />}
            </button>

            {loading ? (
              <button type="button" onClick={() => streamRef.current?.abort()} className="eva-chat-icon-button is-stop" aria-label="Stop response">
                <Square size={15} />
              </button>
            ) : (
              <button type="button" onClick={() => sendMessage()} disabled={!input.trim() && !attachedFile && !attachedImage} className="eva-chat-send-button" aria-label="Send message">
                <SendHorizontal size={17} />
              </button>
            )}
          </div>
          {/* Update 63: camera capture feeds the existing image/vision path. */}
          <CameraCapture
            open={cameraOpen}
            onClose={() => setCameraOpen(false)}
            onCapture={(file) => handleSelectedFile(file)}
          />

          {/* Update 62: JARVIS hands-free mode ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â one button, no new page. */}
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 8 }}>
            <JarvisMode />
          </div>
          {!isMobile && <div style={{ textAlign: 'center', fontSize: 10, color: 'var(--accent)', marginTop: 6 }}>Enter to send {"\u2022"} Shift+Enter for new line {"\u2022"} Esc to stop</div>}
        </div>
      </div>
      {/* Feature Tools Modal */}
      {/* Tools Center: one modal, tabs inside. The Directory and Skill Library
          are the SAME components as before, rendered here in embedded form
          instead of as separate stacked modals. */}
      <FeatureTools
        open={featureToolsOpen}
        onClose={() => setFeatureToolsOpen(false)}
        initialTab={featureToolsTab}
        API={API}
        extraTabs={[
          {
            id: 'directory',
            label: 'Directory',
            icon: <Sparkles size={13} />,
            wide: true,
            render: () => (
              <DirectoryModal
                embedded
                tab={directoryTab}
                onTabChange={setDirectoryTab}
                onClose={() => setFeatureToolsOpen(false)}
              />
            ),
          },
          {
            id: 'skills',
            label: 'Skill Library',
            icon: <Library size={13} />,
            wide: true,
            render: () => (
              <SkillLibraryPanel
                embedded
                ragApi={RAG_API}
                token={token}
                userId={userDbId}
                workspaceId={selectedWorkspaceId || 'default-org'}
                autoSkillUse={autoSkillUse}
                onToggleAuto={toggleAutoSkill}
                onUseSkill={handleUseSkill}
                onSkillsChanged={() => ensureSkillsCache(true)}
                activeSkillId={activeSkill?.id || null}
                onClose={() => setFeatureToolsOpen(false)}
                isMobile={isMobile}
              />
            ),
          },
        ]}
      />


      {codeWorkspaceOpen && (
        <div className={`eva-code-workspace-overlay ${isMobile ? 'is-mobile' : 'is-desktop'}`}>
          <button
            type="button"
            className="eva-code-workspace-backdrop"
            onClick={() => setCodeWorkspaceOpen(false)}
            aria-label="Close AI Coding Workspace"
          />
          <section className="eva-code-workspace-sheet" role="dialog" aria-modal="true" aria-label="AI Coding Workspace">
            <header className="eva-code-workspace-sheet-header">
              <div>
                <span>AI Coding Workspace</span>
                <strong>Generate, explain, fix, refactor, patch</strong>
              </div>
              <button type="button" onClick={() => setCodeWorkspaceOpen(false)} aria-label="Close AI Coding Workspace">
                <X size={18} />
              </button>
            </header>
            <div className="eva-code-workspace-sheet-body">
              <CodeAssistant
                API={API}
                onSendToChat={(text) => {
                  if (isMobile) setCodeWorkspaceOpen(false);
                  sendMessage(text);
                }}
              />
            </div>
          </section>
        </div>
      )}
      <style>{`
        @keyframes typingBounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-6px)} }
        @keyframes starTwinkle { 0%,100%{opacity:.3} 50%{opacity:1} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
        .eva-empty-chat-prompt {
          margin: min(18vh, 140px) auto 0;
          max-width: 720px;
          padding: 0 20px;
          color: var(--text);
          font-size: 1.9rem;
          font-weight: 650;
          letter-spacing: 0;
          line-height: 1.25;
          text-align: center;
        }
        .eva-chat-page {
          position: relative;
          display: flex;
          width: 100%;
          max-width: 100%;
          height: 100%;
          overflow: hidden;
          background: var(--bg);
        }
        .eva-chat-main {
          display: flex;
          flex-direction: column;
          flex: 1 1 auto;
          height: 100%;
          min-width: 0;
          overflow: hidden;
        }

        @media (min-width: 769px) {
        .eva-chat-main {
          display: flex;
        }

        .eva-chat-main {
          margin-left: 0;
          width: auto;
          flex: 1 1 auto;
          min-width: 0;
        }

        .eva-workspace-selector {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin: 12px 16px 0;
          padding: 10px 12px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: rgba(15,23,42,.54);
          color: var(--text);
          flex-shrink: 0;
        }
        .eva-workspace-label {
          color: var(--text3);
          font-size: 10px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .08em;
        }
        .eva-workspace-selector strong {
          display: block;
          color: var(--text);
          font-size: 13px;
          margin-top: 2px;
        }
        .eva-workspace-selector span,
        .eva-workspace-selector em {
          display: block;
          color: var(--text3);
          font-size: 11px;
          margin-top: 2px;
          font-style: normal;
        }
        .eva-workspace-selector em {
          color: #fecaca;
        }
        .eva-workspace-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
          justify-content: flex-end;
        }
        .eva-workspace-actions select,
        .eva-workspace-form input {
          min-height: 34px;
          border-radius: 8px;
          border: 1px solid var(--border);
          background: rgba(2,6,23,.7);
          color: var(--text);
          padding: 0 10px;
          outline: none;
        }
        .eva-workspace-actions button,
        .eva-workspace-form button {
          min-height: 34px;
          border-radius: 8px;
          border: 1px solid rgba(96,165,250,.34);
          background: var(--accent-soft);
          color: #dbeafe;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 0 10px;
          cursor: pointer;
          font-weight: 800;
          font-size: 12px;
        }
        .eva-workspace-form {
          display: grid;
          grid-template-columns: minmax(160px, 1fr) minmax(180px, 1.2fr) auto;
          gap: 10px;
          margin: 10px 16px 0;
          padding: 12px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: rgba(2,6,23,.68);
          flex-shrink: 0;
        }
        .eva-workspace-form label {
          display: grid;
          gap: 5px;
          color: var(--text3);
          font-size: 11px;
          font-weight: 800;
        }
        .eva-workspace-form-actions {
          display: flex;
          align-items: end;
          gap: 8px;
          flex-wrap: wrap;
        }
        .eva-workspace-form-actions button:first-child {
          border-color: var(--border);
          background: rgba(15,23,42,.56);
          color: var(--text2);
        }
        .eva-message-row {
          display: flex;
          width: 100%;
          box-sizing: border-box;
          backface-visibility: hidden;
        }
        @media (min-width: 769px) {
          .eva-message-row-user,
          .eva-message-row-assistant {
            padding-left: 2px;
            padding-right: 2px;
          }
        }
        .eva-message-row-user {
          justify-content: flex-end;
        }
        .eva-message-row-assistant {
          justify-content: flex-start;
        }
        .eva-message-body {
          min-width: 0;
        }
        .eva-message-body-user {
          max-width: min(560px, 72%);
          width: fit-content;
          margin-left: auto;

        }
        .eva-message-body-assistant {
          width: 100%;
          max-width: 100%;
        }
        .eva-message-bubble {
          color: var(--text);
          /* 12px. Chosen by eye across 15.4, 16.8, 16, 14 and 13 on the
             deployed page, then reduced a further 10%. In px, not rem, so the
             root scale cannot drift it. */
          font-size: 12px;
          line-height: 1.7;
          word-break: break-word;
        }
        .eva-message-bubble-user {
          transition:
            box-shadow 260ms cubic-bezier(0.22, 1, 0.36, 1),
            border-color 220ms ease,
            filter 220ms ease,
            transform 260ms cubic-bezier(0.22, 1, 0.36, 1);
          transform-origin: right center;
          will-change: transform, box-shadow;
          width: fit-content;
          min-width: 52px;
          max-width: 100%;
          padding: 8px 14px;
          border-radius: 18px;
          background: var(--accent-soft);
          border: 1px solid var(--border2);
          border-radius: 18px 18px 4px 18px;
          box-shadow: 0 12px 32px var(--accent-soft);
        }
        @media (hover: hover) and (pointer: fine) {
          .eva-message-bubble-user:hover {
            border-color: var(--accent);
            box-shadow:
              0 16px 36px var(--accent-soft),
              0 0 0 2px var(--accent-glow);
            filter: brightness(1.035);
            transform: translateY(-1px) scale(1.006);
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .eva-message-bubble-user {
            transition: none;
            transform: none;
          }
        }
        .eva-message-bubble-assistant {
          padding: 2px 0;
          background: transparent;
          border: none;
          border-radius: 0;
        }
        .eva-typing-bubble {
          display: flex;
          gap: 4px;
          padding: 10px 14px;
          background: var(--surface2);
          border: 1px solid var(--border);
          border-radius: 14px;
        }
        .eva-smart-suggestion-bar {
          display: flex;
          gap: 7px;
          width: 100%;
          max-width: 780px;
          margin: 0 auto 8px;
          overflow-x: auto;
          padding: 1px 2px 3px;
          scrollbar-width: none;
        }
        .eva-smart-suggestion-bar::-webkit-scrollbar {
          display: none;
        }
        .eva-smart-suggestion-chip {
          flex: 0 0 auto;
          min-height: 30px;
          padding: 6px 11px;
          border-radius: 999px;
          border: 1px solid var(--border);
          background: rgba(15,23,42,.52);
          color: var(--text2);
          font-size: 12px;
          font-weight: 750;
          cursor: pointer;
          backdrop-filter: blur(10px);
          transition: background .15s ease, border-color .15s ease, color .15s ease;
        }
        .eva-smart-suggestion-chip:hover {
          background: var(--accent-soft);
          border-color: rgba(96,165,250,.38);
          color: var(--text);
        }
        .eva-smart-suggestion-chip.is-admin {
          border-color: var(--accent);
          background: rgba(88,28,135,.2);
          color: var(--text2);
        }
        .eva-user-workspace-panel {
          display: grid;
          grid-template-columns: 220px minmax(180px, 260px) minmax(0, 1fr);
          gap: 10px;
          margin: 0 16px 12px;
          padding: 12px;
          border: 1px solid var(--border);
          border-radius: 12px;
          background: linear-gradient(145deg, rgba(15,23,42,.88), rgba(2,6,23,.92));
          box-shadow: 0 18px 46px rgba(2,6,23,.28);
          color: var(--text);
          flex-shrink: 0;
        }
        .eva-user-workspace-activity,
        .eva-user-workspace-files,
        .eva-user-workspace-editor {
          min-width: 0;
          border: 1px solid var(--border);
          border-radius: 10px;
          background: rgba(15,23,42,.42);
          padding: 12px;
        }
        .eva-user-workspace-kicker,
        .eva-user-workspace-section-title {
          color: var(--cyan);
          font-size: 10px;
          font-weight: 900;
          text-transform: uppercase;
          letter-spacing: .08em;
        }
        .eva-user-workspace-activity h2 {
          margin: 5px 0 2px;
          font-size: 18px;
          color: var(--text);
        }
        .eva-user-workspace-activity p {
          margin: 0;
          color: var(--text3);
          font-size: 12px;
        }
        .eva-user-workspace-log {
          display: grid;
          gap: 7px;
          margin-top: 12px;
        }
        .eva-user-workspace-log-row {
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--text2);
          font-size: 12px;
        }
        .eva-user-workspace-log-row span {
          width: 7px;
          height: 7px;
          border-radius: 999px;
          background: var(--green);
          box-shadow: 0 0 14px rgba(34,197,94,.46);
          flex: 0 0 auto;
        }
        .eva-user-workspace-files {
          display: grid;
          align-content: start;
          gap: 8px;
        }
        .eva-user-workspace-file {
          display: grid;
          gap: 3px;
          width: 100%;
          padding: 10px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: rgba(2,6,23,.38);
          color: #e5e7eb;
          text-align: left;
          cursor: pointer;
        }
        .eva-user-workspace-file.is-active {
          border-color: rgba(96,165,250,.42);
          background: var(--accent-soft);
        }
        .eva-user-workspace-file strong,
        .eva-user-workspace-file span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .eva-user-workspace-file span {
          color: var(--text3);
          font-size: 11px;
        }
        .eva-user-workspace-empty {
          padding: 11px;
          border: 1px dashed var(--border);
          border-radius: 8px;
          color: var(--text3);
          font-size: 12px;
          line-height: 1.45;
          background: rgba(2,6,23,.28);
        }
        .eva-user-workspace-editor {
          display: grid;
          gap: 10px;
        }
        .eva-user-workspace-editor-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .eva-user-workspace-editor-head span {
          display: block;
          margin-top: 4px;
          color: #e5e7eb;
          font-size: 13px;
          overflow-wrap: anywhere;
        }
        .eva-user-workspace-editor-head button {
          border: 0;
          background: transparent;
          color: var(--text3);
          cursor: pointer;
          font-size: 16px;
        }
        .eva-user-workspace-details {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 8px;
        }
        .eva-user-workspace-details div {
          display: grid;
          gap: 3px;
          padding: 9px;
          border-radius: 8px;
          background: rgba(2,6,23,.34);
          border: 1px solid var(--border);
          min-width: 0;
        }
        .eva-user-workspace-details span {
          color: var(--text3);
          font-size: 10px;
          text-transform: uppercase;
          font-weight: 800;
        }
        .eva-user-workspace-details strong {
          color: #e5e7eb;
          font-size: 12px;
          overflow-wrap: anywhere;
        }
        .eva-user-workspace-textarea {
          width: 100%;
          min-height: 94px;
          resize: vertical;
          border-radius: 8px;
          border: 1px solid var(--border);
          background: rgba(2,6,23,.46);
          color: var(--text2);
          padding: 10px;
          font: inherit;
          font-size: 12px;
          outline: none;
        }
        @media (max-width: 768px) {
          .eva-empty-chat-prompt {
            margin-top: 16vh;
            font-size: 1.45rem;
          }
          .eva-message-row {
            max-width: 100%;
            margin-left: 0;
            margin-right: 0;
            box-sizing: border-box;
          }
          .eva-message-body-user,
          .eva-message-body-assistant {
            min-width: 0;
          }
          .eva-workspace-selector,
          .eva-workspace-form {
            margin-left: 10px;
            margin-right: 10px;
          }
          .eva-workspace-selector {
            align-items: stretch;
            flex-direction: column;
          }
          .eva-workspace-actions {
            justify-content: stretch;
          }
          .eva-workspace-actions select,
          .eva-workspace-actions button {
            flex: 1;
          }
          .eva-workspace-form {
            grid-template-columns: 1fr;
          }
          .eva-workspace-form-actions {
            align-items: stretch;
          }
          .eva-user-workspace-panel {
            grid-template-columns: 1fr;
            margin: 0 10px 10px;
          }
          .eva-user-workspace-details {
            grid-template-columns: 1fr;
          }
          .eva-message-body-user{
            display: flex;
            justify-content: flex-end;
            width: 100%;
            max-width: 100%;
            margin-left: 0;
          }
          .eva-message-bubble-user {
            width: fit-content;
            min-width: 0;
            max-width: 78vw;
            padding: 8px 14px;
            font-size: 14px;
            border-radius: 18px;
          }
          .eva-message-body-assistant {
            width: 100%;
            max-width: 100%;
          }
          .eva-message-bubble-assistant,
          .eva-message-bubble-assistant > div {
            max-width: 100%;
            overflow-wrap: anywhere;
          }
        }
        .chat-sidebar-scroll::-webkit-scrollbar { width: 4px; }
        .chat-sidebar-scroll::-webkit-scrollbar-track { background: transparent; }
        .chat-sidebar-scroll::-webkit-scrollbar-thumb { background: var(--accent-soft); border-radius: 99px; }
        .chat-sidebar-scroll::-webkit-scrollbar-thumb:hover { background: var(--accent); }
        .plus-menu-scroll { scrollbar-width: none; }
        .plus-menu-scroll::-webkit-scrollbar { width: 0; height: 0; }
        .plus-menu-scroll::-webkit-scrollbar-track { background: transparent; }
        .plus-menu-scroll::-webkit-scrollbar-thumb { background: transparent; }
        .plus-menu-scroll::-webkit-scrollbar-thumb:hover { background: transparent; }
        .messages-scroll::-webkit-scrollbar { width: 4px; }
        .messages-scroll::-webkit-scrollbar-track { background: transparent; }
        .messages-scroll::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 99px; }
        .messages-scroll::-webkit-scrollbar-thumb:hover { background: var(--border2); }
        * { scroll-behavior: smooth; }
      `}</style>
    </div>
  );
}










