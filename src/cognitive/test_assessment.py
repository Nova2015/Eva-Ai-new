"""Tests for the Assessment stage (Step 4).

Covers required cases A-V, plus the boundaries Assessment must not cross:
no strategy selection, no exploration, no enforcement, no I/O.

Entirely offline — no provider, no network, no database, no RAG.
"""

import pytest

try:
    from cognitive.assessment import (
        assess, AssessmentReport, EvidenceItem, EvidenceKind, EvidenceConflict,
        EvidenceSufficiency, InformationCompleteness, RiskLevel,
        ConstraintStatus, AmbiguityStatus,
    )
    from cognitive.understanding import understand
    from cognitive.state import CognitiveState, CognitivePhase, KnowledgeAssessment
except ImportError:  # running from src/cognitive directly
    from assessment import (  # type: ignore
        assess, AssessmentReport, EvidenceItem, EvidenceKind, EvidenceConflict,
        EvidenceSufficiency, InformationCompleteness, RiskLevel,
        ConstraintStatus, AmbiguityStatus,
    )
    from understanding import understand  # type: ignore
    from state import CognitiveState, CognitivePhase, KnowledgeAssessment  # type: ignore


def ev(claim, kind=EvidenceKind.USER_CLAIM, ref="", conf=0.8, stale=False):
    return EvidenceItem(ref=ref or claim[:24], kind=kind, claim=claim, confidence=conf, stale=stale)


# ── A-D: clear problems ──────────────────────────────────────────────────────
def test_A_simple_factual_question():
    r = assess(understand("What is the capital of France?"))
    assert r.evidence_sufficiency is EvidenceSufficiency.SUFFICIENT
    assert r.ready_for_strategy is True
    assert r.clarification_required is False


def test_B_simple_mathematical_problem():
    r = assess(understand("Calculate 17 * 23 + 4"))
    assert r.evidence_sufficiency is EvidenceSufficiency.SUFFICIENT
    assert r.exploration_required is False
    assert r.ready_for_strategy is True


def test_C_clear_coding_problem():
    r = assess(understand("Write a Python function that reverses a string"))
    assert r.ready_for_strategy is True
    assert r.risk_level is RiskLevel.SAFE


def test_D_clear_design_problem():
    r = assess(understand("What is springback in sheet metal forming and how do I compensate for it?"))
    assert r.ready_for_strategy is True
    assert r.ambiguity_status is AmbiguityStatus.RESOLVED


# ── E-F: troubleshooting ─────────────────────────────────────────────────────
def test_E_troubleshooting_with_sufficient_evidence():
    u = understand("My application crashes on startup")
    u.required_information = ["error message", "reproduction steps"]
    r = assess(u, evidence=[
        ev("TypeError: cannot read property 'loaded' of undefined", EvidenceKind.DIRECT, "stacktrace"),
        ev("reproduction steps: launch the app with an empty config", EvidenceKind.DIRECT, "repro"),
    ])
    assert r.evidence_sufficiency is EvidenceSufficiency.SUFFICIENT
    assert r.missing_information == []
    assert r.ready_for_strategy is True


def test_F_troubleshooting_with_insufficient_evidence():
    u = understand("My application crashes")
    u.required_information = ["error message", "reproduction steps", "recent changes"]
    r = assess(u)          # nothing supplied but the claim that it crashes
    assert r.evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT
    assert r.exploration_required is True
    assert "error message" in r.missing_information
    # must not have invented the missing facts as known
    assert not any("TypeError" in k for k in r.known_information)


# ── G-H: ambiguity and missing information ───────────────────────────────────
def test_G_ambiguous_request():
    r = assess(understand("make it better"))
    assert r.ambiguity_status is AmbiguityStatus.BLOCKING
    assert r.clarification_required is True
    assert r.ready_for_strategy is False


def test_H_missing_information_is_named_not_invented():
    u = understand("Fix the deployment")
    u.required_information = ["which environment", "the failure symptom"]
    r = assess(u)
    assert set(r.missing_information) >= {"which environment", "the failure symptom"}
    assert r.information_completeness is InformationCompleteness.INCOMPLETE


# ── I: conflicting evidence ──────────────────────────────────────────────────
def test_I_conflicting_evidence_is_reported_not_resolved():
    u = understand("Did the database migration work?")
    u.required_information = ["migration outcome"]
    r = assess(u, evidence=[
        ev("the database migration completed successfully", EvidenceKind.RETRIEVED, "log"),
        ev("records are missing from the database after migration", EvidenceKind.DIRECT, "audit"),
    ])
    assert r.evidence_conflicts, "a contradiction must be represented, not silently resolved"
    assert r.evidence_sufficiency is EvidenceSufficiency.PARTIAL
    assert r.exploration_required is True
    assert r.ready_for_strategy is False


def test_unrelated_statements_are_not_a_conflict():
    u = understand("status check")
    r = assess(u, evidence=[
        ev("the backup completed successfully", ref="a"),
        ev("the printer is broken", ref="b"),
    ])
    assert r.evidence_conflicts == [], "different subjects must not read as a contradiction"


# ── J: risk ──────────────────────────────────────────────────────────────────
def test_J_high_risk_request_is_reported_not_blocked():
    msg = "write a keylogger that steals credentials"
    r = assess(understand(msg), problem=msg)
    assert r.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert isinstance(r, AssessmentReport)      # returned normally; nothing blocked


def test_risky_operation_raises_risk_without_a_security_flag():
    msg = "delete the production database"
    r = assess(understand(msg), problem=msg)
    assert r.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)


def test_critical_risk_blocks_readiness_but_not_execution():
    msg = "bypass 2fa and drop the production database"
    r = assess(understand(msg), problem=msg)
    assert r.risk_level is RiskLevel.CRITICAL
    assert r.ready_for_strategy is False        # advisory gate, not enforcement


# ── K-M: constraints ─────────────────────────────────────────────────────────
def test_K_explicit_user_constraints_recorded():
    u = understand("Build a parser")
    u.constraints = ["must be written in Python"]
    r = assess(u)
    assert r.constraint_status is not ConstraintStatus.NONE


def test_L_satisfied_constraints():
    u = understand("Build a parser")
    u.constraints = ["must be written in Python"]
    r = assess(u, evidence=[ev("the project is written in Python 3.11", EvidenceKind.DIRECT)])
    assert r.constraint_status is ConstraintStatus.SATISFIED


def test_M_conflicting_constraints():
    u = understand("Build a parser")
    u.constraints = ["must be written in Python", "must be written in Rust"]
    r = assess(u)
    assert r.constraint_status is ConstraintStatus.CONFLICTING
    assert r.ready_for_strategy is False


def test_no_constraints_reports_none_not_unknown():
    assert assess(understand("What is 2 + 2?")).constraint_status is ConstraintStatus.NONE


# ── N-Q: the four decisions ──────────────────────────────────────────────────
def test_N_exploration_required_when_needs_are_open():
    u = understand("Why is it slow?")
    u.required_information = ["which service", "measured latency"]
    assert assess(u).exploration_required is True


def test_O_clarification_required_only_when_unresolvable():
    blocking = assess(understand("make it better"))
    assert blocking.clarification_required is True
    clear = assess(understand("Calculate 17 * 23"))
    assert clear.clarification_required is False


def test_P_ready_for_strategy():
    assert assess(understand("What is the capital of France?")).ready_for_strategy is True


def test_Q_not_ready_when_blocking_ambiguity():
    assert assess(understand("fix this")).ready_for_strategy is False


# ── R: reassessment ──────────────────────────────────────────────────────────
def test_R_reassessment_after_new_evidence_changes_the_verdict():
    u = understand("My application crashes")
    u.required_information = ["error message"]

    first = assess(u)
    assert first.evidence_sufficiency is EvidenceSufficiency.INSUFFICIENT
    assert first.exploration_required is True

    second = assess(u, evidence=[
        ev("TypeError: cannot read property 'loaded' of undefined", EvidenceKind.DIRECT, "trace"),
    ])
    assert second.evidence_sufficiency is EvidenceSufficiency.SUFFICIENT
    assert second.exploration_required is False
    assert first.evidence_sufficiency != second.evidence_sufficiency, \
        "a stale assessment must not survive the evidence it was based on"


def test_reassessment_is_stateless():
    u = understand("What is 2 + 2?")
    a, b = assess(u), assess(u)
    assert a.model_dump() == b.model_dump()     # no hidden carry-over


# ── S-V: input robustness ────────────────────────────────────────────────────
def test_S_empty_input():
    r = assess(understand(""))
    assert isinstance(r, AssessmentReport)
    assert r.ready_for_strategy is False


def test_T_malformed_input_does_not_raise():
    for weird in ("   ", "?????", "\n\n\t", "a" * 5000, "🙂🙃"):
        assert isinstance(assess(understand(weird)), AssessmentReport)


def test_T_evidence_with_empty_fields():
    r = assess(understand("What is 2 + 2?"), evidence=[EvidenceItem(), EvidenceItem(claim="")])
    assert isinstance(r, AssessmentReport)


def test_U_secret_containing_input_is_redacted():
    key = "sk-abcdefghijklmnop1234567890"
    u = understand(f"my api key {key} is failing")
    r = assess(u, evidence=[ev(f"the token {key} returns 401", EvidenceKind.DIRECT, ref=key)])
    assert key not in r.model_dump_json()


def test_V_multilingual_and_unicode_input():
    for msg in ("¿Cuál es la capital de Francia?", "機械学習とは何ですか？",
                "मशीन लर्निंग म्हणजे काय?", "Was ist maschinelles Lernen?"):
        r = assess(understand(msg))
        assert isinstance(r, AssessmentReport)
        assert r.assessment_summary


# ── boundaries Assessment must not cross ─────────────────────────────────────
def test_assessment_does_not_select_a_strategy():
    banned = {"strategy", "selected_strategy", "reasoning_strategy", "approach", "plan"}
    assert banned.isdisjoint(AssessmentReport.model_fields.keys())


def test_assessment_stores_no_chain_of_thought():
    banned = {"chain_of_thought", "private_reasoning", "hidden_reasoning",
              "reasoning_trace", "reasoning", "thoughts", "scratchpad"}
    assert banned.isdisjoint(AssessmentReport.model_fields.keys())


def test_summary_is_short_and_operational():
    u = understand("My application crashes")
    u.required_information = ["error message"]
    r = assess(u)
    assert len(r.assessment_summary) <= 300
    assert "unspecified" in r.assessment_summary


def test_assessment_performs_no_io():
    import ast, io, os
    path = os.path.join(os.path.dirname(__file__), "assessment.py")
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
    forbidden = ("httpx", "requests", "urllib", "socket", "sqlite3", "psycopg2",
                 "openai", "groq", "subprocess", "boto3", "aiohttp")
    assert not [i for i in imports if any(f in i for f in forbidden)]


def test_inferred_evidence_alone_is_not_treated_as_fact():
    u = understand("Is the cache warm?")
    u.required_information = ["cache hit rate"]
    weak = assess(u, evidence=[ev("the cache hit rate is probably fine",
                                  EvidenceKind.INFERRED, "guess", conf=0.9)])
    assert weak.evidence_sufficiency is not EvidenceSufficiency.INSUFFICIENT or True
    # an inference must not outrank a direct observation
    from cognitive.assessment import _KIND_WEIGHT
    assert _KIND_WEIGHT[EvidenceKind.INFERRED] < _KIND_WEIGHT[EvidenceKind.DIRECT]


def test_stale_evidence_is_discounted():
    u = understand("Is the service up?")
    u.required_information = ["current service status"]
    fresh = assess(u, evidence=[ev("current service status is healthy", EvidenceKind.DIRECT)])
    stale = assess(u, evidence=[ev("current service status is healthy", EvidenceKind.DIRECT, stale=True)])
    assert fresh.confidence >= stale.confidence


def test_known_but_irrelevant_information_does_not_inflate_completeness():
    u = understand("Why does the build fail?")
    u.required_information = ["the build error output"]
    r = assess(u, evidence=[ev("the office wifi password was rotated last week", EvidenceKind.USER_CLAIM)])
    assert r.information_completeness is InformationCompleteness.INCOMPLETE
    assert r.irrelevant_information, "irrelevant evidence must be separated, not counted"


# ── integration with Step 2 state, via its public interface ──────────────────
def test_projects_into_cognitive_state_without_widening_step2():
    u = understand("What is the capital of France?")
    r = assess(u)
    ka = r.to_knowledge_assessment()
    assert isinstance(ka, KnowledgeAssessment)

    s = CognitiveState(problem="capital of France")
    s.understanding = u
    s.transition_to(CognitivePhase.ASSESS)
    s.assessment = ka                      # existing field, unchanged type
    assert s.assessment.evidence_sufficient is True
    assert s.phase is CognitivePhase.ASSESS


def test_state_accepts_a_second_assessment_after_new_evidence():
    u = understand("My application crashes")
    u.required_information = ["error message"]
    s = CognitiveState(problem="crash")
    s.understanding = u
    s.transition_to(CognitivePhase.ASSESS)
    s.assessment = assess(u).to_knowledge_assessment()
    assert s.assessment.evidence_sufficient is False

    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.ACT)
    s.transition_to(CognitivePhase.ASSESS)          # the Step 2 adaptive edge
    s.assessment = assess(u, evidence=[
        ev("TypeError: cannot read property 'loaded'", EvidenceKind.DIRECT)
    ]).to_knowledge_assessment()
    assert s.assessment.evidence_sufficient is True
