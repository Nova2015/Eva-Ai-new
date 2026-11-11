"""
Standalone checks for route_query word-boundary matching.

No pytest, no deps, no imports of the agent modules. Run from repo root:

    python src/agents/test_router.py

Targets the substring-matching bug: "pr" matched "preserve", so every
enhanced prompt was routed to the Code Agent.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the term lists and matcher without pulling in the agent modules,
# which would drag in the whole app.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_router_src", os.path.join(os.path.dirname(os.path.abspath(__file__)), "router.py")
)
_src = open(_spec.origin, encoding="utf-8").read()

# Strip the relative import of the agent modules so this runs standalone.
_src = re.sub(r"^from \. import .*$", "", _src, flags=re.MULTILINE)
_src = re.sub(r"^AGENTS = \{.*?\}$", "AGENTS = {}", _src, flags=re.MULTILINE | re.DOTALL)
# Replace agent id references with plain strings.
_src = re.sub(r"(\w+)_agent\.AGENT_ID", r'"\1"', _src)
_src = re.sub(r"def get_agent\(.*", "", _src, flags=re.DOTALL)

_mod = {}
exec(compile(_src, "router.py", "exec"), _mod)
route_query = _mod["route_query"]


PASSED, FAILED = [], []


def check(name, actual, expected):
    if actual == expected:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}: got {actual!r}, expected {expected!r}")


BOILERPLATE = (
    "hi\n\n[Internal EVA prompt enhancement]\nIntent: general\n"
    "Preserve the user's meaning and answer the original request.\n"
    "Improve clarity, grammar, structure, assumptions, and concise output "
    "expectations."
)

CASES = [
    # (message, expected_agent, why)
    ("hi", "chat", "bare greeting"),
    ("hello there", "chat", "greeting"),
    ("Who are you?", "chat", "identity question"),
    (BOILERPLATE, "chat", "THE BUG: 'pr' must not match 'Preserve'"),
    ("please preserve the formatting", "chat", "'preserve' is not a code term"),
    ("what is your approach", "chat", "'pr' inside 'approach'"),
    ("print the total", "chat", "'pr' inside 'print'"),
    ("I use docker daily", "chat", "'doc' inside 'docker'"),
    ("the zipper broke", "chat", "'zip' inside 'zipper'"),
    ("this is encoded text", "chat", "'code' inside 'encoded'"),

    # Real matches must still work
    ("fix this python code", "code", "genuine code query"),
    ("I have errors in my build", "code", "plural 'errors'"),
    ("there are bugs here", "code", "plural 'bugs'"),
    ("review my pr", "code", "'pr' as a real word"),
    ("check the stack traces", "code", "plural multi-word term"),
    ("summarize the pdf", "rag", "document query"),
    ("look in my documents", "rag", "plural 'documents'"),
    ("scan for vulnerabilities", "security", "security term"),
    ("train model on this dataset", "ml", "ml term"),
    ("generate image of a cat", "image", "image term"),
]


if __name__ == "__main__":
    print("route_query — word-boundary checks\n")
    for message, expected, why in CASES:
        label = f"{why}: {message[:45]!r}"
        check(label, route_query(message), expected)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
