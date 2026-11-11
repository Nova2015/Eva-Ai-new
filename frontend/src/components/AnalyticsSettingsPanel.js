import { useCallback, useEffect, useState } from 'react';
import { ButtonRow, Panel, Select, SettingRow, Toggle, settingsRequest } from './SettingsPanelPrimitives';
import './AnalyticsSettingsPanel.css';

export default function AnalyticsSettingsPanel({ API }) {
  const [enabled, setEnabled] = useState(true);
  const [errors, setErrors] = useState(true);
  const [retention, setRetention] = useState('90 days');
  const [monitoring, setMonitoring] = useState(null);
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const data = await settingsRequest(API, '/monitoring/status');
    setMonitoring(data);
  }, [API]);

  useEffect(() => {
    load().catch((error) => setStatus(error.message));
  }, [load]);

  const save = () => {
    localStorage.setItem('eva_analytics_settings', JSON.stringify({ enabled, errors, retention }));
    setStatus('Analytics settings saved');
  };

  return (
    <>
      <Panel title="Analytics Controls" subtitle="Usage tracking, error retention, and admin reporting preferences.">
        <SettingRow title="Workspace analytics" detail="Track feature usage and adoption.">
          <Toggle checked={enabled} onChange={setEnabled} />
        </SettingRow>
        <SettingRow title="Error tracking" detail="Capture frontend/backend failure signals.">
          <Toggle checked={errors} onChange={setErrors} />
        </SettingRow>
        <SettingRow title="Retention" detail="How long analytics events are retained.">
          <Select value={retention} options={['30 days', '90 days', '1 year']} onChange={setRetention} />
        </SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button" onClick={load}>Refresh monitoring</button>
          <button type="button" className="eva-settings-button primary" onClick={save}>Save analytics</button>
        </ButtonRow>
      </Panel>
      <Panel title="Monitoring Snapshot">
        <div className="eva-dev-score-grid">
          <div className="eva-dev-score"><span>Backend</span><strong>{monitoring?.status || 'unknown'}</strong></div>
          <div className="eva-dev-score"><span>Latency p50</span><strong>{monitoring?.metrics?.latency_p50_ms || 0} ms</strong></div>
          <div className="eva-dev-score"><span>Latency p95</span><strong>{monitoring?.metrics?.latency_p95_ms || 0} ms</strong></div>
          <div className="eva-dev-score"><span>Cost status</span><strong>{monitoring?.costs?.status || 'unknown'}</strong></div>
        </div>
      </Panel>
    </>
  );
}
