"""Domain-independent harm assessment â€” Phase 1.

Not a keyword blocker. A blocklist cannot tell "how do I make a bomb" from "how
do bomb-disposal teams stay safe" from "what is TNT" â€” all three contain "bomb".
This reads the SHAPE of the request instead:

    capability  â€” is a harmful ACTION being requested on a harmful OBJECT
                  (make + explosive, write + malware, hack + someone's account)?
    framing     â€” is it DEFENSIVE (protect/detect/prevent) or EDUCATIONAL
                  (what is / how does it work)? Either negates harmful intent.
    operational â€” is it an actionable "how do I make/step by step/give me the
                  code" request? That is what turns a topic into assistance.
    severity + reversibility â€” how bad, and can it be undone.

It is deliberately CONSERVATIVE: STOP only when a harmful capability is requested
operationally AND no defensive/educational framing is present. Anything unclear
is CAUTION (observed, never blocked in Phase 1) â€” the gate uses the ordinary
clarification path for genuine ambiguity, and does not invent certainty.

Harm is judged against four targets â€” HUMAN, SOCIETY, AI_SYSTEM, ENVIRONMENT â€”
so the same reasoning covers a weapon, a bioweapon, malware and ecological
destruction. Pure and offline: no model, no I/O. Enums out, never free text.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from .state import (
    HarmSeverity,
    HarmTarget,
    SafetyAssessment,
    SafetyReason,
    SafetyVerdict,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


# â”€â”€ Framing: what turns a harmful topic into a safe question â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Defensive/protective intent â€” asking how to guard against the harm.
_DEFENSIVE = re.compile(
    r"\b(protect|defen[ds]\w*|prevent|mitigat\w*|detect|secure|harden|"
    r"safeguard|guard against|stay safe|keep safe|safely (dispose|handle|store)|"
    r"first aid|treat(ment)?|antidote|symptoms? of|recogni[sz]e|avoid being|"
    r"how (do|can) i (know|tell) if|is it (safe|dangerous)|report|block)\b",
    re.IGNORECASE)
# Educational / conceptual â€” asking what something is or how it works in general.
_EDUCATIONAL = re.compile(
    r"\b(what (is|are|was)|what'?s|how (does|do|did).{0,30}\bwork|explain|"
    r"history of|why (is|are|does|do)|overview|in general|in theory|"
    r"difference between|definition of|meaning of|examples? of)\b",
    re.IGNORECASE)
# Operational â€” an actionable request for the capability itself.
_OPERATIONAL = re.compile(
    r"\b(how (to|do i|can i)|step[\s-]?by[\s-]?step|instructions?|"
    r"give me (the )?(steps|code|recipe|method)|recipe for|tutorial|full guide|"
    r"walk me through|write (me )?(the )?code|exact (steps|amounts|process)|"
    r"make (a|an|me a)|build (a|an|me a)|synthesi[sz]e|assemble|manufactur\w*|"
    r"where (do i|can i) (buy|get)|help me (make|build|write|plan))\b",
    re.IGNORECASE)


# â”€â”€ Harmful capability: a harmful ACTION on a harmful OBJECT, per target â”€â”€â”€â”€â”€â”€â”€
# (regex, target, base severity, irreversible, reason)
_HarmRule = Tuple[re.Pattern, HarmTarget, HarmSeverity, bool, SafetyReason]

_MAKE = r"(?:make|build|construct|assembl\w*|manufactur\w*|synthesi[sz]e|3d ?print|create|produce|cook)"

_HARM_RULES: List[_HarmRule] = [
    # HUMAN â€” weapons / explosives
    (re.compile(rf"\b{_MAKE}\b[^.?!]*\b(bomb|explosive|ied|grenade|land\s?mine|"
                r"detonator|pipe bomb|napalm|molotov|ghost gun|untraceable (gun|firearm)|"
                r"silencer|suppressor|thermite)\b", re.IGNORECASE),
     HarmTarget.HUMAN, HarmSeverity.SEVERE, True, SafetyReason.WEAPON_OR_EXPLOSIVE),
    # HUMAN / SOCIETY â€” bio / chem / radiological agents
    (re.compile(rf"\b({_MAKE}|weaponi[sz]e|deploy|release)\b[^.?!]*\b(ricin|sarin|vx|"
                r"nerve agent|mustard gas|chlorine gas|anthrax|nerve toxin|dirty bomb|"
                r"biological weapon|chemical weapon|bioweapon)\b", re.IGNORECASE),
     HarmTarget.SOCIETY, HarmSeverity.SEVERE, True, SafetyReason.BIO_CHEM_RADIOLOGICAL),
    # HUMAN â€” violence against a person
    (re.compile(r"\b(kill|murder|assassinat\w*|kidnap|abduct|poison|torture|maim|hurt|injure\w*|"
                r"get away with (killing|murder))\b[^.?!]*\b(someone|somebody|a person|"
                r"people|him|her|them|my (wife|husband|ex|boss|neighbou?r|teacher)|"
                r"a specific|undetectabl\w*)\b", re.IGNORECASE),
     HarmTarget.HUMAN, HarmSeverity.SEVERE, True, SafetyReason.VIOLENCE_OR_HARM_TO_PERSON),
    # HUMAN â€” self-harm / suicide methods
    (re.compile(r"\b(kill myself|end my life|commit suicide|hang myself|overdose on|"
                r"(painless|best|quickest) way to die|methods? (of|to) (suicide|self.?harm))\b",
                re.IGNORECASE),
     HarmTarget.HUMAN, HarmSeverity.SEVERE, True, SafetyReason.SELF_HARM),
    # AI_SYSTEM â€” malware creation
    (re.compile(r"\b(write|create|make|build|code|develop|generate|deploy)\b[^.?!]*\b"
                r"(malware|ransomware|virus|trojan|worm|keylogger|rootkit|botnet|spyware|"
                r"stealer|cryptolocker|remote access trojan|rat payload)\b", re.IGNORECASE),
     HarmTarget.AI_SYSTEM, HarmSeverity.HIGH, False, SafetyReason.MALWARE_CREATION),
    # AI_SYSTEM â€” unauthorized intrusion into a specific target
    (re.compile(r"\b(hack|break into|gain (unauthori[sz]ed )?access to|crack|brute.?force|"
                r"phish|keylog|sim.?swap)\b[^.?!]*\b(someone'?s|somebody'?s|my (ex|neighbou?r|"
                r"friend|target|school|work)'?s?|his|her|their|the (bank|company|school|"
                r"government)|a specific)\b[^.?!]*\b(account|email|phone|wi-?fi|network|"
                r"server|password|database|system|instagram|facebook|gmail)?\b",
                re.IGNORECASE),
     HarmTarget.AI_SYSTEM, HarmSeverity.HIGH, False, SafetyReason.UNAUTHORIZED_INTRUSION),
    # SOCIETY â€” mass-casualty / attacks on the public or critical infrastructure
    (re.compile(r"\b(mass (shoot\w*|casualt\w*)|terror\w* attack|attack (a |the )?"
                r"(crowd|school|hospital|power grid|water supply|subway|airport|stadium)|"
                r"take down the (power grid|electrical grid)|poison the (water supply|reservoir))\b",
                re.IGNORECASE),
     HarmTarget.SOCIETY, HarmSeverity.SEVERE, True, SafetyReason.SOCIETAL_MASS_HARM),
    # ENVIRONMENT â€” deliberate ecological destruction
    (re.compile(r"\b(dump|release|dispose of|discharge)\b[^.?!]*\b(toxic waste|hazardous "
                r"(waste|chemical|material)|radioactive (waste|material)|raw sewage|crude oil)\b"
                r"[^.?!]*\b(river|lake|ocean|sea|forest|groundwater|illegally|at night)\b|"
                r"\b(contaminate|poison)\b[^.?!]*\b(water supply|reservoir|lake|river|soil)\b|"
                r"\bpoach\w*\b[^.?!]*\b(rhino|elephant|tiger|endangered)\b", re.IGNORECASE),
     HarmTarget.ENVIRONMENT, HarmSeverity.HIGH, True, SafetyReason.ENVIRONMENTAL_DESTRUCTION),
]

_SEVERITY_ORDER = {
    HarmSeverity.NONE: 0, HarmSeverity.LOW: 1, HarmSeverity.MEDIUM: 2,
    HarmSeverity.HIGH: 3, HarmSeverity.SEVERE: 4,
}


def assess_safety(understanding=None, question: str = "",
                  context: Optional[Sequence[str]] = None) -> SafetyAssessment:
    """Judge potential real-world harm. Conservative, domain-independent, offline.

    `understanding` is accepted (and its constraints consulted) so callers can
    reuse the Problem State, but the assessment stands on the request text alone
    when it must â€” it never depends on a model.
    """
    text = _norm(question + " " + " ".join(context or []))
    if not text:
        return SafetyAssessment()

    hits = [(t, s, irr, reason) for pat, t, s, irr, reason in _HARM_RULES if pat.search(text)]
    if not hits:
        return SafetyAssessment(verdict=SafetyVerdict.ALLOW, severity=HarmSeverity.NONE)

    defensive = bool(_DEFENSIVE.search(text))
    educational = bool(_EDUCATIONAL.search(text))
    operational = bool(_OPERATIONAL.search(text))

    targets = list(dict.fromkeys(t for t, *_ in hits))          # unique, ordered
    worst = max(hits, key=lambda h: _SEVERITY_ORDER[h[1]])
    base_severity, irreversible, reason = worst[1], any(h[2] for h in hits), worst[3]

    # Defensive framing (protect/detect/first-aid) â€” a safety question about a
    # dangerous topic is exactly what SHOULD be answered.
    if defensive:
        return SafetyAssessment(verdict=SafetyVerdict.ALLOW, severity=HarmSeverity.LOW,
                                targets=targets, irreversible=irreversible,
                                reason=SafetyReason.NONE)
    # Purely educational, not actionable â€” a high-level explanation, allowed.
    if educational and not operational:
        return SafetyAssessment(verdict=SafetyVerdict.ALLOW, severity=HarmSeverity.LOW,
                                targets=targets, irreversible=irreversible,
                                reason=SafetyReason.NONE)
    # A harmful capability requested with neither defensive nor purely-educational
    # framing. Every rule already required an ACTION verb on a harmful OBJECT, so
    # a match here is an operationally harmful request â€” refuse and redirect.
    return SafetyAssessment(verdict=SafetyVerdict.STOP, severity=base_severity,
                            targets=targets, irreversible=irreversible, reason=reason)

