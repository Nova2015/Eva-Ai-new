import { ButtonRow, Panel, SettingRow, Toggle, settingsRequest, useRemoteSettings } from './SettingsPanelPrimitives';
import './ChatSettingsPanel.css';

const defaults = {
  default_system_prompt: 'You are EVA AI. Be helpful, concise, and source-aware when knowledge base context is used.',
  chat_memory: true,
  auto_title_chats: true,
  streaming: true,
  voice_reply: false,
  file_upload: true,
  code_copy_button: true,
  markdown_rendering: true,
  export_options: { pdf: true, docx: true, txt: true, json: true },
};

const toggles = [
  ['chat_memory', 'Chat memory', 'Retain useful conversation context.'],
  ['auto_title_chats', 'Auto-title chats', 'Generate conversation titles automatically.'],
  ['streaming', 'Streaming', 'Show responses while they are generated.'],
  ['voice_reply', 'Voice reply', 'Enable speech reply controls.'],
  ['file_upload', 'File upload', 'Allow files in chat.'],
  ['code_copy_button', 'Code copy button', 'Show copy controls on code blocks.'],
  ['markdown_rendering', 'Markdown rendering', 'Render markdown in assistant responses.'],
];

export default function ChatSettingsPanel({ API }) {
  const { settings, setSettings, update, loading, status, setStatus, save } = useRemoteSettings(API, '/settings/chat', defaults);

  const updateExport = (key, value) => {
    setSettings((current) => ({ ...current, export_options: { ...current.export_options, [key]: value } }));
  };

  const clearChats = async () => {
    if (!window.confirm('Clear all chats for this workspace?')) return;
    try {
      const data = await settingsRequest(API, '/settings/chat/history', { method: 'DELETE' });
      setStatus(data.message || 'Chat history clear requested');
    } catch (error) {
      setStatus(error.message || 'Clear failed');
    }
  };

  return (
    <>
      <Panel title="Conversation Defaults" subtitle="Controls EVA response behavior and chat surface defaults.">
        <SettingRow title="Default system prompt" detail="Applied when no custom agent/system prompt is active.">
          <textarea className="eva-settings-textarea" value={settings.default_system_prompt} onChange={(event) => update('default_system_prompt', event.target.value)} />
        </SettingRow>
        {toggles.map(([key, title, detail]) => (
          <SettingRow key={key} title={title} detail={detail}>
            <Toggle checked={!!settings[key]} onChange={(value) => update(key, value)} />
          </SettingRow>
        ))}
      </Panel>

      <Panel title="Export Options" subtitle="Select chat export formats available in the workspace.">
        <div className="eva-settings-check-grid">
          {['pdf', 'docx', 'txt', 'json'].map((format) => (
            <label key={format} className="eva-settings-check">
              <input type="checkbox" checked={!!settings.export_options?.[format]} onChange={(event) => updateExport(format, event.target.checked)} />
              <span>{format.toUpperCase()}</span>
            </label>
          ))}
        </div>
      </Panel>

      <ButtonRow status={loading ? 'Working...' : status}>
        <button type="button" className="eva-settings-button danger" onClick={clearChats}>Clear all chats</button>
        <button type="button" className="eva-settings-button primary" onClick={() => save(settings)}>Save chat settings</button>
      </ButtonRow>
    </>
  );
}
