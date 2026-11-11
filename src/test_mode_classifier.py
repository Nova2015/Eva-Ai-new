"""Tests for the observe-only mode classifier — Update 37.

The classifier changes no answer today, so what these tests guard is not an
outcome the user sees but the SHAPE of the guess the shadow will record. Two
disambiguation decisions were settled before any code and are the reason this
module exists at all — every one of them has a test that fails if the rule is
softened:

  * a shared word (stress/load/pressure/fatigue) is mechanical ONLY beside a
    unit or a domain noun, never on its own; and
  * the verb "design" decides nothing — its object picks the mode.

If either rule regresses, "manage stress at work" starts being answered by an
engineering persona, or "design a study plan" by a UI one. The precedence order
and the strong/weak split are guarded too, because the shadow's whole value is
that STRONG counts are the population Update 37 would route on.
"""

import pytest

try:
    from mode_classifier import (
        classify_mode, Mode, Signal, VALID_MODES, VALID_SIGNALS,
    )
except ImportError:  # running from the repo root
    from src.mode_classifier import (  # type: ignore
        classify_mode, Mode, Signal, VALID_MODES, VALID_SIGNALS,
    )


# ── A: the shared word never fires mechanical on its own ─────────────────────
# The heart of the module. Each of these has a shared word (stress, load,
# pressure, fatigue) but NO unit and NO domain noun, so it must NOT be
# mechanical — it is everyday language.
@pytest.mark.parametrize("text", [
    "how do i manage stress at work",
    "i'm under a lot of pressure lately",
    "feeling fatigue after a long week",
    "the workload on my team is too high",
    "peer pressure is hard to deal with",
])
def test_a_lone_shared_word_is_not_mechanical(text):
    mode, _ = classify_mode(text)
    assert mode is not Mode.MECHANICAL


def test_stress_at_work_is_general_not_engineering():
    # The canonical example: no domain noun, no unit → general.
    assert classify_mode("how do i manage stress at work") == (
        Mode.GENERAL, Signal.DEFAULT)


# ── B: the shared word DOES fire when a unit or domain noun is present ────────
def test_stress_with_a_unit_is_mechanical():
    mode, sig = classify_mode("what is the stress in a bar loaded to 200 MPa")
    assert (mode, sig) == (Mode.MECHANICAL, Signal.STRONG)


def test_stress_with_a_domain_noun_is_mechanical():
    mode, sig = classify_mode("calculate the stress in a 12mm bolt")
    assert (mode, sig) == (Mode.MECHANICAL, Signal.STRONG)


def test_load_on_a_beam_is_mechanical():
    mode, _ = classify_mode("what load can this steel beam carry")
    assert mode is Mode.MECHANICAL


def test_a_bare_domain_noun_needs_no_shared_word():
    # A crankshaft is mechanical with no "stress"/"load" nearby at all.
    assert classify_mode("explain how a crankshaft works")[0] is Mode.MECHANICAL


# ── C: "viral load" is medicine, not mechanics ───────────────────────────────
def test_viral_load_is_medical_not_mechanical():
    # "load" is a shared word, but the medical detector runs first AND there is
    # no unit/domain noun to make it mechanical anyway.
    mode, _ = classify_mode("my viral load came back high after the infection")
    assert mode is Mode.MEDICAL


# ── D: "design a X" — the object decides, never the verb ─────────────────────
def test_design_a_bracket_is_mechanical():
    assert classify_mode("design a bracket to hold a motor")[0] is Mode.MECHANICAL


def test_design_a_gearbox_is_mechanical():
    assert classify_mode("help me design a gearbox")[0] is Mode.MECHANICAL


def test_design_a_housing_is_mechanical_by_object_alone():
    # "housing" is not a standalone domain noun — only "design a <mech thing>"
    # makes it mechanical. This is the case that proves the design-object path
    # earns its keep; without it the sentence falls through to general.
    assert classify_mode("design a housing for the sensor controller")[0] is (
        Mode.MECHANICAL)


def test_design_a_landing_page_is_design():
    assert classify_mode("design a landing page for my startup")[0] is Mode.DESIGN


def test_design_a_poster_is_design_by_object_alone():
    # "poster" appears in no design vocabulary list — only the design-object
    # path routes it. Its twin to the housing case: remove that path and this
    # sentence is general, not design.
    assert classify_mode("design a poster for the school event")[0] is Mode.DESIGN


def test_design_a_logo_is_design():
    assert classify_mode("can you design a logo for us")[0] is Mode.DESIGN


def test_design_a_database_is_coding():
    # "database" is a coding-weak word; no strong design/mech object fires, so
    # it lands in coding at WEAK strength.
    mode, sig = classify_mode("design a database schema for orders")
    assert mode is Mode.CODING


def test_design_a_study_plan_is_general():
    # No object in either design or mechanical vocabulary → nothing fires.
    assert classify_mode("design a study plan for my exams") == (
        Mode.GENERAL, Signal.DEFAULT)


# ── E: coding ────────────────────────────────────────────────────────────────
def test_a_fenced_code_block_is_strong_coding():
    mode, sig = classify_mode("why does this break?\n```\nprint(x)\n```")
    assert (mode, sig) == (Mode.CODING, Signal.STRONG)


def test_a_named_language_is_strong_coding():
    assert classify_mode("write a python function to sort a list") == (
        Mode.CODING, Signal.STRONG)


def test_a_traceback_is_strong_coding():
    assert classify_mode("i got a traceback, what does it mean")[1] is Signal.STRONG


def test_bare_coding_vocabulary_is_weak():
    mode, sig = classify_mode("what is an algorithm")
    assert (mode, sig) == (Mode.CODING, Signal.WEAK)


# ── F: medical ───────────────────────────────────────────────────────────────
def test_a_symptom_is_strong_medical():
    assert classify_mode("i have a fever and a bad cough")[0] is Mode.MEDICAL


def test_a_dosage_question_is_strong_medical():
    mode, sig = classify_mode("how many mg of ibuprofen is safe")
    assert (mode, sig) == (Mode.MEDICAL, Signal.STRONG)


def test_bare_health_vocabulary_is_weak():
    mode, sig = classify_mode("tips for better mental health")
    assert (mode, sig) == (Mode.MEDICAL, Signal.WEAK)


# ── G: design ────────────────────────────────────────────────────────────────
def test_a_wireframe_is_strong_design():
    assert classify_mode("make a wireframe for the checkout")[0] is Mode.DESIGN


def test_bare_layout_vocabulary_is_weak():
    mode, sig = classify_mode("what padding should this button have")
    assert (mode, sig) == (Mode.DESIGN, Signal.WEAK)


# ── H: precedence — coding → medical → mechanical → design → general ──────────
def test_coding_wins_over_a_weak_medical_word():
    # "python" (strong coding) alongside "patient" (weak medical): coding wins.
    mode, _ = classify_mode("write a python script to track each patient")
    assert mode is Mode.CODING


def test_coding_wins_over_a_strong_medical_word():
    # Both fire at STRONG: "python" (code) and "dosage"/"insulin" (medical). A
    # request to WRITE CODE about a clinical topic is a coding task, so the
    # documented order — coding before medical — must decide it. This is the
    # case a lone weak-medical word cannot test: it pins the precedence itself.
    mode, sig = classify_mode(
        "write a python function to calculate the insulin dosage")
    assert (mode, sig) == (Mode.CODING, Signal.STRONG)


def test_medical_strong_wins_over_a_mechanical_shared_word():
    # "dosage" is strong medical; "pressure" is a bare shared word. Medical runs
    # first and there is no unit to make pressure mechanical.
    mode, _ = classify_mode("what dosage lowers blood pressure")
    assert mode is Mode.MEDICAL


def test_mechanical_wins_over_a_weak_design_word():
    # "bolt" (mech domain noun) alongside "layout" (weak design): mechanical
    # strong runs before design weak.
    mode, _ = classify_mode("the layout of the bolt pattern on the flange")
    assert mode is Mode.MECHANICAL


# ── I: the default and the edges ─────────────────────────────────────────────
def test_plain_chat_is_general_default():
    assert classify_mode("what's a good movie to watch tonight") == (
        Mode.GENERAL, Signal.DEFAULT)


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_input_is_general_default(text):
    assert classify_mode(text) == (Mode.GENERAL, Signal.DEFAULT)


def test_an_overlong_message_short_circuits_to_default():
    # Past MAX_LEN we do not scan — a truthful "nothing classified" beats a
    # scan of an 8000-char paste.
    assert classify_mode("bolt " * 4000) == (Mode.GENERAL, Signal.DEFAULT)


# ── J: the contract the shadow depends on ────────────────────────────────────
def test_every_result_is_a_valid_enum_pair():
    for text in ["design a bracket", "manage stress", "fever", "```code```",
                 "", "hello", "design a logo", "viral load high"]:
        mode, sig = classify_mode(text)
        assert mode.value in VALID_MODES
        assert sig.value in VALID_SIGNALS


def test_general_only_ever_pairs_with_default():
    # A general classification is by definition "nothing fired"; it must never
    # be reported as strong/weak, or the shadow's strong_non_general share lies.
    for text in ["hello there", "tell me a joke", "design a study plan", ""]:
        mode, sig = classify_mode(text)
        if mode is Mode.GENERAL:
            assert sig is Signal.DEFAULT


def test_default_signal_only_ever_pairs_with_general():
    for text in ["python code", "fever cough", "design a bracket", "wireframe"]:
        mode, sig = classify_mode(text)
        if sig is Signal.DEFAULT:
            assert mode is Mode.GENERAL
