import { useState } from 'react';

// EVA Skill Creator — v1 (functional page, not a modal).
// Scope: a form that builds a skill.md and downloads it client-side, PLUS an
// optional "from screen recording" path that drafts the same fields via the HF
// ML service (POST /skill/from-video). The manual flow is unchanged.

const RAG_API = process.env.REACT_APP_RAG_API_BASE || 'http://127.0.0.1:7860';

const TOKEN_KEYS = ['aria_token', 'token', 'access_token', 'authToken'];
const getToken = () => TOKEN_KEYS.map((k) => localStorage.getItem(k)).find(Boolean) || '';
// Same identity used by the Chat page (userDbId) so saved skills are scoped consistently.
const getUserId = () => {
  try {
    const u = JSON.parse(localStorage.getItem('aria_user') || '{}');
    return u.email || u.username || u.name || 'user_001';
  } catch {
    return 'user_001';
  }
};
const getWorkspaceId = () => localStorage.getItem('eva_selected_workspace_id') || 'default-org';

const C = {
  bg: '#0e0820',
  panel: '#150a2e',
  border: '#2d1b5e',
  accent: '#7c3aed',
  accent2: '#9333ea',
  text: '#f0e8ff',
  text2: '#cbb8f0',
  muted: '#6b47a8',
  muted2: '#4a2d7a',
};

const S = {
  page: { minHeight: '100%', background: C.bg, color: C.text, padding: '28px 20px 60px', boxSizing: 'border-box', fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif' },
  wrap: { maxWidth: 760, margin: '0 auto' },
  head: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 },
  title: { fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em' },
  sub: { color: C.muted, fontSize: 13, marginBottom: 22 },
  back: { background: 'transparent', border: `1px solid ${C.border}`, color: C.text2, borderRadius: 8, padding: '6px 12px', fontSize: 12, cursor: 'pointer' },
  card: { background: C.panel, border: `1px solid ${C.border}`, borderRadius: 14, padding: 18, marginBottom: 16 },
  label: { display: 'block', fontSize: 12, fontWeight: 600, color: C.text2, marginBottom: 6 },
  hint: { fontSize: 11, color: C.muted, marginTop: 4 },
  input: { width: '100%', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '9px 11px', color: C.text, fontSize: 13, outline: 'none', boxSizing: 'border-box' },
  textarea: { width: '100%', minHeight: 180, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 12px', color: C.text, fontSize: 13, lineHeight: 1.5, outline: 'none', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' },
  compactTextarea: { width: '100%', minHeight: 96, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 12px', color: C.text, fontSize: 13, lineHeight: 1.5, outline: 'none', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' },
  field: { marginBottom: 14 },
  row: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' },
  btn: { background: `linear-gradient(135deg,${C.accent},${C.accent2})`, border: 'none', color: '#fff', borderRadius: 9, padding: '10px 18px', fontSize: 13, fontWeight: 700, cursor: 'pointer' },
  btnDisabled: { opacity: 0.45, cursor: 'not-allowed' },
  ok: { color: '#34d399', fontSize: 12, fontWeight: 600 },
  previewLabel: { fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: C.muted, marginBottom: 8 },
  pre: { margin: 0, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, color: C.text2, fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 520, overflowY: 'auto', overflowX: 'hidden' },
  placeholder: { background: C.panel, border: `1px dashed ${C.border}`, borderRadius: 14, padding: 18, opacity: 0.7 },
  pillSoon: { fontSize: 10, fontWeight: 700, color: C.accent2, background: 'rgba(147,51,234,0.14)', border: `1px solid ${C.border}`, borderRadius: 999, padding: '2px 8px', textTransform: 'uppercase', letterSpacing: '0.05em' },
};

function slugify(name) {
  const s = (name || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'untitled-skill';
}

function listToText(items = []) {
  return Array.isArray(items) ? items.filter(Boolean).map((item) => String(item).trim()).filter(Boolean).join('\n') : '';
}

function textLines(text = '') {
  return String(text)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function numberedSection(title, text) {
  const items = textLines(text);
  return [`## ${title}`, '', ...(items.length ? items.map((item, index) => `${index + 1}. ${item.replace(/^\d+\.\s*/, '')}`) : ['None yet.'])].join('\n');
}

function bulletSection(title, text) {
  const items = textLines(text);
  return [`## ${title}`, '', ...(items.length ? items.map((item) => `- ${item.replace(/^[-*]\s*/, '')}`) : ['None.'])].join('\n');
}

export default function SkillCreator() {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [instructions, setInstructions] = useState('');
  const [steps, setSteps] = useState('');
  const [tips, setTips] = useState('');
  const [warnings, setWarnings] = useState('');
  const [saved, setSaved] = useState(false);
  const [videoLoading, setVideoLoading] = useState(false);
  const [videoStatus, setVideoStatus] = useState('');
  const [videoError, setVideoError] = useState('');
  const [videoFile, setVideoFile] = useState('');
  const [savingLibrary, setSavingLibrary] = useState(false);
  const [librarySaved, setLibrarySaved] = useState(false);
  const [libraryError, setLibraryError] = useState('');

  const buildSkillMd = () => {
    const body = [
      instructions.trim() ? `## Instructions\n\n${instructions.trim()}` : '',
      numberedSection('Steps', steps),
      bulletSection('Tips', tips),
      bulletSection('Warnings', warnings),
    ].filter(Boolean).join('\n\n');

    return `---\nname: ${name.trim() || 'Untitled Skill'}\ndescription: ${description.trim()}\n---\n\n${body}\n`;
  };

  const canSave = name.trim().length > 0 && (instructions.trim().length > 0 || steps.trim().length > 0);

  const download = () => {
    if (!canSave) return;
    const blob = new Blob([buildSkillMd()], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${slugify(name)}.skill.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  // Persist the current draft to the Supabase-backed Skill Library (NOT the filesystem).
  const saveToLibrary = async () => {
    if (!canSave || savingLibrary) return;
    setSavingLibrary(true);
    setLibraryError('');
    setLibrarySaved(false);
    try {
      const token = getToken();
      const res = await fetch(`${RAG_API}/api/skills/save`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          name: name.trim() || 'Untitled Skill',
          description: description.trim(),
          content: buildSkillMd(),
          user_id: getUserId(),
          workspace_id: getWorkspaceId(),
        }),
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* non-JSON */ }
      if (!res.ok || !data || !data.ok) {
        throw new Error(data?.detail || data?.message || `Save failed (${res.status})`);
      }
      setLibrarySaved(true);
      setTimeout(() => setLibrarySaved(false), 3000);
    } catch (err) {
      setLibraryError(err.message || 'Could not save to library');
    } finally {
      setSavingLibrary(false);
    }
  };

  const goBack = () => {
    if (window.history.length > 1) window.history.back();
    else window.location.assign('/chat');
  };

  // ── From screen recording — drafts the fields above via HF /skill/from-video ──
  const composeInstructions = (draft) => {
    return String(draft.instructions || draft.body || '').trim();
  };

  const handleVideoUpload = async (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = ''; // allow re-selecting the same file later
    if (!f) return;
    setVideoFile(f.name);
    setVideoError('');
    setVideoStatus('Analyzing recording...');
    setVideoLoading(true);
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), 120000); // generous: analysis is slow
    try {
      const fd = new FormData();
      fd.append('file', f);
      const token = getToken();
      const res = await fetch(`${RAG_API}/skill/from-video`, {
        method: 'POST',
        headers: { ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}) },
        body: fd,
        signal: controller.signal,
      });
      clearTimeout(tid);
      let data = null;
      try { data = await res.json(); } catch (_) { /* non-JSON response */ }
      if (!res.ok || !data || !data.draft) {
        const detail = data?.detail || data?.message || 'quota/model/API error';
        throw new Error(detail);
      }
      const d = data.draft;
      setName(d.title || 'Untitled workflow');
      setDescription(d.description || '');
      const composed = composeInstructions(d);
      setInstructions(composed);
      setSteps(listToText(d.steps));
      setTips(listToText(d.tips));
      setWarnings(listToText(d.warnings));
      setVideoError('');
      setVideoStatus('Skill draft created');
    } catch (err) {
      const detail = err.name === 'AbortError' ? 'request timed out' : (err.message || 'quota/model/API error');
      setVideoError(`Failed to create skill: quota/model/API error${detail ? ` (${detail})` : ''}`);
      setVideoStatus('');
    } finally {
      clearTimeout(tid);
      setVideoLoading(false);
    }
  };

  return (
    <div style={S.page}>
      <div style={S.wrap}>
        <div style={S.head}>
          <div>
            <div style={S.title}>🛠️ Skill Creator</div>
          </div>
          <button type="button" style={S.back} onClick={goBack}>← Back</button>
        </div>
        <div style={S.sub}>Define a skill and download it as a <code>skill.md</code> file.</div>

        <div style={S.card}>
          <div style={S.field}>
            <label style={S.label}>Skill name</label>
            <input
              style={S.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Invoice Summarizer"
              spellCheck={false}
            />
            {name.trim() && <div style={S.hint}>Saves as <code>{slugify(name)}.skill.md</code></div>}
          </div>

          <div style={S.field}>
            <label style={S.label}>Description</label>
            <input
              style={S.input}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One line on what this skill does and when to use it."
            />
          </div>

          <div style={S.field}>
            <label style={S.label}>Instructions / prompt body</label>
            <textarea
              style={S.textarea}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Write the step-by-step instructions or prompt the skill should follow..."
              spellCheck={false}
            />
          </div>

          <div style={S.field}>
            <label style={S.label}>Steps</label>
            <textarea
              style={S.compactTextarea}
              value={steps}
              onChange={(e) => setSteps(e.target.value)}
              placeholder="One step per line. Screen recording drafts fill this automatically."
              spellCheck={false}
            />
          </div>

          <div style={S.field}>
            <label style={S.label}>Tips</label>
            <textarea
              style={S.compactTextarea}
              value={tips}
              onChange={(e) => setTips(e.target.value)}
              placeholder="One tip per line."
              spellCheck={false}
            />
          </div>

          <div style={S.field}>
            <label style={S.label}>Warnings</label>
            <textarea
              style={S.compactTextarea}
              value={warnings}
              onChange={(e) => setWarnings(e.target.value)}
              placeholder="One warning per line."
              spellCheck={false}
            />
          </div>

          <div style={S.row}>
            <button
              type="button"
              style={{ ...S.btn, ...(canSave ? {} : S.btnDisabled) }}
              onClick={download}
              disabled={!canSave}
            >
              Download skill.md
            </button>
            <button
              type="button"
              style={{
                ...S.btn,
                background: 'transparent',
                border: `1px solid ${C.accent}`,
                color: C.text,
                ...((!canSave || savingLibrary) ? S.btnDisabled : {}),
              }}
              onClick={saveToLibrary}
              disabled={!canSave || savingLibrary}
            >
              {savingLibrary ? 'Saving…' : 'Save to Skill Library'}
            </button>
            {saved && <span style={S.ok}>✓ Downloaded</span>}
            {librarySaved && <span style={S.ok}>✓ Saved to library</span>}
            {!canSave && <span style={S.hint}>Name and instructions or steps are required.</span>}
          </div>
          {libraryError && (
            <div style={{ color: '#f87171', fontSize: 12, fontWeight: 600, marginTop: 10 }}>
              {libraryError}
            </div>
          )}
        </div>

        {(name.trim() || description.trim() || instructions.trim() || steps.trim() || tips.trim() || warnings.trim()) && (
          <div style={S.card}>
            <div style={S.previewLabel}>skill.md preview</div>
            <pre style={S.pre}>{buildSkillMd()}</pre>
          </div>
        )}

        <div style={S.card}>
          <div style={{ ...S.row, justifyContent: 'space-between', marginBottom: 4 }}>
            <strong style={{ fontSize: 14 }}>Create skill from screen recording</strong>
          </div>
          <div style={{ ...S.hint, marginTop: 0, marginBottom: 12 }}>
            Upload a short screen recording (up to 30s) of a workflow and EVA will draft the skill for you.
            The draft fills in the fields above — fully editable before you download.
          </div>
          <label style={{ ...S.btn, ...(videoLoading ? S.btnDisabled : {}), display: 'inline-block' }}>
            {videoLoading ? 'Analyzing recording...' : 'Upload a screen recording'}
            <input
              type="file"
              accept="video/*"
              style={{ display: 'none' }}
              disabled={videoLoading}
              onChange={handleVideoUpload}
            />
          </label>
          {videoFile && !videoLoading && !videoError && (
            <span style={{ ...S.hint, marginLeft: 10 }}>{videoFile}</span>
          )}
          {videoStatus && (
            <div style={{ ...(videoStatus === 'Skill draft created' ? S.ok : S.hint), marginTop: 10 }}>
              {videoStatus}
            </div>
          )}
          {videoLoading && (
            <div style={{ ...S.hint, marginTop: 10 }}>
              Extracting frames and analyzing — this can take up to a minute.
            </div>
          )}
          {videoError && (
            <div style={{ color: '#f87171', fontSize: 12, fontWeight: 600, marginTop: 10 }}>
              {videoError}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
