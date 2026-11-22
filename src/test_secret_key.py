"""Tests for the JWT signing key, which must never have a built-in default.

The defect: SECRET_KEY was read as os.getenv("SECRET_KEY", "EVA-super-secret-
jwt-key-2026-change-me"). SECRET_KEY signs the token that authenticates every
user, so a value printed in the source means anyone holding the repo can mint a
valid token for any account — no history of .env required, and no way to notice,
because a server missing the env var came up and signed with the default as if
nothing were wrong.

The two roles are tested separately because their safe failure differs:

  the SIGNER (app.py) must refuse to start — a server that cannot sign
  securely must not sign at all;

  the VERIFIERS (the rag/skill/suggestion routes, here and in eva-ml-service)
  must fall back to "anonymous" — with no key they can prove no identity, so
  they must grant none, rather than accept a token forged with the old default.
"""

import ast
import os
import re

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
BACKEND_RAG = os.path.join(HERE, "rag", "rag_routes_v2.py")
ML_DIR = os.path.join(os.path.dirname(HERE), "eva-ml-service")
ML_VERIFIERS = [os.path.join(ML_DIR, f) for f in
                ("rag_routes_v2.py", "skill_routes.py", "suggestion_routes.py")]

OLD_DEFAULTS = ("EVA-super-secret-jwt-key-2026-change-me", "eva-secret")


@pytest.fixture(scope="module")
def app_module():
    import sys
    sys.path.insert(0, HERE)
    import app
    return app


# ── A: the signer fails closed ──────────────────────────────────────────────
def test_require_secret_returns_a_value_that_is_set(app_module):
    os.environ["EVA_TEST_SECRET_PROBE"] = "a-real-value"
    try:
        assert app_module._require_secret("EVA_TEST_SECRET_PROBE") == "a-real-value"
    finally:
        del os.environ["EVA_TEST_SECRET_PROBE"]


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_require_secret_refuses_a_missing_or_blank_key(app_module, value):
    name = "EVA_TEST_SECRET_PROBE"
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        with pytest.raises(RuntimeError) as exc:
            app_module._require_secret(name)
        # The message must name the variable and not leak a value.
        assert name in str(exc.value)
    finally:
        os.environ.pop(name, None)


def test_the_error_does_not_suggest_a_default(app_module):
    """A message that whispered "defaulting to..." would reintroduce the habit
    the fix removes."""
    os.environ.pop("EVA_TEST_SECRET_PROBE", None)
    with pytest.raises(RuntimeError) as exc:
        app_module._require_secret("EVA_TEST_SECRET_PROBE")
    text = str(exc.value).lower()
    for word in OLD_DEFAULTS:
        assert word.lower() not in text
    assert "default" not in text or "no built-in default" in text or \
        "deliberately no built-in default" in text


def test_secret_key_is_read_through_require_secret(app_module):
    src = open(APP, encoding="utf-8-sig").read()
    assert re.search(r"SECRET_KEY\s*=\s*_require_secret\(", src), \
        "SECRET_KEY must go through _require_secret, not os.getenv with a default"


# ── B: no hardcoded fallback survives anywhere in the deploying tree ─────────
def _py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "node_modules", ".git")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


_FALLBACK_RE = re.compile(r"getenv\(\s*['\"]SECRET_KEY['\"]\s*,\s*['\"]")


def test_no_file_reads_secret_key_with_a_string_default():
    """The exact shape of the bug: a second argument to getenv is a fallback,
    and for SECRET_KEY any fallback is a signing key in source."""
    offenders = []
    for path in _py_files(HERE):
        # This file names the forbidden shape in its docstring in order to
        # forbid it, so it is the one place allowed to contain it.
        if os.path.abspath(path) == os.path.abspath(__file__):
            continue
        text = open(path, encoding="utf-8-sig", errors="replace").read()
        if _FALLBACK_RE.search(text):
            offenders.append(os.path.relpath(path, HERE))
    assert not offenders, f"SECRET_KEY still has a hardcoded fallback in: {offenders}"


@pytest.mark.parametrize("literal", OLD_DEFAULTS)
def test_the_old_default_strings_are_gone_from_the_backend(literal):
    for path in _py_files(HERE):
        text = open(path, encoding="utf-8-sig", errors="replace").read()
        # Allowed only in this test file, which names them to forbid them.
        if os.path.abspath(path) == os.path.abspath(__file__):
            continue
        assert literal not in text, f"{literal!r} still present in {path}"


# ── C: the verifiers fall back to anonymous, not to a default key ───────────
def test_the_backend_verifier_has_no_default_secret():
    src = open(BACKEND_RAG, encoding="utf-8-sig").read()
    assert not _FALLBACK_RE.search(src)
    assert re.search(r"if not secret:\s*\n\s*return ['\"]anonymous['\"]", src), \
        "the verifier must return anonymous when no key is configured"


@pytest.mark.parametrize("path", ML_VERIFIERS)
def test_each_ml_verifier_has_no_default_secret(path):
    if not os.path.isfile(path):
        pytest.skip("eva-ml-service submodule not checked out")
    src = open(path, encoding="utf-8-sig").read()
    assert not _FALLBACK_RE.search(src), \
        f"{os.path.basename(path)} still defaults SECRET_KEY"
    assert 'os.getenv("SECRET_KEY")' in src or "os.getenv('SECRET_KEY')" in src
    assert re.search(r"if not secret:\s*\n\s*return ['\"]anonymous['\"]", src), \
        f"{os.path.basename(path)} must go anonymous when no key is set"


def test_the_ml_verifiers_do_not_drift_from_each_other():
    """Three copies of the same auth helper. If one is patched and the others
    are not, identity validation depends on which route was called."""
    bodies = []
    for path in ML_VERIFIERS:
        if not os.path.isfile(path):
            pytest.skip("eva-ml-service submodule not checked out")
        src = open(path, encoding="utf-8-sig").read()
        m = re.search(r"secret = \(os\.getenv.*?return ['\"]anonymous['\"]",
                      src, re.S)
        assert m, f"{os.path.basename(path)} has an unexpected verifier shape"
        bodies.append(" ".join(m.group(0).split()))
    assert len(set(bodies)) == 1, "the ML verifiers have drifted apart"
