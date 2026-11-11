PHASE_ROLES = ("Owner", "Admin", "Developer", "Member", "Viewer")


def to_store_role(role: str) -> str:
    if (role or "").strip().lower() == "member":
        return "User"
    return role or "User"


def to_display_role(role: str) -> str:
    if (role or "").strip().lower() == "user":
        return "Member"
    return role
