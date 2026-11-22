import { useState } from 'react';

// EVA Theme Factory — v1 (functional page, not a modal).
// Scope: a form (name, base color, accent strategy, appearance, description) that
// deterministically generates a CSS-variables / design-tokens file for download.
// No LLM call — the palette is derived from the base color via client-side color math.

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
  wrap: { maxWidth: 820, margin: '0 auto' },
  head: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 },
  title: { fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em' },
  sub: { color: C.muted, fontSize: 13, marginBottom: 22 },
  back: { background: 'transparent', border: `1px solid ${C.border}`, color: C.text2, borderRadius: 8, padding: '6px 12px', fontSize: 12, cursor: 'pointer' },
  card: { background: C.panel, border: `1px solid ${C.border}`, borderRadius: 14, padding: 18, marginBottom: 16 },
  label: { display: 'block', fontSize: 12, fontWeight: 600, color: C.text2, marginBottom: 6 },
  hint: { fontSize: 11, color: C.muted, marginTop: 4 },
  input: { width: '100%', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '9px 11px', color: C.text, fontSize: 13, outline: 'none', boxSizing: 'border-box' },
  textarea: { width: '100%', minHeight: 70, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 12px', color: C.text, fontSize: 13, lineHeight: 1.5, outline: 'none', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' },
  select: { width: '100%', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '9px 11px', color: C.text, fontSize: 13, outline: 'none', boxSizing: 'border-box' },
  field: { marginBottom: 14 },
  grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
  row: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' },
  colorRow: { display: 'flex', alignItems: 'center', gap: 10 },
  colorSwatch: { width: 42, height: 42, padding: 0, border: `1px solid ${C.border}`, borderRadius: 8, background: 'transparent', cursor: 'pointer' },
  seg: { display: 'flex', gap: 6 },
  segBtn: { background: 'transparent', border: `1px solid ${C.border}`, color: C.text2, borderRadius: 8, padding: '7px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer' },
  segActive: { background: 'rgba(124,58,237,0.22)', borderColor: C.accent, color: '#c084fc' },
  btn: { background: `linear-gradient(135deg,${C.accent},${C.accent2})`, border: 'none', color: '#fff', borderRadius: 9, padding: '10px 18px', fontSize: 13, fontWeight: 700, cursor: 'pointer' },
  btnGhost: { background: 'transparent', border: `1px solid ${C.border}`, color: C.text2, borderRadius: 9, padding: '10px 16px', fontSize: 13, fontWeight: 700, cursor: 'pointer' },
  btnDisabled: { opacity: 0.45, cursor: 'not-allowed' },
  ok: { color: '#34d399', fontSize: 12, fontWeight: 600 },
  previewLabel: { fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: C.muted, marginBottom: 10 },
  scaleRow: { display: 'flex', borderRadius: 8, overflow: 'hidden', border: `1px solid ${C.border}`, marginBottom: 10 },
  swatch: { flex: 1, height: 40, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', fontSize: 9, paddingBottom: 2 },
  semWrap: { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 },
  semChip: { borderRadius: 8, padding: '6px 12px', fontSize: 11, fontWeight: 700 },
  pre: { margin: 0, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, color: C.text2, fontSize: 11.5, lineHeight: 1.55, whiteSpace: 'pre', wordBreak: 'normal', maxHeight: 300, overflow: 'auto', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace' },
  noteBox: { background: 'rgba(124,58,237,0.08)', border: `1px solid ${C.border}`, borderRadius: 10, padding: '12px 14px', fontSize: 12, color: C.text2, lineHeight: 1.5 },
};

// ── Color math (no dependencies) ──────────────────────────────────────────────
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function hexToRgb(hex) {
  let h = (hex || '').replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return { r: 124, g: 58, b: 237 };
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
function rgbToHex(r, g, b) {
  const h = (x) => clamp(Math.round(x), 0, 255).toString(16).padStart(2, '0');
  return '#' + h(r) + h(g) + h(b);
}
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0; const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
  }
  return { h: h * 360, s: s * 100, l: l * 100 };
}
function hslToHex(h, s, l) {
  h = ((h % 360) + 360) % 360; s = clamp(s, 0, 100) / 100; l = clamp(l, 0, 100) / 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return rgbToHex(f(0) * 255, f(8) * 255, f(4) * 255);
}
function hexToHsl(hex) { const { r, g, b } = hexToRgb(hex); return rgbToHsl(r, g, b); }

const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];
const L_TARGETS = { 50: 96, 100: 90, 200: 81, 300: 70, 400: 60, 500: 50, 600: 42, 700: 34, 800: 25, 900: 16 };

function buildScale(hue, sat) {
  const out = {};
  STEPS.forEach((s) => { out[s] = hslToHex(hue, sat, L_TARGETS[s]); });
  return out;
}

function generatePalette(baseHex, strategy, appearance) {
  const base = hexToHsl(baseHex);
  const brandSat = clamp(base.s, 24, 92);
  const brand = buildScale(base.h, brandSat);
  const neutral = buildScale(base.h, 8);

  let accentHex;
  if (strategy === 'monochrome') {
    accentHex = hslToHex(base.h, brandSat, clamp(base.l + (appearance === 'dark' ? 16 : -10), 10, 90));
  } else {
    const accentH = strategy === 'analogous' ? base.h + 32 : base.h + 180; // complementary default
    accentHex = hslToHex(accentH, clamp(base.s, 42, 90), 54);
  }

  const semantic = {
    success: hslToHex(145, 55, 42),
    warning: hslToHex(38, 92, 50),
    error: hslToHex(4, 72, 52),
    info: hslToHex(base.h, clamp(base.s, 42, 80), 50),
  };
  const semanticBg = appearance === 'dark'
    ? { success: hslToHex(145, 40, 15), warning: hslToHex(38, 48, 15), error: hslToHex(4, 46, 16), info: hslToHex(base.h, 40, 16) }
    : { success: hslToHex(145, 58, 94), warning: hslToHex(38, 92, 91), error: hslToHex(4, 80, 95), info: hslToHex(base.h, 60, 95) };

  const surface = appearance === 'dark'
    ? { background: neutral[900], surface: neutral[800], text: neutral[50], textMuted: neutral[400], border: neutral[700] }
    : { background: neutral[50], surface: '#ffffff', text: neutral[900], textMuted: neutral[600], border: neutral[200] };

  return { brand, neutral, accent: accentHex, primary: brand[500], semantic, semanticBg, surface };
}

function slugify(name) {
  const s = (name || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'eva-theme';
}

function buildCss(name, baseHex, strategy, appearance, description, P) {
  const lines = [];
  lines.push(`/* ${name.trim() || 'EVA Theme'} — generated by EVA Theme Factory */`);
  lines.push(`/* Base ${baseHex} · ${strategy} accent · ${appearance} appearance */`);
  if (description.trim()) lines.push(`/* ${description.trim().replace(/\*\//g, '* /')} */`);
  lines.push('');
  lines.push(':root {');
  lines.push('  /* Brand scale */');
  STEPS.forEach((s) => lines.push(`  --brand-${s}: ${P.brand[s]};`));
  lines.push(`  --color-primary: var(--brand-500);`);
  lines.push(`  --color-accent: ${P.accent};`);
  lines.push('');
  lines.push('  /* Neutral scale */');
  STEPS.forEach((s) => lines.push(`  --neutral-${s}: ${P.neutral[s]};`));
  lines.push('');
  lines.push('  /* Semantic */');
  ['success', 'warning', 'error', 'info'].forEach((k) => {
    lines.push(`  --color-${k}: ${P.semantic[k]};`);
    lines.push(`  --color-${k}-bg: ${P.semanticBg[k]};`);
  });
  lines.push('');
  lines.push('  /* Surface */');
  lines.push(`  --color-background: ${P.surface.background};`);
  lines.push(`  --color-surface: ${P.surface.surface};`);
  lines.push(`  --color-text: ${P.surface.text};`);
  lines.push(`  --color-text-muted: ${P.surface.textMuted};`);
  lines.push(`  --color-border: ${P.surface.border};`);
  lines.push('');
  lines.push('  /* Radius */');
  lines.push('  --radius-sm: 6px;');
  lines.push('  --radius-md: 10px;');
  lines.push('  --radius-lg: 16px;');
  lines.push('  --radius-full: 9999px;');
  lines.push('');
  lines.push('  /* Spacing */');
  [['1', '4px'], ['2', '8px'], ['3', '12px'], ['4', '16px'], ['5', '24px'], ['6', '48px']].forEach(([k, v]) => lines.push(`  --space-${k}: ${v};`));
  lines.push('');
  lines.push('  /* Typography */');
  lines.push('  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;');
  lines.push('}');
  lines.push('');
  return lines.join('\n');
}

function buildJson(name, baseHex, strategy, appearance, description, P) {
  const tokens = {
    name: name.trim() || 'EVA Theme',
    meta: { base: baseHex, accentStrategy: strategy, appearance, description: description.trim() || undefined, generatedBy: 'EVA Theme Factory' },
    color: {
      brand: P.brand,
      neutral: P.neutral,
      primary: P.primary,
      accent: P.accent,
      success: P.semantic.success, successBg: P.semanticBg.success,
      warning: P.semantic.warning, warningBg: P.semanticBg.warning,
      error: P.semantic.error, errorBg: P.semanticBg.error,
      info: P.semantic.info, infoBg: P.semanticBg.info,
      background: P.surface.background, surface: P.surface.surface,
      text: P.surface.text, textMuted: P.surface.textMuted, border: P.surface.border,
    },
    radius: { sm: '6px', md: '10px', lg: '16px', full: '9999px' },
    space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '24px', 6: '48px' },
    font: { sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' },
  };
  return JSON.stringify(tokens, null, 2);
}

const STRATEGIES = [
  { value: 'complementary', label: 'Complementary (opposite hue)' },
  { value: 'analogous', label: 'Analogous (nearby hue)' },
  { value: 'monochrome', label: 'Monochrome (same hue)' },
];

export default function ThemeFactory() {
  const [name, setName] = useState('');
  const [baseColor, setBaseColor] = useState('#7c3aed');
  const [strategy, setStrategy] = useState('complementary');
  const [appearance, setAppearance] = useState('light');
  const [description, setDescription] = useState('');
  const [format, setFormat] = useState('css');
  const [saved, setSaved] = useState(false);

  const validHex = /^#?[0-9a-fA-F]{6}$/.test(baseColor.replace('#', '').length === 3 ? '#000000' : baseColor) || /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(baseColor);
  const palette = generatePalette(baseColor, strategy, appearance);
  const fileText = format === 'css'
    ? buildCss(name, baseColor, strategy, appearance, description, palette)
    : buildJson(name, baseColor, strategy, appearance, description, palette);
  const ext = format === 'css' ? 'css' : 'tokens.json';

  const download = () => {
    const blob = new Blob([fileText], { type: format === 'css' ? 'text/css;charset=utf-8' : 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${slugify(name)}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(fileText);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (_) { /* clipboard unavailable */ }
  };

  const onHexInput = (v) => {
    let val = v.trim();
    if (val && !val.startsWith('#')) val = '#' + val;
    setBaseColor(val);
  };

  const goBack = () => {
    if (window.history.length > 1) window.history.back();
    else window.location.assign('/chat');
  };

  return (
    <div style={S.page}>
      <div style={S.wrap}>
        <div style={S.head}>
          <div style={S.title}>🎭 Theme Factory</div>
          <button type="button" style={S.back} onClick={goBack}>← Back</button>
        </div>
        <div style={S.sub}>Generate a color system and download it as CSS variables or design tokens.</div>

        <div style={S.card}>
          <div style={S.field}>
            <label style={S.label}>Theme name</label>
            <input
              style={S.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Midnight Violet"
              spellCheck={false}
            />
            <div style={S.hint}>Saves as <code>{slugify(name)}.{ext}</code></div>
          </div>

          <div style={S.grid2}>
            <div style={S.field}>
              <label style={S.label}>Base color</label>
              <div style={S.colorRow}>
                <input
                  type="color"
                  style={S.colorSwatch}
                  value={/^#[0-9a-fA-F]{6}$/.test(baseColor) ? baseColor : '#7c3aed'}
                  onChange={(e) => setBaseColor(e.target.value)}
                  aria-label="Base color picker"
                />
                <input
                  style={{ ...S.input, fontFamily: 'ui-monospace,monospace' }}
                  value={baseColor}
                  onChange={(e) => onHexInput(e.target.value)}
                  placeholder="#7c3aed"
                  spellCheck={false}
                />
              </div>
              {!validHex && <div style={{ ...S.hint, color: '#f87171' }}>Enter a 6-digit hex like #7c3aed.</div>}
            </div>

            <div style={S.field}>
              <label style={S.label}>Accent strategy</label>
              <select style={S.select} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
          </div>

          <div style={S.field}>
            <label style={S.label}>Appearance</label>
            <div style={S.seg}>
              {['light', 'dark'].map((a) => (
                <button
                  key={a}
                  type="button"
                  style={{ ...S.segBtn, ...(appearance === a ? S.segActive : {}) }}
                  onClick={() => setAppearance(a)}
                >
                  {a === 'light' ? '☀ Light' : '🌙 Dark'}
                </button>
              ))}
            </div>
          </div>

          <div style={S.field}>
            <label style={S.label}>Style description <span style={{ color: C.muted, fontWeight: 400 }}>(optional)</span></label>
            <textarea
              style={S.textarea}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Notes about the mood or usage — added as a comment in the output."
              spellCheck={false}
            />
          </div>

          <div style={{ ...S.field, marginBottom: 6 }}>
            <label style={S.label}>Output format</label>
            <div style={S.seg}>
              {[['css', 'CSS variables'], ['json', 'JSON tokens']].map(([v, lbl]) => (
                <button
                  key={v}
                  type="button"
                  style={{ ...S.segBtn, ...(format === v ? S.segActive : {}) }}
                  onClick={() => setFormat(v)}
                >
                  {lbl}
                </button>
              ))}
            </div>
          </div>

          <div style={{ ...S.row, marginTop: 10 }}>
            <button type="button" style={S.btn} onClick={download}>Download .{ext}</button>
            <button type="button" style={S.btnGhost} onClick={copy}>Copy</button>
            {saved && <span style={S.ok}>✓ Done</span>}
          </div>
        </div>

        <div style={S.card}>
          <div style={S.previewLabel}>Palette preview</div>

          <div style={{ fontSize: 10, color: C.muted, marginBottom: 4 }}>Brand</div>
          <div style={S.scaleRow}>
            {STEPS.map((s) => (
              <div key={s} style={{ ...S.swatch, background: palette.brand[s], color: s >= 400 ? '#fff' : '#000' }}>{s}</div>
            ))}
          </div>

          <div style={{ fontSize: 10, color: C.muted, marginBottom: 4 }}>Neutral</div>
          <div style={S.scaleRow}>
            {STEPS.map((s) => (
              <div key={s} style={{ ...S.swatch, background: palette.neutral[s], color: s >= 400 ? '#fff' : '#000' }}>{s}</div>
            ))}
          </div>

          <div style={S.semWrap}>
            <span style={{ ...S.semChip, background: palette.accent, color: '#fff' }}>accent</span>
            <span style={{ ...S.semChip, background: palette.semantic.success, color: '#fff' }}>success</span>
            <span style={{ ...S.semChip, background: palette.semantic.warning, color: '#000' }}>warning</span>
            <span style={{ ...S.semChip, background: palette.semantic.error, color: '#fff' }}>error</span>
            <span style={{ ...S.semChip, background: palette.semantic.info, color: '#fff' }}>info</span>
          </div>

          <div style={{ background: palette.surface.background, border: `1px solid ${palette.surface.border}`, borderRadius: 10, padding: 14 }}>
            <div style={{ color: palette.surface.text, fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Sample card</div>
            <div style={{ color: palette.surface.textMuted, fontSize: 12, marginBottom: 10 }}>Text on your generated surface tokens.</div>
            <button type="button" style={{ background: palette.primary, color: '#fff', border: 'none', borderRadius: 8, padding: '7px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>Primary action</button>
          </div>
        </div>

        <div style={S.card}>
          <div style={S.previewLabel}>{format === 'css' ? 'CSS preview' : 'JSON preview'}</div>
          <pre style={S.pre}>{fileText}</pre>
        </div>

        <div style={S.noteBox}>
          This generator builds the theme deterministically from your base color — no AI call.
          An AI-assisted "describe the vibe, get a theme" mode would be a separate, larger feature.
        </div>
      </div>
    </div>
  );
}
