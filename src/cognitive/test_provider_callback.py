
import pytest

from . import provider_callback


def test_unsupported_provider_returns_none(monkeypatch):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda provider_id: True,
    )

    result = provider_callback.build_reasoning_llm("memory")

    assert result is None


def test_unconfigured_provider_returns_none(monkeypatch):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda provider_id: False,
    )

    result = provider_callback.build_reasoning_llm("openai")

    assert result is None


def test_valid_provider_builds_callback(monkeypatch):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda provider_id: True,
    )

    captured = {}

    def fake_dispatch(provider_id, messages, **kwargs):
        captured["provider_id"] = provider_id
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return '{"tasks": []}'

    monkeypatch.setattr(
        provider_callback.providers,
        "dispatch",
        fake_dispatch,
    )

    callback = provider_callback.build_reasoning_llm(
        "openai",
        "gpt-4o-mini",
    )

    assert callable(callback)

    result = callback("Extract constraints from this question.")

    assert result == '{"tasks": []}'
    assert captured["provider_id"] == "openai"
    assert captured["messages"][1]["content"] == (
        "Extract constraints from this question."
    )
    assert captured["kwargs"]["model"] == "gpt-4o-mini"
    assert captured["kwargs"]["max_tokens"] == 1200
    assert captured["kwargs"]["temperature"] == 0.0


def test_provider_id_is_normalized(monkeypatch):
    configured_ids = []

    def fake_configured(provider_id):
        configured_ids.append(provider_id)
        return True

    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        fake_configured,
    )

    callback = provider_callback.build_reasoning_llm(" OPENAI ")

    assert callable(callback)
    assert configured_ids == ["openai"]


def test_empty_prompt_is_rejected(monkeypatch):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda provider_id: True,
    )

    callback = provider_callback.build_reasoning_llm("openai")

    with pytest.raises(ValueError):
        callback("   ")


def test_dispatch_error_is_propagated(monkeypatch):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda provider_id: True,
    )

    def failing_dispatch(*args, **kwargs):
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(
        provider_callback.providers,
        "dispatch",
        failing_dispatch,
    )

    callback = provider_callback.build_reasoning_llm("openai")

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        callback("Extract constraints.")


def test_model_defaults_to_provider_default(monkeypatch):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda provider_id: True,
    )

    captured = {}

    def fake_dispatch(provider_id, messages, **kwargs):
        captured.update(kwargs)
        return "{}"

    monkeypatch.setattr(
        provider_callback.providers,
        "dispatch",
        fake_dispatch,
    )

    callback = provider_callback.build_reasoning_llm("gemini")
    callback("Extract constraints.")

    assert captured["model"] is None
    assert captured["temperature"] == 0.0


@pytest.mark.parametrize(
    "provider_id",
    ["eva_local", "groq", "openai", "gemini", "local"],
)
def test_all_supported_providers_are_accepted(
    monkeypatch,
    provider_id,
):
    monkeypatch.setattr(
        provider_callback.providers,
        "configured",
        lambda pid: True,
    )

    callback = provider_callback.build_reasoning_llm(provider_id)

    assert callable(callback)
