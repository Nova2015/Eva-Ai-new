"""Tests for to_spoken — the deterministic reshaping of an answer for speech.

The reason this exists rather than a third prompt clause: an instruction can be
half-followed, and twice was. So the properties here are absolutes, and the
ones that matter most are the ones about what must NOT change — a transform
that quietly eats content is worse than markdown read aloud.

Pure functions, no imports from app.py, so the whole file runs in milliseconds.
"""

import pytest

try:
    from spoken_text import to_spoken, _latex_to_words, _is_math, _chart_sentence
except ImportError:  # running from the repo root
    from src.spoken_text import (  # type: ignore
        to_spoken, _latex_to_words, _is_math, _chart_sentence,
    )


FENCE = "`" * 3


# ── A: the two defects that survived Update 23 ───────────────────────────────
def test_the_trailing_latex_block_becomes_words():
    """The exact residue live testing found: the model wrote the solution in
    words, then appended a display block as a footnote."""
    out = to_spoken(r"The solution is minus one. $$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$")
    assert "$" not in out
    assert "\\frac" not in out
    assert "over" in out
    assert "square root" in out
    assert "plus or minus" in out


def test_bullets_become_sentences():
    out = to_spoken("Complexities:\n- Insertion: O(1)\n- Search: O(1)")
    assert not out.startswith("-")
    assert "\n- " not in out
    assert "Insertion: O(1)." in out


def test_bold_is_removed():
    assert to_spoken("A **hash map** stores pairs.") == "A hash map stores pairs."


# ── B: what must NOT change — the expensive failures ─────────────────────────
def test_a_fenced_code_block_survives_untouched():
    """A post-process cannot describe code in words, only delete it. Deleting
    it destroys what the user asked for, so fences are left alone."""
    code = FENCE + "python\ndef f(x):\n    return x ** 2  # **not bold**\n" + FENCE
    out = to_spoken("Here you go:\n" + code)
    assert code in out


def test_math_inside_a_fence_is_not_rewritten():
    code = FENCE + "latex\n$$x = \\frac{1}{2}$$\n" + FENCE
    assert code in to_spoken(code)


def test_currency_is_not_eaten():
    """"$5 and $10" contains a $...$ span whose content is " and ". A rule that
    converted every span would delete the sentence between two prices."""
    out = to_spoken("It costs $5 and $10 for the pair.")
    assert "$5" in out and "$10" in out
    assert "and" in out


def test_prose_is_left_alone():
    prose = "A hash map stores key-value pairs. Lookup is constant time."
    assert to_spoken(prose) == prose


def test_multiplication_asterisks_are_not_treated_as_italics():
    out = to_spoken("Compute a * b * c for the result.")
    assert "a * b * c" in out


def test_underscores_in_identifiers_survive():
    out = to_spoken("Call user_id and workspace_id together.")
    assert "user_id" in out and "workspace_id" in out


def test_no_content_is_lost_from_a_list():
    out = to_spoken("- alpha\n- beta\n- gamma")
    for word in ("alpha", "beta", "gamma"):
        assert word in out


# ── C: the rest of the markdown surface ──────────────────────────────────────
def test_headings_lose_their_hashes():
    out = to_spoken("## Time complexity\nIt is constant.")
    assert "#" not in out
    assert "Time complexity" in out


def test_links_keep_the_label_and_drop_the_address():
    """A URL read aloud is one character at a time."""
    out = to_spoken("See [the Python docs](https://docs.python.org/3/) for more.")
    assert "the Python docs" in out
    assert "https" not in out


def test_inline_code_loses_its_backticks():
    assert "`" not in to_spoken("Call `len(x)` on it.")


def test_a_table_becomes_sentences():
    table = ("| Method | Cost |\n| --- | --- |\n"
             "| Chaining | O(1) |\n| Open addressing | O(n) |")
    out = to_spoken(table)
    assert "|" not in out
    assert "---" not in out
    assert "Chaining, O(1)." in out
    assert "Method, Cost." in out


@pytest.mark.parametrize("mark", ["-", "*", "+", "•", "‣", "◦", "·"])
def test_typographic_bullets_are_handled_too(mark):
    """EVA's vision-unavailable message is written with "•". A class of only
    [-*+] left it reading as three bullet characters aloud."""
    out = to_spoken(f"Reasons:\n{mark} Vision model not configured\n{mark} Processor offline")
    assert mark not in out
    assert "Vision model not configured." in out


def test_numbered_lists_become_sentences():
    out = to_spoken("1. First step\n2. Second step")
    assert "First step." in out and "Second step." in out
    assert not out.lstrip().startswith("1.")


def test_horizontal_rules_disappear():
    assert "---" not in to_spoken("One.\n\n---\n\nTwo.")


# ── D: LaTeX conversion in detail ────────────────────────────────────────────
@pytest.mark.parametrize("expr,expected", [
    (r"x^2", "squared"),
    (r"x^3", "cubed"),
    (r"x^{10}", "to the power of 10"),
    (r"\frac{a}{b}", "a over b"),
    (r"\sqrt{9}", "the square root of 9"),
    (r"a \times b", "times"),
    (r"a \neq b", "not equal to"),
    (r"\pi", "pi"),
    (r"x_{i}", "sub i"),
])
def test_latex_fragments(expr, expected):
    assert expected in _latex_to_words(expr)


def test_nested_braces_are_parsed_not_pattern_matched():
    """\\frac{-b \\pm \\sqrt{b^2-4ac}}{2a} nests. A regex that assumes braces
    do not nest mangles precisely the expression this exists for."""
    out = _latex_to_words(r"\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}")
    assert "over 2a" in out
    assert "square root of b squared - 4ac" in out
    assert "{" not in out and "}" not in out


def test_an_unknown_command_does_not_leave_a_backslash():
    assert "\\" not in _latex_to_words(r"\weirdcmd{x}")


@pytest.mark.parametrize("inner,is_math", [
    (r"x^2 + y^2", True),
    (r"a = 1", True),
    (r"\pi", True),
    ("x", True),
    (" and ", False),
    ("5", False),
    ("", False),
])
def test_math_detection(inner, is_math):
    assert _is_math(inner) is is_math


# ── E: charts get something worth hearing (Update 25) ────────────────────────
def chart(payload):
    return FENCE + "chart\n" + payload + "\n" + FENCE


PIE = ('{"type":"pie","title":"Sales","data":['
       '{"label":"A","value":40},{"label":"B","value":30},{"label":"C","value":30}]}')


def test_a_chart_gains_a_spoken_sentence():
    """The deterministic chart path returns the block and nothing else, by
    design. Aloud that is a JSON blob with nothing to say."""
    out = to_spoken(chart(PIE))
    assert "Sales, a pie chart." in out
    assert "A is 40" in out and "B is 30" in out and "C is 30" in out


def test_the_chart_block_itself_is_untouched():
    """The frontend renders it. The sentence goes in FRONT of the block."""
    block = chart(PIE)
    out = to_spoken(block)
    assert block in out
    assert out.index("Sales, a pie chart.") < out.index(FENCE + "chart")


def test_the_values_come_from_the_spec_not_from_a_model():
    out = to_spoken(chart('{"type":"bar","title":"T","data":[{"label":"X","value":7}]}'))
    assert "X is 7" in out
    assert "and" not in out.split("X is 7")[0].split("chart.")[-1]


def test_many_points_are_capped_and_the_rest_counted():
    data = ",".join('{"label":"L%d","value":%d}' % (i, i) for i in range(12))
    out = to_spoken(chart('{"type":"bar","title":"Big","data":[' + data + ']}'))
    assert "and 4 more" in out
    assert "L11 is 11" not in out


def test_two_charts_each_get_their_own_sentence():
    out = to_spoken(chart(PIE) + "\n\n" + chart(
        '{"type":"bar","title":"Costs","data":[{"label":"Q","value":9}]}'))
    assert "Sales, a pie chart." in out
    assert "Costs, a bar chart." in out


def test_announcing_a_chart_is_idempotent():
    """A second pass regenerates the same sentence; it must not stack."""
    once = to_spoken(chart(PIE))
    assert to_spoken(once) == once
    assert once.count("Sales, a pie chart.") == 1


@pytest.mark.parametrize("payload", [
    "not json at all",
    '{"type":"pie"}',                      # no data
    '{"type":"pie","data":[]}',            # empty data
    '{"type":"pie","data":"nonsense"}',    # data not a list
    '[1,2,3]',                             # not an object
    # These reach the per-point loop rather than an earlier guard. Without
    # them a mutation that invented "nothing is 0" for an unreadable spec
    # survived every case above, because none of them got that far.
    '{"type":"pie","data":[1,2,3]}',       # points are not objects
    '{"type":"pie","data":[{"value":5}]}',  # point has no label
    '{"type":"pie","data":[{"label":"A"}]}',  # point has no value
    '{"type":"pie","data":[{"label":"  ","value":1}]}',  # blank label
])
def test_an_unusable_chart_spec_is_left_alone(payload):
    """Never invent a description for something that cannot be read."""
    block = chart(payload)
    out = to_spoken(block)
    assert out.strip() == block.strip()


def test_a_non_chart_fence_gets_no_sentence():
    block = FENCE + "python\nprint(1)\n" + FENCE
    assert to_spoken(block).strip() == block.strip()


def test_a_json_fence_is_not_a_chart():
    """Only ```chart is a chart. A json block that happens to hold a chart-
    shaped object must not be announced — otherwise any fence whose contents
    parse as JSON starts getting narrated."""
    block = FENCE + "json\n" + PIE + "\n" + FENCE
    assert to_spoken(block).strip() == block.strip()


def test_a_titleless_chart_still_reads():
    out = to_spoken(chart('{"type":"line","data":[{"label":"Jan","value":3}]}'))
    assert "Here is a line chart." in out
    assert "Jan is 3" in out


def test_float_values_do_not_read_as_trailing_zero():
    assert "P is 5" in _chart_sentence('{"data":[{"label":"P","value":5.0}]}')
    assert "5.0" not in _chart_sentence('{"data":[{"label":"P","value":5.0}]}')


# ── F: total, and safe on junk ───────────────────────────────────────────────
@pytest.mark.parametrize("value", ["", "   ", None, 42, [], {"a": 1}])
def test_never_raises_on_junk(value):
    to_spoken(value)


def test_unclosed_fence_does_not_swallow_the_answer():
    out = to_spoken("Here:\n" + FENCE + "python\nx = 1\n")
    assert "x = 1" in out


def test_it_is_idempotent():
    once = to_spoken("A **bold** claim.\n- one\n- two")
    assert to_spoken(once) == once
