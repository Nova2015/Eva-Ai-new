from team.roles import to_display_role, to_store_role
from team.workspace_store import DEFAULT_ORG_ID, list_members, remove_member, update_member_role


def list_display_members(organization_id=DEFAULT_ORG_ID, user_id="user_001"):
    members = list_members(organization_id=organization_id, user_id=user_id)
    for member in members:
        member["display_role"] = to_display_role(member.get("role"))
    return members


def change_role(payload):
    return update_member_role(
        organization_id=payload.get("organization_id", DEFAULT_ORG_ID),
        member_id=payload.get("member_id", ""),
        role=to_store_role(payload.get("role", "Member")),
        actor_user_id=payload.get("user_id", "user_001"),
    )


def delete_member(member_id, organization_id=DEFAULT_ORG_ID, user_id="user_001"):
    return remove_member(organization_id=organization_id, member_id=member_id, actor_user_id=user_id)
