import React, { useState } from 'react';
import RuntimeBadge from './RuntimeBadge';

// Phase 19 slice 6 — user-triggered code execution. Nothing runs without a
// click. Renders ONLY when the backend marked the message runnable
// (response.runnable.eligible === true) AND exactly one python/js block is
// found client-side (mirror of backend/runtime_engine/execution_policy.py).
// Results render through the Slice 5 RuntimeBadge (uppercase status map);
// "Executed" therefore can only ever come from a real SUCCESS result.

const _NON_CODE_TAGS = new Set(['chart', 'mermaid']);
const _LANG_MAP = { python: 'python', py: 'python', python3: 'python', javascript: 'javascript', js: 'javascript', node: 'javascript' };

export function extractRunnableBlock(text) {
  const fences = [];
  const re = /```(\w*)[ \t]*\n?([\s\S]*?)```/g;
  let m;
  while ((m = re.exec(String(text || ''))) !== null) {
    const tag = (m[1] || '').toLowerCase();
    if (!_NON_CODE_TAGS.has(tag)) fences.push({ tag, code: (m[2] || '').trim() });
  }
  if (fences.length !== 1) return null;           // single-block rule, same as backend
  const language = _LANG_MAP[fences[0].tag];
  if (!language || !fences[0].code) return null;
  return { language, code: fences[0].code };
}

// Client-side courtesy gate for the MANUAL code box: blocks SUBMIT on obvious
// empty / pure-prose only, to avoid firing a request for "Explain AI". LENIENT by
// design — the backend appears_executable() validator is authoritative. Call this
// on SUBMIT only; never on keystroke, never to block typing.
export function looksLikeCode(code) {
  const s = String(code || '').trim();
  if (!s) return false; // empty -> block submit
  if (/[(){};=]|\[|\]|=>|\b(?:def|class|function|const|let|var|import|from|return|for|while|if|elif|else|print|console|lambda)\b/.test(s)) return true;
  if (/\n/.test(s)) return true; // multi-line -> allow (could be code)
  const words = s.split(/\s+/).filter(Boolean);
  // single line, no code punctuation: 2+ plain words reading as prose -> block
  if (words.length >= 2 && /^[A-Za-z][A-Za-z ,.'"?!:;-]*$/.test(s)) return false;
  return true; // default lenient
}

function unknownResult(language, message) {
  // Shape matches the backend model so RuntimeBadge renders it verbatim.
  return {
    status: 'UNKNOWN', language, stdout: '', stderr: '', exit_code: null,
    execution_ms: null, timed_out: false, truncated: false,
    runtime_source: 'piston', error: message,
  };
}

export default function RunCodeButton({ messageText, runnable, apiBase, token }) {
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);

  // No eligible flag / flag false / old responses without runnable -> nothing.
  if (!runnable || runnable.eligible !== true) return null;
  const block = extractRunnableBlock(messageText);
  if (!block) return null;

  const run = async () => {
    setRunning(true);
    setResult(null);
    try {
      const r = await fetch(`${apiBase}/runtime/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
          ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ language: block.language, code: block.code }),
      });
      if (r.ok) {
        setResult(await r.json());
      } else if (r.status === 403 || r.status === 404) {
        setResult(unknownResult(block.language, 'Execution is disabled on this server'));
      } else {
        setResult(unknownResult(block.language, `execute endpoint http ${r.status}`));
      }
    } catch (e) {
      setResult(unknownResult(block.language, `execute request failed: ${e.message}`));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ marginTop: 8 }}>
      <button
        type="button"
        data-testid="run-code-btn"
        onClick={run}
        disabled={running}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11,
          fontWeight: 600, padding: '5px 12px', borderRadius: 8, cursor: running ? 'wait' : 'pointer',
          color: '#e9d5ff', background: 'rgba(124,58,237,.18)', border: '1px solid rgba(139,92,246,.45)',
        }}
      >
        {running ? '… Running' : `▶ Run ${block.language}`}
      </button>
      {result && <div style={{ marginTop: 6 }}><RuntimeBadge runtime={result} /></div>}
    </div>
  );
}
