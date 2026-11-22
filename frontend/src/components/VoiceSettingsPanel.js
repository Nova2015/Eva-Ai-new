import { useEffect, useMemo, useState } from 'react';
import { Panel, Select, SettingRow } from './SettingsPanelPrimitives';
import {
  VOICE_CATEGORIES,
  VOICE_PROFILES,
  SPEAKING_STYLES,
  DEFAULT_VOICE_SETTINGS,
  getVoiceSettings,
  setVoiceSettings,
  previewVoice,
  cancelSpeech,
  whenVoicesReady,
  resolveVoice,
  getProfile,
  probeElevenLabs,
} from '../lib/voiceProfiles';

/**
 * Voice Settings — extends the existing speech layer, does not replace it.
 * Built on the same Panel/SettingRow/Select primitives as the other settings
 * panels so it inherits their spacing, theming and mobile behaviour.
 */
export default function VoiceSettingsPanel() {
  const [settings, setSettings] = useState(getVoiceSettings);
  const [voices, setVoices] = useState([]);
  const [previewing, setPreviewing] = useState(false);
  const [neuralAvailable, setNeuralAvailable] = useState(false);

  // getVoices() is empty on first call in Chromium and fills in asynchronously,
  // so the resolved-voice line below would otherwise read "browser default"
  // forever on a fresh load.
  useEffect(() => {
    let alive = true;
    whenVoicesReady().then((list) => { if (alive) setVoices(list); });
    // Whether ElevenLabs is offered depends on the server having a key. Asking
    // here means an unconfigured deployment never shows an option that would
    // always fail.
    probeElevenLabs().then((ok) => { if (alive) setNeuralAvailable(ok); });
    return () => { alive = false; };
  }, []);

  const update = (patch) => setSettings(setVoiceSettings(patch));

  const profilesInCategory = useMemo(() => {
    const byCategory = {};
    for (const p of VOICE_PROFILES) (byCategory[p.category] ||= []).push(p);
    return byCategory;
  }, []);

  const currentProfile = getProfile(settings.profile);
  const category = currentProfile.category;
  const categoryProfiles = profilesInCategory[category] || [];
  const resolved = voices.length ? resolveVoice(currentProfile, voices, settings.lang) : null;

  const languages = useMemo(() => {
    const seen = new Set();
    for (const v of voices) {
      const lang = String(v.lang || '').trim();
      if (lang) seen.add(lang);
    }
    return ['Auto', ...[...seen].sort()];
  }, [voices]);

  const doPreview = async () => {
    setPreviewing(true);
    try { await previewVoice(settings); } finally { setPreviewing(false); }
  };

  return (
    <>
      <Panel
        title="Voice"
        subtitle="Applies to Jarvis Mode and the Read aloud button. Saved for this browser."
      >
        <SettingRow
          title="Engine"
          detail={
            neuralAvailable
              ? 'Neural gives real character voices. Browser is built-in, free and offline.'
              : 'Neural voices need ELEVENLABS_API_KEY set on the server. Using built-in browser speech.'
          }
        >
          <Select
            value={settings.provider === 'elevenlabs' && neuralAvailable ? 'Neural (ElevenLabs)' : 'Browser (built-in)'}
            options={neuralAvailable ? ['Browser (built-in)', 'Neural (ElevenLabs)'] : ['Browser (built-in)']}
            onChange={(v) => update({ provider: v.startsWith('Neural') ? 'elevenlabs' : 'webspeech' })}
          />
        </SettingRow>

        <SettingRow title="Category" detail="Groups the available voice profiles.">
          <Select
            value={VOICE_CATEGORIES.find((c) => c.id === category)?.label || 'Professional'}
            options={VOICE_CATEGORIES.map((c) => c.label)}
            onChange={(label) => {
              const cat = VOICE_CATEGORIES.find((c) => c.label === label);
              const first = (profilesInCategory[cat?.id] || [])[0];
              if (first) update({ profile: first.id });
            }}
          />
        </SettingRow>

        <SettingRow title="Voice profile" detail="Character and age of the speaking voice.">
          <Select
            value={currentProfile.label}
            options={categoryProfiles.map((p) => `${p.emoji} ${p.label}`.trim())}
            onChange={(label) => {
              const clean = String(label).replace(/^[^\w]*\s*/, '').trim();
              const hit = categoryProfiles.find((p) => p.label === clean);
              if (hit) update({ profile: hit.id });
            }}
          />
        </SettingRow>

        <SettingRow title="Speaking style" detail="Changes delivery only — never the wording of an answer.">
          <Select
            value={SPEAKING_STYLES.find((s) => s.id === settings.style)?.label || 'Calm'}
            options={SPEAKING_STYLES.map((s) => s.label)}
            onChange={(label) => {
              const hit = SPEAKING_STYLES.find((s) => s.label === label);
              if (hit) update({ style: hit.id });
            }}
          />
        </SettingRow>

        <SettingRow title="Language" detail="Restricts voice selection to one language.">
          <Select
            value={settings.lang || 'Auto'}
            options={languages}
            onChange={(v) => update({ lang: v === 'Auto' ? '' : v })}
          />
        </SettingRow>
      </Panel>

      <Panel title="Delivery" subtitle="Fine-tune on top of the selected profile.">
        <SettingRow title="Speed" detail={`${Number(settings.rate).toFixed(2)}x`}>
          <input
            type="range" min="0.6" max="1.6" step="0.05"
            value={settings.rate}
            aria-label="Speaking speed"
            onChange={(e) => update({ rate: Number(e.target.value) })}
          />
        </SettingRow>
        <SettingRow title="Pitch" detail={`${Number(settings.pitch).toFixed(2)}x`}>
          <input
            type="range" min="0.6" max="1.6" step="0.05"
            value={settings.pitch}
            aria-label="Voice pitch"
            onChange={(e) => update({ pitch: Number(e.target.value) })}
          />
        </SettingRow>
        <SettingRow title="Volume" detail={`${Math.round(Number(settings.volume) * 100)}%`}>
          <input
            type="range" min="0" max="1" step="0.05"
            value={settings.volume}
            aria-label="Voice volume"
            onChange={(e) => update({ volume: Number(e.target.value) })}
          />
        </SettingRow>
        <SettingRow
          title="Pause length"
          detail="Longer pauses between sentences. Approximated with pacing — the browser speech API has no pause control."
        >
          <Select
            value={settings.pauseScale > 1.2 ? 'Long' : 'Normal'}
            options={['Normal', 'Long']}
            onChange={(v) => update({ pauseScale: v === 'Long' ? 1.4 : 1 })}
          />
        </SettingRow>
      </Panel>

      <Panel
        title="Preview"
        subtitle={
          resolved
            ? `Using system voice: ${resolved.name} (${resolved.lang})`
            : 'Using the browser default voice.'
        }
      >
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="eva-settings-button primary" onClick={doPreview} disabled={previewing}>
            {previewing ? 'Speaking…' : '▶ Preview voice'}
          </button>
          <button type="button" className="eva-settings-button" onClick={() => { cancelSpeech(); setPreviewing(false); }}>
            Stop
          </button>
          <button
            type="button"
            className="eva-settings-button"
            onClick={() => { cancelSpeech(); setSettings(setVoiceSettings(DEFAULT_VOICE_SETTINGS)); }}
          >
            Reset to default
          </button>
        </div>
        <p style={{ marginTop: 10, fontSize: 12, color: 'var(--text3)', lineHeight: 1.6 }}>
          {settings.provider === 'elevenlabs' && neuralAvailable ? (
            <>
              Neural voices are generated by ElevenLabs through EVA&apos;s server, so the
              API key never reaches your browser. They are billed per character and need
              a network round trip, so the first play of a new phrase is slower than the
              built-in voice; repeated phrases are cached. If the service is unavailable
              or out of quota, EVA falls back to browser speech automatically rather than
              going silent.
            </>
          ) : (
            <>
              Built-in voices come from the ones installed on your device, shaped by pitch
              and pace. Child and character profiles are approximations rather than
              dedicated recordings, and the available set differs between Windows, macOS,
              iOS and Android. Switch the engine to Neural for true character voices.
            </>
          )}
        </p>
      </Panel>
    </>
  );
}
