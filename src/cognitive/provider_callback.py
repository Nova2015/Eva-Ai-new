
"""Provider callback for structured reasoning extraction.

Uses the same provider that generated the assistant answer.
Does not perform automatic failover or choose another provider.
"""

from __future__ import annotations

from typing import Callable, Optional

import providers


_ALLOWED_PROVIDERS = frozenset({
    "eva_local",
    "groq",
    "openai",
    "gemini",
    "local",
})


def build_reasoning_llm(
    provider_id: Optional[str],
    model_name: Optional[str] = None,
) -> Optional[Callable[[str], str]]:
    """Build a JSON-extraction callback for a known provider.

    Returns None for unsupported providers.
    Provider errors are allowed to propagate to the orchestrator,
    which handles them as INCONCLUSIVE.
    """

    if not isinstance(provider_id, str):
        return None

    provider_id = provider_id.strip().lower()

    if provider_id not in _ALLOWED_PROVIDERS:
        return None

    if not providers.configured(provider_id):
        return None

    if model_name is not None:
        if not isinstance(model_name, str) or not model_name.strip():
            model_name = None
        else:
            model_name = model_name.strip()

    def extraction_llm(prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Reasoning extraction prompt is empty.")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a structured constraint extraction engine. "
                    "Return only valid JSON matching the requested schema. "
                    "Do not include Markdown fences or explanations. "
                    "Do not invent constraints or task dependencies."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        return providers.dispatch(
            provider_id,
            messages,
            model=model_name,
            max_tokens=1200,
            temperature=0.0,
        )

    return extraction_llm
