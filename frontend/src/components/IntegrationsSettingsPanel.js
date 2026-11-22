import { useMemo } from 'react';
import { ButtonRow, Panel, SettingRow, StatusBadge, TextInput, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import './IntegrationsSettingsPanel.css';

const names = ['Google Drive', 'Gmail', 'Google Calendar', 'GitHub', 'Hugging Face', 'Cloudinary', 'Notion', 'Slack', 'Zapier/Webhooks'];
const defaults = {
  integrations: Object.fromEntries(names.map((name) => [name, { connected: false, status: 'not_connected', api_key: '', oauth_placeholder: 'OAuth connection pending', webhook_url: '', webhook_secret: '' }])),
  webhook_endpoint: '/integrations/webhook/eva',
};

export default function IntegrationsSettingsPanel({ API }) {
  const { settings, setSettings, loading, status, setStatus, save } = useRemoteSettings(API, '/settings/integrations', defaults);
  const endpoint = useMemo(() => `${window.location.origin}${settings.webhook_endpoint || '/integrations/webhook/eva'}`, [settings.webhook_endpoint]);

  const updateIntegration = (name, key, value) => {
    setSettings((current) => ({
      ...current,
      integrations: {
        ...current.integrations,
        [name]: { ...current.integrations[name], [key]: value },
      },
    }));
  };

  const testIntegration = async (name) => {
    try {
      const data = await settingsRequest(API, '/settings/integrations/test', { method: 'POST', body: JSON.stringify({ integration: name }) });
      setStatus(`${name}: ${data.status}`);
    } catch (error) {
      setStatus(error.message || 'Test failed');
    }
  };

  const disconnect = async (name) => {
    if (!window.confirm(`Disconnect ${name}?`)) return;
    try {
      const data = await settingsRequest(API, '/settings/integrations/disconnect', { method: 'POST', body: JSON.stringify({ integration: name }) });
      setSettings(data.settings || settings);
      setStatus(`${name} disconnected`);
    } catch (error) {
      setStatus(error.message || 'Disconnect failed');
    }
  };

  const copyEndpoint = async () => {
    await navigator.clipboard?.writeText(endpoint);
    setStatus('Webhook endpoint copied');
  };

  return (
    <>
      <Panel title="Webhook Endpoint" subtitle="Use this endpoint for Zapier/Webhooks style integrations.">
        <SettingRow title="Webhook URL" detail="Public callback endpoint placeholder.">
          <div className="eva-settings-inline-control">
            <input className="eva-settings-input" value={endpoint} readOnly />
            <button type="button" className="eva-settings-button" onClick={copyEndpoint}>Copy</button>
          </div>
        </SettingRow>
      </Panel>

      <div className="eva-settings-card-grid">
        {names.map((name) => {
          const item = settings.integrations?.[name] || defaults.integrations[name];
          return (
            <Panel key={name} title={name} actions={<StatusBadge tone={item.connected ? 'success' : 'neutral'}>{item.status || 'not_connected'}</StatusBadge>}>
              <SettingRow title="Connected" detail="Enable or pause this integration.">
                <Toggle checked={!!item.connected} onChange={(value) => updateIntegration(name, 'connected', value)} />
              </SettingRow>
              <SettingRow title="API key / OAuth placeholder" detail="Secrets stay masked after saving.">
                <TextInput value={item.api_key || ''} type="password" placeholder="sk-****abcd" onChange={(value) => updateIntegration(name, 'api_key', value)} />
              </SettingRow>
              {name === 'Zapier/Webhooks' && (
                <>
                  <SettingRow title="Webhook URL" detail="Destination URL for outgoing events.">
                    <TextInput value={item.webhook_url || ''} placeholder="https://hooks.zapier.com/..." onChange={(value) => updateIntegration(name, 'webhook_url', value)} />
                  </SettingRow>
                  <SettingRow title="Webhook secret" detail="Used to sign placeholder webhook calls.">
                    <TextInput value={item.webhook_secret || ''} type="password" placeholder="whsec-****abcd" onChange={(value) => updateIntegration(name, 'webhook_secret', value)} />
                  </SettingRow>
                </>
              )}
              <ButtonRow>
                <button type="button" className="eva-settings-button" onClick={() => testIntegration(name)}>Test</button>
                <button type="button" className="eva-settings-button" onClick={() => disconnect(name)}>Disconnect</button>
              </ButtonRow>
            </Panel>
          );
        })}
      </div>

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button primary" onClick={() => save(settings)}>Save integrations</button>
      </ButtonRow>
    </>
  );
}
