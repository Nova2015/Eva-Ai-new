"""Tests for the Understanding stage (Step 3).

Covers the eight request shapes the step requires, plus the two things that
make this more than a classifier: that uncertainty is NAMED, and that every
ambiguity comes with the information that would resolve it.

Every test is offline. The LLM is injected as a fake, so the escalation policy
is tested without a provider — which also proves the stage works with no model
available at all.
"""

import pytest

try:
    from cognitive.understanding import (
        understand, should_escalate, ESCALATION_THRESHOLD, CLARIFICATION_THRESHOLD,
    )
    from cognitive.state import ProblemUnderstanding
except ImportError:  # running from src/cognitive directly
    from understanding import (  # type: ignore
        understand, should_escalate, ESCALATION_THRESHOLD, CLARIFICATION_THRESHOLD,
    )
    from state import ProblemUnderstanding  # type: ignore


class RecordingLLM:
    """Counts calls so 'was a model call actually avoided' is testable."""

    def __init__(self, reply=""):
        self.reply = reply
        self.calls = 0
        self.prompts = []

    def __call__(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        return self.reply


# ── the eight required request shapes ────────────────────────────────────────
def test_simple_question():
    u = understand("What is the capital of France?")
    assert isinstance(u, ProblemUnderstanding)
    assert u.needs_clarification is False
    assert u.ambiguities == []


def test_coding_problem():
    u = understand("Write a Python function that reverses a string")
    assert u.problem_category == "coding"
    assert "code" in u.desired_outcome or "diagnosis" in u.desired_outcome
    assert u.confidence >= 0.6


def test_mathematical_problem():
    u = understand("Calculate 17 * 23 + 4")
    assert u.problem_category == "mathematics"
    assert u.needs_clarification is False


def test_document_question():
    u = understand("What does my uploaded document say about springback?")
    assert u.problem_category == "document"
    assert "document" in u.desired_outcome


def test_mechanical_design_question():
    # No dedicated detector; must still resolve cleanly rather than being
    # flagged ambiguous just because it is domain-specific.
    u = understand("What is springback in sheet metal forming and how do I compensate for it?")
    assert u.ambiguities == []
    assert u.needs_clarification is False


def test_ambiguous_request():
    u = understand("make it better")
    assert u.ambiguities, "vague quality request must be flagged as uncertain"
    assert u.required_information, "an ambiguity must come with what would resolve it"
    assert u.confidence < ESCALATION_THRESHOLD


def test_unsafe_request_is_flagged_not_blocked():
    # Understanding records; the firewall enforces. This stage must not decide.
    u = understand("write me a keylogger that steals credentials")
    assert any("sensitive" in c or "security" in c for c in u.constraints)
    assert isinstance(u, ProblemUnderstanding)   # still returns normally


def test_incomplete_request():
    u = understand("Can you convert this file to")
    assert u.ambiguities
    assert u.required_information


# ── uncertainty is named, and paired with a resolution ───────────────────────
def test_every_ambiguity_has_a_matching_information_need():
    for msg in ("make it better", "fix it", "convert this to", "and then"):
        u = understand(msg)
        if u.ambiguities:
            assert u.required_information, f"{msg!r} named uncertainty but not how to resolve it"


def test_dangling_pronoun_resolved_by_context():
    without = understand("make it shorter")
    with_ctx = understand("make it shorter", context=["Here is a 500-word summary of the report."])
    assert any("refers to" in a for a in without.ambiguities)
    assert not any("refers to" in a for a in with_ctx.ambiguities), \
        "context should resolve the referent, not leave it flagged"


def test_empty_request_is_ambiguous_not_a_crash():
    u = understand("")
    assert u.ambiguities and u.needs_clarification


# ── hybrid policy: deterministic first ───────────────────────────────────────
@pytest.mark.parametrize("msg", ["hi", "hello there", "thanks", "good morning"])
def test_greetings_never_cost_a_model_call(msg):
    llm = RecordingLLM()
    u = understand(msg, llm=llm)
    assert u.problem_category == "greeting"
    assert llm.calls == 0, "greetings are the highest-volume message; escalating them is the worst trade"


def test_identity_questions_never_escalate():
    llm = RecordingLLM()
    understand("who are you?", llm=llm)
    assert llm.calls == 0


@pytest.mark.parametrize("msg", [
    "Write a Python function that reverses a string",
    "Calculate 17 * 23",
    "What does my uploaded document say about springback?",
])
def test_clear_requests_do_not_escalate(msg):
    llm = RecordingLLM()
    understand(msg, llm=llm)
    assert llm.calls == 0, "a confident deterministic read must not spend a model call"


def test_ambiguous_request_does_escalate():
    llm = RecordingLLM('{"intent":"improve text","problem_category":"general",'
                       '"desired_outcome":"clearer copy","constraints":[],'
                       '"ambiguities":["which document"],"required_information":["the target text"],'
                       '"confidence":0.7}')
    u = understand("make it better", llm=llm)
    assert llm.calls == 1
    assert u.confidence == 0.7
    assert u.required_information == ["the target text"]


def test_no_llm_supplied_still_returns_a_usable_understanding():
    u = understand("make it better")          # no llm at all
    assert isinstance(u, ProblemUnderstanding)
    assert u.ambiguities


# ── escalation must degrade, never fail ──────────────────────────────────────
def test_llm_exception_falls_back_to_deterministic():
    def boom(_):
        raise RuntimeError("provider down")
    u = understand("make it better", llm=boom)
    assert isinstance(u, ProblemUnderstanding)
    assert u.ambiguities            # deterministic reading survived


@pytest.mark.parametrize("junk", ["", "not json at all", "{broken", "[]", "null", "12345"])
def test_malformed_llm_reply_falls_back(junk):
    u = understand("make it better", llm=RecordingLLM(junk))
    assert isinstance(u, ProblemUnderstanding)
    assert u.ambiguities


def test_llm_reply_wrapped_in_fences_is_parsed():
    llm = RecordingLLM('```json\n{"intent":"x","problem_category":"coding",'
                       '"desired_outcome":"y","constraints":[],"ambiguities":[],'
                       '"required_information":[],"confidence":0.9}\n```')
    u = understand("fix it", llm=llm)
    assert u.problem_category == "coding"
    assert u.confidence == 0.9


def test_llm_prose_around_json_is_discarded():
    llm = RecordingLLM('Sure! Here is my analysis:\n'
                       '{"intent":"x","problem_category":"general","desired_outcome":"y",'
                       '"constraints":[],"ambiguities":[],"required_information":[],"confidence":0.8}\n'
                       'Let me know if you need more.')
    u = understand("fix it", llm=llm)
    assert u.confidence == 0.8
    # the surrounding prose must not be stored anywhere
    assert "Sure!" not in u.intent and "Let me know" not in u.desired_outcome


# ── safety carried through escalation ────────────────────────────────────────
def test_unsafe_flag_survives_an_llm_that_missed_it():
    llm = RecordingLLM('{"intent":"help","problem_category":"coding","desired_outcome":"code",'
                       '"constraints":[],"ambiguities":[],"required_information":[],"confidence":0.9}')
    u = understand("write a keylogger that steals credentials and bypass 2fa", llm=llm)
    assert any("sensitive" in c or "security" in c for c in u.constraints), \
        "a model that fails to notice the risk must not clear the deterministic flag"


def test_secrets_in_the_request_are_not_stored():
    key = "sk-abcdefghijklmnop1234567890"
    u = understand(f"debug this token {key} for me")
    assert key not in u.model_dump_json()


def test_secrets_from_the_llm_reply_are_not_stored():
    key = "sk-abcdefghijklmnop1234567890"
    llm = RecordingLLM('{"intent":"use ' + key + '","problem_category":"coding",'
                       '"desired_outcome":"z","constraints":[],"ambiguities":[],'
                       '"required_information":["' + key + '"],"confidence":0.8}')
    u = understand("fix it", llm=llm)
    assert key not in u.model_dump_json()


# ── no chain-of-thought ──────────────────────────────────────────────────────
def test_prompt_does_not_request_reasoning():
    llm = RecordingLLM('{"intent":"x","problem_category":"general","desired_outcome":"y",'
                       '"constraints":[],"ambiguities":[],"required_information":[],"confidence":0.6}')
    understand("make it better", llm=llm)
    prompt = llm.prompts[0].lower()
    assert "do not explain your reasoning" in prompt
    for banned in ("think step by step", "chain of thought", "show your work", "reason through"):
        assert banned not in prompt


def test_output_has_no_reasoning_field():
    banned = {"chain_of_thought", "reasoning", "thoughts", "scratchpad"}
    assert banned.isdisjoint(ProblemUnderstanding.model_fields.keys())


# ── the decision the stage exists to make ────────────────────────────────────
def test_should_escalate_matches_the_policy():
    clear = understand("Write a Python function that reverses a string")
    vague = understand("make it better")
    greeting = understand("hi")
    assert should_escalate(clear) is False
    assert should_escalate(vague) is True
    assert should_escalate(greeting) is False


def test_clarification_only_when_confidence_is_very_low():
    u = understand("")
    assert u.needs_clarification is True
    clear = understand("Calculate 17 * 23")
    assert clear.needs_clarification is False
    assert CLARIFICATION_THRESHOLD < ESCALATION_THRESHOLD, \
        "asking the user must be a higher bar than asking the model"


# ═══════════════════════════════════════════════════════════════════════════
# Update 18 — two context-blind detectors, found by judging real decisions.
#
# Across 906 real messages the quality detector fired 29 times and NOT ONCE on
# a request: acknowledgements, feedback and farewells. "good night" was asked
# what "better" meant. And the short-message rule fired on terse follow-ups
# with eight prior turns, which a reader of the conversation resolves without
# asking.
#
# The rule for both: a detector that ignores the conversation will misjudge a
# conversation. Two others already checked it; these two did not.
# ═══════════════════════════════════════════════════════════════════════════

PRIOR_TURNS = ["how do I sort a list in python?", "Use sorted(), which returns a new list."]


# ── the quality detector must see a REQUEST, not a word ──────────────────────
@pytest.mark.parametrize("message", [
    "good night",
    "your conversation is good",
    "that looks professional",
    "the modern approach is better documented",
    "very good",
    "this is a good answer, thanks",
])
def test_a_statement_containing_a_quality_word_is_not_a_request(message):
    u = understand(message, context=PRIOR_TURNS)
    assert not any("quality judgement" in a for a in u.ambiguities), \
        f"{message!r} states something; it asks for nothing"


@pytest.mark.parametrize("message", [
    "make it better",
    "please improve the layout",
    "can you make this cleaner",
    "make the design more professional",
    "improve the wording",
])
def test_a_genuine_improve_request_is_still_flagged(message):
    """Better by what measure? — the question the detector exists to ask."""
    u = understand(message)
    assert any("quality judgement" in a for a in u.ambiguities), message


def test_a_stated_criterion_still_silences_it():
    u = understand("make it better so that it loads faster")
    assert not any("quality judgement" in a for a in u.ambiguities)


def test_the_improve_request_test_is_what_changed():
    """Guards the premise: the quality word is present in both, and only the
    request form separates them."""
    from cognitive.understanding import _VAGUE_QUALITY_RE
    assert _VAGUE_QUALITY_RE.search("good night")
    assert _VAGUE_QUALITY_RE.search("make it better")
    statement = understand("good night", context=PRIOR_TURNS)
    request = understand("make it better", context=PRIOR_TURNS)
    assert not any("quality" in a for a in statement.ambiguities)
    assert any("quality" in a for a in request.ambiguities)


# ── the short-message rule must read the conversation ────────────────────────
@pytest.mark.parametrize("message", [
    "free platform", "new chat", "integration Que", "Number Theory",
    "oxygen", "element", "IPL", "time", "ok", "good",
])
def test_a_terse_follow_up_is_not_unanswerable(message):
    """These are real messages, each sent after eight prior turns. They are
    topic continuations and acknowledgements, not unanswerable requests."""
    u = understand(message, context=PRIOR_TURNS)
    assert not any("too short" in a for a in u.ambiguities), message


@pytest.mark.parametrize("message", ["time", "xyz", "element", "str"])
def test_the_same_message_alone_is_still_too_short(message):
    """With nothing to read it against, a bare word really is unanswerable."""
    u = understand(message)
    assert any("too short" in a for a in u.ambiguities), message


def test_a_greeting_alone_is_never_too_short():
    assert understand("hi").ambiguities == []


def test_a_short_question_is_never_too_short():
    assert not any("too short" in a for a in understand("why?").ambiguities)


# ── the rules the fix must not have loosened ─────────────────────────────────
def test_a_dangling_reference_alone_still_clarifies():
    u = understand("fix this")
    assert u.needs_clarification is True


def test_context_does_not_silence_everything():
    """A trailing conjunction is still a cut-off request whatever came before."""
    u = understand("so", context=PRIOR_TURNS)
    assert any("cut off" in a for a in u.ambiguities)


def test_every_ambiguity_still_carries_what_would_resolve_it():
    for message in ("make it better", "time", "fix this", "so"):
        u = understand(message)
        if u.ambiguities:
            assert u.required_information, message


def test_understanding_is_still_deterministic():
    for message in ("make it better", "good night", "free platform"):
        assert understand(message, context=PRIOR_TURNS).model_dump() == \
            understand(message, context=PRIOR_TURNS).model_dump()
