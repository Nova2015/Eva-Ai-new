"""Phase 1 Decision Gate — decide() builds the Problem State BEFORE the answer.

It reuses the EXISTING engine — understand(), assess(), select_strategy() — plus
the new assess_safety(). It re-implements none of them. It returns one structured
GateDecision (PROCEED / CLARIFY / SAFETY_STOP) up front, so the cognitive state
can be authoritative rather than run post-hoc over a reply that already exists.

Precedence: SAFETY first (a serious/irreversible harmful request stops before
anything else), then CLARIFY (genuine ambiguity — ask, don't guess), else
PROCEED. Pure and offline. Shadow recording and the authoritative short-circuit
live in app.py; this module only decides.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from .assessment import assess
from .safety import assess_safety
from .state import (
    GateAction,
    GateDecision,
    ReasoningStrategy,
    SafetyVerdict,
    SolutionPaths,
)
from .strategy import select_strategy
from .understanding import understand

try:
    from .verification import available_requirements
except Exception:  # pragma: no cover
    def available_requirements():
        return None


def _context_from_history(history) -> List[str]:
    out: List[str] = []
    for h in (history or []):
        if isinstance(h, dict):
            c = str(h.get("content") or h.get("message") or h.get("text") or "").strip()
            if c:
                out.append(c)
    return out[-6:]


def _solution_paths(strategy_decision, understanding, assessment) -> SolutionPaths:
    """Coarse Phase-1 signal only — NOT Fixed/Two/Multi/Open (a later phase)."""
    strat = getattr(strategy_decision, "strategy", None)
    if strat in (ReasoningStrategy.MULTI_STEP, ReasoningStrategy.ANALYSIS):
        return SolutionPaths.MULTIPLE
    if (understanding.confidence >= 0.7 and not understanding.needs_clarification
            and strat in (ReasoningStrategy.DIRECT, ReasoningStrategy.RETRIEVAL,
                          ReasoningStrategy.CALCULATION)):
        return SolutionPaths.OBVIOUS
    return SolutionPaths.UNCERTAIN


def _derive_assumptions(understanding, assessment, clarifying: bool) -> List[str]:
    """What EVA is proceeding on WITHOUT evidence. Empty when clarifying — asking
    is the opposite of assuming. Drawn from missing info, so it is disjoint from
    known_information (facts) by construction."""
    if clarifying:
        return []
    missing = list(assessment.missing_information) or list(understanding.required_information)
    return [f"assuming a sensible default for: {m}" for m in missing[:5] if m]


def _clarify_question(understanding, assessment) -> str:
    needs = (list(understanding.required_information)
             or list(assessment.missing_information)
             or list(understanding.ambiguities))
    needs = [n for n in needs if n]
    if not needs:
        return "Could you share a little more detail so I can help precisely?"
    if len(needs) == 1:
        return f"To help precisely, could you clarify: {needs[0]}?"
    bullets = "\n".join(f"- {n}" for n in needs[:4])
    return "To help precisely, could you clarify:\n" + bullets


def decide(question: str, history=None, has_image: bool = False,
           context: Optional[Sequence[str]] = None) -> GateDecision:
    """The Phase-1 gate. Never raises the caller's request — on any internal
    error it returns a PROCEED (the safe default: behave as EVA does today)."""
    try:
        ctx = list(context or []) + _context_from_history(history)
        u = understand(question or "", context=ctx, has_image=has_image)
        a = assess(u, context=ctx, problem=question or "")
        safety = assess_safety(u, question or "", context=ctx)

        try:
            strat = select_strategy(u, a, problem=question or "",
                                    available=available_requirements())
        except Exception:
            strat = None
        paths = _solution_paths(strat, u, a) if strat is not None else SolutionPaths.UNCERTAIN

        will_clarify = bool(u.needs_clarification or a.clarification_required)
        if safety.verdict is SafetyVerdict.STOP:
            action = GateAction.SAFETY_STOP
            will_clarify = False
        elif will_clarify:
            action = GateAction.CLARIFY
        else:
            action = GateAction.PROCEED

        clarifying = action is GateAction.CLARIFY
        decision = GateDecision(
            action=action,
            safety=safety,
            solution_paths=paths,
            strategy=(strat.strategy if strat is not None else ReasoningStrategy.DIRECT),
            confidence=u.confidence,
            needs_clarification=will_clarify,
            clarification_question=_clarify_question(u, a) if clarifying else "",
            facts=list(a.known_information),
            assumptions=_derive_assumptions(u, a, clarifying),
            unknowns=list(a.missing_information),
        )
        decision._understanding = u
        decision._assessment = a
        decision._strategy_decision = strat
        return decision
    except Exception:
        # The gate must never cost a user their answer: default to PROCEED.
        return GateDecision(action=GateAction.PROCEED)
