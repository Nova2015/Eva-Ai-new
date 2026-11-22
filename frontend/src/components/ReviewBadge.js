import React from 'react';

// Phase 19 slice 3 — response-review UI above assistant messages.
//
// Reads the backend payload VERBATIM. Zero status logic client-side: no
// recomputing from score/issues, no per-code-block badges. Informational
// only — the message content always renders fully regardless of status.
//
// Backend contract (grepped from src/app.py + integration_adapter.py):
//   always:      message.review = { status: "VALID"|"WARNING"|"FAILED"|"UNKNOWN"|null, badge: bool }
//   debug only:  + { valid, score, issues:[{code,detail}], checks,
//                    review_meta:{ mode, validator_version, execution_ms, error } }
// So the warning list and debug panel can only appear under DEBUG_REVIEW /
// request.debug_review — the minimal payload has no `issues`.
const STATUS_MAP = {
  VALID:   { label: '✓ Validated', color: '#22c55e', bg: 'rgba(34,197,94,.12)',   border: 'rgba(34,197,94,.35)' },
  WARNING: { label: '⚠ Warning',   color: '#f59e0b', bg: 'rgba(245,158,11,.12)',  border: 'rgba(245,158,11,.35)' },
  FAILED:  { label: '✗ Invalid',   color: '#ef4444', bg: 'rgba(239,68,68,.12)',   border: 'rgba(239,68,68,.35)' },
  UNKNOWN: { label: '? Unknown',   color: '#9ca3af', bg: 'rgba(156,163,175,.12)', border: 'rgba(156,163,175,.35)' },
};

// EXACT issue codes emitted by backend/review_engine validators (all 12).
const ISSUE_LABELS = {
  claim_without_block:  'Chart mentioned but missing',
  malformed_block:      'Invalid chart structure',
  empty_data:           'Chart has no data',
  merged_datasets:      'Datasets may be merged',
  missing_diagram_type: 'Diagram type missing',
  empty_diagram:        'Empty diagram',
  unbalanced_brackets:  'Mermaid syntax issue',
  prose_not_diagram:    'Diagram contains prose',
  python_syntax_error:  'Python syntax error',
  json_parse_error:     'JSON parse failure',
  js_syntax_error:      'JavaScript syntax issue',
  unclosed_fence:       'Unclosed code block',
};

function safeIssues(review) {
  const issues = review && review.issues;
  if (!Array.isArray(issues)) return [];
  return issues
    .filter((i) => i && typeof i === 'object' && typeof i.code === 'string')
    .map((i) => ({ code: i.code, label: ISSUE_LABELS[i.code] || i.code }));
}

export default function ReviewBadge({ review }) {
  // PART C — safe fallbacks: missing/malformed review, non-string status,
  // undefined issues/checks: render nothing, never throw. Silence is default.
  let pill = null;
  try {
    if (!review || typeof review !== 'object' || review.badge !== true) return null;
    if (typeof review.status !== 'string') return null;
    pill = STATUS_MAP[review.status];
    if (!pill) return null;
  } catch (_) {
    return null;
  }

  const issues = safeIssues(review);
  const meta = review.review_meta && typeof review.review_meta === 'object' ? review.review_meta : null;

  return (
    <div style={{ minHeight: 20, marginBottom: 6, lineHeight: 1 }}>
      <span
        data-testid="review-badge"
        title={`Response check: ${review.status}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 10,
          fontWeight: 600,
          lineHeight: 1,
          padding: '3px 8px',
          borderRadius: 999,
          color: pill.color,
          background: pill.bg,
          border: `1px solid ${pill.border}`,
          whiteSpace: 'nowrap',
          verticalAlign: 'middle',
        }}
      >
        {pill.label}
      </span>

      {issues.length > 0 && (
        <ul
          data-testid="review-issues"
          style={{ margin: '6px 0 0', padding: '0 0 0 16px', listStyle: 'disc' }}
        >
          {issues.map((i, idx) => (
            <li key={idx} style={{ fontSize: 11, color: '#b29dd9', marginBottom: 2 }}>
              {i.label}
            </li>
          ))}
        </ul>
      )}

      {meta && (
        <details data-testid="review-debug" style={{ marginTop: 4, fontSize: 10, color: '#8b6fc7' }}>
          <summary style={{ cursor: 'pointer' }}>review debug</summary>
          <div style={{ padding: '4px 0 0 8px' }}>
            <div>status: {String(review.status)}</div>
            <div>score: {String(review.score)} (check-ratio, not a quality score)</div>
            <div>execution_ms: {String(meta.execution_ms)}</div>
            <div>issues: {issues.length ? issues.map((i) => i.code).join(', ') : 'none'}</div>
            {meta.error ? <div>error: {String(meta.error)}</div> : null}
          </div>
        </details>
      )}
    </div>
  );
}
