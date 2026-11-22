/**
 * EVA voice profiles
 * ==================
 * Extends the existing speech layer rather than replacing it. JarvisMode and
 * the per-message "Read aloud" button both still call window.speechSynthesis;
 * this module only decides WHICH voice and with what delivery.
 *
 * ── An honest note on what the browser can and cannot do ──────────────────
 * Everything here runs on the Web Speech API, which is free, offline-capable
 * and already shipping. It exposes the voices installed on the user's system
 * plus rate, pitch and volume — and nothing else.
 *
 * That means age and character profiles are APPROXIMATIONS built from a real
 * system voice plus pitch/rate shaping. A "child" profile is a higher-pitched,
 * slightly faster system voice; it is not a neural child voice, and it will not
 * be mistaken for one. Likewise the speaking styles shape delivery through the
 * three dials available — they are not neural emotion models.
 *
 * True character and emotional synthesis needs a neural provider (ElevenLabs,
 * OpenAI, Azure, Google). Those are paid, per-character, and need API keys, so
 * they are a product decision rather than something to enable silently. The
 * provider registry below exists so one can be added without touching callers:
 * implement the same speak(text, settings) shape, register it, and profiles,
 * styles and the settings UI keep working unchanged.
 */

export const VOICE_CATEGORIES = [
  { id: 'child', label: 'Child' },
  { id: 'teen', label: 'Teen' },
  { id: 'young-adult', label: 'Young Adult' },
  { id: 'adult', label: 'Adult' },
  { id: 'mature', label: 'Mature' },
  { id: 'professional', label: 'Professional' },
];

// `match` are substrings tested against installed system voice names, best
// first. They are hints, not requirements: voice availability varies wildly
// across Windows, macOS, iOS, Android and Chrome, so resolution always falls
// back to a language match and finally to the browser default.
export const VOICE_PROFILES = [
  { id: 'baby-boy',     label: 'Baby Boy',      emoji: '👦', category: 'child',       pitch: 1.65, rate: 1.05, gender: 'male',   match: ['george', 'daniel', 'alex'] },
  { id: 'baby-girl',    label: 'Baby Girl',     emoji: '👧', category: 'child',       pitch: 1.75, rate: 1.05, gender: 'female', match: ['zira', 'samantha', 'karen'] },
  { id: 'teen-boy',     label: 'Teen Boy',      emoji: '👦', category: 'teen',        pitch: 1.30, rate: 1.06, gender: 'male',   match: ['george', 'daniel', 'alex'] },
  { id: 'teen-girl',    label: 'Teen Girl',     emoji: '👧', category: 'teen',        pitch: 1.40, rate: 1.06, gender: 'female', match: ['zira', 'samantha', 'karen'] },
  { id: 'young-man',    label: 'Young Man',     emoji: '👨', category: 'young-adult', pitch: 1.08, rate: 1.03, gender: 'male',   match: ['daniel', 'george', 'alex'] },
  { id: 'young-woman',  label: 'Young Woman',   emoji: '👩', category: 'young-adult', pitch: 1.15, rate: 1.03, gender: 'female', match: ['samantha', 'zira', 'karen'] },
  { id: 'adult-male',   label: 'Adult Male',    emoji: '👨', category: 'adult',       pitch: 0.95, rate: 1.00, gender: 'male',   match: ['david', 'daniel', 'alex'] },
  { id: 'adult-female', label: 'Adult Female',  emoji: '👩', category: 'adult',       pitch: 1.02, rate: 1.00, gender: 'female', match: ['zira', 'samantha', 'susan'] },
  { id: 'senior-male',  label: 'Senior Male',   emoji: '👨', category: 'mature',      pitch: 0.80, rate: 0.90, gender: 'male',   match: ['david', 'daniel'] },
  { id: 'senior-female',label: 'Senior Female', emoji: '👩', category: 'mature',      pitch: 0.90, rate: 0.90, gender: 'female', match: ['susan', 'zira', 'karen'] },

  { id: 'teacher',      label: 'Teacher',       emoji: '🎓', category: 'professional', pitch: 1.00, rate: 0.92, gender: 'female', match: ['samantha', 'zira'] },
  { id: 'business',     label: 'Business Pro',  emoji: '💼', category: 'professional', pitch: 0.97, rate: 1.00, gender: 'male',   match: ['david', 'daniel'] },
  { id: 'jarvis',       label: 'Jarvis',        emoji: '🤖', category: 'professional', pitch: 0.88, rate: 0.98, gender: 'male',   match: ['daniel', 'david', 'george'] },
  { id: 'news-reader',  label: 'News Reader',   emoji: '📰', category: 'professional', pitch: 1.00, rate: 1.04, gender: 'female', match: ['zira', 'samantha'] },
  { id: 'narrator',     label: 'Narrator',      emoji: '🎙️', category: 'professional', pitch: 0.93, rate: 0.90, gender: 'male',   match: ['daniel', 'alex', 'david'] },
];

// Multiplicative on rate/pitch, additive on volume, so a style composes with
// any profile instead of overwriting its character.
export const SPEAKING_STYLES = [
  { id: 'friendly',     label: 'Friendly',     rate: 1.00, pitch: 1.04, volume: 0 },
  { id: 'calm',         label: 'Calm',         rate: 0.92, pitch: 0.97, volume: -0.05 },
  { id: 'professional', label: 'Professional', rate: 1.00, pitch: 1.00, volume: 0 },
  { id: 'cheerful',     label: 'Cheerful',     rate: 1.08, pitch: 1.12, volume: 0.05 },
  { id: 'serious',      label: 'Serious',      rate: 0.95, pitch: 0.93, volume: 0 },
  { id: 'motivational', label: 'Motivational', rate: 1.06, pitch: 1.08, volume: 0.08 },
  { id: 'excited',      label: 'Excited',      rate: 1.14, pitch: 1.16, volume: 0.08 },
  { id: 'empathetic',   label: 'Empathetic',   rate: 0.90, pitch: 1.02, volume: -0.03 },
];

export const DEFAULT_VOICE_SETTINGS = {
  provider: 'webspeech',
  profile: 'jarvis',
  style: 'calm',
  rate: 1,
  pitch: 1,
  volume: 1,
  pauseScale: 1,
  lang: '',        // '' = follow the page/browser language
};

const STORAGE_KEY = 'eva_voice_settings';

export function getVoiceSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return { ...DEFAULT_VOICE_SETTINGS, ...(raw && typeof raw === 'object' ? raw : {}) };
  } catch {
    return { ...DEFAULT_VOICE_SETTINGS };
  }
}

export function setVoiceSettings(patch = {}) {
  const next = { ...getVoiceSettings(), ...patch };
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* quota */ }
  // Same-tab listeners: the storage event only fires in OTHER tabs.
  try { window.dispatchEvent(new CustomEvent('eva:voice-settings', { detail: next })); } catch { /* SSR */ }
  return next;
}

export function getProfile(id) {
  return VOICE_PROFILES.find((p) => p.id === id) || VOICE_PROFILES.find((p) => p.id === 'jarvis');
}

export function getStyle(id) {
  return SPEAKING_STYLES.find((s) => s.id === id) || SPEAKING_STYLES.find((s) => s.id === 'professional');
}

export function listVoices() {
  try { return window.speechSynthesis?.getVoices?.() || []; } catch { return []; }
}

/**
 * getVoices() is famously empty on first call in Chromium — the list populates
 * asynchronously and fires voiceschanged. Callers that need voices at startup
 * should await this rather than reading an empty array and caching it.
 */
export function whenVoicesReady(timeoutMs = 2000) {
  return new Promise((resolve) => {
    const existing = listVoices();
    if (existing.length) { resolve(existing); return; }
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try { window.speechSynthesis.removeEventListener('voiceschanged', finish); } catch { /* older browsers */ }
      resolve(listVoices());
    };
    const timer = setTimeout(finish, timeoutMs);
    try { window.speechSynthesis.addEventListener('voiceschanged', finish); } catch { finish(); }
  });
}

/** Pick the closest installed voice for a profile. Never throws, never returns
 *  undefined-but-truthy — a null result means "let the browser decide". */
export function resolveVoice(profile, voices = listVoices(), lang = '') {
  if (!voices.length) return null;
  const wanted = (lang || navigator.language || 'en').toLowerCase().slice(0, 2);
  const sameLang = voices.filter((v) => String(v.lang || '').toLowerCase().startsWith(wanted));
  const pool = sameLang.length ? sameLang : voices;

  for (const needle of profile.match || []) {
    const hit = pool.find((v) => String(v.name || '').toLowerCase().includes(needle));
    if (hit) return hit;
  }
  // No name match: fall back to a gender hint where the platform exposes one in
  // the voice name, then to the first voice in the right language.
  const genderHint = profile.gender === 'female' ? ['female', 'woman'] : ['male', 'man'];
  const byGender = pool.find((v) => genderHint.some((g) => String(v.name || '').toLowerCase().includes(g)));
  return byGender || pool[0] || null;
}

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

/** Effective rate/pitch/volume for a settings object: profile x style x user. */
export function resolveDelivery(settings = getVoiceSettings()) {
  const profile = getProfile(settings.profile);
  const style = getStyle(settings.style);
  return {
    // The Web Speech spec allows rate 0.1–10 and pitch 0–2, but anything past
    // these bounds is unintelligible rather than characterful.
    rate: clamp(profile.rate * style.rate * (settings.rate || 1), 0.5, 2),
    pitch: clamp(profile.pitch * style.pitch * (settings.pitch || 1), 0.4, 2),
    volume: clamp((settings.volume ?? 1) + style.volume, 0, 1),
    profile,
    style,
  };
}

/**
 * Strip markup that is unlistenable, and shape pauses.
 * Kept here so JarvisMode and Read-aloud cannot drift apart — this logic used
 * to live only inside JarvisMode.
 */
export function toSpokenText(text, pauseScale = 1) {
  let spoken = String(text || '')
    .replace(/```[\s\S]*?```/g, ' (code block omitted) ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s*\|.*\|\s*$/gm, ' ')
    .replace(/[#*_`>~$]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
  // Longer pauses are approximated with commas/ellipses: the Web Speech API has
  // no pause control, and SSML <break> is not supported by speechSynthesis.
  if (pauseScale > 1.2) spoken = spoken.replace(/([.!?])\s+/g, '$1 … ');
  return spoken;
}

// ── Provider registry ────────────────────────────────────────────────────────
// A provider is { id, label, isAvailable(), speak(text, settings, handlers),
// cancel() }. Adding ElevenLabs/OpenAI/Azure means registering one more object;
// callers and UI need no change. speak() resolves when playback finishes so
// fallback can chain.
const providers = new Map();

export function registerVoiceProvider(provider) {
  if (provider && provider.id) providers.set(provider.id, provider);
}

export function listVoiceProviders() {
  return [...providers.values()];
}

const webSpeechProvider = {
  id: 'webspeech',
  label: 'Browser (built-in)',
  isAvailable: () => typeof window !== 'undefined' && !!window.speechSynthesis,
  cancel: () => { try { window.speechSynthesis.cancel(); } catch { /* not supported */ } },
  speak: (text, settings, handlers = {}) => new Promise((resolve, reject) => {
    const synth = window.speechSynthesis;
    if (!synth) { reject(new Error('speechSynthesis unavailable')); return; }
    const spoken = toSpokenText(text, settings.pauseScale).slice(0, 1000);
    if (!spoken) { resolve(); return; }

    const { rate, pitch, volume, profile } = resolveDelivery(settings);
    const utter = new SpeechSynthesisUtterance(spoken);
    const voice = resolveVoice(profile, listVoices(), settings.lang);
    if (voice) utter.voice = voice;
    if (settings.lang) utter.lang = settings.lang;
    utter.rate = rate;
    utter.pitch = pitch;
    utter.volume = volume;

    let settled = false;
    const finish = (err) => {
      if (settled) return;
      settled = true;
      handlers.onend?.();
      // A cancel() mid-utterance surfaces as an error event; that is a normal
      // barge-in, not a failure, so it must not trigger provider fallback.
      if (err && err.error && err.error !== 'interrupted' && err.error !== 'canceled') reject(new Error(err.error));
      else resolve();
    };
    utter.onstart = () => handlers.onstart?.();
    utter.onend = () => finish(null);
    utter.onerror = (e) => finish(e);

    synth.cancel();
    synth.speak(utter);
  }),
};

registerVoiceProvider(webSpeechProvider);

// ── ElevenLabs (neural) ──────────────────────────────────────────────────────
// Goes through EVA's backend, never directly to api.elevenlabs.io. The API key
// is a secret and this bundle is public: a browser-side call would ship the key
// to every visitor and let anyone spend the account's character quota. The
// backend holds the key and proxies.
//
// ElevenLabs premade voices, present on every account. The settings UI can
// override these with the account's real voice list via /api/voice/elevenlabs/voices.
const ELEVEN_VOICES = {
  'baby-girl':     'EXAVITQu4vr4xnSDxMaL', // Bella — soft, youngest-sounding premade
  'baby-boy':      'yoZ06aMxZJJ28mfd3POQ', // Sam
  'teen-girl':     'EXAVITQu4vr4xnSDxMaL', // Bella
  'teen-boy':      'yoZ06aMxZJJ28mfd3POQ', // Sam
  'young-woman':   'MF3mGyEYCl7XYWbV9V6O', // Elli — expressive
  'young-man':     'ErXwobaYiN019PkySvjV', // Antoni
  'adult-female':  '21m00Tcm4TlvDq8ikWAM', // Rachel
  'adult-male':    'pNInz6obpgDQGcFmaJgB', // Adam
  'senior-female': 'AZnzlk1XvdvUeBnXmlld', // Domi
  'senior-male':   'TxGEqnHWrfWFTfGW9XjX', // Josh — deep
  teacher:         '21m00Tcm4TlvDq8ikWAM', // Rachel — clear, patient
  business:        'ErXwobaYiN019PkySvjV', // Antoni
  jarvis:          'pNInz6obpgDQGcFmaJgB', // Adam — calm, deep
  'news-reader':   '21m00Tcm4TlvDq8ikWAM', // Rachel
  narrator:        'TxGEqnHWrfWFTfGW9XjX', // Josh — warm
};

// stability: lower = more variation and emotion, higher = flatter and steadier.
// style: exaggeration of the voice's own delivery.
const ELEVEN_STYLE = {
  friendly:     { stability: 0.45, style: 0.35 },
  calm:         { stability: 0.75, style: 0.05 },
  professional: { stability: 0.65, style: 0.10 },
  cheerful:     { stability: 0.35, style: 0.55 },
  serious:      { stability: 0.80, style: 0.05 },
  motivational: { stability: 0.30, style: 0.60 },
  excited:      { stability: 0.25, style: 0.70 },
  empathetic:   { stability: 0.55, style: 0.30 },
};

// Cached so every speak() does not re-probe. null = not yet checked.
let elevenAvailable = null;
let currentAudio = null;

function apiBase() {
  return (process.env.REACT_APP_API_BASE || '').replace(/\/+$/, '');
}

function authHeaders() {
  const token = localStorage.getItem('aria_token');
  return {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/** Ask the backend whether a key is configured. Result is cached for the tab. */
export async function probeElevenLabs() {
  try {
    const res = await fetch(`${apiBase()}/api/voice/providers`, { headers: authHeaders() });
    if (!res.ok) { elevenAvailable = false; return false; }
    const data = await res.json();
    elevenAvailable = !!data?.elevenlabs?.available;
    return elevenAvailable;
  } catch {
    elevenAvailable = false;
    return false;
  }
}

export function isElevenLabsKnownAvailable() {
  return elevenAvailable === true;
}

// Client-side cache on top of the server's. Saves the round trip entirely for
// repeated phrases, which matters most for the preview button.
const audioCache = new Map();
const AUDIO_CACHE_MAX = 24;

const elevenLabsProvider = {
  id: 'elevenlabs',
  label: 'ElevenLabs (neural)',
  // Never returns true until probeElevenLabs() has confirmed a server key, so
  // an unconfigured deployment falls straight through to browser speech.
  isAvailable: () => elevenAvailable === true,
  cancel: () => {
    if (currentAudio) {
      try { currentAudio.pause(); currentAudio.currentTime = 0; } catch { /* already gone */ }
      currentAudio = null;
    }
  },
  speak: async (text, settings, handlers = {}) => {
    const spoken = toSpokenText(text, settings.pauseScale).slice(0, 800);
    if (!spoken) return;

    const profile = getProfile(settings.profile);
    const style = ELEVEN_STYLE[settings.style] || ELEVEN_STYLE.professional;
    const voiceId = settings.elevenVoiceId || ELEVEN_VOICES[profile.id] || ELEVEN_VOICES.jarvis;
    const { rate } = resolveDelivery(settings);

    const cacheKey = JSON.stringify([spoken, voiceId, style, rate]);
    let url = audioCache.get(cacheKey);

    if (!url) {
      const res = await fetch(`${apiBase()}/api/voice/elevenlabs/speak`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          text: spoken,
          voice_id: voiceId,
          stability: style.stability,
          style: style.style,
          similarity_boost: 0.75,
          speed: rate,
        }),
      });
      // Any non-200 throws so speakWithVoice falls through to browser speech —
      // an expired key or spent quota must never leave the user in silence.
      if (!res.ok) throw new Error(`elevenlabs ${res.status}`);
      const blob = await res.blob();
      url = URL.createObjectURL(blob);
      audioCache.set(cacheKey, url);
      while (audioCache.size > AUDIO_CACHE_MAX) {
        const oldest = audioCache.keys().next().value;
        try { URL.revokeObjectURL(audioCache.get(oldest)); } catch { /* ignore */ }
        audioCache.delete(oldest);
      }
    }

    await new Promise((resolve, reject) => {
      const audio = new Audio(url);
      currentAudio = audio;
      audio.volume = Math.max(0, Math.min(1, settings.volume ?? 1));
      let settled = false;
      const finish = (err) => {
        if (settled) return;
        settled = true;
        if (currentAudio === audio) currentAudio = null;
        handlers.onend?.();
        // A pause() from cancel() ends playback without 'ended'; that is a
        // barge-in, not a failure, so it resolves rather than rejecting.
        if (err) reject(err); else resolve();
      };
      audio.onplay = () => handlers.onstart?.();
      audio.onended = () => finish(null);
      audio.onerror = () => finish(new Error('audio playback failed'));
      audio.onpause = () => finish(null);
      audio.play().catch((e) => finish(e));
    });
  },
};

registerVoiceProvider(elevenLabsProvider);

/**
 * Speak through the configured provider, falling back to any other available
 * provider (browser speech last) if it fails. Returns the provider id used, or
 * null if nothing could speak.
 */
export async function speakWithVoice(text, overrides = {}, handlers = {}) {
  const settings = { ...getVoiceSettings(), ...overrides };
  const preferred = providers.get(settings.provider);
  const order = [
    ...(preferred ? [preferred] : []),
    ...listVoiceProviders().filter((p) => p.id !== settings.provider),
  ];
  for (const provider of order) {
    try {
      if (!provider.isAvailable?.()) continue;
      await provider.speak(text, settings, handlers);
      return provider.id;
    } catch {
      // Try the next provider. A dead cloud provider must never leave the user
      // in silence when the browser can still speak.
    }
  }
  return null;
}

export function cancelSpeech() {
  for (const provider of listVoiceProviders()) {
    try { provider.cancel?.(); } catch { /* ignore */ }
  }
}

/** Short sample so a profile can be auditioned before it is selected. */
export function previewVoice(settings) {
  const profile = getProfile(settings.profile);
  cancelSpeech();
  return speakWithVoice(
    `Hello, I'm EVA speaking as ${profile.label}. This is how I'll sound in your conversations.`,
    settings,
  );
}
