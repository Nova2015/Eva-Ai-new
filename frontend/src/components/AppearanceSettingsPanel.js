import { useState } from 'react';
import { ButtonRow, Panel, Select, SettingRow, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import { getFeedbackPrefs, setFeedbackPrefs, isHapticsSupported, systemReducedMotion, playSound, haptic } from '../lib/feedback';
import { useTheme } from '../context/ThemeContext';
import './AppearanceSettingsPanel.css';

const defaults = {
  theme: 'Dark',
  accent_color: 'Auto',
  font_size: 'Medium',
  chat_bubble_style: 'Modern',
  sidebar_style: 'Expanded',
  message_density: 'Comfortable',
};

const accentMap = {
  // 'Auto' defers to the active theme's own accent — without it every palette
  // renders with the same accent colour and the themes stop being distinct.
  Auto: 'var(--accent)',
  Blue: '#2563eb',
  Purple: '#8b5cf6',
  Green: '#10b981',
  Orange: '#f97316',
  Pink: '#ec4899',
};

function toLabel(value) {
  const text = String(value || '').toLowerCase();
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}

function applyAppearance(settings, themeApi) {
  themeApi.setTheme(settings.theme);
  themeApi.setAccent(settings.accent_color);
  document.documentElement.style.setProperty('--eva-font-scale', settings.font_size === 'Large' ? '1.06' : settings.font_size === 'Small' ? '0.94' : '1');
  localStorage.setItem('eva_appearance_settings', JSON.stringify(settings));
}

export default function AppearanceSettingsPanel({ API }) {
  const themeApi = useTheme();
  const [fb, setFb] = useState(getFeedbackPrefs);
  const { settings, setSettings, update, loading, status, setStatus, save } = useRemoteSettings(API, '/settings/appearance', defaults);
  const selectedTheme = toLabel(themeApi.theme);
  const selectedAccent = toLabel(themeApi.accent);
  const appliedSettings = {
    ...settings,
    theme: selectedTheme || settings.theme,
    accent_color: selectedAccent || settings.accent_color,
  };

  const updateAndApply = (key, value) => {
    const next = { ...appliedSettings, [key]: value };
    setSettings(next);
    applyAppearance(next, themeApi);
  };

  const saveAppearance = async () => {
    await save(appliedSettings);
    applyAppearance(appliedSettings, themeApi);
  };

  const resetAppearance = async () => {
    try {
      const data = await settingsRequest(API, '/settings/appearance/reset', { method: 'POST', body: JSON.stringify({}) });
      const next = data.settings || defaults;
      setSettings(next);
      applyAppearance(next, themeApi);
      setStatus('Reset');
    } catch (error) {
      setStatus(error.message || 'Reset failed');
    }
  };

  return (
    <>
      <Panel title="Theme" subtitle="Applied immediately and persisted after reload.">
        <div className="eva-theme-grid">
          {themeApi.presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`eva-theme-card ${themeApi.theme === preset.id ? 'is-active' : ''}`}
              onClick={() => updateAndApply('theme', preset.id)}
              aria-pressed={themeApi.theme === preset.id}
            >
              {/* Swatch is the palette's own colours, so the card previews
                  the theme rather than describing it. */}
              <span className="eva-theme-bars" aria-hidden="true">
                {preset.swatch.map((c) => <i key={c} style={{ background: c }} />)}
              </span>
              <span>{preset.label}</span>
            </button>
          ))}
        </div>
        <SettingRow title="Accent color" detail="Used for buttons, active states, and highlights.">
          <div className="eva-settings-swatch-row">
            {Object.keys(accentMap).map((accent) => (
              <button
                key={accent}
                type="button"
                className={`eva-settings-color-swatch ${appliedSettings.accent_color === accent ? 'is-active' : ''}`}
                style={{ background: accentMap[accent] }}
                title={accent}
                onClick={() => updateAndApply('accent_color', accent)}
              />
            ))}
          </div>
        </SettingRow>
      </Panel>

      <Panel title="Feedback" subtitle="Sound, haptics, and motion. All optional.">
        <SettingRow title="Interface sounds" detail="Short tones for sent, received, and completed actions. Off by default.">
          <Toggle checked={fb.sound} onChange={(v) => { setFb(setFeedbackPrefs({ sound: v })); if (v) playSound('success'); }} />
        </SettingRow>
        <SettingRow
          title="Haptics"
          detail={isHapticsSupported()
            ? 'Light vibration on actions (supported on this device).'
            : 'Not available in this browser — iOS Safari exposes no vibration API.'}
        >
          <Toggle
            checked={fb.haptics && isHapticsSupported()}
            onChange={(v) => { setFb(setFeedbackPrefs({ haptics: v })); if (v) haptic('medium'); }}
          />
        </SettingRow>
        <SettingRow
          title="Animations"
          detail={systemReducedMotion()
            ? 'Your system asks for reduced motion, so animations stay off.'
            : 'Off disables all motion; Minimal keeps only essential transitions.'}
        >
          <Select
            value={fb.motion === 'off' ? 'Off' : fb.motion === 'minimal' ? 'Minimal' : 'Full'}
            options={['Off', 'Minimal', 'Full']}
            onChange={(v) => setFb(setFeedbackPrefs({ motion: v.toLowerCase() }))}
          />
        </SettingRow>
      </Panel>

      <Panel title="Workspace Feel" subtitle="Tune density, chat bubbles, and layout.">
        <SettingRow title="Font size" detail="Small, medium, or large UI text.">
          <Select value={settings.font_size} options={['Small', 'Medium', 'Large']} onChange={(value) => updateAndApply('font_size', value)} />
        </SettingRow>
        <SettingRow title="Chat bubble style" detail="Visual treatment for message bubbles.">
          <Select value={settings.chat_bubble_style} options={['Modern', 'Compact', 'Glass']} onChange={(value) => update('chat_bubble_style', value)} />
        </SettingRow>
        <SettingRow title="Sidebar style" detail="Main sidebar density preference.">
          <Select value={settings.sidebar_style} options={['Expanded', 'Compact', 'Icon only']} onChange={(value) => update('sidebar_style', value)} />
        </SettingRow>
        <SettingRow title="Message density" detail="Controls chat vertical spacing.">
          <Select value={settings.message_density} options={['Comfortable', 'Compact']} onChange={(value) => update('message_density', value)} />
        </SettingRow>
      </Panel>

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button" onClick={resetAppearance}>Reset</button>
        <button type="button" className="eva-settings-button primary" onClick={saveAppearance}>Save appearance</button>
      </ButtonRow>
    </>
  );
}
