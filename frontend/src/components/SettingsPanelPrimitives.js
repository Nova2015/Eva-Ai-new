import { useCallback, useEffect, useState } from 'react';

export const joinApi = (API = '', path = '') => `${API || ''}${path}`;

function storageKey(path = '') {
  return `eva_settings_${String(path || 'general').replace(/[^a-z0-9_-]+/gi, '_')}`;
}

function readLocalSettings(path, defaults) {
  try {
    const saved = localStorage.getItem(storageKey(path));
    return saved ? { ...defaults, ...JSON.parse(saved) } : defaults;
  } catch {
    return defaults;
  }
}

function writeLocalSettings(path, settings) {
  localStorage.setItem(storageKey(path), JSON.stringify(settings || {}));
}

export async function settingsRequest(API, path, options = {}) {
  const token = localStorage.getItem('aria_token');
  const headers = {
    'ngrok-skip-browser-warning': 'true',
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(joinApi(API, path), { ...options, headers });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { text };
  }
  if (!res.ok) throw new Error(data.detail || data.message || `Request failed (${res.status})`);
  return data;
}

export function useRemoteSettings(API, path, defaults) {
  const [settings, setSettingsState] = useState(() => readLocalSettings(path, defaults));
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');

  const setSettings = (nextSettings) => {
    setSettingsState((current) => {
      const resolved = typeof nextSettings === 'function' ? nextSettings(current) : nextSettings;
      const next = { ...defaults, ...(resolved || {}) };
      writeLocalSettings(path, next);
      return next;
    });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setStatus('');
    try {
      const data = await settingsRequest(API, path);
      const next = { ...defaults, ...(data.settings || {}) };
      setSettingsState(next);
      writeLocalSettings(path, next);
    } catch (error) {
      const local = readLocalSettings(path, defaults);
      setSettingsState(local);
      setStatus(local === defaults ? 'Using local defaults' : 'Using saved local settings');
    } finally {
      setLoading(false);
    }
  }, [API, path, defaults]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (nextSettings = settings) => {
    setLoading(true);
    writeLocalSettings(path, nextSettings);
    try {
      const data = await settingsRequest(API, path, {
        method: 'POST',
        body: JSON.stringify({ settings: nextSettings }),
      });
      const next = { ...defaults, ...(data.settings || nextSettings) };
      setSettingsState(next);
      writeLocalSettings(path, next);
      setStatus('Saved');
      return data;
    } catch (error) {
      setSettingsState({ ...defaults, ...nextSettings });
      setStatus('Saved locally');
      return { ok: false, local: true, settings: nextSettings, error: error.message || 'Backend unavailable' };
    } finally {
      setLoading(false);
    }
  };

  const update = (key, value) => {
    setSettings((current) => {
      const next = { ...current, [key]: value };
      writeLocalSettings(path, next);
      return next;
    });
  };

  return { settings, setSettings, update, loading, status, setStatus, save, load };
}

export function Panel({ title, subtitle, children, actions }) {
  return (
    <section className="eva-settings-panel">
      <div className="eva-settings-panel-head">
        <div>
          <h3 className="eva-settings-panel-title">{title}</h3>
          {subtitle && <p className="eva-settings-panel-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="eva-settings-panel-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function SettingRow({ title, detail, children }) {
  return (
    <div className="eva-settings-row">
      <div>
        <div className="eva-settings-row-title">{title}</div>
        {detail && <div className="eva-settings-row-detail">{detail}</div>}
      </div>
      <div className="eva-settings-control-wrap">{children}</div>
    </div>
  );
}

export function Select({ value, onChange, options }) {
  return (
    <select className="eva-settings-select" value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => {
        const valueText = typeof option === 'string' ? option : option.value;
        const label = typeof option === 'string' ? option : option.label;
        return <option key={valueText} value={valueText}>{label}</option>;
      })}
    </select>
  );
}

export function Toggle({ checked = false, onChange }) {
  return (
    <button type="button" className="eva-settings-toggle" aria-pressed={checked} onClick={() => onChange?.(!checked)}>
      <span className="eva-settings-toggle-thumb" />
    </button>
  );
}

export function StatusBadge({ children, tone = 'neutral' }) {
  return <span className={`eva-settings-badge ${tone}`}>{children}</span>;
}

export function ButtonRow({ children, status }) {
  return (
    <div className="eva-settings-button-row">
      {children}
      {status && <span className="eva-settings-chip">{status}</span>}
    </div>
  );
}

export function NumberInput({ value, onChange, min = 0, max, step = 1 }) {
  return (
    <input
      className="eva-settings-input"
      type="number"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  );
}

export function TextInput({ value, onChange, type = 'text', placeholder = '' }) {
  return (
    <input
      className="eva-settings-input"
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
