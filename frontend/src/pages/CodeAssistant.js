import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Code2, FolderOpen, Sparkles, Wrench, GitBranch, Upload,
  Copy, Download, Play, Eye, RefreshCw, ChevronRight,
  ChevronDown, X, Plus, Search, Terminal, Diff, Loader, Check,
  AlertTriangle, Zap, Folder, SendHorizontal,
} from 'lucide-react';

// â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const TOKEN_KEYS = ['aria_token', 'token', 'access_token', 'authToken'];
const getToken = () => TOKEN_KEYS.map((key) => localStorage.getItem(key)).find(Boolean) || '';

function authHeaders(extra = {}) {
  const token = getToken();
  return {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

// â”€â”€ Fetch with timeout to prevent frozen loading state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function fetchWithTimeout(url, options = {}, ms = 10000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(tid);
    return res;
  } catch (err) {
    clearTimeout(tid);
    if (err.name === 'AbortError') throw new Error('Request timed out. Server may be sleeping â€” try again.');
    throw err;
  }
}

async function apiFetch(API, path, body) {
  const res = await fetchWithTimeout(`${API}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = Array.isArray(err.detail)
      ? err.detail.map((item) => item.msg || JSON.stringify(item)).join(', ')
      : err.detail || err.message;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// â”€â”€ Model Router â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const MODEL_ROUTER = {
  generate:  { label: 'Qwen Coder / Claude',    hint: 'Code generation' },
  explain:   { label: 'Gemini Flash',            hint: 'Fast explanation' },
  fix:       { label: 'Claude / GPT-4o-mini',   hint: 'Bug fixing' },
  refactor:  { label: 'Qwen Coder',             hint: 'Code refactoring' },
  patch:     { label: 'Claude Sonnet',           hint: 'Precise patching' },
};

const LANG_MAP = {
  js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  py: 'python', css: 'css', html: 'html', json: 'json', md: 'markdown',
  sh: 'bash', yml: 'yaml', yaml: 'yaml', sql: 'sql', txt: 'text',
};
const langFromName = (name = '') => LANG_MAP[name.split('.').pop()?.toLowerCase()] || 'text';
const extIcon = (name = '') => {
  const ext = name.split('.').pop()?.toLowerCase();
  if (['js', 'jsx', 'ts', 'tsx'].includes(ext)) return 'âš¡';
  if (ext === 'py') return 'ðŸ';
  if (['css', 'scss'].includes(ext)) return 'ðŸŽ¨';
  if (ext === 'html') return 'ðŸŒ';
  if (ext === 'json') return '{}';
  if (ext === 'md') return 'ðŸ“';
  if (['sh', 'bash'].includes(ext)) return 'ðŸ’»';
  return 'ðŸ“„';
};

const STARTER_FILES = [
  { name: 'main.py', content: '# Welcome to EVA Code Workspace\n# Paste your code here or generate from a prompt\n\ndef hello():\n    print("Hello from EVA!")\n\nhello()\n', type: 'file' },
  { name: 'utils.js', content: '// Utility functions\nexport const greet = (name) => "Hello, " + name + "!";\n', type: 'file' },
  { name: 'README.md', content: '# My Project\n\nAI-assisted development with EVA.\n', type: 'file' },
];

// â”€â”€ Syntax highlight â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function highlight(code = '', lang = 'text') {
  let html = code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  if (lang === 'text' || lang === 'markdown') return html;
  html = html.replace(/(["'`])(?:(?!\1)[^\\]|\\.)*?\1/g, '<span style="color:#a5d6a7">$&</span>');
  html = html.replace(/(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)/g, '<span style="color:#546e7a;font-style:italic">$1</span>');
  const kw = lang === 'python'
    ? /\b(def|class|import|from|return|if|elif|else|for|while|in|not|and|or|True|False|None|with|as|try|except|finally|raise|pass|lambda|yield|async|await)\b/g
    : /\b(const|let|var|function|return|if|else|for|while|class|import|export|default|from|async|await|try|catch|throw|new|typeof|instanceof|null|undefined|true|false|void|this|super|extends|implements|interface|type|enum)\b/g;
  html = html.replace(kw, '<span style="color:#ce93d8">$1</span>');
  html = html.replace(/\b(\d+\.?\d*)\b/g, '<span style="color:#80cbc4">$1</span>');
  html = html.replace(/\b([a-zA-Z_]\w*)\s*(?=\()/g, '<span style="color:#90caf9">$1</span>');
  return html;
}

// â”€â”€ File Tree Node â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function FileNode({ node, depth = 0, active, onSelect, onDelete }) {
  const [open, setOpen] = useState(true);
  const isDir = node.type === 'folder';
  return (
    <div>
      <div
        className={`eva-code-file-row ${active ? 'is-active' : ''}`}
        style={{ paddingLeft: 10 + depth * 14 }}
        onClick={() => isDir ? setOpen(o => !o) : onSelect(node)}
      >
        {isDir
          ? (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)
          : <span style={{ fontSize: 12 }}>{extIcon(node.name)}</span>
        }
        {isDir ? <Folder size={13} style={{ color: '#fbbf24' }} /> : null}
        <span className="eva-code-file-name">{node.name}</span>
        {!isDir && (
          <button
            className="eva-code-file-del"
            onClick={e => { e.stopPropagation(); onDelete(node.name); }}
          >
            <X size={10} />
          </button>
        )}
      </div>
      {isDir && open && node.children?.map(child => (
        <FileNode key={child.name} node={child} depth={depth + 1} active={active} onSelect={onSelect} onDelete={onDelete} />
      ))}
    </div>
  );
}

// â”€â”€ Diff View â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function DiffView({ patch }) {
  if (!patch) return null;
  return (
    <div style={{ fontFamily: 'monospace', fontSize: 12, lineHeight: 1.7, overflowX: 'auto' }}>
      {patch.split('\n').map((line, i) => {
        const bg = line.startsWith('+') ? 'rgba(74,222,128,.12)' : line.startsWith('-') ? 'rgba(248,113,113,.12)' : 'transparent';
        const color = line.startsWith('+') ? '#4ade80' : line.startsWith('-') ? '#f87171' : '#8b9ab0';
        return (
          <div key={i} style={{ background: bg, color, padding: '0 8px', whiteSpace: 'pre' }}>
            {line || ' '}
          </div>
        );
      })}
    </div>
  );
}

// â”€â”€ Main Component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const LOCAL_API = 'http://127.0.0.1:8000';

export default function CodeAssistant({ API = '', onSendToChat }) {
  API = API || LOCAL_API;
  const [files, setFiles] = useState(STARTER_FILES);
  const [activeFile, setActiveFile] = useState(STARTER_FILES[0]);
  const [code, setCode] = useState(STARTER_FILES[0].content);
  const [selected, setSelected] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  // AI panel â€” NOTE: renamed state to aiPrompt to avoid conflict with window.prompt
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiOutput, setAiOutput] = useState('');
  const [aiMode, setAiMode] = useState('generate');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [patch, setPatch] = useState('');
  const [copied, setCopied] = useState(false);
  const [patchApplied, setPatchApplied] = useState(false);

  const [repoUrl, setRepoUrl] = useState('');
  const [repoLoading, setRepoLoading] = useState(false);
  const [repoMsg, setRepoMsg] = useState('');

  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [activePanel, setActivePanel] = useState('editor');
  const textareaRef = useRef(null);
  const zipRef = useRef(null);

  const [runOutput, setRunOutput] = useState(null);
  const [runningCode, setRunningCode] = useState(false);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const selectFile = useCallback((node) => {
    setFiles(prev => prev.map(f => f.name === activeFile?.name ? { ...f, content: code } : f));
    setActiveFile(node);
    setCode(node.content || '');
    setAiOutput('');
    setPatch('');
    setError('');
    if (isMobile) setActivePanel('editor');
  }, [activeFile, code, isMobile]);

  const deleteFile = useCallback((name) => {
    setFiles(prev => {
      const next = prev.filter(f => f.name !== name);
      if (activeFile?.name === name && next.length) {
        setActiveFile(next[0]);
        setCode(next[0].content || '');
      }
      return next;
    });
  }, [activeFile]);

  // FIX: use window.prompt explicitly to avoid conflict with aiPrompt state
  const addNewFile = () => {
    const name = window.prompt('File name (e.g. helper.py):');
    if (!name?.trim()) return;
    const newFile = { name: name.trim(), content: `# ${name.trim()}\n`, type: 'file' };
    setFiles(prev => [...prev, newFile]);
    setActiveFile(newFile);
    setCode(newFile.content);
  };

  const codeToSend = selected.trim() || code;

  // â”€â”€ AI Actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const runAI = useCallback(async (mode) => {
    if (!codeToSend && mode !== 'generate') { setError('No code to analyze.'); return; }
    if (mode === 'generate' && !aiPrompt.trim()) { setError('Enter a prompt first.'); return; }
    setLoading(true);
    setError('');
    setAiOutput('');
    setPatch('');
    setPatchApplied(false);
    setAiMode(mode);

    try {
      let result;
      if (mode === 'generate') {
        result = await apiFetch(API, '/code/generate', { prompt: aiPrompt.trim(), language: langFromName(activeFile?.name) });
        setAiOutput(result.code || result.result || '');
      } else if (mode === 'explain') {
        result = await apiFetch(API, '/code/analyze', { code: codeToSend, filename: activeFile?.name });
        setAiOutput(result.explanation || result.result || '');
      } else if (mode === 'fix') {
        result = await apiFetch(API, '/code/fix', { code: codeToSend, filename: activeFile?.name });
        setAiOutput(result.fixed_code || result.code || result.result || '');
      } else if (mode === 'refactor') {
        result = await apiFetch(API, '/code/refactor', { code: codeToSend, filename: activeFile?.name, instructions: aiPrompt.trim() });
        setAiOutput(result.refactored_code || result.code || result.result || '');
      } else if (mode === 'patch') {
        result = await apiFetch(API, '/code/patch', { original: codeToSend, filename: activeFile?.name, instructions: aiPrompt.trim() });
        setPatch(result.patch || '');
        setAiOutput(result.explanation || '');
      }
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, [API, codeToSend, aiPrompt, activeFile]);

  const applyToEditor = () => {
    if (!aiOutput) return;
    setCode(aiOutput);
    setFiles(prev => prev.map(f => f.name === activeFile?.name ? { ...f, content: aiOutput } : f));
    setAiOutput('');
    if (isMobile) setActivePanel('editor');
  };

  const applyPatch = () => {
    try {
      const lines = code.split('\n');
      const patchLines = patch.split('\n');
      let result = [...lines];
      let offset = 0;
      patchLines.forEach(pl => {
        if (pl.startsWith('+') && !pl.startsWith('+++')) {
          result.splice(offset, 0, pl.slice(1));
          offset++;
        } else if (pl.startsWith('-') && !pl.startsWith('---')) {
          const idx = result.findIndex((l, i) => i >= offset && l === pl.slice(1));
          if (idx !== -1) result.splice(idx, 1);
        }
      });
      setCode(result.join('\n'));
      setFiles(prev => prev.map(f => f.name === activeFile?.name ? { ...f, content: result.join('\n') } : f));
      setPatchApplied(true);
    } catch {
      setError('Could not apply patch automatically. Copy and apply manually.');
    }
  };

  const copyOutput = () => {
    navigator.clipboard.writeText(aiOutput || patch);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadOutput = () => {
    const content = patch || aiOutput || code;
    const blob = new Blob([content], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = patch ? `patch_${activeFile?.name || 'code.diff'}` : aiOutput ? `generated_${activeFile?.name || 'code.txt'}` : (activeFile?.name || 'code.txt');
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const sendOutputToChat = () => {
    const content = patch || aiOutput;
    if (!content?.trim()) return;
    const label = aiMode === 'patch' ? 'patch' : aiMode;
    onSendToChat?.(`AI Coding Workspace ${label} output for ${activeFile?.name || 'current file'}:\n\n${content}`);
  };

  const loadFromGitHub = async () => {
    if (!repoUrl.trim()) return;
    setRepoLoading(true);
    setRepoMsg('');
    try {
      const match = repoUrl.match(/github\.com\/([^/]+)\/([^/\s]+)/);
      if (!match) throw new Error('Invalid GitHub URL');
      const [, owner, repo] = match;
      const apiUrl = `https://api.github.com/repos/${owner}/${repo.replace(/\.git$/, '')}/contents`;
      const res = await fetchWithTimeout(apiUrl, { headers: { Accept: 'application/vnd.github.v3+json' } }, 8000);
      if (!res.ok) throw new Error('Could not fetch repo (may be private)');
      const items = await res.json();
      const fileItems = items.filter(i => i.type === 'file' && i.size < 100000);
      const loaded = await Promise.all(
        fileItems.slice(0, 5).map(async item => {
          const r = await fetch(item.download_url);
          const content = await r.text();
          return { name: item.name, content, type: 'file' };
        })
      );
      setFiles(loaded);
      if (loaded.length) { setActiveFile(loaded[0]); setCode(loaded[0].content); }
      setRepoMsg(`âœ… Loaded ${loaded.length} files from ${owner}/${repo}`);
    } catch (e) {
      setRepoMsg(`âŒ ${e.message}`);
    }
    setRepoLoading(false);
  };

  const handleZipUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { setError('ZIP too large (max 10MB)'); return; }
    const allowedTypes = ['application/zip', 'application/x-zip-compressed'];
    if (!allowedTypes.includes(file.type) && !file.name.endsWith('.zip')) {
      setError('Only .zip files allowed'); return;
    }
    setRepoLoading(true);
    setError('');
    setRepoMsg('Uploading ZIP to EVA...');
    try {
      const form = new FormData();
      form.append('file', file);
      const token = getToken();
      const res = await fetchWithTimeout(`${API}/code/upload-zip`, {
        method: 'POST',
        headers: {
          'ngrok-skip-browser-warning': 'true',
          ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: form,
      }, 15000);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'ZIP upload failed');
      const loaded = Array.isArray(data.files) ? data.files : [];
      setFiles(loaded);
      if (loaded.length) { setActiveFile(loaded[0]); setCode(loaded[0].content || ''); }
      setRepoMsg(`âœ… Loaded ${loaded.length} files from ${file.name}`);
      if (isMobile) setActivePanel('editor');
    } catch (err) {
      setError(err.message || 'ZIP upload failed');
      setRepoMsg('');
    } finally {
      setRepoLoading(false);
      e.target.value = '';
    }
  };

  const handleSelect = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    const sel = ta.value.substring(ta.selectionStart, ta.selectionEnd);
    setSelected(sel);
  };

  const handleRunCode = async () => {
    setRunningCode(true);
    setRunOutput(null);
    setError('');

    try {
      const runApi =
        window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
          ? 'http://127.0.0.1:8000'
          : 'http://127.0.0.1:8000'
      const res = await fetchWithTimeout(`${runApi}/code-run-test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({
          code,
          language: 'python',
        }),
      }, 12000);

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Code run failed');
      }

      setRunOutput(data);
    } catch (err) {
      setRunOutput({
        stdout: '',
        stderr: err.message || 'Code run failed',
        returncode: 1,
      });
    } finally {
      setRunningCode(false);
    }
  };

  const filteredFiles = files.filter(f => !searchQuery || f.name.toLowerCase().includes(searchQuery.toLowerCase()));

  const modeButtons = [
    { mode: 'generate', icon: <Sparkles size={13} />, label: 'Generate' },
    { mode: 'explain',  icon: <Eye size={13} />,      label: 'Explain' },
    { mode: 'fix',      icon: <Wrench size={13} />,   label: 'Fix' },
    { mode: 'refactor', icon: <RefreshCw size={13} />, label: 'Refactor' },
    { mode: 'patch',    icon: <Diff size={13} />,     label: 'Patch' },
  ];

  // â”€â”€ File Explorer Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const ExplorerPanel = () => (
    <div className="eva-code-explorer">
      <div className="eva-code-panel-header">
        <FolderOpen size={14} />
        <span>Explorer</span>
        <button className="eva-code-header-btn" onClick={addNewFile} title="New file"><Plus size={13} /></button>
      </div>
      <div className="eva-code-search-wrap">
        <Search size={12} />
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search files..."
          className="eva-code-search"
        />
      </div>
      <div className="eva-code-file-list">
        {filteredFiles.map(f => (
          <FileNode
            key={f.name}
            node={f}
            active={activeFile?.name === f.name}
            onSelect={selectFile}
            onDelete={deleteFile}
          />
        ))}
      </div>
      <div className="eva-code-section-label"><GitBranch size={12} /> GitHub</div>
      <div className="eva-code-github-wrap">
        <input
          value={repoUrl}
          onChange={e => setRepoUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          className="eva-code-input"
          onKeyDown={e => e.key === 'Enter' && loadFromGitHub()}
        />
        <button className="eva-code-btn-sm" onClick={loadFromGitHub} disabled={repoLoading}>
          {repoLoading ? <Loader size={12} className="eva-spin" /> : <GitBranch size={12} />}
        </button>
      </div>
      {repoMsg && <div className="eva-code-repo-msg">{repoMsg}</div>}
      <div className="eva-code-section-label"><Upload size={12} /> ZIP Upload</div>
      <button className="eva-code-btn-outline" onClick={() => zipRef.current?.click()}>
        <Upload size={13} /> Upload ZIP
      </button>
      <input ref={zipRef} type="file" accept=".zip" style={{ display: 'none' }} onChange={handleZipUpload} />
    </div>
  );

  // â”€â”€ Editor Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


  // â”€â”€ AI Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const MobileTabBar = () => (
    <div className="eva-code-mobile-tabs">
      {[
        { id: 'explorer', icon: <FolderOpen size={15} />, label: 'Files' },
        { id: 'editor',   icon: <Code2 size={15} />,      label: 'Editor' },
        { id: 'ai',       icon: <Sparkles size={15} />,   label: 'AI' },
      ].map(({ id, icon, label }) => (
        <button
          key={id}
          className={`eva-code-mobile-tab ${activePanel === id ? 'is-active' : ''}`}
          onClick={() => setActivePanel(id)}
        >
          {icon}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );

  return (
    <div className="eva-code-workspace">
      {isMobile && <MobileTabBar />}
      <div className="eva-code-layout">
        {(!isMobile || activePanel === 'explorer') && <ExplorerPanel />}
        {(!isMobile || activePanel === 'editor') && (
          <div className="eva-code-editor-wrap">
            <div className="eva-code-panel-header">
              <span>{activeFile?.name || 'editor'}</span>
              <span className="eva-code-lang-badge">{langFromName(activeFile?.name)}</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <button className="eva-code-header-btn" onClick={downloadOutput} title="Download"><Download size={13} /></button>
                <button className="eva-code-header-btn" onClick={() => navigator.clipboard.writeText(code)} title="Copy"><Copy size={13} /></button>
              </div>
            </div>
            <textarea
              ref={textareaRef}
              className="eva-code-textarea"
              value={code}
              onChange={e => setCode(e.target.value)}
              onSelect={handleSelect}
              onMouseUp={handleSelect}
              onKeyUp={handleSelect}
              spellCheck={false}
              autoCapitalize="off"
              autoComplete="off"
              autoCorrect="off"
            />
            {selected && (
              <div className="eva-code-selection-bar">
                <span>Selected: {selected.length} chars</span>
                <button onClick={() => runAI('explain')}>Explain</button>
                <button onClick={() => runAI('fix')}>Fix</button>
                <button onClick={() => runAI('refactor')}>Refactor</button>
              </div>
            )}
          </div>
        )}
        {(!isMobile || activePanel === 'ai') && (
          <div className="eva-code-ai-wrap">
            <div className="eva-code-panel-header">
              <Zap size={14} style={{ color: '#c084fc' }} />
              <span>AI Assistant</span>
              {selected && <span className="eva-code-sel-badge">Selection active</span>}
            </div>
            <div className="eva-code-router-bar">
              <span className="eva-code-router-label">ðŸ§  Model:</span>
              <span className="eva-code-router-model">{(MODEL_ROUTER[aiMode] || {}).label}</span>
              <span className="eva-code-router-hint">{(MODEL_ROUTER[aiMode] || {}).hint}</span>
            </div>
            <div className="eva-code-mode-row">
              {modeButtons.map(({ mode, icon, label }) => (
                <button key={mode} className={`eva-code-mode-btn ${aiMode === mode ? 'is-active' : ''}`} onClick={() => setAiMode(mode)}>
                  {icon} {label}
                </button>
              ))}
            </div>
            <div className="eva-code-prompt-wrap">
              <textarea
                className="eva-code-prompt"
                value={aiPrompt}
                onChange={e => setAiPrompt(e.target.value)}
                placeholder={aiMode === 'generate' ? 'Describe what to generate...' : aiMode === 'refactor' ? 'Refactor instructions...' : aiMode === 'patch' ? 'Describe the changes...' : 'Optional context...'}
                rows={3}
                onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) runAI(aiMode); }}
              />
              <button className="eva-code-run-btn" onClick={() => runAI(aiMode)} disabled={loading}>
                {loading ? <><Loader size={14} className="eva-spin" /> Running...</> : <><Sparkles size={14} /> Run AI</>}
              </button>
            </div>
            {error && <div className="eva-code-error"><AlertTriangle size={13} /> {error}</div>}
            {(aiOutput || patch) && (
              <div className="eva-code-output-wrap">
                <div className="eva-code-output-header">
                  <span>{aiMode === 'patch' ? 'Patch Preview' : aiMode === 'explain' ? 'Explanation' : 'Generated Code'}</span>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="eva-code-out-btn" onClick={copyOutput}>{copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}</button>
                    {aiOutput && aiMode !== 'explain' && <button className="eva-code-out-btn is-apply" onClick={applyToEditor}><Check size={12} /> Apply</button>}
                    {patch && !patchApplied && <button className="eva-code-out-btn is-apply" onClick={applyPatch}><Diff size={12} /> Apply Patch</button>}
                    {patchApplied && <span style={{ fontSize: 11, color: '#4ade80' }}>âœ“ Applied</span>}
                  </div>
                </div>
                <div className="eva-code-output-body">
                  {aiMode === 'explain' ? <div className="eva-code-explain-text">{aiOutput}</div> : patch ? <DiffView patch={patch} /> : <pre className="eva-code-output-pre" dangerouslySetInnerHTML={{ __html: highlight(aiOutput, langFromName(activeFile?.name)) }} />}
                </div>
                <div className="eva-code-output-footer">
                  <button className="eva-code-out-btn" onClick={downloadOutput}><Download size={12} /> Download</button>
                  <button className="eva-code-out-btn" onClick={sendOutputToChat} disabled={!onSendToChat}><SendHorizontal size={12} /> Send to chat</button>
                  <button className="eva-code-out-btn" onClick={() => { setAiOutput(''); setPatch(''); }}><X size={12} /> Clear</button>
                </div>
              </div>
            )}
            <div className="eva-code-run-placeholder">
              <Terminal size={13} />
              <span>POST /code-run-test</span>
              <button
                className="eva-code-out-btn"
                onClick={handleRunCode}
                disabled={runningCode}
              >
                {runningCode ? <><Loader size={12} className="eva-spin" /> Running...</> : <><Play size={12} /> Run</>}
              </button>
            </div>

            {runOutput && (
              <div className="eva-code-run-output">
                <div className="eva-code-output-header">
                  <span>Run Output</span>
                  <small>Return code: {runOutput.returncode}</small>
                </div>

                <pre>
                  {runOutput.stdout || runOutput.stderr || 'No output'}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        .eva-code-workspace { display:flex; flex-direction:column; height:100%; background:var(--bg,#060b16); color:var(--text,#e8e0ff); font-family:inherit; overflow:hidden; }
        .eva-code-layout { display:grid; grid-template-columns:220px 1fr 340px; flex:1; min-height:0; overflow:hidden; }
        .eva-code-panel-header { display:flex; align-items:center; gap:7px; padding:9px 12px; border-bottom:1px solid rgba(255,255,255,.07); font-size:12px; font-weight:600; color:#b29dd9; flex-shrink:0; background:rgba(255,255,255,.02); }
        .eva-code-header-btn { background:none; border:none; color:#6b47a8; cursor:pointer; padding:3px; border-radius:5px; display:flex; align-items:center; }
        .eva-code-header-btn:hover { color:#c084fc; background:rgba(192,132,252,.1); }
        .eva-code-lang-badge { padding:1px 7px; border-radius:99px; background:rgba(99,102,241,.15); border:1px solid rgba(99,102,241,.2); font-size:10px; color:#a5b4fc; }
        .eva-code-sel-badge { padding:1px 7px; border-radius:99px; background:rgba(251,191,36,.12); border:1px solid rgba(251,191,36,.2); font-size:10px; color:#fbbf24; }
        .eva-code-router-bar { display:flex; align-items:center; gap:6px; padding:5px 12px; background:rgba(139,92,246,.06); border-bottom:1px solid rgba(139,92,246,.1); font-size:11px; flex-shrink:0; }
        .eva-code-router-label { color:#6b47a8; }
        .eva-code-router-model { color:#c084fc; font-weight:700; }
        .eva-code-router-hint { color:#4a2d7a; margin-left:auto; }
        .eva-code-explorer { display:flex; flex-direction:column; border-right:1px solid rgba(255,255,255,.06); overflow:hidden; background:rgba(255,255,255,.015); }
        .eva-code-search-wrap { display:flex; align-items:center; gap:7px; padding:7px 10px; border-bottom:1px solid rgba(255,255,255,.05); color:#4a2d7a; }
        .eva-code-search { flex:1; background:none; border:none; outline:none; font-size:12px; color:#e8e0ff; }
        .eva-code-search::placeholder { color:#4a2d7a; }
        .eva-code-file-list { flex:1; overflow-y:auto; padding:4px 0; }
        .eva-code-file-row { display:flex; align-items:center; gap:6px; padding:5px 10px; cursor:pointer; font-size:12px; color:#8b7ab0; }
        .eva-code-file-row:hover { background:rgba(255,255,255,.04); color:#c084fc; }
        .eva-code-file-row.is-active { background:rgba(139,92,246,.15); color:#e9d5ff; }
        .eva-code-file-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .eva-code-file-del { background:none; border:none; color:#4a2d7a; cursor:pointer; opacity:0; display:flex; align-items:center; padding:2px; border-radius:3px; }
        .eva-code-file-row:hover .eva-code-file-del { opacity:1; }
        .eva-code-file-del:hover { color:#f87171; background:rgba(248,113,113,.1); }
        .eva-code-section-label { display:flex; align-items:center; gap:6px; padding:8px 10px 4px; font-size:10px; font-weight:700; color:#4a2d7a; text-transform:uppercase; letter-spacing:.06em; flex-shrink:0; }
        .eva-code-github-wrap { display:flex; gap:6px; padding:0 10px 6px; flex-shrink:0; }
        .eva-code-input { flex:1; background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:7px; padding:5px 9px; font-size:11px; color:#e8e0ff; outline:none; min-width:0; }
        .eva-code-input:focus { border-color:rgba(139,92,246,.4); }
        .eva-code-btn-sm { background:rgba(139,92,246,.15); border:1px solid rgba(139,92,246,.25); border-radius:7px; color:#c084fc; cursor:pointer; display:flex; align-items:center; padding:5px 7px; flex-shrink:0; }
        .eva-code-btn-sm:hover { background:rgba(139,92,246,.25); }
        .eva-code-btn-sm:disabled { opacity:.5; cursor:not-allowed; }
        .eva-code-repo-msg { padding:4px 10px 8px; font-size:11px; color:#8b7ab0; }
        .eva-code-btn-outline { display:flex; align-items:center; gap:6px; margin:0 10px 10px; padding:6px 10px; background:none; border:1px dashed rgba(255,255,255,.1); border-radius:8px; color:#6b47a8; font-size:11px; cursor:pointer; transition:.15s; }
        .eva-code-btn-outline:hover { border-color:rgba(139,92,246,.35); color:#c084fc; background:rgba(139,92,246,.06); }
        .eva-code-editor-wrap { display:flex; flex-direction:column; border-right:1px solid rgba(255,255,255,.06); overflow:hidden; }
        .eva-code-textarea { flex:1; width:100%; background:#060b16; border:none; outline:none; padding:16px; color:#cdd5e0; caret-color:#e8e0ff; font-family:'Fira Code',monospace; font-size:13px; line-height:1.65; resize:none; white-space:pre; overflow:auto; box-sizing:border-box; tab-size:2; }
        .eva-code-selection-bar { display:flex; align-items:center; gap:8px; padding:6px 12px; background:rgba(251,191,36,.07); border-top:1px solid rgba(251,191,36,.15); font-size:11px; color:#fbbf24; flex-shrink:0; }
        .eva-code-selection-bar button { padding:2px 10px; border-radius:6px; border:1px solid rgba(251,191,36,.25); background:rgba(251,191,36,.1); color:#fbbf24; font-size:11px; cursor:pointer; }
        .eva-code-selection-bar button:hover { background:rgba(251,191,36,.2); }
        .eva-code-ai-wrap { display:flex; flex-direction:column; overflow:hidden; background:rgba(255,255,255,.012); }
        .eva-code-mode-row { display:flex; gap:4px; padding:8px 10px; flex-wrap:wrap; border-bottom:1px solid rgba(255,255,255,.05); flex-shrink:0; }
        .eva-code-mode-btn { display:flex; align-items:center; gap:4px; padding:4px 9px; border-radius:7px; border:1px solid rgba(255,255,255,.08); background:transparent; color:#6b47a8; font-size:11px; cursor:pointer; transition:.15s; }
        .eva-code-mode-btn:hover { border-color:#8b5cf6; color:#c084fc; }
        .eva-code-mode-btn.is-active { background:rgba(139,92,246,.2); border-color:rgba(139,92,246,.4); color:#e9d5ff; }
        .eva-code-prompt-wrap { display:flex; flex-direction:column; gap:7px; padding:10px; border-bottom:1px solid rgba(255,255,255,.05); flex-shrink:0; }
        .eva-code-prompt { background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:10px; padding:9px 11px; font-size:12.5px; color:#e8e0ff; outline:none; resize:none; font-family:inherit; line-height:1.5; transition:border-color .15s; }
        .eva-code-prompt:focus { border-color:rgba(139,92,246,.4); }
        .eva-code-prompt::placeholder { color:#4a2d7a; }
        .eva-code-run-btn { display:flex; align-items:center; justify-content:center; gap:7px; padding:9px; border-radius:10px; border:none; background:linear-gradient(135deg,#7c3aed,#a855f7); color:#fff; font-size:13px; font-weight:600; cursor:pointer; transition:opacity .15s,transform .1s; }
        .eva-code-run-btn:hover { opacity:.9; transform:translateY(-1px); }
        .eva-code-run-btn:disabled { opacity:.5; cursor:not-allowed; transform:none; }
        .eva-code-error { display:flex; align-items:center; gap:7px; margin:8px 10px; padding:9px 12px; background:rgba(248,113,113,.1); border:1px solid rgba(248,113,113,.2); border-radius:9px; font-size:12px; color:#f87171; }
        .eva-code-output-wrap { flex:1; display:flex; flex-direction:column; overflow:hidden; border-top:1px solid rgba(255,255,255,.05); }
        .eva-code-output-header { display:flex; align-items:center; justify-content:space-between; padding:7px 10px; font-size:11px; font-weight:600; color:#8b7ab0; border-bottom:1px solid rgba(255,255,255,.05); flex-shrink:0; gap:6px; }
        .eva-code-output-body { flex:1; overflow:auto; background:rgba(0,0,0,.2); }
        .eva-code-output-pre { margin:0; padding:12px; font-family:'Fira Code',monospace; font-size:12px; line-height:1.65; color:#cdd5e0; white-space:pre-wrap; word-break:break-word; }
        .eva-code-explain-text { padding:12px; font-size:13px; line-height:1.7; color:#c4b5d9; white-space:pre-wrap; }
        .eva-code-output-footer { display:flex; gap:6px; padding:7px 10px; border-top:1px solid rgba(255,255,255,.05); flex-shrink:0; }
        .eva-code-out-btn { display:flex; align-items:center; gap:5px; padding:4px 10px; border-radius:7px; border:1px solid rgba(255,255,255,.1); background:transparent; color:#8b7ab0; font-size:11px; cursor:pointer; transition:.15s; }
        .eva-code-out-btn:hover { border-color:#8b5cf6; color:#c084fc; }
        .eva-code-out-btn.is-apply { border-color:rgba(74,222,128,.3); color:#4ade80; }
        .eva-code-out-btn.is-apply:hover { background:rgba(74,222,128,.1); }
        .eva-code-out-btn:disabled { opacity:.4; cursor:not-allowed; }
        .eva-code-run-placeholder { display:flex; align-items:center; gap:8px; padding:10px; margin:8px 10px; border:1px dashed rgba(255,255,255,.07); border-radius:10px; font-size:11px; color:#4a2d7a; flex-shrink:0; }
        .eva-code-run-placeholder span { flex:1; }
        .eva-code-mobile-tabs { display:flex; border-bottom:1px solid rgba(255,255,255,.07); flex-shrink:0; }
        .eva-code-mobile-tab { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px; padding:8px; background:none; border:none; color:#4a2d7a; font-size:10px; cursor:pointer; transition:.15s; border-bottom:2px solid transparent; }
        .eva-code-mobile-tab.is-active { color:#c084fc; border-bottom-color:#8b5cf6; }
        .eva-code-run-output {
            margin: 0 10px 10px;
            border: 1px solid rgba(255,255,255,.08);
            border-radius: 10px;
            background: rgba(0,0,0,.22);
            overflow: hidden;
            flex-shrink: 0;
          }

          .eva-code-run-output pre {
            margin: 0;
            padding: 10px;
            font-family: 'Fira Code', monospace;
            font-size: 12px;
            line-height: 1.6;
            color: #cdd5e0;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 180px;
            overflow: auto;
          }

          .eva-code-run-output small {
            color: #6b47a8;
            font-size: 10px;
          }
        @media (max-width:767px) {
          .eva-code-layout { grid-template-columns:1fr; grid-template-rows:1fr; }
          .eva-code-explorer, .eva-code-editor-wrap, .eva-code-ai-wrap { height:100%; }
        }
        @keyframes eva-code-spin { to { transform:rotate(360deg); } }
        .eva-spin { animation:eva-code-spin .8s linear infinite; }
      `}</style>
    </div>
  );
}

