import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Mic, MicOff, Square, Volume2 } from 'lucide-react';
import VoiceOrb from './VoiceOrb';
import { speakWithVoice, cancelSpeech } from '../lib/voiceProfiles';

/**
 * Update 62 — JARVIS Mode (voice layer)
 * =====================================
 * Hands-free loop:  wake word -> capture -> EVA's normal chat pipeline
 *                   -> spoken reply -> re-arm
 *
 * Deliberately thin. It does NOT own a second brain: the captured utterance is
 * dispatched into the existing chat flow (`eva:chat-command` type `send`), so a
 * spoken question goes through the same routing, RAG, memory, security firewall
 * and history as a typed one. Anything EVA can answer, it can answer by voice.
 *
 * Runs entirely in the browser. No new backend surface, no new attack surface.
 *
 * Privacy: SpeechRecognition in Chromium streams microphone audio to Google's
 * speech service. That is a real disclosure, not boilerplate — the consent
 * prompt below says so, wake mode is off by default, and the state persists
 * only after an explicit opt-in.
 */

const WAKE_WORDS = ['hey eva', 'hello eva', 'ok eva', 'hi eva', 'eva'];
const CONSENT_KEY = 'eva_jarvis_consent';
const ENABLED_KEY = 'eva_jarvis_enabled';

const STATES = {
  off: { label: 'Voice off', hint: 'Click to enable hands-free mode' },
  idle: { label: 'Listening for "Hey EVA"', hint: 'Say the wake word to talk' },
  armed: { label: 'Go ahead…', hint: 'Speak your question' },
  thinking: { label: 'Thinking…', hint: 'EVA is answering' },
  speaking: { label: 'Speaking', hint: 'Say anything to interrupt' },
};

function stripWakeWord(text) {
  const lower = text.toLowerCase().trim();
  for (const w of WAKE_WORDS) {
    const i = lower.indexOf(w);
    if (i !== -1) return text.slice(i + w.length).replace(/^[\s,.:!?-]+/, '').trim();
  }
  return null;
}

export default function JarvisMode() {
  const [mode, setMode] = useState('off');
  const [transcript, setTranscript] = useState('');
  const [supported, setSupported] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);   // slice 3: full panel
  const [elapsed, setElapsed] = useState(0);
  const [lastReply, setLastReply] = useState('');

  const recogRef = useRef(null);
  const enabledRef = useRef(false);
  const armedRef = useRef(false);
  const speakingRef = useRef(false);
  const armTimerRef = useRef(null);

  const speak = useCallback((text) => {
    if (!text) return;
    // Delivery now comes from the user's saved voice profile instead of the
    // hardcoded rate 1.02 / pitch 1 this used to use. Markdown stripping moved
    // into toSpokenText (inside speakWithVoice) so Jarvis and the per-message
    // Read-aloud button cannot drift apart.
    //
    // The recogniser still stops while speaking so EVA does not transcribe
    // itself, and barge-in still works: cancelSpeech() surfaces as an
    // 'interrupted' error, which speakWithVoice treats as a normal stop.
    speakWithVoice(text, {}, {
      onstart: () => {
        speakingRef.current = true;
        setMode('speaking');
        try { recogRef.current?.stop(); } catch {}
      },
      onend: () => {
        speakingRef.current = false;
        if (enabledRef.current) {
          setMode('idle');
          try { recogRef.current?.start(); } catch {}
        } else {
          setMode('off');
        }
      },
    });
  }, []);

  const dispatchCommand = useCallback((command) => {
    const full = { id: Date.now(), createdAt: Date.now(), ...command };
    localStorage.setItem('eva_chat_command', JSON.stringify(full));
    window.dispatchEvent(new CustomEvent('eva:chat-command', { detail: full }));
  }, []);

  const send = useCallback((text) => {
    if (!text) return;
    setTranscript(text);

    // Update 63: "open camera" / "take a photo" opens the capture view instead
    // of asking the LLM about it. Everything else is a normal question.
    if (/^(open|start|show|launch)\s+(the\s+)?camera\b|^take\s+(a\s+)?(photo|picture)\b/i.test(text.trim())) {
      dispatchCommand({ type: 'camera' });
      speak('Opening the camera.');
      return;
    }

    setMode('thinking');
    dispatchCommand({ type: 'send', text });
  }, [dispatchCommand, speak]);

  // Speak whatever the chat pipeline finished answering.
  useEffect(() => {
    const onReply = (e) => {
      if (!enabledRef.current) return;
      setLastReply(e.detail?.text || '');
      speak(e.detail?.text || '');
    };
    window.addEventListener('eva:assistant-reply', onReply);
    return () => window.removeEventListener('eva:assistant-reply', onReply);
  }, [speak]);

  // Session timer, only while the panel is open and voice is on.
  useEffect(() => {
    if (!expanded || mode === 'off') { setElapsed(0); return undefined; }
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [expanded, mode]);

  const handleResult = useCallback((event) => {
    let finalText = '';
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const r = event.results[i];
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }

    // Barge-in: any speech while EVA talks cancels the reply.
    if (speakingRef.current && (finalText || interim)) {
      cancelSpeech();
    }

    if (interim && !armedRef.current) setTranscript(interim);
    if (!finalText.trim()) return;

    if (armedRef.current) {
      armedRef.current = false;
      clearTimeout(armTimerRef.current);
      send(finalText.trim());
      return;
    }

    const after = stripWakeWord(finalText);
    if (after === null) return;          // no wake word — ignore entirely
    if (after) { send(after); return; }  // "Hey EVA, what is X" in one breath

    // Wake word alone: arm for the follow-up utterance.
    armedRef.current = true;
    setMode('armed');
    setTranscript('');
    clearTimeout(armTimerRef.current);
    armTimerRef.current = setTimeout(() => {
      armedRef.current = false;
      if (enabledRef.current) setMode('idle');
    }, 8000);
  }, [send]);

  const stopListening = useCallback(() => {
    enabledRef.current = false;
    armedRef.current = false;
    clearTimeout(armTimerRef.current);
    cancelSpeech();
    try { recogRef.current?.stop(); } catch {}
    recogRef.current = null;
    setMode('off');
    setTranscript('');
    localStorage.setItem(ENABLED_KEY, 'false');
  }, []);

  const startListening = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setSupported(false); return; }

    if (localStorage.getItem(CONSENT_KEY) !== 'true') {
      const ok = window.confirm(
        'Enable hands-free voice mode?\n\n'
        + 'EVA will keep the microphone open and listen for "Hey EVA".\n\n'
        + 'Your browser sends microphone audio to its speech-recognition service '
        + '(in Chrome, that is Google) for transcription. Audio is not stored by EVA.\n\n'
        + 'You can turn this off any time with the same button.'
      );
      if (!ok) return;
      localStorage.setItem(CONSENT_KEY, 'true');
    }

    const recog = new SR();
    recog.continuous = true;
    recog.interimResults = true;
    recog.lang = 'en-US';
    recog.onresult = handleResult;
    recog.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setError('Microphone permission denied.');
        stopListening();
      } else if (e.error === 'no-speech' || e.error === 'aborted') {
        // Routine in continuous mode — onend restarts us.
      } else {
        setError(`Speech error: ${e.error}`);
      }
    };
    // Browsers end continuous recognition periodically; restart while enabled.
    recog.onend = () => {
      if (enabledRef.current && !speakingRef.current) {
        try { recog.start(); } catch {}
      }
    };

    recogRef.current = recog;
    enabledRef.current = true;
    setError('');
    setMode('idle');
    localStorage.setItem(ENABLED_KEY, 'true');
    try { recog.start(); } catch { /* already started */ }
  }, [handleResult, stopListening]);

  // Restore only after a prior explicit opt-in; never auto-enable a microphone.
  useEffect(() => {
    if (localStorage.getItem(ENABLED_KEY) === 'true'
        && localStorage.getItem(CONSENT_KEY) === 'true') {
      startListening();
    }
    return () => {
      enabledRef.current = false;
      clearTimeout(armTimerRef.current);
      try { recogRef.current?.stop(); } catch {}
      cancelSpeech();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!supported) {
    return (
      <div className="eva-jarvis" title="This browser has no Speech Recognition API">
        <button type="button" className="eva-jarvis-button" disabled>
          <MicOff size={16} /><span>Voice unavailable</span>
        </button>
      </div>
    );
  }

  const on = mode !== 'off';
  const info = STATES[mode] || STATES.off;

  return (
    <div className="eva-jarvis">
      <button
        type="button"
        className={`eva-jarvis-button${on ? ' is-on' : ''}${mode === 'armed' || mode === 'thinking' ? ' is-active' : ''}`}
        onClick={on ? stopListening : startListening}
        title={info.hint}
        aria-pressed={on}
      >
        {mode === 'speaking' ? <Volume2 size={16} /> : on ? <Mic size={16} /> : <MicOff size={16} />}
        <span>{on ? 'EVA listening' : 'Start EVA'}</span>
        {on && <i className={`eva-jarvis-dot${mode === 'armed' ? ' is-armed' : ''}`} />}
      </button>
      {on && (
        <button
          type="button"
          className="eva-jarvis-expand"
          onClick={() => setExpanded(true)}
          title="Open voice panel"
        >
          <span>{info.label}</span>
          <ChevronDown size={13} style={{ transform: 'rotate(180deg)' }} />
        </button>
      )}
      {error && <div className="eva-jarvis-error">{error}</div>}

      {expanded && on && createPortal(
        <div className="eva-vp-backdrop" onClick={() => setExpanded(false)}>
          <section
            className="eva-vp"
            role="dialog"
            aria-modal="true"
            aria-label="EVA Voice"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="eva-vp-head">
              <span>EVA Voice</span>
              <button type="button" onClick={() => setExpanded(false)} aria-label="Collapse voice panel">
                <ChevronDown size={17} />
              </button>
            </header>

            <div className="eva-vp-orb">
              {/* active={expanded} — the analyser stream exists only while
                  the panel is open, so nothing extra runs in the background. */}
              <VoiceOrb state={mode} size={176} active={expanded} />
            </div>

            <p className={`eva-vp-state is-${mode}`}>{info.label}</p>

            <div className="eva-vp-transcript" aria-live="polite">
              {transcript
                ? <span className="eva-vp-you">“{transcript}”</span>
                : <span className="eva-vp-idle">{info.hint}</span>}
            </div>

            {lastReply && mode !== 'armed' && (
              <p className="eva-vp-reply">{lastReply.slice(0, 220)}</p>
            )}

            <div className="eva-vp-meta">
              <span>{String(Math.floor(elapsed / 60)).padStart(2, '0')}:{String(elapsed % 60).padStart(2, '0')}</span>
              <span>·</span>
              <span>Wake word “Hey EVA”</span>
            </div>

            <div className="eva-vp-actions">
              <button
                type="button"
                className="eva-vp-stop"
                onClick={() => { stopListening(); setExpanded(false); }}
              >
                <Square size={13} /> Stop listening
              </button>
              {mode === 'speaking' && (
                <button
                  type="button"
                  onClick={() => { cancelSpeech(); setMode('idle'); }}
                >
                  Skip reply
                </button>
              )}
            </div>
          </section>
        </div>,
        document.body,
      )}

      <style>{`
        .eva-jarvis{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
        .eva-jarvis-button{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;
          border-radius:999px;border:1px solid var(--eva-border,#2a2f45);
          background:var(--eva-surface,#171b2c);color:inherit;cursor:pointer;font-size:13px}
        .eva-jarvis-button.is-on{border-color:#8b5cf6;box-shadow:0 0 0 3px rgba(139,92,246,.16)}
        .eva-jarvis-button.is-active{border-color:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.18)}
        .eva-jarvis-button:disabled{opacity:.55;cursor:default}
        .eva-jarvis-dot{width:8px;height:8px;border-radius:50%;background:#8b5cf6;
          animation:evaPulse 1.5s ease-in-out infinite}
        .eva-jarvis-dot.is-armed{background:#22c55e}
        @keyframes evaPulse{0%,100%{opacity:.35;transform:scale(.85)}50%{opacity:1;transform:scale(1.15)}}
        @media (prefers-reduced-motion: reduce){.eva-jarvis-dot{animation:none;opacity:.9}}
        .eva-jarvis-status{font-size:12px;opacity:.75;display:flex;gap:8px;align-items:center}
        .eva-jarvis-status em{font-style:normal;opacity:.75}
        .eva-jarvis-error{font-size:12px;color:#f87171}
        .eva-jarvis-expand{display:inline-flex;align-items:center;gap:5px;padding:5px 10px;
          border-radius:999px;border:1px solid var(--border,#2a2f45);background:transparent;
          color:var(--text3,#94A3B8);font-size:11.5px;cursor:pointer}
        .eva-jarvis-expand:hover{color:var(--text,#F8FAFC);border-color:var(--border2,#343a57)}

        /* ── Expanded voice panel (slice 3) ── */
        .eva-vp-backdrop{position:fixed;inset:0;z-index:4500;display:flex;align-items:center;
          justify-content:center;padding:16px;background:rgba(6,8,18,.72)}
        .eva-vp{width:min(360px,100%);max-height:calc(100dvh - 32px);display:flex;flex-direction:column;
          align-items:center;gap:10px;padding:14px 16px 16px;border-radius:20px;
          background:rgba(17,24,39,.96);border:1px solid rgba(255,255,255,.09);
          box-shadow:0 20px 60px rgba(0,0,0,.5);color:var(--text,#F8FAFC);
          animation:evaVpIn 200ms ease-out}
        .eva-vp-head{width:100%;display:flex;align-items:center;justify-content:space-between;
          font-size:14px;font-weight:600}
        .eva-vp-head button{background:none;border:0;color:var(--text3,#94A3B8);cursor:pointer;
          padding:4px;border-radius:8px}
        .eva-vp-head button:hover{color:var(--text,#F8FAFC)}
        .eva-vp-orb{display:grid;place-items:center;margin:2px 0}
        .eva-vp-state{margin:0;font-size:14px;font-weight:600}
        .eva-vp-state.is-armed{color:#22C55E}
        .eva-vp-state.is-thinking{color:#F59E0B}
        .eva-vp-state.is-speaking{color:#38BDF8}
        .eva-vp-transcript{min-height:38px;width:100%;display:grid;place-items:center;
          text-align:center;font-size:13px;padding:0 4px}
        .eva-vp-you{color:var(--text,#F8FAFC)}
        .eva-vp-idle{color:var(--text3,#94A3B8)}
        .eva-vp-reply{margin:0;font-size:12px;line-height:1.5;color:var(--text2,#CBD5E1);
          text-align:center;max-height:4.5em;overflow:hidden}
        .eva-vp-meta{display:flex;gap:7px;align-items:center;font-size:11px;
          color:var(--text3,#94A3B8);font-variant-numeric:tabular-nums}
        .eva-vp-actions{display:flex;gap:8px;margin-top:2px}
        .eva-vp-actions button{display:inline-flex;align-items:center;gap:6px;padding:9px 15px;
          border-radius:999px;border:1px solid var(--border,#2a2f45);background:rgba(255,255,255,.04);
          color:var(--text2,#CBD5E1);font-size:12.5px;cursor:pointer}
        .eva-vp-actions button:hover{background:rgba(255,255,255,.08);color:var(--text,#F8FAFC)}
        .eva-vp-stop{color:#f87171!important;border-color:rgba(239,68,68,.34)!important}
        @keyframes evaVpIn{from{transform:translateY(10px) scale(.98);opacity:0}to{transform:none;opacity:1}}
        @media (max-width:768px){
          .eva-vp-backdrop{align-items:flex-end;padding:0}
          .eva-vp{width:100%;border-radius:20px 20px 0 0;
            padding-bottom:calc(18px + env(safe-area-inset-bottom))}
        }
        @media (prefers-reduced-motion: reduce){.eva-vp{animation:none}}
      `}</style>
    </div>
  );
}
