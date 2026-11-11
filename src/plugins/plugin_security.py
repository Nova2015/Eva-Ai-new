from fastapi import HTTPException


AUTH_TYPES = ("None", "API Key", "OAuth", "Bearer Token")


def validate_auth_type(auth_type: str) -> str:
    value = auth_type or "None"
    if value not in AUTH_TYPES:
        raise HTTPException(status_code=400, detail="Invalid auth type")
    return value


def dangerous_endpoint(endpoint: str) -> bool:
    endpoint = (endpoint or "").lower()
    return endpoint.startswith(("file://", "javascript:")) or "localhost" in endpoint
