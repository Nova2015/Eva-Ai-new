import { useMemo } from 'react';
import { ButtonRow, NumberInput, Panel, Select, SettingRow, StatusBadge, TextInput, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import './ModelSettingsPanel.css';

const providerModels = {
  OpenAI: ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini'],
  Gemini: ['gemini-3.5-flash', 'gemini-1.5-pro', 'gemini-2.5-flash'],
  Claude: ['claude-3-5-sonnet', 'claude-3-5-haiku', 'claude-3-opus'],
  Groq: ['openai/gpt-oss-120b', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
  'Local Model': ['llama.cpp', 'ollama:llama3', 'local-custom'],
};

const defaults = {
  default_model: 'Groq:openai/gpt-oss-120b',
  providers: Object.fromEntries(Object.entries(providerModels).map(([provider, models]) => [
    provider,
    { enabled: provider === 'Groq', api_key: '', model: models[0], temperature: 0.3, max_tokens: 2048, status: 'not_configured' },
  ])),
};

export default function ModelSettingsPanel({ API }) {
  const { settings, setSettings, loading, status, setStatus, save } = useRemoteSettings(API, '/settings/models', defaults);
  const defaultOptions = useMemo(
    () => Object.entries(providerModels).flatMap(([provider, models]) => models.map((model) => `${provider}:${model}`)),
    []
  );

  const updateProvider = (provider, key, value) => {
    setSettings((current) => ({
      ...current,
      providers: {
        ...current.providers,
        [provider]: { ...current.providers[provider], [key]: value },
      },
    }));
  };

  const testProvider = async (provider) => {
    setStatus(`Testing ${provider}...`);
    try {
      const data = await settingsRequest(API, '/settings/models/test', {
        method: 'POST',
        body: JSON.stringify({ provider }),
      });
      setStatus(data.message || `${provider} tested`);
    } catch (error) {
      setStatus(error.message || 'Test failed');
    }
  };

  return (
    <>
      <Panel title="Default Model" subtitle="Choose the provider/model EVA should use first.">
        <SettingRow title="Default model selector" detail="Fallback rules still apply when a provider is disabled.">
          <Select value={settings.default_model} options={defaultOptions} onChange={(value) => setSettings((current) => ({ ...current, default_model: value }))} />
        </SettingRow>
      </Panel>

      {Object.entries(settings.providers || {}).map(([provider, config]) => (
        <Panel
          key={provider}
          title={provider}
          subtitle={provider === 'Local Model' ? 'Local runtime configuration placeholder.' : 'Provider credentials are saved masked and never returned in full.'}
          actions={<StatusBadge tone={config.enabled ? 'success' : 'neutral'}>{config.enabled ? 'Enabled' : 'Disabled'}</StatusBadge>}
        >
          <SettingRow title="Enable provider" detail="Allow this provider in model routing.">
            <Toggle checked={!!config.enabled} onChange={(value) => updateProvider(provider, 'enabled', value)} />
          </SettingRow>
          <SettingRow title="API key" detail="Displayed masked after saving.">
            <TextInput value={config.api_key || ''} type="password" placeholder="sk-****abcd" onChange={(value) => updateProvider(provider, 'api_key', value)} />
          </SettingRow>
          <SettingRow title="Model" detail="Allowed values are validated by the backend.">
            <Select value={config.model} options={providerModels[provider] || []} onChange={(value) => updateProvider(provider, 'model', value)} />
          </SettingRow>
          <SettingRow title={`Temperature: ${config.temperature}`} detail="Controls response creativity.">
            <input className="eva-settings-range" type="range" min="0" max="2" step="0.1" value={config.temperature} onChange={(event) => updateProvider(provider, 'temperature', Number(event.target.value))} />
          </SettingRow>
          <SettingRow title="Max tokens" detail="Caps generated response length.">
            <NumberInput value={config.max_tokens} min={1} max={128000} onChange={(value) => updateProvider(provider, 'max_tokens', value)} />
          </SettingRow>
          <ButtonRow>
            <button type="button" className="eva-settings-button" onClick={() => testProvider(provider)}>Test connection</button>
          </ButtonRow>
        </Panel>
      ))}

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button primary" onClick={() => save(settings)}>Save model settings</button>
      </ButtonRow>
    </>
  );
}
