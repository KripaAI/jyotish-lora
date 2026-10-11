"""Phase 1.6: keyword-based topic tags for chunks. Tags drive coverage sampling in the dataset generator."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from src.chart.constants import NAKSHATRAS

_PLANETS = {
    "sun": r"sun|sury|surya|ravi", "moon": r"moon|chandra?|candra?|soma", "mars": r"mars|mangala?|kuja|angaraka",
    "mercury": r"mercury|budha?", "jupiter": r"jupiter|guru|brihaspati|brhaspati",
    "venus": r"venus|shukra?|sukra?", "saturn": r"saturn|shani|sani", "rahu": r"rahu", "ketu": r"ketu",
}
_SIGNS = {
    "aries": r"aries|mesha", "taurus": r"taurus|vrishabha|vrisha|rishabha", "gemini": r"gemini|mithuna",
    "cancer": r"cancer|karka|kataka", "leo": r"leo|simha", "virgo": r"virgo|kanya",
    "libra": r"libra|tula|thula", "scorpio": r"scorpio|vrischika|vrishchika", "sagittarius": r"sagittarius|dhanus?",
    "capricorn": r"capricorn|makara", "aquarius": r"aquarius|kumbha", "pisces": r"pisces|meena|mina",
}
_ORD = ["1st|first", "2nd|second", "3rd|third", "4th|fourth", "5th|fifth", "6th|sixth",
        "7th|seventh", "8th|eighth", "9th|ninth", "10th|tenth", "11th|eleventh", "12th|twelfth"]
_BHAVA = ["tanu|lagna bhava", "dhana? bhava", "sahaja?|bhratri", "sukha? bhava|bandhu|matru", "putra?",
          "ripu|shatru|ari bhava|roga bhava", "kalatra|yuvati|jaya bhava", "ayur? bhava|randhra?|mrityu",
          "dharma? bhava|bhagya", "karma? bhava", "labha?", "vyaya?"]
_YOGAS = ["raja", "dhana", "gajakesari", "kemadruma", "sunapha", "anapha", "durudhara", "vesi", "vosi",
          "ubhayachari", "adhi", "amala", "harsha", "sarala", "vimala", "viparita", "neecha ?bhanga",
          "parivartana", "lakshmi", "saraswati", "ruchaka", "bhadra", "hamsa", "malavya", "sas?ha",
          "pancha ?mahapurusha", "kala ?sarpa", "shakata|sakata", "chandra ?mangala", "budhaditya",
          "nabhasa", "arishta", "pravrajya|sannyasa"]
_THEMES = {
    "marriage": r"marriage|marri|spouse|wife|husband|kalatra|conjugal",
    "career": r"career|profession|occupation|employment|livelihood|business",
    "wealth": r"wealth|riches|money|financ|prosperity",
    "children": r"children|progeny|sons?\b|issue\b|putra",
    "health": r"disease|illness|health|sickness|ailment",
    "longevity": r"longevity|death|maraka|ayurdaya|span of life|balarishta",
    "education": r"education|learning|studies|vidya",
    "foreign": r"foreign|abroad|travel",
    "spirituality": r"spiritual|moksha|liberation|renunciation|ascetic",
    "litigation": r"litigation|court|lawsuit|enemies",
    "speculation": r"speculat|stock market|share market|gambling|lottery",
    "remedy": r"remed|upaya|mantra|propitiat|charity|donat|japa|fasting|worship of",
    "gemstone": r"gem|ruby|pearl|coral|emerald|sapphire|diamond|hessonite|cat'?s eye|gomed",
    "dasha": r"dasa|dasha|antardasa|antardasha|bhukti|vimshottari|vimsottari",
    "transit": r"transit|gochara|gochar",
    "divisional": r"navamsa|navamsha|varga|dasamsa|drekkana|hora chart",
    "ashtakavarga": r"ashtakavarga|ashtaka ?varga|bindu|rekha",
    "jaimini": r"chara ?karaka|atmakaraka|arudha|karakamsa|chara dasa|upapada",
    "compatibility": r"koota|kuta|porutham|matching|compatib",
    "muhurta": r"muhurta|muhurtha|auspicious time|electional",
    "prashna": r"prashna|prasna|horary|query",
    "nakshatra": r"nakshatra|naksatra|asterism|constellation",
    "aspect": r"aspect|drishti",
    "mundane": r"king(dom)?s?\b|rain|famine|war\b|eclipse",
}


def _rx(alts: str) -> re.Pattern:
    return re.compile(rf"\b(?:{alts})\b", re.IGNORECASE)


_COMPILED: list[tuple[str, re.Pattern, int]] = []
for name, alts in _PLANETS.items():
    _COMPILED.append((f"planet:{name}", _rx(alts), 2))
for name, alts in _SIGNS.items():
    _COMPILED.append((f"sign:{name}", _rx(alts), 2))
for i, (o, b) in enumerate(zip(_ORD, _BHAVA), start=1):
    _COMPILED.append((f"house:{i}", re.compile(rf"\b(?:{o}) (?:house|bhava)\b|\b(?:{b})\b", re.I), 1))
_COMPILED.append(("house:1", _rx(r"lagna|ascendant"), 2))
# Distinctive names count even without the word "yoga" ("Neecha Bhanga", "Kala Sarpa dosha");
# generic ones (raja, dhana, adhi...) need "yoga", optionally after "raja" ("Viparita Raja Yoga").
_DISTINCTIVE = {"gajakesari", "kemadruma", "sunapha", "anapha", "durudhara", "ubhayachari", "viparita",
                "neecha ?bhanga", "parivartana", "ruchaka", "malavya", "pancha ?mahapurusha", "kala ?sarpa",
                "budhaditya", "chandra ?mangala", "nabhasa", "arishta", "pravrajya|sannyasa"}
for y in _YOGAS:
    pattern = rf"\b(?:{y})\b" if y in _DISTINCTIVE else rf"\b(?:{y})(?: raja)? ?yoga"
    _COMPILED.append((f"yoga:{y.split('|')[0].replace(' ?', '').replace('?', '')}", re.compile(pattern, re.I), 1))
for name, alts in _THEMES.items():
    _COMPILED.append((name, re.compile(rf"\b(?:{alts})", re.I), 2))
for n in NAKSHATRAS:
    _COMPILED.append((f"nakshatra:{n.lower().replace(' ', '_')}", re.compile(rf"\b{n.split()[-1]}\b", re.I), 2))


def fold(text: str) -> str:
    """Strip diacritics so 'Śani', 'Sūrya' match 'sani', 'surya'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def tag_topics(text: str) -> list[str]:
    text = fold(text)
    hits: Counter = Counter()
    for tag, rx, need in _COMPILED:
        n = len(rx.findall(text))
        if n >= need:
            hits[tag] = max(hits[tag], n)
    return sorted(hits)
