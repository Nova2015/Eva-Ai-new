import { useCallback, useEffect, useState } from 'react';
import { ButtonRow, Panel, Select, SettingRow, TextInput, settingsRequest } from './SettingsPanelPrimitives';
import './TeamSettingsPanel.css';

const roles = ['Owner', 'Admin', 'Developer', 'Member', 'Viewer'];

export default function TeamSettingsPanel({ API }) {
  const [workspace, setWorkspace] = useState({ name: 'EVA Workspace' });
  const [invite, setInvite] = useState({ name: '', email: '', role: 'Member' });
  const [members, setMembers] = useState([]);
  const [limits, setLimits] = useState({});
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const [membersData, limitsData] = await Promise.all([
      settingsRequest(API, '/team/members'),
      settingsRequest(API, '/team/limits'),
    ]);
    setMembers(membersData.members || []);
    setLimits(limitsData.limits || {});
  }, [API]);

  useEffect(() => {
    load().catch((error) => setStatus(error.message));
  }, [load]);

  const saveWorkspace = async () => {
    const data = await settingsRequest(API, '/team/workspace', { method: 'POST', body: JSON.stringify(workspace) });
    setStatus(`Saved ${data.workspace?.name || workspace.name}`);
  };

  const sendInvite = async () => {
    const data = await settingsRequest(API, '/team/invite', { method: 'POST', body: JSON.stringify(invite) });
    setStatus(`Invited ${data.member?.email || invite.email}`);
    setInvite({ name: '', email: '', role: 'Member' });
    await load();
  };

  const changeRole = async (member_id, role) => {
    await settingsRequest(API, '/team/member/role', { method: 'POST', body: JSON.stringify({ member_id, role }) });
    await load();
  };

  const removeMember = async (member_id) => {
    if (!window.confirm('Remove this member?')) return;
    await settingsRequest(API, `/team/member/${member_id}`, { method: 'DELETE' });
    await load();
  };

  return (
    <>
      <Panel title="Workspace" subtitle="Create and manage the active team workspace.">
        <SettingRow title="Workspace name" detail="Visible to invited members.">
          <TextInput value={workspace.name} onChange={(value) => setWorkspace({ ...workspace, name: value })} />
        </SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button primary" onClick={saveWorkspace}>Create workspace</button>
        </ButtonRow>
      </Panel>

      <Panel title="Invite Team Member" subtitle="Owner, Admin, Developer, Member, and Viewer roles are supported.">
        <SettingRow title="Name"><TextInput value={invite.name} onChange={(value) => setInvite((current) => ({ ...current, name: value }))} /></SettingRow>
        <SettingRow title="Email"><TextInput value={invite.email} onChange={(value) => setInvite((current) => ({ ...current, email: value }))} /></SettingRow>
        <SettingRow title="Role"><Select value={invite.role} options={roles} onChange={(value) => setInvite((current) => ({ ...current, role: value }))} /></SettingRow>
        <ButtonRow>
          <button type="button" className="eva-settings-button primary" onClick={sendInvite}>Invite</button>
        </ButtonRow>
      </Panel>

      <Panel title="Team Table">
        <div className="eva-settings-table">
          {members.map((member) => (
            <div key={member.id} className="eva-team-row">
              <span>{member.name}</span>
              <span>{member.email}</span>
              <Select value={member.display_role || (member.role === 'User' ? 'Member' : member.role)} options={roles} onChange={(value) => changeRole(member.id, value)} />
              <button type="button" className="eva-settings-button danger" onClick={() => removeMember(member.id)}>Remove</button>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Workspace Usage Limits" subtitle="Plan-aware placeholders for workspace governance.">
        <div className="eva-dev-score-grid">
          {Object.entries(limits).map(([key, value]) => (
            <div key={key} className="eva-dev-score">
              <span>{key.replaceAll('_', ' ')}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}
