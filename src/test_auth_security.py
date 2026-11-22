"""Regression tests for EVA AI authentication security."""

import ast
import base64
import json
import os

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
APP_SOURCE = os.path.join(HERE, "app.py")


@pytest.fixture(scope="module")
def app_module():
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import app
    return app


def credentials(app_module, token):
    return app_module.HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token,
    )


def unsigned_jwt(payload):
    """Create a JWT-shaped token with no valid signature."""
    def encode(data):
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = {"alg": "none", "typ": "JWT"}
    return f"{encode(header)}.{encode(payload)}."


def test_valid_eva_jwt_is_accepted(app_module):
    token = app_module.create_access_token(
        {"sub": "valid-user@example.test"}
    )
    result = app_module.get_current_user(credentials(app_module, token))
    assert result == "valid-user@example.test"


def test_get_current_user_rejects_unsigned_jwt(app_module):
    token = unsigned_jwt({
        "sub": "attacker@example.test",
        "email": "attacker@example.test",
        "role": "user",
    })

    with pytest.raises(app_module.HTTPException) as exc:
        app_module.get_current_user(credentials(app_module, token))

    assert exc.value.status_code == 401


def test_auth_payload_rejects_unsigned_admin_jwt(app_module):
    token = unsigned_jwt({
        "sub": "attacker@example.test",
        "email": "attacker@example.test",
        "role": "admin",
    })

    with pytest.raises(app_module.HTTPException) as exc:
        app_module._decode_auth_payload(credentials(app_module, token))

    assert exc.value.status_code == 401


def test_demo_token_is_rejected_when_demo_auth_is_disabled(
    app_module, monkeypatch
):
    monkeypatch.setenv("EVA_ALLOW_DEMO_AUTH", "false")
    monkeypatch.setenv("EVA_ENV", "production")

    with pytest.raises(app_module.HTTPException) as exc:
        app_module.get_current_user(
            credentials(app_module, "offline_test-token")
        )

    assert exc.value.status_code == 401


def test_optional_auth_does_not_accept_demo_token_in_production(
    app_module, monkeypatch
):
    monkeypatch.setenv("EVA_ALLOW_DEMO_AUTH", "false")
    monkeypatch.setenv("EVA_ENV", "production")

    result = app_module.get_optional_user(
        credentials(app_module, "offline_test-token")
    )

    assert result == "anonymous"


def test_optional_user_has_only_one_definition():
    with open(APP_SOURCE, encoding="utf-8-sig") as f:
        tree = ast.parse(f.read())

    definitions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "get_optional_user"
    ]

    assert len(definitions) == 1, (
        f"Expected one get_optional_user definition, found {len(definitions)}"
    )