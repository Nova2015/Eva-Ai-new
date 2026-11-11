"""EVA Cognitive Engine.

Step 2 scope: the CognitiveState model only. Nothing here is wired into the
chat path — importing this package has no effect on request handling, and
src/app.py does not import it. That is deliberate: the state model is the
contract every later stage depends on, so it lands and gets tested before any
behaviour moves.
"""

from .state import (  # noqa: F401
    CognitivePhase,
    CognitiveState,
    ReasoningStrategy,
    TaskStatus,
    VerificationStatus,
    FailureCategory,
    ProblemUnderstanding,
    KnowledgeAssessment,
    StrategySelection,
    PlannedTask,
    ActionRecord,
    Observation,
    VerificationResult,
    CognitiveError,
    LearningCandidate,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TASKS,
    DEFAULT_MAX_TRANSITIONS,
    redact_secrets,
)
