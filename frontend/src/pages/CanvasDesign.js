import { useState } from 'react';

// EVA Canvas Design — v1 (functional page, not a modal).
// Generates an image via the Render backend POST /image/generate-v2
// (Pollinations AI — free, no API key). Displays the result and offers download.

const API = (process.env.REACT_APP_API_BASE || 'http://127.0.0.1:8002').replace(/\/+$/, '');

const TOKEN_KEYS = ['aria_token', 'token', 'access_token', 'authToken'];
const getToken = () => TOKEN_KEYS.map((k) => localStorage.getItem(k)).find(Boolean) || '';
function authHeaders(extra = {}) {
  const token = getToken();
  return {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

async function fetchWithTimeout(url, options = {}, ms = 90000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(tid);
    return res;
  } catch (err) {
    clearTimeout(tid);
    if (err.name === 'AbortError') throw new Error('Request timed out — image generation can be slow. Try again.');
    throw err;
  }
}

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
  textarea: { width: '100%', minHeight: 90, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 12px', color: C.text, fontSize: 13, lineHeight: 1.5, outline: 'none', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' },
  field: { marginBottom: 14 },
  row: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' },
  dimRow: { display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' },
  dimField: { flex: '0 0 auto' },
  dimInput: { width: 96, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '9px 11px', color: C.text, fontSize: 13, outline: 'none', boxSizing: 'border-box' },
  presets: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  preset: { background: 'transparent', border: `1px solid ${C.border}`, color: C.text2, borderRadius: 999, padding: '5px 11px', fontSize: 11, fontWeight: 600, cursor: 'pointer' },
  presetActive: { background: 'rgba(124,58,237,0.22)', borderColor: C.accent, color: '#c084fc' },
  btn: { background: `linear-gradient(135deg,${C.accent},${C.accent2})`, border: 'none', color: '#fff', borderRadius: 9, padding: '10px 18px', fontSize: 13, fontWeight: 700, cursor: 'pointer' },
  btnGhost: { background: 'transparent', border: `1px solid ${C.border}`, color: C.text2, borderRadius: 9, padding: '10px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer' },
  btnDisabled: { opacity: 0.45, cursor: 'not-allowed' },
  err: { color: '#f87171', fontSize: 12, fontWeight: 600, background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.3)', borderRadius: 8, padding: '9px 11px', marginTop: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' },
  previewLabel: { fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: C.muted, marginBottom: 10 },
  imgWrap: { display: 'flex', justifyContent: 'center', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 10, padding: 12, marginBottom: 12 },
  img: { maxWidth: '100%', maxHeight: 480, borderRadius: 6, display: 'block' },
  meta: { fontSize: 11, color: C.muted, marginTop: 4 },
  spinner: { display: 'inline-block', width: 14, height: 14, border: `2px solid ${C.muted2}`, borderTopColor: '#fff', borderRadius: '50%', animation: 'cd-spin 0.7s linear infinite', marginRight: 8, verticalAlign: 'middle' },
  loadingBox: { display: 'flex', alignItems: 'center', color: C.text2, fontSize: 13, padding: '24px 0', justifyContent: 'center' },
};

const PRESETS = [
  { label: 'Square', w: 512, h: 512 },
  { label: 'Portrait', w: 512, h: 768 },
  { label: 'Landscape', w: 768, h: 512 },
  { label: 'Large', w: 1024, h: 1024 },
];

function clampDim(v) {
  const n = parseInt(v, 10);
  if (Number.isNaN(n)) return 512;
  return Math.max(64, Math.min(1536, n));
}

export default function CanvasDesign() {
  const [prompt, setPrompt] = useState('');
  const [style, setStyle] = useState('');
  const [width, setWidth] = useState(512);
  const [height, setHeight] = useState(512);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [downloading, setDownloading] = useState(false);

  const canGenerate = prompt.trim().length > 0 && !loading;

  const generate = async () => {
    if (!canGenerate) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await fetchWithTimeout(`${API}/image/generate-v2`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          prompt: prompt.trim(),
          style: style.trim(),
          width: clampDim(width),
          height: clampDim(height),
        }),
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* non-JSON response */ }
      if (!res.ok) {
        const detail = (data && (data.detail || data.error)) || `Request failed (${res.status})`;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      }
      if (!data || !data.image_url) throw new Error('No image URL was returned by the server.');
      setResult(data);
    } catch (e) {
      setError(e.message || 'Image generation failed.');
    } finally {
      setLoading(false);
    }
  };

  const download = async () => {
    if (!result || !result.image_url) return;
    setDownloading(true);
    try {
      const r = await fetch(result.image_url);
      const blob = await r.blob();
      const ext = (blob.type && blob.type.split('/')[1]) || 'png';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eva-canvas-${Date.now()}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (_) {
      // Cross-origin / network fallback: open the image so the user can save it manually.
      window.open(result.image_url, '_blank', 'noopener');
    } finally {
      setDownloading(false);
    }
  };

  const goBack = () => {
    if (window.history.length > 1) window.history.back();
    else window.location.assign('/chat');
  };

  const matchesPreset = (p) => clampDim(width) === p.w && clampDim(height) === p.h;

  return (
    <div style={S.page}>
      <div style={S.wrap}>
        <div style={S.head}>
          <div style={S.title}>🎨 Canvas Design</div>
          <button type="button" style={S.back} onClick={goBack}>← Back</button>
        </div>
        <div style={S.sub}>Describe an image and generate it with AI. Free, no API key required.</div>

        <div style={S.card}>
          <div style={S.field}>
            <label style={S.label}>Prompt</label>
            <textarea
              style={S.textarea}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. A neon koi fish swimming through a cyberpunk city, highly detailed"
              spellCheck={false}
            />
          </div>

          <div style={S.field}>
            <label style={S.label}>Style modifier <span style={{ color: C.muted, fontWeight: 400 }}>(optional)</span></label>
            <input
              style={S.input}
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              placeholder="e.g. watercolor, 3D render, photorealistic, pixel art"
            />
          </div>

          <div style={{ ...S.field, marginBottom: 10 }}>
            <label style={S.label}>Dimensions</label>
            <div style={S.dimRow}>
              <div style={S.dimField}>
                <div style={{ ...S.hint, marginTop: 0, marginBottom: 4 }}>Width</div>
                <input
                  type="number"
                  style={S.dimInput}
                  value={width}
                  min={64}
                  max={1536}
                  onChange={(e) => setWidth(e.target.value)}
                  onBlur={(e) => setWidth(clampDim(e.target.value))}
                />
              </div>
              <div style={{ color: C.muted, paddingBottom: 9 }}>×</div>
              <div style={S.dimField}>
                <div style={{ ...S.hint, marginTop: 0, marginBottom: 4 }}>Height</div>
                <input
                  type="number"
                  style={S.dimInput}
                  value={height}
                  min={64}
                  max={1536}
                  onChange={(e) => setHeight(e.target.value)}
                  onBlur={(e) => setHeight(clampDim(e.target.value))}
                />
              </div>
            </div>
          </div>

          <div style={{ ...S.presets, marginBottom: 16 }}>
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                style={{ ...S.preset, ...(matchesPreset(p) ? S.presetActive : {}) }}
                onClick={() => { setWidth(p.w); setHeight(p.h); }}
              >
                {p.label} {p.w}×{p.h}
              </button>
            ))}
          </div>

          <div style={S.row}>
            <button
              type="button"
              style={{ ...S.btn, ...(canGenerate ? {} : S.btnDisabled) }}
              onClick={generate}
              disabled={!canGenerate}
            >
              {loading ? 'Generating…' : 'Generate'}
            </button>
            {!prompt.trim() && <span style={S.hint}>Enter a prompt to generate.</span>}
          </div>

          {error && <div style={S.err}>{error}</div>}
        </div>

        {loading && (
          <div style={S.card}>
            <div style={S.loadingBox}>
              <span style={S.spinner} />
              Generating your image — this can take 20–40 seconds…
            </div>
          </div>
        )}

        {result && result.image_url && !loading && (
          <div style={S.card}>
            <div style={S.previewLabel}>Result</div>
            <div style={S.imgWrap}>
              <img style={S.img} src={result.image_url} alt={result.prompt || prompt} />
            </div>
            <div style={S.row}>
              <button
                type="button"
                style={{ ...S.btn, ...(downloading ? S.btnDisabled : {}) }}
                onClick={download}
                disabled={downloading}
              >
                {downloading ? 'Downloading…' : 'Download'}
              </button>
              <button type="button" style={S.btnGhost} onClick={generate}>Regenerate</button>
            </div>
            <div style={S.meta}>
              {clampDim(width)}×{clampDim(height)}
              {result.provider ? ` · ${result.provider}` : ''}
            </div>
          </div>
        )}
      </div>

      <style>{`@keyframes cd-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
