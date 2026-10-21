"""Stage 2B.4: chart-claim checker. Every checkable statement an answer makes about the attached chart is parsed and
verified against the chart dict: planet in house, planet in sign, lord of a house, Nth house from the Moon, dignity
flags, aspects on a house. The share of verified claims is a code metric for evaluation and the reward for Stage 2D.

    from src.eval.claims import check_claims
    claims = check_claims(answer_text, chart)      # [{"kind", "text", "ok"}]
"""
from __future__ import annotations

import re

from src.chart.constants import PLANETS, SIGNS
from src.chart.render import houses_from

_P = "|".join(PLANETS)
_S = "|".join(SIGNS)
_ORD = r"(\d{1,2})(?:st|nd|rd|th)"
_NOT_FROM = r"(?!\s+(?:from|counted|reckoned))"
PATTERNS = {
    "planet_in_house": re.compile(
        rf"\b({_P})\b(?P<mid>[^.;:\n]{{0,40}}?)\b(?:is |are |sits |sitting |placed |posited |occupies |occupying |located |tenants )?"
        rf"(?:in|occupies|occupying|tenanting)\s+(?:the |your |his |her |its )?{_ORD}\s*(?:house|bhava)\b{_NOT_FROM}", re.I),
    "lord_is": re.compile(rf"\b(?:the |your )?{_ORD}(?:[- ]house)?[- ]lord,?\s+(?:is\s+|being\s+)?({_P})\b", re.I),
    "lord_of": re.compile(rf"\blord of (?:the |your )?{_ORD}(?: house| bhava)?,?\s+(?:is\s+|being\s+)?({_P})\b", re.I),
    "planet_in_sign": re.compile(rf"\b({_P})\b\s+(?:is |sits |placed |posited )?(?:in|occupies)\s+(?:the sign of |the sign )?({_S})\b", re.I),
    "planet_from_moon": re.compile(rf"\b({_P})\b[^.;:\n]{{0,40}}?\b{_ORD}\s+(?:house\s+)?from\s+(?:the\s+|your\s+)?Moon\b", re.I),
    "sign_from_moon": re.compile(rf"\b{_ORD}\s+(?:house\s+)?from\s+(?:the\s+|your\s+)?Moon\s+(?:is|falls in|lies in|holds)\s+(?:the sign )?({_S})\b", re.I),
    "dignity": re.compile(rf"\b({_P})\b\s+(?:is\s+|being\s+)?(exalted|debilitated|in (?:its|his|her) own sign|combust|retrograde)\b", re.I),
    "aspects_house": re.compile(rf"\b({_P})\b\s+(?:aspects|casts (?:its|a|his|her) (?:drishti|aspect|glance) on|has (?:a |its )?(?:drishti|aspect) on)\s+"
                                rf"(?:the |your )?{_ORD}\b", re.I),
}
_OTHER_PLANET = re.compile(rf"\b(?:{_P})\b", re.I)


def check_claims(text: str, chart: dict) -> list[dict]:
    by_name = {p["name"]: p for p in chart["planets"]}
    lords = {h["house"]: h["lord"] for h in chart["houses"]}
    moon = houses_from(chart, "Moon")
    out = []

    def add(kind, m, ok):
        out.append({"kind": kind, "text": m.group(0)[:90], "ok": bool(ok)})

    for m in PATTERNS["planet_in_house"].finditer(text):
        if _OTHER_PLANET.search(m.group("mid")):
            continue          # another planet sits between: the house belongs to that one
        p, h = m.group(1).title(), int(m.group(3))
        if 1 <= h <= 12:
            add("planet_in_house", m, by_name[p]["house"] == h)
    for kind in ("lord_is", "lord_of"):
        for m in PATTERNS[kind].finditer(text):
            h, p = int(m.group(1)), m.group(2).title()
            if 1 <= h <= 12:
                add("lord", m, lords[h] == p)
    for m in PATTERNS["planet_in_sign"].finditer(text):
        p, s = m.group(1).title(), m.group(2).title()
        add("planet_in_sign", m, by_name[p]["sign"] == s)
    for m in PATTERNS["planet_from_moon"].finditer(text):
        p, n = m.group(1).title(), int(m.group(2))
        if 1 <= n <= 12:
            add("from_moon", m, p in moon[n - 1]["occupants"])
    for m in PATTERNS["sign_from_moon"].finditer(text):
        n, s = int(m.group(1)), m.group(2).title()
        if 1 <= n <= 12:
            add("from_moon", m, moon[n - 1]["sign"] == s)
    for m in PATTERNS["dignity"].finditer(text):
        p, flag = m.group(1).title(), m.group(2).lower()
        pl = by_name[p]
        if flag == "exalted":
            ok = pl["dignity"] == "exalted"
        elif flag == "debilitated":
            ok = pl["dignity"] == "debilitated"
        elif flag.startswith("in"):
            ok = pl["dignity"] in ("own sign", "moolatrikona")
        elif flag == "combust":
            ok = pl["combust"]
        else:
            ok = pl["retrograde"] and p not in ("Rahu", "Ketu")
        add("dignity", m, ok)
    for m in PATTERNS["aspects_house"].finditer(text):
        p, h = m.group(1).title(), int(m.group(2))
        if p not in ("Rahu", "Ketu") and 1 <= h <= 12:
            add("aspect", m, h in by_name[p]["aspects_houses"])
    return out


def claim_rate(text: str, chart: dict) -> tuple[int, int]:
    """(verified, total) claims in one answer."""
    c = check_claims(text, chart)
    return sum(x["ok"] for x in c), len(c)
