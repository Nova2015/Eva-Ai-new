/**
 * EVA VoiceCommand.js
 * Full voice pipeline: STT → intent classification → action dispatch → TTS response
 * Drop into any EVA page with: <VoiceCommand API={API} onTranscript={fn} onAction={fn} />
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { Mic, Square, Volume2, VolumeX, Zap } from 'lucide-react';

// ── Intent classifier ──────────────────────────────────────────
const INTENT_PATTERNS = [
  { intent: 'navigate',    patterns: [/^(go to|open|navigate to|show me)\s+(.+)/i] },
  { intent: 'search',      patterns: [/^(search|find|look up|what is|who is|tell me about)\s+(.+)/i] },
  { intent: 'code',        patterns: [/^(write|create|build|generate|fix|debug|explain this code)\s+(.+)/i] },
  { intent: 'upload',      patterns: [/^(upload|attach|add file|load document)\s*(.*)/i] },
  { intent: 'image',       patterns: [/^(create image|generate image|draw|make a picture of)\s+(.+)/i] },
  { intent: 'system',      patterns: [/^(status|health|check system|is .* running|ping|uptime)/i] },
  { intent: 'stop',        patterns: [/^(stop|cancel|halt|abort|nevermind|never mind)$/i] },
  { intent: 'chat',        patterns: [/.+/] }, // catch-all
];

function classifyIntent(transcript) {
  const t = transcript.trim();
  for (const { intent, patterns } of INTENT_PATTERNS) {
    for (const p of patterns) {
      const m = t.match(p);
      if (m) return { intent, match: m };
    }
  }
  return { intent: 'chat', match: null };
}

// Navigate intent → map keyword to route
const NAV_MAP = {
  chat: '/chat', home: '/chat', rag: '/rag', 'rag center': '/rag',
  upload: '/upload', files: '/upload', code: '/code', 'code assistant': '/code',
  agents: '/agents', agent: '/agents', studio: '/studio', 'ai studio': '/studio',
  security: '/security', analytics: '/analytics', settings: '/settings',
  memory: '/memory', team: '/team', billing: '/billing',
};

function resolveNavTarget(match) {
  const raw = (match[2] || '').toLowerCase().trim();
  return NAV_MAP[raw] || null;
}

// ── TTS helper ─────────────────────────────────────────────────
function speak(text, enabled) {
  if (!enabled || !text || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text.slice(0, 300));
  utt.lang = 'en-US'; utt.rate = 1.05; utt.pitch = 1.0;
  const voices = window.speechSynthesis.getVoices();
  const v = voices.find(v => v.name.includes('Google') && v.lang === 'en-US')
         || voices.find(v => v.lang.startsWith('en'));
  if (v) utt.voice = v;
  window.speechSynthesis.speak(utt);
}

// ── Component ──────────────────────────────────────────────────
export default function VoiceCommand({ API, onTranscript, onAction, navigate = null }) {
  const [listening, setListening]   = useState(false);
  const [transcript, setTranscript] = useState('');
  const [intent, setIntent]         = useState(null);
  const [feedback, setFeedback]     = useState('');
  const [ttsEnabled, setTtsEnabled] = useState(() => localStorage.getItem('eva_voice_response') !== 'false');
  const [supported, setSupported]   = useState(true);
  const recogRef = useRef(null);

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) setSupported(false);
    // Pre-load voices
    if ('speechSynthesis' in window) window.speechSynthesis.getVoices();
  }, []);

  const dispatch = useCallback(async (text) => {
    const { intent: i, match } = classifyIntent(text);
    setIntent(i);

    if (i === 'stop') {
      window.speechSynthesis?.cancel();
      setFeedback('Stopped.');
      speak('Stopped.', ttsEnabled);
      onAction?.({ type: 'stop' });
      return;
    }

    if (i === 'navigate') {
      const target = resolveNavTarget(match);
      if (target) {
        setFeedback(`Navigating to ${match[2]}…`);
        speak(`Opening ${match[2]}`, ttsEnabled);
        onAction?.({ type: 'navigate', target });
        if (navigate) navigate(target);
      } else {
        setFeedback(`I don't know how to navigate to "${match[2]}".`);
        speak(`I don't know that page.`, ttsEnabled);
      }
      return;
    }

    if (i === 'system') {
      setFeedback('Checking system status…');
      try {
        const token = localStorage.getItem('aria_token');
        const r = await fetch(`${API}/health`, {
          headers: { 'ngrok-skip-browser-warning': 'true', ...(token ? { Authorization: `Bearer ${token}` } : {}) }
        });
        const d = await r.json();
        const msg = `EVA backend is ${d.status || 'online'}. RAG: ${d.rag || 'unknown'}.`;
        setFeedback(msg);
        speak(msg, ttsEnabled);
        onAction?.({ type: 'system_status', data: d });
      } catch {
        const msg = 'Backend not reachable.';
        setFeedback(msg);
        speak(msg, ttsEnabled);
      }
      return;
    }

    // For chat/search/code/image — pass to parent to send through /chat endpoint
    setFeedback(`Sending: "${text}"`);
    onTranscript?.(text);
    onAction?.({ type: i, text });
  }, [API, ttsEnabled, navigate, onTranscript, onAction]);

  const startListening = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR || listening) return;
    const r = new SR();
    recogRef.current = r;
    r.lang = 'en-US';
    r.continuous = false;
    r.interimResults = false;
    r.onstart = () => setListening(true);
    r.onresult = e => {
      const t = e.results[0][0].transcript.trim();
      setTranscript(t);
      setListening(false);
      dispatch(t);
    };
    r.onerror = () => { setListening(false); setFeedback('Microphone error — check permissions.'); };
    r.onend   = () => setListening(false);
    r.start();
  }, [listening, dispatch]);

  const stopListening = () => {
    recogRef.current?.stop();
    setListening(false);
  };

  const toggleTts = () => {
    const next = !ttsEnabled;
    setTtsEnabled(next);
    localStorage.setItem('eva_voice_response', String(next));
  };

  const INTENT_COLORS = {
    chat: '#7c3aed', navigate: '#0891b2', search: '#059669',
    code: '#d97706', image: '#db2777', system: '#475569',
    upload: '#0891b2', stop: '#dc2626',
  };

  if (!supported) return (
    <div style={{ padding: '10px 14px', background: 'var(--color-background-secondary)', borderRadius: 8, fontSize: 12, color: 'var(--color-text-secondary)', border: '0.5px solid var(--color-border-tertiary)' }}>
      Voice not supported — use Chrome or Edge.
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Controls row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>

        {/* Main mic button */}
        <button
          onClick={listening ? stopListening : startListening}
          aria-label={listening ? 'Stop listening' : 'Start voice command'}
          style={{
            width: 48, height: 48, borderRadius: '50%',
            background: listening ? '#dc2626' : '#7c3aed',
            border: 'none', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'all 0.2s',
            boxShadow: listening ? '0 0 0 6px rgba(220,38,38,0.18), 0 0 0 12px rgba(220,38,38,0.08)' : 'none',
            animation: listening ? 'eva-pulse 1.4s ease-in-out infinite' : 'none',
          }}
        >
          {listening
            ? <Square size={18} color="#fff" />
            : <Mic size={20} color="#fff" />}
        </button>

        {/* Status text */}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>
            {listening ? '🔴 Listening…' : transcript ? `"${transcript.slice(0, 60)}${transcript.length > 60 ? '…' : ''}"` : 'Tap mic to speak'}
          </div>
          {intent && !listening && (
            <div style={{ fontSize: 11, marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Zap size={11} color={INTENT_COLORS[intent] || '#7c3aed'} />
              <span style={{ color: INTENT_COLORS[intent] || '#7c3aed', fontWeight: 500, textTransform: 'capitalize' }}>{intent}</span>
              <span style={{ color: 'var(--color-text-secondary)' }}>intent detected</span>
            </div>
          )}
        </div>

        {/* TTS toggle */}
        <button
          onClick={toggleTts}
          title={ttsEnabled ? 'Voice response on — click to mute' : 'Voice response off — click to enable'}
          aria-label={ttsEnabled ? 'Mute voice response' : 'Enable voice response'}
          style={{ background: 'none', border: '0.5px solid var(--color-border-secondary)', borderRadius: 8, padding: '6px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, color: ttsEnabled ? '#7c3aed' : 'var(--color-text-secondary)', fontSize: 11 }}
        >
          {ttsEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
          {ttsEnabled ? 'TTS on' : 'TTS off'}
        </button>
      </div>

      {/* Feedback bar */}
      {feedback && (
        <div style={{ fontSize: 12, padding: '7px 12px', background: 'var(--color-background-secondary)', border: '0.5px solid var(--color-border-tertiary)', borderRadius: 8, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
          {feedback}
        </div>
      )}

      {/* Quick command hints */}
      {!listening && !transcript && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {['Go to code', 'Check system status', 'Search for RAG', 'Create a React component'].map(hint => (
            <button key={hint} onClick={() => { setTranscript(hint); dispatch(hint); }}
              style={{ fontSize: 11, padding: '4px 10px', borderRadius: 99, border: '0.5px solid var(--color-border-secondary)', background: 'var(--color-background-secondary)', color: 'var(--color-text-secondary)', cursor: 'pointer' }}>
              {hint}
            </button>
          ))}
        </div>
      )}

      <style>{`
        @keyframes eva-pulse {
          0%, 100% { box-shadow: 0 0 0 4px rgba(220,38,38,0.2), 0 0 0 10px rgba(220,38,38,0.08); }
          50%       { box-shadow: 0 0 0 8px rgba(220,38,38,0.25), 0 0 0 18px rgba(220,38,38,0.05); }
        }
      `}</style>
    </div>
  );
}
