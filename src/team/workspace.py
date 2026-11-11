from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from eva_phase_common import now_iso, read_state, write_state
from team.audit import list_audit, record_audit
from team.invitations import invite
from team.limits import workspace_limits
from team.members import change_role, delete_member, list_display_members
from team.roles import PHASE_ROLES
from team.workspace_store import DEFAULT_ORG_ID, ensure_default_workspace, workspace_summary


router = APIRouter(tags=["team"])


@router.post("/team/workspace")
def create_workspace(payload: Dict[str, Any]):
    org = ensure_default_workspace(user_id=payload.get("user_id", "user_001"), name=payload.get("owner_name", "EVA Owner"), email=payload.get("owner_email", "owner@eva.local"))
    state = read_state("team_workspace_settings", {})
    state.update({
        "organization_id": org.get("id", DEFAULT_ORG_ID),
        "name": payload.get("name") or org.get("name", "EVA Workspace"),
        "organization_settings": payload.get("organization_settings", {}),
        "updated_at": now_iso(),
    })
    write_state("team_workspace_settings", state)
    record_audit("workspace_created_or_updated", payload.get("user_id", "user_001"), {"organization_id": org.get("id")})
    return {"ok": True, "workspace": {**org, **state}, "roles": list(PHASE_ROLES)}


@router.get("/team/members/phase")
def team_members_phase(organization_id: str = DEFAULT_ORG_ID, user_id: str = "user_001"):
    return {"ok": True, "members": list_display_members(organization_id, user_id), "roles": list(PHASE_ROLES)}


@router.post("/team/invite")
def team_invite_phase(payload: Dict[str, Any]):
    try:
        member = invite(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit("member_invited", payload.get("user_id", "user_001"), {"email": member.get("email"), "role": member.get("role")})
    return {"ok": True, "member": member, "roles": list(PHASE_ROLES)}


@router.post("/team/member/role")
def team_member_role_phase(payload: Dict[str, Any]):
    member = change_role(payload)
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    record_audit("member_role_changed", payload.get("user_id", "user_001"), {"member_id": payload.get("member_id"), "role": payload.get("role")})
    return {"ok": True, "member": member}


@router.delete("/team/member/{member_id}")
def team_member_delete_phase(member_id: str, organization_id: str = DEFAULT_ORG_ID, user_id: str = "user_001"):
    try:
        member = delete_member(member_id, organization_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    record_audit("member_removed", user_id, {"member_id": member_id, "email": member.get("email")})
    return {"ok": True, "removed": member}


@router.get("/team/audit")
def team_audit():
    return {"ok": True, "audit": list_audit()}


@router.get("/team/limits")
def team_limits(plan: str = "Free", organization_id: str = DEFAULT_ORG_ID, user_id: str = "user_001"):
    summary = workspace_summary(organization_id=organization_id, user_id=user_id)
    return {"ok": True, "limits": workspace_limits(plan), "usage": summary.get("counts", {}), "plan": plan}
