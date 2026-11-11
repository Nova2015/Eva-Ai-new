"""Which persona EVA WOULD adopt for a message — Update 37, observe-only.

src/modes/registry.py holds five personas (general, medical, coding, mechanical,
design) and nothing selects one: the mode selector was removed, and the
Cognitive Engine picks a strategy, not a persona. This module is the missing
picker, built to be MEASURED first. It changes no answer; the shadow records
what it would choose so the choice can be proven on real traffic before Update
37 ever lets it route.

The design decisions it encodes were settled before any code (see the project's
mode-classification notes):

  * DISAMBIGUATE ON DOMAIN NOUN + UNIT, NEVER A LONE KEYWORD. "stress", "load",
    "pressure", "fatigue" belong to medicine and engineering both. They read as
    mechanical only next to a domain noun (bolt, beam, bearing) or a unit (MPa,
    Nm, kg). "manage stress at work" is not mechanical.
  * THE VERB "design" DECIDES NOTHING — ITS OBJECT DOES. "design a bracket" is
    mechanical, "design a landing page" is design, "design a database" is
    coding, "design a study plan" is general.
  * SAFETY IS NOT HERE. The health safety floor is always on in the base prompt;
    a medical classification adds clinical depth, it is not what makes a health
    answer safe. So a miss here costs style, never safety.

Pure: no I/O, no imports from app or the cognitive package. A string in, an enum
pair out. Storage lives in mode_shadow.py and app.py.
"""

import re
from enum import Enum
from typing import Tuple

__all__ = ["Mode", "Signal", "classify_mode", "VALID_MODES", "VALID_SIGNALS"]


class Mode(str, Enum):
    GENERAL = "general"
    CODING = "coding"
    MEDICAL = "medical"
    MECHANICAL = "mechanical"
    DESIGN = "design"


class Signal(str, Enum):
    STRONG = "strong"      # an unambiguous, on-topic phrase fired
    WEAK = "weak"          # a softer signal; kept apart so a later threshold can drop it
    DEFAULT = "default"    # nothing fired — general by default


VALID_MODES = frozenset(m.value for m in Mode)
VALID_SIGNALS = frozenset(s.value for s in Signal)

MAX_LEN = 8000


def _norm(text: str) -> str:
    # Keep the backtick: a fenced ``` block is the strongest coding signal there
    # is, and stripping it here would leave _CODE_STRONG's ``` branch unable to
    # ever fire. + # . / and ' survive for c++, c#, api.endpoint, and-so-on.
    s = re.sub(r"[^a-z0-9+#/.\-'` ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


# ── coding ───────────────────────────────────────────────────────────────────
_CODE_STRONG = re.compile(
    r"```|"
    r"\b(python|javascript|typescript|java|kotlin|swift|golang|rust|c\+\+|c#|"
    r"php|ruby|sql|bash|html|css|react|node|django|flask|pandas|numpy)\b|"
    r"\b(def |class |import |function|const |let |var |=>|null|undefined|"
    r"traceback|stack ?trace|exception|nullpointer|segfault|compile|compiler|"
    r"syntax error|runtime error|regex|regexp|api endpoint|rest api|"
    r"git|github|npm|pip install|docker|kubernetes)\b|"
    r"\b(debug|refactor)(ging|ged)?\b",
    re.IGNORECASE)
_CODE_WEAK = re.compile(
    r"\b(code|coding|program|programming|script|algorithm|bug|function|"
    r"variable|array|loop|database|query|deploy|endpoint|library)\b",
    re.IGNORECASE)


# ── medical ──────────────────────────────────────────────────────────────────
_MED_STRONG = re.compile(
    r"\b(symptom|symptoms|fever|nausea|vomit\w*|diarrh\w*|migraine|"
    r"blood pressure|heart rate|dosage|dose|milligram|mg\b|prescri\w*|"
    r"diagnos\w*|antibiotic|ibuprofen|paracetamol|acetaminophen|insulin|"
    r"chemotherapy|infection|inflammation|tumou?r|biopsy|x-?ray|mri|ct scan|"
    r"blood test|cholesterol|diabetes|hypertension|asthma|arthritis|"
    r"pregnan\w*|allerg\w*)\b|"
    r"\b(my|his|her|their)\s+\w*\s*(pain|ache|rash|cough|swelling|"
    r"cramps?|sprain)\b|"
    r"\b(chest|back|stomach|abdominal|joint|muscle)\s+pain\b",
    re.IGNORECASE)
_MED_WEAK = re.compile(
    r"\b(health|medical|medicine|clinic\w*|doctor|physician|nurse|patient|"
    r"treatment|therapy|disease|illness|sick|nutrition|vitamin|"
    r"mental health|anxiety|depression)\b",
    re.IGNORECASE)


# ── mechanical: a domain noun, or a shared word paired with unit/domain ───────
_MECH_NOUN = re.compile(
    r"\b(bolt|nut|screw|beam|bearing|gear|gearbox|weld|welding|shaft|bracket|"
    r"flange|piston|valve|actuator|chassis|axle|coupling|fastener|rivet|"
    r"crankshaft|camshaft|gasket|bushing|spring|cam|"
    r"cad|gd&t|tolerance stack|machining|milling|lathe|cnc|"
    r"safety factor|yield strength|tensile strength|moment of inertia|"
    r"finite element|fea|cfd)\b",
    re.IGNORECASE)
# The shared words — mechanical ONLY when a unit or a domain noun is near.
_MECH_SHARED = re.compile(
    r"\b(stress|load|fatigue|pressure|torque|deflection|strain|shear|"
    r"bending|thermal expansion)\b", re.IGNORECASE)
_MECH_UNIT = re.compile(
    r"\b\d+\s?(mpa|gpa|kpa|pa|psi|bar|n|kn|nm|kg|g|mm|cm|m|rpm|hz|deg|°|"
    r"newton|newtons|pascal|joule)\b|"
    r"\b(mpa|gpa|kpa|psi|newton-?met(er|re)|kilonewton)\b",
    re.IGNORECASE)


# ── design: visual / product design ──────────────────────────────────────────
_DESIGN_STRONG = re.compile(
    r"\b(wireframe|mockup|mock-?up|figma|typograph\w*|kerning|leading|"
    r"colou?r palette|colou?r scheme|ui design|ux design|user interface|"
    r"user experience|visual hierarchy|whitespace|white space|"
    r"accessibility contrast|wcag|design system|style guide|"
    r"landing page|hero section)\b",
    re.IGNORECASE)
_DESIGN_WEAK = re.compile(
    r"\b(layout|spacing|padding|margin|alignment|contrast|font|fonts|"
    r"colou?r scheme|icon|button|screen|interface|branding|logo)\b",
    re.IGNORECASE)
# Objects that resolve "design a X" to a specific mode.
_DESIGN_OBJECT = re.compile(
    r"\bdesign\s+(?:a|an|the|my|our|some)?\s*"
    r"(landing page|web ?page|website|web ?site|logo|poster|banner|ui|"
    r"interface|screen|app|mobile app|dashboard|icon|flyer|brochure|"
    r"slide|presentation)\b", re.IGNORECASE)
_MECH_DESIGN_OBJECT = re.compile(
    r"\bdesign\s+(?:a|an|the|my|our|some)?\s*"
    r"(bracket|gearbox|shaft|housing|part|component|assembly|frame|chassis|"
    r"beam|joint|mechanism|machine|enclosure|mount|fixture)\b", re.IGNORECASE)


def classify_mode(text: str) -> Tuple[Mode, Signal]:
    """The persona this message would take, and how strongly it fired.

    Precedence is coding → medical → mechanical → design → general, and each
    detector is deliberately conservative so overlaps are rare. Returns
    (Mode.GENERAL, Signal.DEFAULT) when nothing fires.
    """
    s = _norm(text)
    if not s or len(text or "") > MAX_LEN:
        return (Mode.GENERAL, Signal.DEFAULT)

    # coding — strong, unambiguous first
    if _CODE_STRONG.search(s):
        return (Mode.CODING, Signal.STRONG)

    # medical
    if _MED_STRONG.search(s):
        return (Mode.MEDICAL, Signal.STRONG)

    # mechanical: a domain noun, or a "design a <mechanical thing>", or a shared
    # word standing next to a unit or a domain noun. Never a lone shared word.
    if _MECH_NOUN.search(s) or _MECH_DESIGN_OBJECT.search(s):
        return (Mode.MECHANICAL, Signal.STRONG)
    if _MECH_SHARED.search(s) and (_MECH_UNIT.search(s) or _MECH_NOUN.search(s)):
        return (Mode.MECHANICAL, Signal.STRONG)

    # design: "design a <visual thing>" or clear visual-design vocabulary
    if _DESIGN_OBJECT.search(s) or _DESIGN_STRONG.search(s):
        return (Mode.DESIGN, Signal.STRONG)

    # weaker signals, in the same order
    if _CODE_WEAK.search(s):
        return (Mode.CODING, Signal.WEAK)
    if _MED_WEAK.search(s):
        return (Mode.MEDICAL, Signal.WEAK)
    if _DESIGN_WEAK.search(s):
        return (Mode.DESIGN, Signal.WEAK)

    return (Mode.GENERAL, Signal.DEFAULT)
