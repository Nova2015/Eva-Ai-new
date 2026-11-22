import { useEffect, useState } from 'react';
import { ButtonRow, Panel, SettingRow, TextInput, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import './SecuritySettingsPanel.css';

const defaults = {
  two_factor: false,
  login_alerts: true,
  api_key_visibility_protection: true,
  active_sessions: [],
  activity_log: [],
};

export default function SecuritySettingsPanel({ API }) {
  const { settings, update, loading, status, setStatus, save, load } = useRemoteSettings(API, '/settings/security', defaults);
  const [passwords, setPasswords] = useState({ current_password: '', new_password: '' });
  const [activity, setActivity] = useState([]);

  useEffect(() => {
    settingsRequest(API, '/settings/security/activity').then((data) => setActivity(data.activity || [])).catch(() => {});
  }, [API, settings.updated_at]);

  const changePassword = async () => {
    try {
      const data = await settingsRequest(API, '/settings/security/change-password', { method: 'POST', body: JSON.stringify(passwords) });
      setStatus(data.message || 'Password change requested');
      setPasswords({ current_password: '', new_password: '' });
    } catch (error) {
      setStatus(error.message || 'Password change failed');
    }
  };

  const logoutAll = async () => {
    if (!window.confirm('Logout all other devices?')) return;
    const data = await settingsRequest(API, '/settings/security/logout-all', { method: 'POST', body: JSON.stringify({}) });
    setStatus('Sessions refreshed');
    if (data.settings) load();
  };

  const exportData = async () => {
    const data = await settingsRequest(API, '/settings/security/export-data', { method: 'POST', body: JSON.stringify({}) });
    const blob = new Blob([JSON.stringify(data.export || data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'eva-security-export.json';
    link.click();
    URL.revokeObjectURL(url);
    setStatus('Security export prepared');
  };

  const deleteAccount = async () => {
    const confirmation = window.prompt('Type DELETE to request account deletion');
    if (confirmation !== 'DELETE') return;
    const data = await settingsRequest(API, '/settings/security/account', { method: 'DELETE', body: JSON.stringify({ confirmation }) });
    setStatus(data.message || 'Delete request recorded');
  };

  return (
    <>
      <Panel title="Protection" subtitle="Sensitive controls require explicit confirmation for destructive actions.">
        <SettingRow title="2FA" detail="Require a second factor for login.">
          <Toggle checked={!!settings.two_factor} onChange={(value) => update('two_factor', value)} />
        </SettingRow>
        <SettingRow title="Login alerts" detail="Notify the workspace owner about new sessions.">
          <Toggle checked={!!settings.login_alerts} onChange={(value) => update('login_alerts', value)} />
        </SettingRow>
        <SettingRow title="API key visibility protection" detail="Mask secrets across settings and integrations.">
          <Toggle checked={!!settings.api_key_visibility_protection} onChange={(value) => update('api_key_visibility_protection', value)} />
        </SettingRow>
      </Panel>

      <Panel title="Active Sessions" subtitle="Current sessions scoped to this workspace.">
        <div className="eva-settings-table">
          {(settings.active_sessions || []).map((session) => (
            <div key={session.id} className="eva-settings-table-row">
              <span>{session.device}</span>
              <span>{session.location || 'Unknown location'}</span>
              <span>{session.current ? 'Current' : session.last_active}</span>
            </div>
          ))}
        </div>
        <ButtonRow>
          <button type="button" className="eva-settings-button" onClick={logoutAll}>Logout all devices</button>
        </ButtonRow>
      </Panel>

      <Panel title="Password" subtitle="Passwords are never logged or returned by the backend.">
        <SettingRow title="Current password" detail="Required for password change validation.">
          <TextInput value={passwords.current_password} type="password" onChange={(value) => setPasswords((current) => ({ ...current, current_password: value }))} />
        </SettingRow>
        <SettingRow title="New password" detail="Use a strong, unique password.">
          <TextInput value={passwords.new_password} type="password" onChange={(value) => setPasswords((current) => ({ ...current, new_password: value }))} />
        </SettingRow>
        <ButtonRow>
          <button type="button" className="eva-settings-button" onClick={changePassword}>Change password</button>
        </ButtonRow>
      </Panel>

      <Panel title="Security Activity" subtitle="Recent sensitive events.">
        <div className="eva-settings-table">
          {(activity.length ? activity : settings.activity_log || []).slice(0, 8).map((item, index) => (
            <div key={`${item.event}-${index}`} className="eva-settings-table-row">
              <span>{item.event}</span>
              <span>{item.severity || 'info'}</span>
              <span>{item.created_at}</span>
            </div>
          ))}
        </div>
      </Panel>

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button" onClick={exportData}>Export data</button>
        <button type="button" className="eva-settings-button danger" onClick={deleteAccount}>Delete account</button>
        <button type="button" className="eva-settings-button primary" onClick={() => save(settings)}>Save security</button>
      </ButtonRow>
    </>
  );
}
