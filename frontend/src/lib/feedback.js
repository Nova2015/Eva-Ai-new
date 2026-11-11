/**
 * Slice 6 — sound, haptics and motion preferences
 * ===============================================
 * Three opt-in feedback channels, all off or conservative by default.
 *
 * Sound is SYNTHESISED with Web Audio (oscillator + gain envelope) rather than
 * shipped as audio files: the project has no audio assets, and a handful of
 * short UI tones cost zero bytes and no network requests this way. They are
 * deliberately quiet, short, and pitched to sit under speech.
 *
 * Haptics use navigator.vibrate, which Android Chrome supports and iOS Safari
 * does NOT — there is no web API for iOS haptics. isHapticsSupported() reports
 * that honestly so the setting can be shown as unavailable instead of looking
 * broken.
 *
 * Motion is a preference level written to <html data-motion>, so CSS keys off
 * it. The OS-level prefers-reduced-motion always wins: a user who asked their
 * system for less motion should not have to ask again here.
 */

const KEY = 'eva_feedback_prefs';

const DEFAULTS = {
  sound: false,        // opt-in: unexpected noise from a web page is hostile
  soundVolume: 0.18,   // quiet by default
  haptics: true,       // free and unobtrusive where supported
  motion: 'full',      // 'off' | 'minimal' | 'full'
};

let prefs = load();
let ctx = null;

function load() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
  } catch {
    return { ...DEFAULTS };
  }
}

export function getFeedbackPrefs() {
  return { ...prefs };
}

export function setFeedbackPrefs(patch) {
  prefs = { ...prefs, ...patch };
  localStorage.setItem(KEY, JSON.stringify(prefs));
  applyMotion();
  return { ...prefs };
}

/** OS setting wins — never override an explicit accessibility request. */
export function systemReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false;
}

export function applyMotion() {
  const level = systemReducedMotion() ? 'off' : prefs.motion;
  document.documentElement.setAttribute('data-motion', level);
}

export function isHapticsSupported() {
  return typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function';
}

const HAPTIC_PATTERNS = {
  light: 8,
  medium: 18,
  success: [10, 40, 14],
  error: [24, 50, 24],
};

export function haptic(kind = 'light') {
  if (!prefs.haptics || !isHapticsSupported()) return;
  try { navigator.vibrate(HAPTIC_PATTERNS[kind] ?? HAPTIC_PATTERNS.light); } catch { /* ignore */ }
}

/* ── Synthesised UI tones ───────────────────────────────────────────────
   [frequency Hz, duration s, waveform]. Two-note pairs read as a gesture
   (rising = sent/success, falling = error) without a sample library. */
const TONES = {
  send:      [[520, 0.05, 'sine'], [700, 0.06, 'sine']],
  receive:   [[660, 0.06, 'sine'], [520, 0.07, 'sine']],
  imageDone: [[600, 0.05, 'triangle'], [820, 0.07, 'triangle'], [1000, 0.08, 'triangle']],
  voiceOn:   [[440, 0.05, 'sine'], [660, 0.07, 'sine']],
  shutter:   [[1400, 0.02, 'square'], [900, 0.03, 'square']],
  toolOpen:  [[480, 0.04, 'sine']],
  success:   [[660, 0.05, 'sine'], [880, 0.09, 'sine']],
  error:     [[300, 0.09, 'sawtooth'], [200, 0.12, 'sawtooth']],
};

export function playSound(name) {
  if (!prefs.sound) return;
  const seq = TONES[name];
  if (!seq) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    if (!ctx) ctx = new AC();
    // Autoplay policy: a suspended context stays silent until a gesture.
    if (ctx.state === 'suspended') ctx.resume?.();

    let at = ctx.currentTime;
    for (const [freq, dur, type] of seq) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, at);
      // Short attack/decay envelope — a raw gate click is unpleasant.
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, prefs.soundVolume), at + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      osc.connect(gain).connect(ctx.destination);
      osc.start(at);
      osc.stop(at + dur + 0.02);
      at += dur * 0.75;
    }
  } catch { /* audio is a nicety; never let it break a flow */ }
}

/** Convenience: the two channels almost always fire together. */
export function feedback(sound, hapticKind) {
  playSound(sound);
  if (hapticKind) haptic(hapticKind);
}

// Apply the stored motion level immediately on import, and follow the OS if it
// changes mid-session.
applyMotion();
window.matchMedia?.('(prefers-reduced-motion: reduce)')
  ?.addEventListener?.('change', applyMotion);
