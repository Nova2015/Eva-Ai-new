import re

from . import chat_agent, code_agent, image_agent, ml_agent, rag_agent, security_agent, vision_agent

AGENTS = {
    chat_agent.AGENT_ID: chat_agent,
    rag_agent.AGENT_ID: rag_agent,
    vision_agent.AGENT_ID: vision_agent,
    code_agent.AGENT_ID: code_agent,
    security_agent.AGENT_ID: security_agent,
    ml_agent.AGENT_ID: ml_agent,
    image_agent.AGENT_ID: image_agent,
}

RAG_TERMS = (
    "pdf", "document", "doc", "file", "knowledge base", "uploaded", "according to",
    "summarize the", "from the report", "from my", "in my document",
)

CODE_TERMS = (
    "error", "code", "bug", "compile", "build", "stack trace", "github", "pull request",
    "pr", "patch", "zip", "repository", "repo", "react", "python", "javascript",
)

SECURITY_TERMS = (
    "security", "threat", "pii", "malware", "vulnerability", "attack", "firewall",
    "audit", "risk", "exploit", "credential", "token leak",
)

ML_TERMS = (
    "train model", "machine learning", "dataset", "feature engineering", "model selection",
    "classifier", "regression", "accuracy", "precision", "recall", "fine tune",
)

IMAGE_TERMS = (
    "generate image", "create image", "draw", "make image", "image generation",
    "photo of", "picture of", "illustration",
)


# â”€â”€ Word-boundary matching â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# These lists were previously matched with `term in message`, an unbounded
# substring test. Short entries made that badly wrong:
#
#   "pr"   matched "preserve", "print", "approach", "expression"
#   "doc"  matched "docker"
#   "zip"  matched "zipper"
#   "code" matched "encoded", "decode"
#   "risk" matched "brisker"
#
# "pr" was the damaging one: enhance_prompt() prepends "Preserve the user's
# meaning...", so every enhanced prompt hit CODE_TERMS and every message was
# routed to the Code Agent regardless of content.
#
# The optional (?:s|es)? keeps plurals working â€” "errors", "bugs",
# "documents", "stack traces" â€” which a bare \bterm\b would have dropped.


def _compile(terms):
    return [
        re.compile(r"\b" + re.escape(term) + r"(?:s|es)?\b", re.IGNORECASE)
        for term in terms
    ]


_RAG_RE = _compile(RAG_TERMS)
_CODE_RE = _compile(CODE_TERMS)
_SECURITY_RE = _compile(SECURITY_TERMS)
_ML_RE = _compile(ML_TERMS)
_IMAGE_RE = _compile(IMAGE_TERMS)


def _matches(patterns, text):
    return any(pattern.search(text) for pattern in patterns)


def route_query(message, has_image=False):
    if has_image:
        return vision_agent.AGENT_ID

    m = (message or "").lower()

    workspace_terms = (
        "src/", "app.py", ".py", ".js", ".jsx", ".ts", ".tsx",
        "ask_groq", "provider", "providers.", "function", "class ",
        "method", "variable", "local file", "workspace", "folder",
        "directory", "read file", "inspect file",
    )

    if any(term in m for term in workspace_terms):
        return code_agent.AGENT_ID

    if _matches(_IMAGE_RE, m):
        return image_agent.AGENT_ID

    if _matches(_CODE_RE, m):
        return code_agent.AGENT_ID

    if _matches(_SECURITY_RE, m):
        return security_agent.AGENT_ID

    if _matches(_ML_RE, m):
        return ml_agent.AGENT_ID

    if _matches(_RAG_RE, m):
        return rag_agent.AGENT_ID

    return chat_agent.AGENT_ID


def get_agent(agent_id):
    return AGENTS.get(agent_id, chat_agent)


def get_agent_instruction(agent_id):
    return get_agent(agent_id).SYSTEM_INSTRUCTIONS.strip()


def get_agent_status(agent_id):
    agent = get_agent(agent_id)
    label = f"{agent.ICON} {agent.DISPLAY_NAME}"
    return {
        "id": agent.AGENT_ID,
        "name": agent.DISPLAY_NAME,
        "icon": agent.ICON,
        "label": label,
        "path": f"ðŸ§  Router â†’ {label}",
    }

