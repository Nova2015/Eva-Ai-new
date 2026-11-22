import json
from typing import Iterable


def examples_to_jsonl(examples: Iterable[dict]) -> str:
    lines = []
    for item in examples:
        prompt = item.get("prompt") or item.get("question") or "Domain question"
        completion = item.get("completion") or item.get("answer") or item.get("content") or ""
        lines.append(json.dumps({"messages": [
            {"role": "system", "content": "You are EVA AI with domain-specific knowledge."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": completion},
        ]}, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")
