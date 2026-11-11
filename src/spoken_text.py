"""Turn an answer written for a screen into one worth hearing.

Update 26. Two prompt-side attempts failed to stop the model formatting for a
display when the answer was going to a speech engine:

  Update 22  appended "no markdown, no LaTeX" after the general-knowledge
             prompt's "CRITICAL: you MUST use LaTeX". Live, the model emitted
             $...$ exactly as the CRITICAL rule demanded.
  Update 23  removed the conflicting half instead of arguing with it. That
             worked for bold and for the body of a maths answer, but the model
             still appended a trailing $$...$$ block and still used bullets.

An instruction can be half-followed. A transform cannot, which is the whole
point of doing this deterministically rather than asking a third time.

WHAT THIS DELIBERATELY DOES NOT TOUCH

Fenced code blocks. They read terribly aloud, but a post-process cannot
describe code in words the way the prompt asks the model to — it can only
delete it, and deleting a code block destroys content the user asked for. The
prompt handles fences; if one arrives anyway, it survives intact.

The same answer string is also rendered in the chat window, so this changes the
displayed copy too. That tradeoff is deliberate and recorded with the change.
"""

import json
import re

__all__ = ["to_spoken"]


# ── charts ───────────────────────────────────────────────────────────────────
# Update 25. A ```chart block IS the answer to a chart request — the frontend
# renders it, and every prompt-side rule carves chart mode out precisely so it
# survives. But a speech engine handed one reads out JSON, and the deterministic
# chart path returns the block and nothing else, by design ("no prose"), so
# there is literally nothing to say.
#
# The block is left exactly as it is. A sentence describing it is added BEFORE
# it, built from the spec's own labels and values — no model, no invention. The
# picture still renders and the listener hears what it shows.
_CHART_FENCE = re.compile(r"```chart\s*\n(.*?)```", re.S)
_MAX_SPOKEN_POINTS = 8


def _num(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _chart_sentence(raw):
    """A spoken description of one chart spec, or "" if it is not usable."""
    try:
        spec = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(spec, dict):
        return ""
    data = spec.get("data")
    if not isinstance(data, list) or not data:
        return ""

    points = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        value = item.get("value")
        if not label or value is None:
            continue
        points.append(f"{label} is {_num(value)}")
    if not points:
        return ""

    extra = len(points) - _MAX_SPOKEN_POINTS
    shown = points[:_MAX_SPOKEN_POINTS]
    if len(shown) == 1:
        body = shown[0]
    else:
        body = ", ".join(shown[:-1]) + ", and " + shown[-1]
    if extra > 0:
        body += f", and {extra} more"

    kind = str(spec.get("type", "")).strip().lower()
    title = str(spec.get("title", "")).strip()
    kind_phrase = f"a {kind} chart" if kind else "a chart"
    lead = f"{title}, {kind_phrase}." if title else f"Here is {kind_phrase}."
    return f"{lead} {body}."


def _announce_charts(text):
    """Put a spoken sentence in front of each chart block, once."""
    def repl(m):
        sentence = _chart_sentence(m.group(1))
        if not sentence:
            return m.group(0)
        # Idempotent: a second pass regenerates the same sentence, so if it is
        # already sitting in front of this block, leave it alone.
        if text[:m.start()].rstrip().endswith(sentence):
            return m.group(0)
        return f"{sentence}\n{m.group(0)}"

    return _CHART_FENCE.sub(repl, text)


# ── LaTeX ────────────────────────────────────────────────────────────────────
_SYMBOLS = {
    r"\pm": "plus or minus",
    r"\mp": "minus or plus",
    r"\times": "times",
    r"\cdot": "times",
    r"\div": "divided by",
    r"\leq": "less than or equal to",
    r"\le": "less than or equal to",
    r"\geq": "greater than or equal to",
    r"\ge": "greater than or equal to",
    r"\neq": "not equal to",
    r"\ne": "not equal to",
    r"\approx": "approximately",
    r"\infty": "infinity",
    r"\pi": "pi",
    r"\alpha": "alpha",
    r"\beta": "beta",
    r"\theta": "theta",
    r"\lambda": "lambda",
    r"\mu": "mu",
    r"\sigma": "sigma",
    r"\Delta": "delta",
    r"\delta": "delta",
    r"\sum": "the sum of",
    r"\int": "the integral of",
    r"\rightarrow": "goes to",
    r"\to": "goes to",
}

_POWERS = {"2": "squared", "3": "cubed"}


def _group(s, i):
    """Content of the balanced {...} starting at s[i], and the index after it.

    Written by hand because \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a} nests, and a
    regex that pretends braces do not nest silently mangles exactly the
    expression this exists to read aloud.
    """
    if i >= len(s) or s[i] != "{":
        # Bare single-token argument, e.g. x^2 or \sqrt2.
        return (s[i], i + 1) if i < len(s) else ("", i)
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def _latex_to_words(expr):
    """A LaTeX fragment as something a speech engine can read."""
    out = []
    i = 0
    while i < len(expr):
        ch = expr[i]

        if ch == "\\":
            if expr.startswith(r"\frac", i):
                num, j = _group(expr, i + 5)
                den, j = _group(expr, j)
                out.append(f"{_latex_to_words(num)} over {_latex_to_words(den)}")
                i = j
                continue
            if expr.startswith(r"\sqrt", i):
                arg, j = _group(expr, i + 5)
                out.append(f"the square root of {_latex_to_words(arg)}")
                i = j
                continue
            # Longest symbol first, so \leq is not read as \le followed by "q".
            for name in sorted(_SYMBOLS, key=len, reverse=True):
                if expr.startswith(name, i):
                    out.append(f" {_SYMBOLS[name]} ")
                    i += len(name)
                    break
            else:
                i += 1  # unknown command: drop the backslash, keep the letters
            continue

        if ch == "^":
            arg, j = _group(expr, i + 1)
            word = _POWERS.get(arg.strip())
            out.append(f" {word}" if word
                       else f" to the power of {_latex_to_words(arg)}")
            i = j
            continue

        if ch == "_":
            arg, j = _group(expr, i + 1)
            out.append(f" sub {_latex_to_words(arg)}")
            i = j
            continue

        if ch in "{}":
            i += 1
            continue

        out.append(ch)
        i += 1

    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


def _is_math(inner):
    """Whether $...$ is mathematics rather than two currency amounts.

    "it costs $5 and $10" contains a $...$ span whose content is " and ". A
    rule that converted every span would eat the sentence between two prices.
    """
    s = inner.strip()
    if not s:
        return False
    if any(c in s for c in "\\^_="):
        return True
    # A single letter is a variable: $x$. Anything longer is prose until
    # proven otherwise — "up to three alphanumerics" also matched "and", which
    # is exactly the span sitting between "$5" and "$10".
    return len(s) == 1 and s.isalpha()


def _strip_math(text):
    text = re.sub(r"\$\$(.+?)\$\$",
                  lambda m: _latex_to_words(m.group(1)),
                  text, flags=re.S)
    return re.sub(
        r"\$([^$\n]+?)\$",
        lambda m: _latex_to_words(m.group(1)) if _is_math(m.group(1)) else m.group(0),
        text)


# ── markdown ─────────────────────────────────────────────────────────────────
_FENCE = re.compile(r"```.*?```", re.S)
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*\|[\s:|-]*\|?\s*$")
# Includes the typographic bullets, not just the markdown ones. EVA's own
# vision-unavailable message is written with "•", so a class of [-*+] left it
# reading as three bullet characters aloud on the one path this was added for.
_BULLET = re.compile(r"^\s*[-*+•‣◦·]\s+")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s*")
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _line_to_sentence(line):
    """A list item or table row as a sentence, so it is not read as hyphens."""
    line = line.rstrip()
    if not line:
        return line
    if line[-1] not in ".!?:;,":
        line += "."
    return line


def to_spoken(text):
    """Reshape an answer for a speech engine. Never raises; total on str input.

    Order matters. Fences are removed from play first so nothing inside them is
    rewritten, and inline markers are stripped before list markers so that
    "- **Average case:** O(1)" becomes a sentence rather than a bullet
    containing asterisks.
    """
    if not isinstance(text, str) or not text.strip():
        return text if isinstance(text, str) else ""

    # Before parking, so the sentence lands outside the block and the block
    # itself is still preserved verbatim by the parking below.
    text = _announce_charts(text)

    blocks = []

    def _park(m):
        blocks.append(m.group(0))
        return f"\x00FENCE{len(blocks) - 1}\x00"

    text = _FENCE.sub(_park, text)

    text = _strip_math(text)

    # Links before inline code, so [text](`url`) does not lose its label.
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)
    # Italics never have whitespace just inside the markers. Without those two
    # guards "a * b * c" reads as an emphasised " b " and multiplication is
    # silently deleted from the answer.
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", text)

    out = []
    for line in text.split("\n"):
        if _RULE.match(line) or _TABLE_SEP.match(line):
            continue
        if _HEADING.match(line):
            out.append(_line_to_sentence(_HEADING.sub("", line)))
            continue
        if line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            cells = [c for c in cells if c]
            if cells:
                out.append(_line_to_sentence(", ".join(cells)))
            continue
        if _BULLET.match(line):
            out.append(_line_to_sentence(_BULLET.sub("", line)))
            continue
        if _NUMBERED.match(line):
            out.append(_line_to_sentence(_NUMBERED.sub("", line)))
            continue
        out.append(line)

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    for n, block in enumerate(blocks):
        text = text.replace(f"\x00FENCE{n}\x00", block)

    return text.strip()
