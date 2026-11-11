"""Tests for Cloudinary delivery of generated files.

The credential is the thing to protect. This module is the only place in the
backend that holds an API secret, and the codes it returns end up in a chat
response and on health output, so the load-bearing tests are about what must
never come back out.
"""

import pytest

try:
    from file_delivery import credentials, signature, public_id, upload_raw, MAX_UPLOAD_BYTES
except ImportError:  # running from the repo root
    from src.file_delivery import (  # type: ignore
        credentials, signature, public_id, upload_raw, MAX_UPLOAD_BYTES)


URL = "cloudinary://123456789012345:abcdefSECRETvalue123@demo-cloud"


# ── A: parsing the credential ────────────────────────────────────────────────
def test_a_well_formed_url_is_parsed(monkeypatch):
    monkeypatch.setenv("CLOUDINARY_URL", URL)
    assert credentials() == ("demo-cloud", "123456789012345", "abcdefSECRETvalue123")


@pytest.mark.parametrize("value", [
    "", "   ",
    "https://api.cloudinary.com/v1_1/demo",        # wrong scheme
    "cloudinary://demo-cloud",                     # no key or secret
    "cloudinary://key@demo-cloud",                 # no secret
    "not a url at all",
])
def test_a_malformed_url_is_rejected_here_not_remotely(monkeypatch, value):
    """Failing locally gives a clear code. A half-parsed value produces a
    request that looks valid and is rejected with something unhelpful."""
    monkeypatch.setenv("CLOUDINARY_URL", value)
    assert credentials() is None


def test_an_unset_url_is_none(monkeypatch):
    monkeypatch.delenv("CLOUDINARY_URL", raising=False)
    assert credentials() is None


# ── B: the signature ─────────────────────────────────────────────────────────
def test_the_signature_is_stable_for_the_same_parameters():
    p = {"timestamp": 1000, "public_id": "eva/x-1000"}
    assert signature(dict(p), "sec") == signature(dict(p), "sec")


def test_the_signature_changes_with_the_secret():
    p = {"timestamp": 1000, "public_id": "eva/x-1000"}
    assert signature(dict(p), "sec-a") != signature(dict(p), "sec-b")


def test_the_signature_changes_with_the_parameters():
    a = signature({"timestamp": 1000, "public_id": "x"}, "sec")
    b = signature({"timestamp": 1001, "public_id": "x"}, "sec")
    assert a != b


def test_file_and_api_key_are_excluded_from_the_signature():
    """Cloudinary's own rule. Including them yields a request that always
    fails authentication, with an error that does not say why."""
    base = {"timestamp": 1000, "public_id": "x"}
    with_extra = dict(base, file=b"bytes", api_key="123", signature="old")
    assert signature(with_extra, "sec") == signature(base, "sec")


def test_the_secret_is_not_recoverable_from_the_signature():
    sig = signature({"timestamp": 1000}, "abcdefSECRETvalue123")
    assert "SECRET" not in sig
    assert len(sig) == 40 and all(c in "0123456789abcdef" for c in sig)


# ── C: ids ───────────────────────────────────────────────────────────────────
def test_ids_are_unique_across_time():
    """Cloudinary upserts on public_id, so two people asking for "sales" must
    not overwrite each other's download."""
    assert public_id("sales", now=1000) != public_id("sales", now=1001)


@pytest.mark.parametrize("stem", ["../../etc/passwd", "a b/c\\d?e", "", "  "])
def test_ids_are_made_safe(stem):
    pid = public_id(stem, now=1000)
    assert pid.startswith("eva/")
    assert not set(pid[4:]) & set("/\\?. ")


# ── D: refusing before spending an upload ────────────────────────────────────
def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_empty_bytes_are_refused_without_a_request(monkeypatch):
    monkeypatch.setenv("CLOUDINARY_URL", URL)
    url, code = _run(upload_raw(b"", "x.xlsx"))
    assert url is None and code == "empty"


def test_an_oversized_file_is_refused_locally(monkeypatch):
    monkeypatch.setenv("CLOUDINARY_URL", URL)
    url, code = _run(upload_raw(b"x" * (MAX_UPLOAD_BYTES + 1), "x.xlsx"))
    assert url is None and code == "too_large"


def test_missing_configuration_is_reported_not_attempted(monkeypatch):
    monkeypatch.delenv("CLOUDINARY_URL", raising=False)
    url, code = _run(upload_raw(b"data", "x.xlsx"))
    assert url is None and code == "not_configured"


def test_an_exception_that_quotes_the_request_still_leaks_nothing(monkeypatch):
    """The real hazard. Many HTTP clients put the request — headers, form
    fields, signed parameters — into the exception message, and this module
    holds the only API secret in the backend.

    The previous version of this test relied on a DNS failure, whose message
    mentions only the host, so it never exercised the leak and a mutation
    returning str(exc) survived it.
    """
    import sys as _sys
    import types as _types

    class _Boom(Exception):
        pass

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise _Boom("upload failed: api_key=KEYLEAK123 "
                        "signature=abc secret=SECRETLEAK456")

    stub = _types.ModuleType("httpx")
    stub.AsyncClient = _Client
    monkeypatch.setitem(_sys.modules, "httpx", stub)
    monkeypatch.setenv("CLOUDINARY_URL", URL)

    url, code = _run(upload_raw(b"data", "x.xlsx"))
    assert url is None
    assert "KEYLEAK123" not in code
    assert "SECRETLEAK456" not in code
    assert code == "error__Boom"


def test_a_failure_code_never_carries_the_credential(monkeypatch):
    """Cloudinary errors quote the request, which carries api_key and the
    signed parameters. Only the exception class may come back."""
    monkeypatch.setenv("CLOUDINARY_URL",
                       "cloudinary://KEYLEAK123:SECRETLEAK456@nonexistent-cloud-xyz")
    url, code = _run(upload_raw(b"data", "x.xlsx", timeout=3))
    assert url is None
    assert "KEYLEAK123" not in code
    assert "SECRETLEAK456" not in code
    assert code.startswith("error_") or code.startswith("http_")
