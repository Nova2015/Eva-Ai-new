"""Build a real .pptx from content the user supplied, and prove it opens and
lays out cleanly. Update 39A.

THE CONTENT COMES FROM THE USER, NEVER FROM A MODEL. Same rule the Excel and
chart tools already follow: the slides carry the title, sections, bullets and
tables the message actually contains. A deck of invented facts is worse than
prose — it looks authoritative and gets presented to a room. If a request has a
verb and "presentation" but no content to put in it, parse_presentation_spec
returns None and the caller asks for the content rather than inventing a deck.

VERIFICATION IS NOT OPTIONAL, AND IT IS HONEST ABOUT WHAT IT CANNOT DO.
  * verify_pptx_structure opens the bytes back and checks the deck is the one
    that was planned: slide count, every planned title present, no empty slides,
    and every source table value round-tripped.
  * verify_pptx_layout checks geometry deterministically from the shapes —
    out-of-bounds, overlap, unreadable fonts, blank slides. True pixel-level
    clipping needs a renderer (LibreOffice), which this environment does not
    have, so that check is reported UNAVAILABLE, never as passed.

Pure: python-pptx only, no network, no app imports. Delivery lives in app.py.
"""

import io
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    from pydantic import BaseModel, ConfigDict, Field
except Exception:  # pragma: no cover
    BaseModel = object       # type: ignore
    ConfigDict = dict        # type: ignore

__all__ = [
    "MAX_SLIDES", "MIN_READABLE_PT", "SlideKind", "PlannedSlide",
    "PresentationPlan", "looks_like_presentation_request",
    "parse_presentation_spec", "build_powerpoint",
    "verify_pptx_structure", "verify_pptx_layout",
]

# Bounded so a malformed message cannot ask for a thousand-slide deck on a
# free-tier container. Well above any deck a person types into chat.
MAX_SLIDES = 40
MAX_BULLETS = 8
MIN_READABLE_PT = 12.0          # below this, text is not readable on a slide
# 16:9, the modern default.
SLIDE_W_EMU = 12192000          # 13.333"
SLIDE_H_EMU = 6858000           # 7.5"


# ── The gate ─────────────────────────────────────────────────────────────────
# A verb of creation next to a presentation noun. Deliberately narrow, and it
# shares nothing with the spreadsheet/chart nouns, so a deck request and a sheet
# request can never be confused. Questions ABOUT presentations do not fire.
_REQUEST_RE = re.compile(
    r"\b(creat(?:e|ing)|mak(?:e|ing)|generat(?:e|ing)|build(?:ing)?|"
    r"design(?:ing)?|prepar(?:e|ing)|put\s+together|give\s+me|"
    r"turn\s+.*\binto)\b[^.?!]*"
    r"\b(power\s*point|powerpoint|presentation|slide\s*deck|slide\s*show|"
    r"slideshow|pptx?|\bppt\b|deck|slides)\b",
    re.IGNORECASE,
)
_NOT_A_REQUEST_RE = re.compile(
    r"\b(what|which|why|when|who|explain|difference|meaning|"
    r"how\s+do\s+i\s+open|how\s+to\s+open)\b",
    re.IGNORECASE,
)


def looks_like_presentation_request(text: str) -> bool:
    """Whether the message asks for a presentation FILE to be produced."""
    s = (text or "").strip()
    if not s or len(s) > 8000:
        return False
    if _NOT_A_REQUEST_RE.search(s):
        return False
    return bool(_REQUEST_RE.search(s))


# ── The plan (structured metadata, no raw prompt) ────────────────────────────
class SlideKind(str, Enum):
    TITLE = "title"
    AGENDA = "agenda"
    CONTENT = "content"
    TABLE = "table"
    CLOSING = "closing"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannedSlide(_Base):
    kind: SlideKind
    title: str
    bullets: List[str] = Field(default_factory=list)
    table: Optional[List[List[str]]] = None     # header + rows, user data only


class PresentationPlan(_Base):
    title: str
    subtitle: str = ""
    audience: str = "unknown"
    objective: str = ""
    slides: List[PlannedSlide]

    @property
    def slide_count(self) -> int:
        return len(self.slides)


_TITLE_RE = re.compile(
    r"\b(?:presentation|deck|slides?|slideshow|powerpoint|pptx?|ppt)\b[^\n]*?"
    r"\b(?:about|on|regarding|titled|called|for\s+the\s+topic\s+of)\s+"
    r"([^\n.?!]{3,90})", re.IGNORECASE)
_AUDIENCE_RE = re.compile(
    r"\bfor\s+(?:an?\s+|the\s+|my\s+)?"
    r"([a-z][\w-]*(?:\s+[a-z][\w-]*){0,3}\s+"
    r"(?:team|audience|class|group|department|committee|board|stakeholders|"
    r"management|review|meeting))\b", re.IGNORECASE)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an|my|our)\s+", re.IGNORECASE)
_TABLE_LINE = re.compile(r".+[|\t].+")
_RULE_ROW = re.compile(r"^[\s|:+-]+$")
_HEADING = re.compile(r"^\s*(?:#{1,3}\s+|\d+[.)]\s+)?(.+?):\s*$")
_BULLET = re.compile(r"^\s*[-*•‣◦]\s+(.+\S)\s*$")
_MD_HEADING = re.compile(r"^\s*#{1,3}\s+(.+\S)\s*$")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _table_from_lines(lines: List[str]) -> Optional[List[List[str]]]:
    """Rectangular string table from pipe/tab lines — user values only."""
    rows: List[List[str]] = []
    for line in lines:
        if not _TABLE_LINE.match(line) or _RULE_ROW.match(line.strip()):
            continue
        sep = "|" if "|" in line else "\t"
        cells = [c.strip() for c in line.strip().strip("|").split(sep)]
        if len([c for c in cells if c]) >= 2:
            rows.append(cells)
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (width - len(r)))
    return rows[:50]


def parse_presentation_spec(text: str) -> Optional[PresentationPlan]:
    """A deterministic plan from the user's content, or None to ask for it.

    Extracts a title, optional audience, section headings with their bullets,
    and any table — attributing the table to the section it appears under.
    Invents nothing: an auto slide's title ("Agenda", "Summary") is a structural
    label, and the agenda/summary bullets are the user's own section titles,
    never generated facts. With a verb and a presentation noun but no content to
    carry, returns None so the caller can ask.
    """
    if not text:
        return None
    raw = text.strip()

    title_m = _TITLE_RE.search(raw)
    title = _LEADING_ARTICLE.sub("", _clean(title_m.group(1))) if title_m else ""
    audience_m = _AUDIENCE_RE.search(raw)
    audience = _LEADING_ARTICLE.sub("", _clean(audience_m.group(1))) if audience_m else "unknown"

    # One pass: headings open a section; bullets/content lines fill it; pipe/tab
    # lines accumulate as that section's table.
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    loose: List[str] = []
    loose_table: List[str] = []

    def new_section(t):
        s = {"title": t, "bullets": [], "table_lines": []}
        sections.append(s)
        return s

    for line in raw.splitlines():
        if _TABLE_LINE.match(line) and not _RULE_ROW.match(line.strip()):
            (current["table_lines"] if current else loose_table).append(line)
            continue
        if _RULE_ROW.match(line.strip()):
            continue
        md = _MD_HEADING.match(line)
        head = _HEADING.match(line)
        bul = _BULLET.match(line)
        if md:
            current = new_section(_clean(md.group(1)))
        elif head and not bul:
            current = new_section(_clean(head.group(1)))
        elif bul:
            b = _clean(bul.group(1))
            (current["bullets"] if current else loose).append(b) if (
                not current or len(current["bullets"]) < MAX_BULLETS) else None
        else:
            stripped = _clean(line)
            if stripped and len(stripped) > 2 and not _REQUEST_RE.search(line):
                if current and len(current["bullets"]) < MAX_BULLETS:
                    current["bullets"].append(stripped)
                elif not current:
                    loose.append(stripped)

    for s in sections:
        s["table"] = _table_from_lines(s["table_lines"])
    loose_tbl = _table_from_lines(loose_table)

    if not title:
        title = sections[0]["title"] if sections else (loose[0] if loose else "")

    content_sections = [s for s in sections if s["bullets"] or s.get("table")]
    if loose and not content_sections:
        content_sections = [{"title": "Overview", "bullets": loose[:MAX_BULLETS], "table": None}]
    elif loose:
        content_sections.insert(0, {"title": "Overview", "bullets": loose[:MAX_BULLETS], "table": None})

    has_any = bool(content_sections or loose_tbl)
    if not has_any or not title:
        return None                              # nothing to carry → ask

    slides: List[PlannedSlide] = [
        PlannedSlide(kind=SlideKind.TITLE, title=title,
                     bullets=([audience] if audience != "unknown" else [])),
    ]
    if len(content_sections) >= 2:
        slides.append(PlannedSlide(
            kind=SlideKind.AGENDA, title="Agenda",
            bullets=[s["title"] for s in content_sections][:MAX_BULLETS]))
    for s in content_sections:
        if len(slides) >= MAX_SLIDES - 1:
            break
        if s.get("table"):
            slides.append(PlannedSlide(kind=SlideKind.TABLE, title=s["title"],
                                       table=s["table"]))
        else:
            slides.append(PlannedSlide(kind=SlideKind.CONTENT, title=s["title"],
                                       bullets=s["bullets"][:MAX_BULLETS]))
    if loose_tbl and len(slides) < MAX_SLIDES - 1:
        slides.append(PlannedSlide(kind=SlideKind.TABLE, title="Data", table=loose_tbl))
    slides.append(PlannedSlide(
        kind=SlideKind.CLOSING, title="Summary",
        bullets=[s["title"] for s in content_sections][:MAX_BULLETS]))

    return PresentationPlan(title=title, subtitle="", audience=audience,
                            objective="", slides=slides[:MAX_SLIDES])


# ── The build (professional, restrained, controlled geometry) ────────────────
_FONT = "Calibri"
_INK = (0x1F, 0x38, 0x64)        # deep blue for titles
_BODY = (0x33, 0x33, 0x33)
_MUTED = (0x80, 0x80, 0x80)
_ACCENT = (0x2E, 0x74, 0xB5)


def build_powerpoint(plan: PresentationPlan) -> bytes:
    """A .pptx containing exactly `plan`. Raises on an empty plan."""
    if not plan or not plan.slides:
        raise ValueError("refusing to build an empty presentation")

    from pptx import Presentation
    from pptx.util import Emu, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE

    prs = Presentation()
    prs.slide_width = Emu(SLIDE_W_EMU)
    prs.slide_height = Emu(SLIDE_H_EMU)
    blank = prs.slide_layouts[6]

    margin = Emu(640080)          # 0.7"
    inner_w = Emu(SLIDE_W_EMU - 2 * 640080)

    def rgb(t):
        return RGBColor(*t)

    def textbox(slide, left, top, width, height):
        box = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(width), Emu(height))
        tf = box.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE   # renderer shrinks to fit
        return box, tf

    def set_run(run, text, size, color, bold=False):
        run.text = text
        run.font.name = _FONT
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = rgb(color)

    def add_footer(slide, page):
        # 12pt, the readability floor: a footer smaller than the tool's own
        # minimum would fail its own layout check, and be hard to read besides.
        _, tf = textbox(slide, int(margin), 6480000, 9000000, 274320)  # y≈7.08"
        p = tf.paragraphs[0]
        set_run(p.add_run(), f"{plan.title}", 12, _MUTED)
        _, ptf = textbox(slide, 11000000, 6480000, 1040080, 274320)
        pr = ptf.paragraphs[0]
        pr.alignment = PP_ALIGN.RIGHT
        set_run(pr.add_run(), str(page), 12, _MUTED)

    def accent_bar(slide):
        from pptx.enum.shapes import MSO_SHAPE
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, int(margin), 1600200,
                                     Emu(1828800), Emu(45720))  # under the title
        bar.fill.solid(); bar.fill.fore_color.rgb = rgb(_ACCENT)
        bar.line.fill.background()

    for idx, planned in enumerate(plan.slides, start=1):
        slide = prs.slides.add_slide(blank)

        if planned.kind is SlideKind.TITLE:
            _, tf = textbox(slide, int(margin), 2400300, int(inner_w), 1600200)
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
            set_run(p.add_run(), planned.title, 40, _INK, bold=True)
            if planned.bullets:
                sub = tf.add_paragraph()
                set_run(sub.add_run(), f"Audience: {planned.bullets[0]}", 20, _MUTED)
            continue

        # Title band (consistent position/size/font on every content slide).
        _, ttf = textbox(slide, int(margin), 457200, int(inner_w), 1000000)
        tp = ttf.paragraphs[0]
        set_run(tp.add_run(), planned.title, 30, _INK, bold=True)
        accent_bar(slide)

        if planned.kind is SlideKind.TABLE and planned.table:
            rows = planned.table
            nrows, ncols = len(rows), max(len(r) for r in rows)
            top = 1828800
            height = min(4200000, 320000 * nrows)
            gtable = slide.shapes.add_table(nrows, ncols, int(margin), Emu(top),
                                            int(inner_w), Emu(height)).table
            for c in range(ncols):
                gtable.columns[c].width = Emu(int(SLIDE_W_EMU - 2 * 640080) // ncols)
            for ri, row in enumerate(rows):
                for ci in range(ncols):
                    cell = gtable.cell(ri, ci)
                    cell.text = str(row[ci]) if ci < len(row) else ""
                    para = cell.text_frame.paragraphs[0]
                    for run in para.runs:
                        run.font.name = _FONT
                        run.font.size = Pt(14 if ri else 15)
                        run.font.bold = bool(ri == 0)
                        run.font.color.rgb = rgb(_INK if ri == 0 else _BODY)
        else:
            # Bullets. Consistent body box, generous margins, readable size.
            _, btf = textbox(slide, int(margin), 1828800, int(inner_w), 4400000)
            first = True
            for bullet in (planned.bullets or [""]):
                para = btf.paragraphs[0] if first else btf.add_paragraph()
                first = False
                para.space_after = Pt(10)
                set_run(para.add_run(), f"•  {bullet}" if bullet else "", 20, _BODY)

        add_footer(slide, idx)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ── Structural verification ──────────────────────────────────────────────────
def _slide_title_text(slide) -> str:
    """The first non-empty text on the slide — where the build puts the title."""
    for shape in slide.shapes:
        if shape.has_text_frame:
            t = (shape.text_frame.text or "").strip()
            if t:
                return t
    return ""


def _all_text(slide) -> str:
    parts = []
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text:
            parts.append(shape.text_frame.text)
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    parts.append(cell.text or "")
    return "\n".join(parts)


def verify_pptx_structure(data: bytes, plan: PresentationPlan) -> Tuple[bool, Dict[str, Any]]:
    """Open the bytes back and confirm they are the deck that was planned."""
    report: Dict[str, Any] = {"opened": False, "slides": 0, "reason": ""}
    if not data:
        report["reason"] = "empty"
        return False, report
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        slides = list(prs.slides)
    except Exception as exc:
        report["reason"] = f"unreadable_{type(exc).__name__}"
        return False, report

    report["opened"] = True
    report["slides"] = len(slides)
    if len(slides) != plan.slide_count:
        report["reason"] = "slide_count_mismatch"
        return False, report

    for i, (planned, slide) in enumerate(zip(plan.slides, slides)):
        title = _slide_title_text(slide)
        if not title:
            report["reason"] = f"empty_slide_{i}"
            return False, report
        if _clean(planned.title).lower() not in _clean(title).lower():
            report["reason"] = f"title_missing_{i}"
            return False, report
        body = _all_text(slide)
        for bullet in planned.bullets:
            if _clean(bullet) and _clean(bullet).lower() not in _clean(body).lower():
                report["reason"] = f"bullet_missing_{i}"
                return False, report
        if planned.table:
            has_table = any(getattr(s, "has_table", False) and s.has_table
                            for s in slide.shapes)
            if not has_table:
                report["reason"] = f"table_missing_{i}"
                return False, report
            for row in planned.table:
                for value in row:
                    if str(value).strip() and str(value).strip().lower() not in body.lower():
                        report["reason"] = "table_value_dropped"
                        return False, report

    report["reason"] = "ok"
    return True, report


# ── Visual verification (programmatic; render-clipping is UNAVAILABLE) ────────
def verify_pptx_layout(data: bytes) -> Tuple[bool, Dict[str, Any]]:
    """Geometry checks from the shapes: bounds, overlap, font size, blank slides.

    Deterministic and dependency-free. True pixel clipping needs a renderer,
    which this environment lacks, so the report says render_clipping:
    "UNAVAILABLE" rather than claiming a check it did not run.
    """
    report: Dict[str, Any] = {
        "opened": False, "render_clipping": "UNAVAILABLE",
        "out_of_bounds": 0, "overlaps": 0, "tiny_fonts": 0, "blank_slides": 0,
        "reason": "",
    }
    if not data:
        report["reason"] = "empty"
        return False, report
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        sw, sh = int(prs.slide_width), int(prs.slide_height)
        slides = list(prs.slides)
    except Exception as exc:
        report["reason"] = f"unreadable_{type(exc).__name__}"
        return False, report

    report["opened"] = True
    tol = 9144           # 0.01" tolerance for rounding

    def boxes(slide):
        out = []
        for shape in slide.shapes:
            try:
                left, top = int(shape.left), int(shape.top)
                width, height = int(shape.width), int(shape.height)
            except (TypeError, ValueError):
                continue
            out.append((shape, left, top, width, height))
        return out

    for slide in slides:
        bs = boxes(slide)
        text_present = any(
            s.has_text_frame and (s.text_frame.text or "").strip() for s, *_ in bs
        ) or any(getattr(s, "has_table", False) and s.has_table for s, *_ in bs)
        if not bs or not text_present:
            report["blank_slides"] += 1

        for shape, left, top, width, height in bs:
            if left < -tol or top < -tol or left + width > sw + tol or top + height > sh + tol:
                report["out_of_bounds"] += 1
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        sz = run.font.size
                        if sz is not None and sz.pt < MIN_READABLE_PT:
                            report["tiny_fonts"] += 1

        # Pairwise overlap of text boxes (substantial only).
        text_bs = [b for b in bs if b[0].has_text_frame and (b[0].text_frame.text or "").strip()]
        for i in range(len(text_bs)):
            for j in range(i + 1, len(text_bs)):
                _, l1, t1, w1, h1 = text_bs[i]
                _, l2, t2, w2, h2 = text_bs[j]
                ox = max(0, min(l1 + w1, l2 + w2) - max(l1, l2))
                oy = max(0, min(t1 + h1, t2 + h2) - max(t1, t2))
                area = ox * oy
                smaller = max(1, min(w1 * h1, w2 * h2))
                if area > 0.35 * smaller:      # >35% of the smaller box
                    report["overlaps"] += 1

    ok = (report["out_of_bounds"] == 0 and report["overlaps"] == 0
          and report["tiny_fonts"] == 0 and report["blank_slides"] == 0)
    report["reason"] = "ok" if ok else "layout_issue"
    return ok, report
