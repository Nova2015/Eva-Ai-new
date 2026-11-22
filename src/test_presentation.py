"""Tests for the PowerPoint tool (Update 39A).

The properties that matter for a deck that gets presented to a room:

  1. A request for a deck is recognised; a question ABOUT decks, and a
     spreadsheet request, are not.
  2. The plan carries only the user's content — titles, bullets, tables — and
     invents nothing; a contentless request yields None so the caller can ask.
  3. The file actually opens, and it is the deck that was planned: slide count,
     every planned title, and every source table value.
  4. The layout checks catch the things that make a deck unprofessional —
     objects off the slide, overlapping boxes, unreadable fonts, blank slides —
     and are honest that pixel-level clipping needs a renderer we do not have.
"""

import io

import pytest

try:
    from presentation import (
        MAX_SLIDES, MIN_READABLE_PT, SlideKind, PresentationPlan, PlannedSlide,
        looks_like_presentation_request, parse_presentation_spec,
        build_powerpoint, verify_pptx_structure, verify_pptx_layout,
        SLIDE_W_EMU, SLIDE_H_EMU,
    )
except ImportError:  # pragma: no cover
    from src.presentation import (  # type: ignore
        MAX_SLIDES, MIN_READABLE_PT, SlideKind, PresentationPlan, PlannedSlide,
        looks_like_presentation_request, parse_presentation_spec,
        build_powerpoint, verify_pptx_structure, verify_pptx_layout,
        SLIDE_W_EMU, SLIDE_H_EMU,
    )


DECK = """Create a 6-slide professional presentation for the engineering team about the Gearbox Redesign Project

## Objective
- Reduce gearbox weight by 12 percent
- Keep the safety factor at or above 2.0

## Approach
- Switch housing to 6061-T6 aluminium
- Topology-optimise the mounting bracket

## Results
| metric | before | after |
| mass kg | 8.4 | 7.3 |
| safety factor | 2.3 | 2.1 |
"""


# ── A: gating ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "create a powerpoint presentation about the bridge study",
    "make me a 6-slide deck",
    "build a presentation for the design review",
    "generate a slideshow of these findings",
    "put together a pptx for my project",
])
def test_a_request_for_a_deck_is_recognised(text):
    assert looks_like_presentation_request(text) is True


@pytest.mark.parametrize("text", [
    "what is a powerpoint",
    "how do i open a pptx",
    "explain the difference between keynote and powerpoint",
    "why is my presentation slow",
    "create an excel sheet from this data",     # a different artifact
    "create a bar chart of sales",              # a different artifact
    "what is the capital of France",
    "",
])
def test_a_question_or_other_artifact_is_not_a_deck_request(text):
    assert looks_like_presentation_request(text) is False


def test_a_very_long_message_is_not_treated_as_a_request():
    assert looks_like_presentation_request("make a presentation " + "x" * 9000) is False


# ── B: the plan carries the user's content, invents nothing ──────────────────
def test_the_plan_extracts_title_audience_sections_and_table():
    plan = parse_presentation_spec(DECK)
    assert plan is not None
    assert plan.title == "Gearbox Redesign Project"
    assert plan.audience == "engineering team"
    kinds = [s.kind for s in plan.slides]
    assert kinds[0] is SlideKind.TITLE and kinds[-1] is SlideKind.CLOSING
    assert SlideKind.TABLE in kinds
    # the table is attributed to its section, not dumped on a generic slide
    table_slide = next(s for s in plan.slides if s.kind is SlideKind.TABLE)
    assert table_slide.title == "Results"
    assert table_slide.table[0] == ["metric", "before", "after"]


def test_every_bullet_comes_from_the_user():
    plan = parse_presentation_spec(DECK)
    all_bullets = [b for s in plan.slides for b in s.bullets]
    # the agenda/summary bullets are the user's own section titles
    assert "Reduce gearbox weight by 12 percent" in all_bullets
    assert "Objective" in all_bullets            # in agenda + summary
    # nothing that was not in the input
    for b in all_bullets:
        assert b in DECK or b in ("Objective", "Approach", "Results", "engineering team")


@pytest.mark.parametrize("text", [
    "make me a powerpoint",
    "create a presentation",
    "build a 10-slide deck please",
])
def test_a_request_with_no_content_returns_none_so_the_caller_can_ask(text):
    assert parse_presentation_spec(text) is None


def test_loose_lines_with_no_headings_still_make_a_deck():
    plan = parse_presentation_spec(
        "create a presentation about Q3\nRevenue grew 8 percent\nChurn fell to 2 percent")
    assert plan is not None
    body = [b for s in plan.slides for b in s.bullets]
    assert "Revenue grew 8 percent" in body


def test_the_plan_is_bounded():
    big = "create a deck about X\n" + "\n".join(f"## Section {i}\n- point" for i in range(80))
    plan = parse_presentation_spec(big)
    assert plan.slide_count <= MAX_SLIDES


# ── C: the file opens and is the planned deck ────────────────────────────────
def test_the_pptx_is_valid_and_has_the_planned_slides():
    plan = parse_presentation_spec(DECK)
    data = build_powerpoint(plan)
    assert data[:2] == b"PK"                     # zip / OOXML signature
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) == plan.slide_count


def test_structural_verification_passes_for_a_real_build():
    plan = parse_presentation_spec(DECK)
    ok, report = verify_pptx_structure(build_powerpoint(plan), plan)
    assert ok is True and report["reason"] == "ok"
    assert report["slides"] == plan.slide_count


def test_source_table_values_are_preserved_exactly():
    plan = parse_presentation_spec(DECK)
    data = build_powerpoint(plan)
    from pptx import Presentation
    text = []
    for slide in Presentation(io.BytesIO(data)).slides:
        for shape in slide.shapes:
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        text.append(cell.text)
    for value in ("mass kg", "8.4", "7.3", "safety factor", "2.3", "2.1"):
        assert value in text


def test_structural_verification_catches_a_missing_slide():
    plan = parse_presentation_spec(DECK)
    data = build_powerpoint(plan)
    shorter = PresentationPlan(title=plan.title, slides=plan.slides + [
        PlannedSlide(kind=SlideKind.CONTENT, title="Ghost", bullets=["never built"])])
    ok, report = verify_pptx_structure(data, shorter)
    assert ok is False and report["reason"] == "slide_count_mismatch"


def test_structural_verification_catches_a_dropped_table_value():
    plan = parse_presentation_spec(DECK)
    data = build_powerpoint(plan)
    tampered = PresentationPlan(title=plan.title, slides=[
        s if s.kind is not SlideKind.TABLE else PlannedSlide(
            kind=SlideKind.TABLE, title=s.title,
            table=[["metric", "before", "after"], ["mass kg", "8.4", "9.9"]])
        for s in plan.slides])
    ok, report = verify_pptx_structure(data, tampered)
    assert ok is False and report["reason"] == "table_value_dropped"


def test_building_nothing_is_refused():
    with pytest.raises(ValueError):
        build_powerpoint(PresentationPlan(title="x", slides=[]))


# ── D: the layout checks bite (built with deliberate faults) ─────────────────
def _blank_deck_with(shape_fn):
    """A one-slide deck whose single slide is shaped by shape_fn(slide, prs)."""
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    prs.slide_width = Emu(SLIDE_W_EMU)
    prs.slide_height = Emu(SLIDE_H_EMU)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape_fn(slide, prs)
    buf = io.BytesIO(); prs.save(buf)
    return buf.getvalue()


def test_layout_passes_for_a_clean_deck():
    plan = parse_presentation_spec(DECK)
    ok, report = verify_pptx_layout(build_powerpoint(plan))
    assert ok is True
    assert report["render_clipping"] == "UNAVAILABLE"     # honest about the gap
    assert report["out_of_bounds"] == 0 and report["overlaps"] == 0
    assert report["tiny_fonts"] == 0 and report["blank_slides"] == 0


def test_layout_detects_an_object_off_the_slide():
    from pptx.util import Emu, Pt
    def off_edge(slide, prs):
        box = slide.shapes.add_textbox(Emu(SLIDE_W_EMU - 100000), Emu(500000),
                                       Emu(3000000), Emu(500000))  # runs off the right
        r = box.text_frame.paragraphs[0].add_run(); r.text = "off the edge"; r.font.size = Pt(20)
    ok, report = verify_pptx_layout(_blank_deck_with(off_edge))
    assert ok is False and report["out_of_bounds"] >= 1


def test_layout_detects_overlapping_boxes():
    from pptx.util import Emu, Pt
    def overlap(slide, prs):
        for _ in range(2):
            box = slide.shapes.add_textbox(Emu(1000000), Emu(1000000), Emu(4000000), Emu(2000000))
            r = box.text_frame.paragraphs[0].add_run(); r.text = "stacked"; r.font.size = Pt(20)
    ok, report = verify_pptx_layout(_blank_deck_with(overlap))
    assert ok is False and report["overlaps"] >= 1


def test_layout_detects_unreadable_fonts():
    from pptx.util import Emu, Pt
    def tiny(slide, prs):
        box = slide.shapes.add_textbox(Emu(800000), Emu(800000), Emu(4000000), Emu(1000000))
        r = box.text_frame.paragraphs[0].add_run(); r.text = "microscopic"; r.font.size = Pt(6)
    ok, report = verify_pptx_layout(_blank_deck_with(tiny))
    assert ok is False and report["tiny_fonts"] >= 1


def test_layout_detects_a_blank_slide():
    ok, report = verify_pptx_layout(_blank_deck_with(lambda slide, prs: None))
    assert ok is False and report["blank_slides"] >= 1


def test_layout_reports_unreadable_bytes_rather_than_passing():
    ok, report = verify_pptx_layout(b"not a pptx")
    assert ok is False and report["reason"].startswith("unreadable")


def test_the_readable_floor_is_a_real_threshold():
    assert MIN_READABLE_PT >= 12.0
