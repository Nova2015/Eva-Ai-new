import React from 'react';

// Phase 19 slice 5 — runtime execution badge + output panel.
//
// Adapter maps the REAL backend fields (backend/runtime_engine make_result):
//   { status(UPPERCASE), language, stdout, stderr, exit_code, execution_ms,
//     timed_out, truncated, runtime_source, error }
// into the UI shape { language, status, stdout, stderr, duration_ms,
// truncated, source }. `executed` is DERIVED, never stored: only
// SUCCESS / RUNTIME_ERROR / TIMEOUT mean the code actually ran.
// Exactly the backend's 4 states — no invented ones (no compile_error:
// python3/javascript on Piston have no compile stage). Unrecognized or
// non-uppercase status values render NOTHING (safe default, never crash,
// never a hardcoded "Executed").

export function adaptRuntime(runtime) {
  if (!runtime || typeof runtime !== 'object' || Array.isArray(runtime)) return null;
  if (typeof runtime.status !== 'string') return null;
  return {
    language: typeof runtime.language === 'string' ? runtime.language : '',
    status: runtime.status, // pass through EXACT backend value
    stdout: typeof runtime.stdout === 'string' ? runtime.stdout : '',
    stderr: typeof runtime.stderr === 'string' ? runtime.stderr : '',
    duration_ms: Number.isFinite(runtime.execution_ms) ? runtime.execution_ms : null,
    truncated: runtime.truncated === true,
    source: typeof runtime.runtime_source === 'string' ? runtime.runtime_source : 'piston',
    error: typeof runtime.error === 'string' ? runtime.error : null,
  };
}

export function isExecuted(adapted) {
  return !!adapted && ['SUCCESS', 'RUNTIME_ERROR', 'TIMEOUT'].includes(adapted.status);
}

const RUNTIME_MAP = {
  SUCCESS:       { label: 'Executed',          color: '#22c55e', bg: 'rgba(34,197,94,.12)',   border: 'rgba(34,197,94,.35)' },
  RUNTIME_ERROR: { label: 'Runtime Error',     color: '#ef4444', bg: 'rgba(239,68,68,.12)',   border: 'rgba(239,68,68,.35)' },
  TIMEOUT:       { label: 'Timeout',           color: '#f97316', bg: 'rgba(249,115,22,.12)',  border: 'rgba(249,115,22,.35)' },
  UNKNOWN:       { label: 'Execution Unknown', color: '#9ca3af', bg: 'rgba(156,163,175,.12)', border: 'rgba(156,163,175,.35)' },
  // Not runnable code — input did not parse as code (pure prose). DISTINCT from
  // RUNTIME_ERROR (code RAN and failed) and never merged with it. No suggestion block.
  INVALID_INPUT: { label: 'Not runnable code', color: '#f59e0b', bg: 'rgba(245,158,11,.12)', border: 'rgba(245,158,11,.4)', icon: '⚠' },
};

const COLLAPSE_THRESHOLD = 2000; // chars; larger outputs start collapsed

function OutputSection({ title, text, testId }) {
  const body = text || '';
  const open = body.length <= COLLAPSE_THRESHOLD;
  return (
    <details open={open} data-testid={testId} style={{ marginTop: 6 }}>
      <summary style={{ cursor: 'pointer', fontSize: 10, color: '#8b6fc7', fontWeight: 600 }}>
        {title}{!open ? ` (${body.length.toLocaleString()} chars — click to expand)` : ''}
      </summary>
      <pre style={{ margin: '4px 0 0', padding: '8px 10px', background: '#0e0820', border: '1px solid #2d1b5e', borderRadius: 8, overflowX: 'auto', maxHeight: 260, overflowY: 'auto', fontSize: 11, color: '#f0e8ff', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
        {body || '(no stdout)'}
      </pre>
    </details>
  );
}

export default function RuntimeBadge({ runtime }) {
  const a = adaptRuntime(runtime);
  if (!a) return null;
  const s = RUNTIME_MAP[a.status]; // exact uppercase switch
  if (!s) return null;             // lowercase/garbage -> safe default: nothing

  const executed = isExecuted(a);

  return (
    <div style={{ marginBottom: 6, lineHeight: 1 }}>
      <span
        data-testid="runtime-badge"
        title={`Code execution: ${a.status} (via ${a.source})`}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10,
          fontWeight: 600, lineHeight: 1, padding: '3px 8px', borderRadius: 999,
          color: s.color, background: s.bg, border: `1px solid ${s.border}`,
          whiteSpace: 'nowrap', verticalAlign: 'middle',
        }}
      >
        {s.icon || '▶'} {s.label}
      </span>

      {a.status === 'INVALID_INPUT' && a.error && (
        <div data-testid="runtime-invalid-msg" style={{ marginTop: 4, fontSize: 11, color: '#c99a3a' }}>
          {a.error}
        </div>
      )}

      {executed && (
        <div data-testid="runtime-panel" style={{ marginTop: 4 }}>
          <OutputSection title="stdout" text={a.stdout} testId="runtime-stdout" />
          {(a.stderr || '').length > 0 && (
            <OutputSection title="stderr" text={a.stderr} testId="runtime-stderr" />
          )}
          <div data-testid="runtime-meta" style={{ marginTop: 4, fontSize: 10, color: '#8b6fc7' }}>
            {a.language || '?'} · {a.source}
            {a.duration_ms !== null ? ` · ${a.duration_ms} ms` : ''}
            {a.truncated ? ' · output truncated' : ''}
          </div>
        </div>
      )}
    </div>
  );
}
