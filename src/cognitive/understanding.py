"""Understanding â€” Step 3 of the Cognitive Engine.

This is NOT an intent classifier. A classifier answers "what kind of question
is this" and stops. This stage answers four things, and the last two are what
make the rest of the engine adaptive:

    what is the user actually trying to achieve   -> intent, desired_outcome
    what do we currently understand               -> problem_category, confidence
    what is uncertain                             -> ambiguities
    what would reduce that uncertainty            -> required_information

Without the last one, ACT -> ASSESS and VERIFY -> ASSESS have nothing to carry:
the engine can loop but has no statement of what it is looping to find out.

HYBRID BY DESIGN
================
Understanding runs on every message, so an unconditional model call would add
latency and provider spend to every single request â€” and this project has
already exhausted its free-tier quota twice. So:

    deterministic first   â€” greetings, obvious code/maths/document questions
                            and clearly-scoped requests resolve with no model
                            call at all.
    escalate only on real ambiguity â€” when the deterministic read is weak or
                            contradictory, and an `llm` callable was supplied.
    degrade, never fail   â€” with no llm, or if it errors or returns junk, the
                            deterministic reading stands. Understanding must
                            never be the reason a request fails.

The LLM is INJECTED, never imported. This module has no knowledge of
model_router, app.py or any provider: callers pass a `llm(prompt) -> str`. That
keeps the whole stage testable offline and stops the Cognitive Engine
hard-coupling to a provider stack it should merely call.

NO CHAIN-OF-THOUGHT. The escalation prompt asks for a small JSON object of
fields that already exist on ProblemUnderstanding. It never asks the model to
think aloud, and any prose it volunteers outside the JSON is discarded rather
than stored.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .state import ProblemUnderstanding, REASON_MAX, redact_secrets

# Reuse the existing category regexes rather than writing a second set that
# would drift from routing. route_query answers "which agent"; it has no notion
# of uncertainty, which is the part this module adds.
try:
    from agents.router import route_query as _route_query
except Exception:  # pragma: no cover - agents package unavailable (offline tests)
    _route_query = None


# â”€â”€ deterministic signal detectors â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#å›º An optional trailing address ("hello there", "hi eva") still makes it a
# greeting; without it, "hello there" fell through to the general path and
# would have cost a model call.
_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|good\s+(morning|afternoon|evening)|"
    r"how('s| is) it going|what's up|sup|thanks|thank you|ok|okay|cool|bye)"
    r"(\s+(there|eva|everyone|all|again))?\b[\s!.?]*$",
    re.I,
)
_IDENTITY_RE = re.compile(r"\b(who are you|what are you|your name|who made you|what can you do)\b", re.I)

# Arithmetic or explicit maths. Requires an operator or an explicit verb so
# "what is machine learning" is not mistaken for a calculation.
_MATH_RE = re.compile(
    r"(\d+\s*[\+\-\*/^%]\s*\d+)|\b(calculate|compute|solve for|derivative|integral|"
    r"factorial|square root|percentage of|how much is)\b",
    re.I,
)
_CODE_RE = re.compile(
    r"\b(code|python|javascript|typescript|java|c\+\+|c#|program|programming|script|"
    r"function|class|method|api|endpoint|bug|error|exception|stack ?trace|compile|"
    r"syntax|refactor|unit test|regex|sql query|algorithm)\b|```",
    re.I,
)
_DOC_RE = re.compile(
    r"\b(my|the|this|that|uploaded|attached)\s+(document|doc|file|pdf|paper|report|manual|spec)\b"
    r"|\b(according to|in the) (document|doc|file|pdf|paper|report|manual)\b",
    re.I,
)
_COMPARISON_RE = re.compile(r"\b(compare|versus|vs\.?|difference between|better than|pros and cons)\b", re.I)
_PROCEDURE_RE = re.compile(r"\b(how (do|can) i|how to|steps to|walk me through|guide me)\b", re.I)

# Unsafe is FLAGGED, never enforced here â€” the firewall owns enforcement and
# already runs ahead of this in the request path. Understanding only records
# that the request looks sensitive so the engine can route it carefully.
_UNSAFE_RE = re.compile(
    r"\b(exploit|malware|ransomware|keylogger|ddos|sql\s*inject|bypass\s+(auth|login|2fa)|"
    r"crack (a )?password|steal (data|credentials)|phish)\w*\b",
    re.I,
)

# Referring words with nothing to refer to. The single biggest real source of
# ambiguity in a chat product: "make it shorter" is unanswerable without the
# previous turn.
#
# Position matters, and matching the pronoun anywhere is wrong. It flags
# "write a function THAT reverses a string" and "what is springback ... how do
# I compensate for IT" â€” both have a perfectly good antecedent earlier in the
# same sentence. A pronoun is only DANGLING when nothing precedes it to bind
# to, which in practice means it appears in the opening tokens of a subjectless
# request. Token position stands in for an antecedent check that would
# otherwise need a POS tagger.
_DANGLING_REF_RE = re.compile(r"^(it|this|that|these|those|them)$", re.I)
_DANGLING_MAX_TOKEN_INDEX = 2


def _has_dangling_reference(message: str) -> bool:
    for index, token in enumerate(re.findall(r"[A-Za-z']+", message.lower())):
        if index > _DANGLING_MAX_TOKEN_INDEX:
            return False      # anything this late has earlier words to refer to
        if _DANGLING_REF_RE.match(token):
            return True
    return False
_SUBJECTLESS_IMPERATIVE_RE = re.compile(
    r"^\s*(fix|improve|change|update|convert|translate|shorten|extend|optimi[sz]e|"
    r"rewrite|redo|continue|explain)\b", re.I,
)
# Vague quality words with no stated criterion â€” "make it better" how?
_VAGUE_QUALITY_RE = re.compile(r"\b(better|nicer|good|proper|professional|modern|clean(er)?|improve)\b", re.I)
# The quality word only means something when improvement is being ASKED for.
# An imperative, or a modal request, or "make it ..." â€” not a sentence that
# merely contains "good".
_IMPROVE_REQUEST_RE = re.compile(
    r"^\s*(please\s+)?(make|improve|clean|polish|refine|rewrite|redo|"
    r"optimi[sz]e|enhance|upgrade|fix)\b"
    r"|\b(can|could|would|will|please)\s+(you\s+)?(make|improve|clean|polish|"
    r"refine|rewrite|redo|optimi[sz]e|enhance|upgrade|fix)\b"
    r"|\bmake\s+(it|this|that|them|the\b)",
    re.I,
)
_INCOMPLETE_TAIL_RE = re.compile(r"\b(and|but|or|because|so|with|for|to|of|in|the|a|an)\s*$", re.I)

# Confidence at or below this escalates to the model when one is available.
ESCALATION_THRESHOLD = 0.55
# Below this, we ask the user rather than guessing â€” even after escalation.
CLARIFICATION_THRESHOLD = 0.40

_CATEGORY_BY_AGENT = {
    "code": "coding",
    "rag": "document",
    "image": "image_generation",
    "ml": "machine_learning",
    "security": "security",
    "vision": "vision",
    "chat": "general",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _detect_category(message: str, has_image: bool = False) -> Tuple[str, float]:
    """Category plus how strongly the signal fired. Deterministic, no model."""
    m = _norm(message)
    low = m.lower()

    if has_image:
        return "vision", 0.9
    if _GREETING_RE.match(low):
        return "greeting", 0.95
    if _IDENTITY_RE.search(low):
        return "identity", 0.9
    if _MATH_RE.search(low):
        return "mathematics", 0.85
    if _DOC_RE.search(low):
        return "document", 0.8
    if _CODE_RE.search(low):
        return "coding", 0.8
    if _COMPARISON_RE.search(low):
        return "comparison", 0.75
    if _PROCEDURE_RE.search(low):
        return "procedure", 0.75

    # Fall back to the existing router. Weaker confidence on purpose: it is a
    # routing heuristic, not an understanding.
    if _route_query is not None:
        try:
            agent = _route_query(m, has_image=has_image)
            category = _CATEGORY_BY_AGENT.get(agent, "general")
            return category, 0.6 if category != "general" else 0.5
        except Exception:
            pass
    return "general", 0.5


def _detect_ambiguities(message: str, context: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Return (ambiguities, information that would resolve them).

    The pairing matters: an ambiguity with no corresponding question is a
    complaint, not something the engine can act on.
    """
    m = _norm(message)
    low = m.lower()
    ambiguities: List[str] = []
    needed: List[str] = []
    has_context = bool([c for c in (context or []) if str(c).strip()])

    if not m:
        ambiguities.append("the request is empty")
        needed.append("what the user wants to do")
        return ambiguities, needed

    # A pronoun with no prior turn to bind it to.
    if _has_dangling_reference(low) and not has_context:
        ambiguities.append("refers to something not present in this conversation")
        needed.append("what 'it'/'this' refers to")

    # "fix" / "convert" with no object and no history.
    if _SUBJECTLESS_IMPERATIVE_RE.match(low) and not has_context and len(m.split()) <= 6:
        ambiguities.append("an action is requested but the target is not stated")
        needed.append("the subject the action applies to")

    # "make it better" â€” better by what measure?
    #
    # The quality word must appear inside a REQUEST to improve something. On
    # its own it fired on any sentence containing "good", "modern" or
    # "professional" â€” across 906 real messages this produced 29 flags and not
    # one was a request: they were acknowledgements, feedback and farewells.
    # "good night" asked the user what "better" meant.
    if (_IMPROVE_REQUEST_RE.search(low)
            and _VAGUE_QUALITY_RE.search(low)
            and not re.search(r"\b(so that|because|for|by|in terms of)\b", low)):
        ambiguities.append("a quality judgement is requested without a criterion")
        needed.append("what 'better' means here (speed, clarity, cost, style)")

    # Trailing conjunction: the sentence stopped mid-thought.
    if _INCOMPLETE_TAIL_RE.search(low):
        ambiguities.append("the request appears to be cut off")
        needed.append("the rest of the request")

    # Very short and not a greeting: too little to act on â€” but only when
    # there is no conversation to read it against. "free platform" or "new
    # chat" after eight turns is a terse follow-up, not an unanswerable one,
    # and asking what it means is the wrong move. Same condition the dangling
    # reference rule above already applies, for the same reason.
    if (len(m.split()) <= 2 and not _GREETING_RE.match(low) and "?" not in m
            and not has_context):
        ambiguities.append("too short to determine what is being asked")
        needed.append("a fuller statement of the question")

    return ambiguities, needed


def _desired_outcome(category: str, message: str) -> str:
    return {
        "greeting": "acknowledge and offer help",
        "identity": "describe EVA's capabilities",
        "mathematics": "a computed result",
        "coding": "working code or a diagnosis",
        "document": "an answer grounded in the user's documents",
        "comparison": "a structured comparison",
        "procedure": "an ordered set of steps",
        "image_generation": "a generated image",
        "vision": "an interpretation of the supplied image",
    }.get(category, "a direct answer to the question")


def _score(category_conf: float, ambiguities: Sequence[str], word_count: int) -> float:
    """Confidence that we understand the problem â€” not that we can answer it.

    Each ambiguity is a concrete reason we might act on the wrong problem, so
    each one costs. Very short messages carry little signal either way.
    """
    score = category_conf
    score -= 0.18 * len(ambiguities)
    if word_count <= 3:
        score -= 0.10
    return max(0.0, min(1.0, round(score, 3)))


# â”€â”€ LLM escalation (optional) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_ESCALATION_PROMPT = """Analyse the user request below and reply with ONE JSON object and nothing else.

Keys, all required:
  "intent":              a short verb phrase for what the user wants done
  "problem_category":    one of greeting, identity, mathematics, coding, document,
                         comparison, procedure, image_generation, vision, general
  "desired_outcome":     what a successful answer looks like, one short phrase
  "constraints":         array of explicit limits the user stated (may be empty)
  "ambiguities":         array of things genuinely unclear (may be empty)
  "required_information":array of what would resolve each ambiguity (may be empty)
  "confidence":          0.0-1.0, how clearly the request is specified

Do not explain your reasoning. Do not include any text outside the JSON object.

REQUEST:
{message}
{context_block}"""


def _parse_llm(raw: str) -> Optional[Dict]:
    """Extract the JSON object. Tolerant of fences and surrounding prose, and
    returns None rather than raising â€” a malformed escalation must fall back to
    the deterministic reading, not break the request."""
    if not raw:
        return None
    text = str(raw).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.S)
        if not brace:
            return None
        text = brace.group(0)
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_str_list(value, limit: int = 6) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        s = _norm(str(item))
        if s:
            out.append(redact_secrets(s)[:REASON_MAX])
        if len(out) >= limit:
            break
    return out


def should_escalate(understanding: ProblemUnderstanding) -> bool:
    """Escalate only when the deterministic read is genuinely weak.

    Greetings and identity questions never escalate however short they are â€”
    they are the highest-volume messages and the cheapest to get right, so
    spending a model call on "hi" would be the worst possible trade.
    """
    if understanding.problem_category in {"greeting", "identity"}:
        return False
    return understanding.confidence <= ESCALATION_THRESHOLD or bool(understanding.ambiguities)


def understand(
    message: str,
    context: Optional[Sequence[str]] = None,
    has_image: bool = False,
    llm: Optional[Callable[[str], str]] = None,
) -> ProblemUnderstanding:
    """Build a ProblemUnderstanding. Deterministic unless genuinely ambiguous.

    `llm` is optional and injected. Without it this is pure, offline and free.
    """
    context = list(context or [])
    message = _norm(message)

    category, category_conf = _detect_category(message, has_image=has_image)
    ambiguities, needed = _detect_ambiguities(message, context)

    # A flagged-unsafe request is not ambiguous, but it is something the engine
    # must know about; the firewall remains the thing that enforces.
    constraints: List[str] = []
    if _UNSAFE_RE.search(message.lower()):
        constraints.append("request touches a sensitive/security-restricted topic")

    confidence = _score(category_conf, ambiguities, len(message.split()))

    result = ProblemUnderstanding(
        intent=f"{category}:{_desired_outcome(category, message)}"[:REASON_MAX],
        problem_category=category,
        desired_outcome=_desired_outcome(category, message),
        constraints=constraints,
        ambiguities=ambiguities,
        required_information=needed,
        needs_clarification=confidence < CLARIFICATION_THRESHOLD,
        confidence=confidence,
    )

    if llm is None or not should_escalate(result):
        return result

    # â”€â”€ escalation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    context_block = ""
    if context:
        recent = " | ".join(_norm(str(c)) for c in context[-3:])
        context_block = f"\nRECENT CONTEXT: {recent[:800]}"
    try:
        raw = llm(_ESCALATION_PROMPT.format(message=message[:2000], context_block=context_block))
    except Exception:
        return result          # provider down or rate-limited: keep what we have
    parsed = _parse_llm(raw)
    if not parsed:
        return result          # malformed reply: keep what we have

    merged_ambiguities = _as_str_list(parsed.get("ambiguities")) or result.ambiguities
    merged_needed = _as_str_list(parsed.get("required_information")) or result.required_information
    try:
        llm_conf = float(parsed.get("confidence", result.confidence))
    except (TypeError, ValueError):
        llm_conf = result.confidence
    llm_conf = max(0.0, min(1.0, llm_conf))

    category_out = _norm(str(parsed.get("problem_category") or result.problem_category)).lower()
    return ProblemUnderstanding(
        intent=_norm(str(parsed.get("intent") or result.intent))[:REASON_MAX],
        problem_category=category_out or result.problem_category,
        desired_outcome=_norm(str(parsed.get("desired_outcome") or result.desired_outcome))[:REASON_MAX],
        # Deterministic constraints are kept: the unsafe flag must survive a
        # model that did not notice it.
        constraints=result.constraints + [
            c for c in _as_str_list(parsed.get("constraints")) if c not in result.constraints
        ],
        ambiguities=merged_ambiguities,
        required_information=merged_needed,
        needs_clarification=llm_conf < CLARIFICATION_THRESHOLD or bool(merged_ambiguities and llm_conf < ESCALATION_THRESHOLD),
        confidence=llm_conf,
    )
