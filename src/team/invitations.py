from team.roles import to_store_role
from team.workspace_store import DEFAULT_ORG_ID, invite_member


def invite(payload):
    return invite_member(
        organization_id=payload.get("organization_id", DEFAULT_ORG_ID),
        name=payload.get("name", ""),
        email=payload.get("email", ""),
        role=to_store_role(payload.get("role", "Member")),
        invited_by=payload.get("user_id", "user_001"),
    )
