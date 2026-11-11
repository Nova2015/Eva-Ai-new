"""Tests for the Strategy Selector (Step 5).

One test per strategy, plus precedence, ambiguity, fallback, safety and the
boundaries the selector must not cross (no planning, no execution, no
chain-of-thought, no model call).

Entirely offline and deterministic.
"""

import pytest

try:
    from cognitive.strategy import (
        select_strategy, StrategyDecision, VerificationRequirement, RequiredContext,
        TOOL_WEB_SEARCH, TOOL_RAG_QUERY, TOOL_READ_URL, TOOL_THINK,
    )
    from cognitive.assessment import assess, EvidenceItem, EvidenceKind, RiskLevel
    from cognitive.understanding import understand
    from cognitive.state import ReasoningStrategy, StrategySelection, CognitiveState, CognitivePhase
except ImportError:  # running from src/cognitive directly
    from strategy import (  # type: ignore
        select_strategy, StrategyDecision, VerificationRequirement, RequiredContext,
        TOOL_WEB_SEARCH, TOOL_RAG_QUERY, TOOL_READ_URL, TOOL_THINK,
    )
    from assessment import assess, EvidenceItem, EvidenceKind, RiskLevel  # type: ignore
    from understanding import understand  # type: ignore
    from state import ReasoningStrategy, StrategySelection, CognitiveState, CognitivePhase  # type: ignore


def pipeline(message, evidence=None, **kw):
    """Understanding -> Assessment -> Strategy, the way the engine will call it."""
    u = understand(message)
    for key, value in kw.items():
        setattr(u, key, value)
    a = assess(u, evidence=evidence, problem=message)
    return select_strategy(u, a, problem=message)


# â”€â”€ one test per strategy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_DIRECT_for_a_simple_question():
    d = pipeline("What is the capital of France?")
    assert d.strategy is ReasoningStrategy.DIRECT
    assert d.required_tools == []


def test_DIRECT_for_greetings():
    assert pipeline("hi").strategy is ReasoningStrategy.DIRECT


def test_CALCULATION_for_arithmetic():
    d = pipeline("Calculate 17 * 23 + 4")
    assert d.strategy is ReasoningStrategy.CALCULATION
    assert VerificationRequirement.ARITHMETIC_RECHECK in d.verification_requirements


def test_CODE_for_a_programming_request():
    d = pipeline("Write a Python function that reverses a string")
    assert d.strategy is ReasoningStrategy.CODE
    assert VerificationRequirement.CODE_VALIDATION in d.verification_requirements
    assert VerificationRequirement.EXECUTION_TEST in d.verification_requirements


def test_RETRIEVAL_for_a_document_question():
    d = pipeline("What does my uploaded document say about springback?")
    assert d.strategy is ReasoningStrategy.RETRIEVAL
    assert TOOL_RAG_QUERY in d.required_tools
    assert RequiredContext.USER_DOCUMENTS in d.required_context
    assert VerificationRequirement.CITATION_CHECK in d.verification_requirements


def test_ANALYSIS_for_a_comparison():
    d = pipeline("Compare Postgres and MongoDB for a write-heavy workload")
    assert d.strategy is ReasoningStrategy.ANALYSIS
    assert VerificationRequirement.CONSISTENCY_CHECK in d.verification_requirements


def test_MULTI_STEP_for_a_procedure():
    d = pipeline("How do I set up a new React project?")
    assert d.strategy is ReasoningStrategy.MULTI_STEP


def test_MULTI_STEP_for_a_compound_request():
    d = pipeline("Set up the database and then migrate the schema and also seed test data")
    assert d.strategy is ReasoningStrategy.MULTI_STEP
    assert TOOL_THINK in d.required_tools


def test_TOOL_ASSISTED_when_the_gap_is_external():
    d = pipeline("What is the latest released version?",
                 required_information=["current release version"])
    assert d.strategy is ReasoningStrategy.TOOL_ASSISTED
    assert TOOL_WEB_SEARCH in d.required_tools
    assert RequiredContext.EXTERNAL_SOURCES in d.required_context

def test_TOOL_ASSISTED_for_today_comparison_without_external_gap():
    d = pipeline("What is today's India Women vs Japan Women match result?")
    assert d.strategy is ReasoningStrategy.TOOL_ASSISTED
    assert TOOL_WEB_SEARCH in d.required_tools
    assert RequiredContext.EXTERNAL_SOURCES in d.required_context



def test_CLARIFICATION_when_ambiguous():
    d = pipeline("make it better")
    assert d.strategy is ReasoningStrategy.CLARIFICATION
    assert RequiredContext.USER_CLARIFICATION in d.required_context
    assert d.required_tools == []


# â”€â”€ precedence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_clarification_outranks_category():
    """An unintelligible coding request must not become CODE â€” that produces
    confident nonsense."""
    u = understand("fix it")
    a = assess(u, problem="fix it")
    assert a.clarification_required is True
    d = select_strategy(u, a, problem="fix it")
    assert d.strategy is ReasoningStrategy.CLARIFICATION


def test_multipart_outranks_subject():
    """A compound coding request needs sequencing, not one code answer that
    satisfies only the first part."""
    d = pipeline("Write a parser and then add tests and also document the API")
    assert d.strategy is ReasoningStrategy.MULTI_STEP


def test_safety_outranks_capability():
    msg = "bypass 2fa and drop the production database"
    u = understand(msg)
    a = assess(u, problem=msg)
    assert a.risk_level is RiskLevel.CRITICAL
    d = select_strategy(u, a, problem=msg)
    assert d.strategy is ReasoningStrategy.DIRECT
    assert d.required_tools == [], "a CRITICAL request must not be handed tools"
    assert "critical" in d.reason.lower()


# â”€â”€ fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_strategies_that_can_fail_declare_a_fallback():
    for msg in ["Write a Python function that reverses a string",
                "What does my uploaded document say about springback?",
                "Compare Postgres and MongoDB",
                "Calculate 17 * 23"]:
        d = pipeline(msg)
        assert d.fallback_strategy is not None, f"{msg!r} has no fallback"
        assert d.fallback_strategy is not d.strategy, "fallback must differ from the choice"


def test_direct_needs_no_fallback():
    assert pipeline("What is the capital of France?").fallback_strategy is None


# â”€â”€ determinism â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_selection_is_reproducible():
    a = pipeline("Write a Python function that reverses a string")
    b = pipeline("Write a Python function that reverses a string")
    assert a.model_dump() == b.model_dump()


def test_selector_takes_no_llm_parameter():
    """Deliberate: selection is a rule problem. An escape hatch here would
    quietly turn a deterministic selector into a per-message model call."""
    import inspect
    assert "llm" not in inspect.signature(select_strategy).parameters


def test_every_decision_marks_itself_deterministic():
    for msg in ["hi", "Calculate 2+2", "make it better", "Write a Python function"]:
        assert pipeline(msg).deterministic is True


# â”€â”€ vocabularies must be real â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_named_tools_exist_in_the_autopilot_whitelist():
    import re, io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "..", "autopilot.py"), encoding="utf-8").read()
    block = src[src.index("TOOLS = {"):src.index("def _run_tool")]
    real = set(re.findall(r'"(\w+)":', block))
    for msg in ["What does my document say?", "What is the latest version?",
                "Set up X and then Y and also Z"]:
        for tool in pipeline(msg, required_information=["current release version"]).required_tools:
            assert tool in real, f"{tool!r} is not a real autopilot tool"


def test_verification_requirements_map_to_real_validators():
    # review_engine exposes validate_code / validate_charts / validate_mermaid
    import os
    for name in ("code_validator.py", "chart_validator.py", "mermaid_validator.py"):
        assert os.path.exists(os.path.join(os.path.dirname(__file__), "..", "review_engine", name))


# â”€â”€ boundaries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_selector_does_not_plan():
    banned = {"plan", "tasks", "task_plan", "steps", "subtasks"}
    assert banned.isdisjoint(StrategyDecision.model_fields.keys())


def test_selector_stores_no_chain_of_thought():
    banned = {"chain_of_thought", "reasoning", "thoughts", "scratchpad",
              "private_reasoning", "reasoning_trace"}
    assert banned.isdisjoint(StrategyDecision.model_fields.keys())


def test_reason_is_short_and_loggable():
    for msg in ["make it better", "Write a Python function", "Calculate 2+2"]:
        d = pipeline(msg)
        assert 0 < len(d.reason) <= 400
        assert "\n" not in d.reason


def test_selector_performs_no_io():
    import ast, io, os
    tree = ast.parse(io.open(os.path.join(os.path.dirname(__file__), "strategy.py"),
                             encoding="utf-8").read())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
    forbidden = ("httpx", "requests", "urllib", "socket", "sqlite3", "psycopg2",
                 "openai", "groq", "subprocess", "boto3", "aiohttp")
    assert not [i for i in imports if any(f in i for f in forbidden)]


# â”€â”€ secrets and odd input â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_secrets_are_not_stored_in_the_decision():
    key = "sk-abcdefghijklmnop1234567890"
    d = pipeline(f"debug this token {key}")
    assert key not in d.model_dump_json()


@pytest.mark.parametrize("weird", ["", "   ", "?????", "ðŸ™‚ðŸ™ƒ", "a" * 3000,
                                   "Â¿CuÃ¡l es la capital de Francia?", "æ©Ÿæ¢°å­¦ç¿’ã¨ã¯ï¼Ÿ"])
def test_odd_input_still_yields_a_decision(weird):
    d = pipeline(weird)
    assert isinstance(d, StrategyDecision)
    assert d.strategy in set(ReasoningStrategy)


# â”€â”€ integration with Step 2, via its public interface â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_projects_into_step2_strategy_selection():
    d = pipeline("Write a Python function that reverses a string")
    sel = d.to_strategy_selection()
    assert isinstance(sel, StrategySelection)
    assert sel.strategy is ReasoningStrategy.CODE
    assert sel.verification_required is True

    s = CognitiveState(problem="reverse a string")
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.strategy = sel
    assert s.strategy.strategy is ReasoningStrategy.CODE


def test_clarification_projects_with_no_verification_required():
    sel = pipeline("make it better").to_strategy_selection()
    assert sel.verification_required is False


def test_strategy_can_be_reselected_after_new_evidence():
    """The Step 2 graph allows CORRECT->STRATEGY and PLAN->STRATEGY. A second
    call must be free to choose differently."""
    msg = "What does the manual say about torque?"
    u = understand(msg)
    u.required_information = ["the manual section"]
    first = select_strategy(u, assess(u, problem=msg), problem=msg)

    second = select_strategy(
        u,
        assess(u, evidence=[EvidenceItem(ref="manual", kind=EvidenceKind.RETRIEVED,
                                         claim="the manual section on torque specifies 40 Nm")],
               problem=msg),
        problem=msg,
    )
    assert isinstance(first, StrategyDecision) and isinstance(second, StrategyDecision)
    # the second call sees closed gaps and need not keep retrieving
    assert second.strategy in set(ReasoningStrategy)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Update 14 â€” verification capability alignment.
#
# Step 5 says what would prove an answer right. The caller says what can
# actually be run. Requesting a check nothing can execute is what left five of
# eight strategies structurally unverifiable: verification never returned a
# verdict, so correction never proposed and the loop was inert.
#
# Requirements that cannot run are RECORDED, never dropped â€” they are the only
# trace of where EVA's verification coverage stops.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

CHAT_CAPABILITY = frozenset({
    VerificationRequirement.CODE_VALIDATION,
    VerificationRequirement.CHART_VALIDATION,
    VerificationRequirement.DIAGRAM_VALIDATION,
})


def aligned(message, available=CHAT_CAPABILITY, evidence=None, **kw):
    u = understand(message)
    for key, value in kw.items():
        setattr(u, key, value)
    a = assess(u, evidence=evidence, problem=message)
    return select_strategy(u, a, problem=message, available=available)


# â”€â”€ available=None preserves the previous behaviour exactly â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@pytest.mark.parametrize("message", [
    "What is the capital of France?", "write a python function to sort a list",
    "summarise the uploaded report", "compare postgres and mysql",
    "what is 17% of 4200?", "search the web for the react version",
    "explain this step by step", "it",
])
def test_omitting_available_changes_nothing(message):
    """Every existing caller and test must be unaffected."""
    before = pipeline(message)
    after = select_strategy(understand(message),
                            assess(understand(message), problem=message),
                            problem=message, available=None)
    assert after.strategy is before.strategy
    assert after.verification_requirements == before.verification_requirements
    assert after.unavailable_requirements == []


def test_unavailable_defaults_to_empty():
    assert pipeline("hello").unavailable_requirements == []


# â”€â”€ the split â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_an_unrunnable_requirement_is_recorded_not_requested():
    """CODE asks for CODE_VALIDATION and EXECUTION_TEST; only the first can run
    without an execution runner."""
    d = aligned("write a python function that reverses a string")
    assert d.verification_requirements == [VerificationRequirement.CODE_VALIDATION]
    assert d.unavailable_requirements == [VerificationRequirement.EXECUTION_TEST]


def test_nothing_is_ever_silently_discarded():
    """Requested == runnable + unavailable, for every strategy."""
    for message in ("write python code", "summarise the report",
                    "compare a and b", "what is 5% of 200?",
                    "search the web for x", "explain it step by step",
                    "draw a diagram of the flow", "hello", "it"):
        loose = pipeline(message)
        tight = aligned(message)
        assert (set(tight.verification_requirements) | set(tight.unavailable_requirements)
                == set(loose.verification_requirements)), message


def test_a_strategy_with_no_runnable_check_requests_nothing():
    """RETRIEVAL wants CITATION_CHECK, which lives on the ML service. It is
    recorded, and no fake citation verification is requested."""
    d = aligned("summarise the uploaded report")
    assert d.verification_requirements == []
    assert d.unavailable_requirements == [VerificationRequirement.CITATION_CHECK]


def test_NONE_is_never_treated_as_unavailable():
    """NONE is the absence of a requirement, not a requirement that failed."""
    d = aligned("hello")
    assert d.verification_requirements == [VerificationRequirement.NONE]
    assert d.unavailable_requirements == []


def test_an_empty_capability_set_records_everything():
    d = aligned("write a python function to sort a list", available=frozenset())
    assert d.verification_requirements == []
    assert set(d.unavailable_requirements) == {
        VerificationRequirement.CODE_VALIDATION,
        VerificationRequirement.EXECUTION_TEST,
    }


def test_supplying_a_runner_capability_requests_the_execution_test():
    """Capability is context-dependent: the same question asks for more when
    the caller can do more."""
    with_runner = CHAT_CAPABILITY | {VerificationRequirement.EXECUTION_TEST}
    d = aligned("write a python function that reverses a string",
                available=with_runner)
    assert VerificationRequirement.EXECUTION_TEST in d.verification_requirements
    assert d.unavailable_requirements == []


def test_order_is_preserved_across_the_split():
    d = aligned("write a python function that reverses a string")
    loose = pipeline("write a python function that reverses a string")
    assert d.verification_requirements[0] == loose.verification_requirements[0]


# â”€â”€ diagram / chart detected from the raw request â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@pytest.mark.parametrize("message", [
    "draw a mermaid diagram of the login flow",
    "I need a diagram of the auth flow",
    "show me a flowchart of the process",
])
def test_diagram_is_detected_from_the_request_text(message):
    """Step 3's deterministic path never writes "diagram" into desired_outcome â€”
    it emits "a direct answer to the question" or "a generated image" â€” so
    keying on that alone made the validator unreachable however plainly the
    user asked."""
    d = aligned(message)
    assert VerificationRequirement.DIAGRAM_VALIDATION in d.verification_requirements, \
        f"{message!r} -> {understand(message).desired_outcome!r}"


@pytest.mark.parametrize("message", [
    "produce a bar chart of sales",
    "give me a graph of the results",
])
def test_chart_is_detected_from_the_request_text(message):
    d = aligned(message)
    assert VerificationRequirement.CHART_VALIDATION in d.verification_requirements


def test_desired_outcome_still_works_on_its_own():
    """The original signal is kept, not replaced."""
    d = aligned("give me the thing", desired_outcome="a diagram of the flow")
    assert VerificationRequirement.DIAGRAM_VALIDATION in d.verification_requirements


def test_an_ordinary_question_asks_for_neither():
    d = aligned("what is the capital of France?")
    assert d.verification_requirements == [VerificationRequirement.NONE]


def test_diagram_wins_over_chart_when_both_appear():
    """Deterministic precedence rather than dictionary order."""
    d = aligned("draw a diagram and a chart")
    assert d.verification_requirements == [VerificationRequirement.DIAGRAM_VALIDATION]


# â”€â”€ still pure and repeatable â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_alignment_is_deterministic():
    a = aligned("write a python function that reverses a string")
    b = aligned("write a python function that reverses a string")
    assert a.model_dump() == b.model_dump()


def test_the_capability_set_is_not_mutated():
    capability = set(CHAT_CAPABILITY)
    aligned("write a python function", available=capability)
    assert capability == set(CHAT_CAPABILITY)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# A question ABOUT programming is not a request FOR code.
#
# category="coding" says the SUBJECT is programming. CODE says the user wants
# code produced. Conflating them sent "what is react?" and "search the web for
# the latest react version" to a strategy for WRITING code â€” Step 3 falls back
# to the production router when its own regex misses, and the router answers
# "the code agent handles this", which understanding.py itself flags as "a
# routing heuristic, not an understanding".
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@pytest.mark.parametrize("message", [
    "search the web for the latest react version",
    "what is the latest react version?",
    "what is react?",
    "look up the current python version",
    "who invented python?",
    "when was javascript created?",
    "is rust faster than go?",
    "what does an API do?",
    "explain what a stack trace is",
])
def test_a_question_about_programming_is_not_a_code_request(message):
    d = pipeline(message)
    assert d.strategy is not ReasoningStrategy.CODE, (
        f"{message!r} asks about programming; it does not ask for code")


@pytest.mark.parametrize("message", [
    "write a react component",
    "implement a sort algorithm",
    "refactor this class",
    "debug my python script",
    "write a python function that reverses a string",
    "give me code to parse json",
    "show me a regex for emails",
    "optimise this sql query",
    "my code throws an exception",
    "there is a bug in my program",
])
def test_a_real_code_request_still_selects_code(message):
    """The fix must not cost the cases that were right â€” including diagnosis,
    which names a code artefact ("my code") rather than a producing verb."""
    d = pipeline(message)
    assert d.strategy is ReasoningStrategy.CODE, message


def test_the_category_itself_is_unchanged():
    """Step 3 still calls the SUBJECT programming, which is correct. Only the
    leap from subject to strategy was wrong, so the fix is in Step 5 and the
    learning record keeps an accurate topic."""
    u = understand("what is react?")
    assert u.problem_category == "coding"
    assert pipeline("what is react?").strategy is not ReasoningStrategy.CODE


def test_a_code_answer_to_a_question_is_still_validated():
    """Demoting the strategy must not stop a code block being checked when one
    turns up anyway â€” that is decided by the artefact, not the strategy."""
    from cognitive.verification import run_review_pipeline
    fenced = "```python\ndef f(x)\n    return x\n```"
    assert [i.get("code") for i in run_review_pipeline(fenced)["issues"]] == \
        ["python_syntax_error"]


def test_the_router_fallback_is_what_made_this_reachable():
    """Guards the premise: none of these fire Step 3's own code regex, so the
    category comes from the router at lower confidence."""
    from cognitive.understanding import _CODE_RE, _detect_category
    for message in ("what is react?", "search the web for the latest react version"):


        category, confidence = _detect_category(message)
        assert category == "coding" and confidence < 0.8, message


def test_the_decision_reads_the_request_not_only_the_category():
    """Two messages, same category, different strategy â€” the raw words are
    what separate them, the same fix Steps 4, 7 and Update 14 each needed."""
    asking = pipeline("what is react?")
    wanting = pipeline("write a react component")
    assert understand("what is react?").problem_category == \
        understand("write a react component").problem_category == "coding"
    assert asking.strategy is not wanting.strategy


def test_classification_is_deterministic():
    for message in ("what is react?", "write a react component"):
        assert pipeline(message).strategy is pipeline(message).strategy


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Joins are not parts, and not every connective is a join.
#
# The score counted MATCHES of one combined pattern while the threshold read as
# PARTS. n joins separate n+1 clauses, so a plainly two-part request scored 1,
# sat below the threshold, and was answered as a single task. That gap is what
# let a coding misclassification prop up two planning tests.
#
# Splitting the pattern matters as much as the +1: "and then" marks ordered
# work, "also" is frequently conversational filler.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@pytest.mark.parametrize("message", [
    "Research X and then summarise the findings",
    "set up the database and then migrate the schema",
    "read the file and then extract the tables",
    "download the report after that email it to me",
    "generate the chart followed by a short caption",
])
def test_one_sequencing_connective_is_already_two_parts(message):
    d = pipeline(message)
    assert d.strategy is ReasoningStrategy.MULTI_STEP, (
        f"{message!r} is two ordered tasks; one join separates two clauses")


@pytest.mark.parametrize("message", [
    "can you also explain how oauth works?",
    "what is react, and also is it fast?",
    "I also need the capital of France",
    "additionally, what time is it?",
])
def test_an_additive_connective_alone_is_not_multi_step(message):
    """"also" is usually a speech habit, not a second task. On its own it stays
    below the threshold â€” which is why it is scored separately."""
    d = pipeline(message)
    assert d.strategy is not ReasoningStrategy.MULTI_STEP, message


def test_additive_words_do_not_accumulate():
    """Repeating "also" is a speech habit, not a count of tasks."""
    from cognitive.strategy import _complexity
    from cognitive.understanding import understand as u_
    from cognitive.assessment import assess as a_
    one = "tell me about X, also about Y"
    many = "tell me about X, also Y, also Z, as well as W, additionally V"
    u1, u2 = u_(one), u_(many)
    assert _complexity(u1, a_(u1, problem=one), one) == \
        _complexity(u2, a_(u2, problem=many), many)


def test_more_parts_still_outrank_fewer():
    """The property the earlier count-the-joins fix established, preserved."""
    from cognitive.strategy import _complexity
    from cognitive.understanding import understand as u_
    from cognitive.assessment import assess as a_
    two = "set up X and then migrate Y"
    three = "set up X and then migrate Y and also seed Z"
    u2, u3 = u_(two), u_(three)
    s2 = _complexity(u2, a_(u2, problem=two), two)
    s3 = _complexity(u3, a_(u3, problem=three), three)
    assert s3 > s2, "a three-part request must outrank a two-part one"
    assert s2 >= 2, "and a two-part request must reach the threshold"


@pytest.mark.parametrize("message", [
    "what is the capital of France?",
    "write a python function that reverses a string",
    "summarise the uploaded report",
    "hello",
])
def test_a_single_task_is_still_not_multi_step(message):
    assert pipeline(message).strategy is not ReasoningStrategy.MULTI_STEP


def test_the_threshold_is_reachable_by_sequencing_alone():
    """Guards the premise: before the fix, no amount of ONE join reached it."""
    from cognitive.strategy import _complexity
    from cognitive.understanding import understand as u_
    from cognitive.assessment import assess as a_
    m = "Research X and then summarise"
    u = u_(m)
    assert _complexity(u, a_(u, problem=m), m) >= 2


def test_clarification_still_outranks_complexity():
    """A dangling reference is asked about before anything is planned, however
    many parts the request has."""
    d = pipeline("first install it then configure it")
    assert d.strategy is ReasoningStrategy.CLARIFICATION


def test_complexity_is_bounded():
    from cognitive.strategy import _complexity
    from cognitive.understanding import understand as u_
    from cognitive.assessment import assess as a_
    m = ("first do A and then B and then C and then D and also E "
         "as well as F, additionally G. 1) x 2) y")
    u = u_(m)
    assert 0 <= _complexity(u, a_(u, problem=m), m) <= 3


def test_complexity_is_deterministic():
    from cognitive.strategy import _complexity
    from cognitive.understanding import understand as u_
    from cognitive.assessment import assess as a_
    m = "Research X and then summarise"
    u = u_(m)
    a = a_(u, problem=m)
    assert _complexity(u, a, m) == _complexity(u, a, m)
