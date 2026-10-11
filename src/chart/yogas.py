"""Rule-based yoga detection (33 yogas).

Rules follow the most common Parashari formulations. Where classical texts differ, the simpler
widely-used variant is implemented and noted in the docstring of the rule.
"""
from __future__ import annotations

from itertools import combinations

from src.chart.constants import (
    DEBILITATION, DUSTHANAS, EXALTATION, FRIENDS, KENDRAS, OWN_SIGNS, SEVEN, SIGN_LORD, SIGNS,
    TRIKONAS, ordinal,
)


class _C:
    """Small query helper over the chart dict."""

    def __init__(self, chart: dict):
        self.chart = chart
        self.p = {pl["name"]: pl for pl in chart["planets"]}
        self.lagna_sign = SIGNS.index(chart["lagna"]["sign"])

    def house(self, planet: str) -> int:
        return self.p[planet]["house"]

    def sign(self, planet: str) -> int:
        return SIGNS.index(self.p[planet]["sign"])

    def lord(self, house: int) -> str:
        return SIGN_LORD[(self.lagna_sign + house - 1) % 12]

    def from_(self, planet: str, ref: str) -> int:
        """House position of `planet` counted from `ref`'s sign (ref = 1)."""
        return (self.sign(planet) - self.sign(ref)) % 12 + 1

    def conj(self, a: str, b: str) -> bool:
        return self.sign(a) == self.sign(b)

    def aspects(self, a: str, b: str) -> bool:
        return self.house(b) in self.p[a]["aspects_houses"]

    def exchange(self, a: str, b: str) -> bool:
        return SIGN_LORD[self.sign(a)] == b and SIGN_LORD[self.sign(b)] == a

    def related(self, a: str, b: str) -> str | None:
        """Parashari sambandha between two planets: conjunction, mutual aspect or exchange."""
        if a == b:
            return None
        if self.conj(a, b):
            return "conjunction"
        if self.aspects(a, b) and self.aspects(b, a):
            return "mutual aspect"
        if self.exchange(a, b):
            return "exchange"
        return None

    def strong_sign(self, planet: str) -> bool:
        return self.p[planet]["dignity"] in ("exalted", "own sign", "moolatrikona")


def detect_yogas(chart: dict) -> list[dict]:
    c = _C(chart)
    found: list[dict] = []
    add = lambda name, detail: found.append({"name": name, "detail": detail})

    # 1-5 Pancha Mahapurusha: planet in own/exalted sign in a kendra from lagna
    for planet, name in [("Mars", "Ruchaka"), ("Mercury", "Bhadra"), ("Jupiter", "Hamsa"),
                         ("Venus", "Malavya"), ("Saturn", "Shasha")]:
        if c.house(planet) in KENDRAS and c.strong_sign(planet):
            add(f"{name} Yoga", f"{planet} {c.p[planet]['dignity']} in the {ordinal(c.house(planet))} house (Pancha Mahapurusha)")

    # 6 Gajakesari: Jupiter in a kendra from the Moon
    if c.from_("Jupiter", "Moon") in KENDRAS:
        add("Gajakesari Yoga", f"Jupiter in the {ordinal(c.from_('Jupiter', 'Moon'))} from the Moon")
    # 7 Budhaditya, 8 Chandra-Mangala
    if c.conj("Sun", "Mercury"):
        add("Budhaditya Yoga", f"Sun and Mercury together in {c.p['Sun']['sign']}")
    if c.conj("Moon", "Mars"):
        add("Chandra-Mangala Yoga", f"Moon and Mars together in {c.p['Moon']['sign']}")

    # 9-12 Lunar yogas (planets other than Sun, Rahu, Ketu around the Moon)
    lunar = [p for p in SEVEN if p not in ("Sun", "Moon")]
    second = [p for p in lunar if c.from_(p, "Moon") == 2]
    twelfth = [p for p in lunar if c.from_(p, "Moon") == 12]
    with_moon = [p for p in lunar if c.from_(p, "Moon") == 1]
    if second and twelfth:
        add("Durudhara Yoga", f"{', '.join(second)} in the 2nd and {', '.join(twelfth)} in the 12th from the Moon")
    elif second:
        add("Sunapha Yoga", f"{', '.join(second)} in the 2nd from the Moon")
    elif twelfth:
        add("Anapha Yoga", f"{', '.join(twelfth)} in the 12th from the Moon")
    elif not with_moon:
        # Common cancellation: a planet in a kendra from the lagna
        cancelled = any(c.house(p) in KENDRAS for p in lunar)
        add("Kemadruma Yoga", "no planet in the 2nd, 12th or with the Moon"
            + (" (cancelled: a planet occupies a kendra from the lagna)" if cancelled else ""))

    # 13-15 Solar yogas (planets other than Moon, Rahu, Ketu around the Sun)
    solar = [p for p in SEVEN if p not in ("Sun", "Moon")]
    s2 = [p for p in solar if c.from_(p, "Sun") == 2]
    s12 = [p for p in solar if c.from_(p, "Sun") == 12]
    if s2 and s12:
        add("Ubhayachari Yoga", f"{', '.join(s2)} in the 2nd and {', '.join(s12)} in the 12th from the Sun")
    elif s2:
        add("Vesi Yoga", f"{', '.join(s2)} in the 2nd from the Sun")
    elif s12:
        add("Vosi Yoga", f"{', '.join(s12)} in the 12th from the Sun")

    # 16 Adhi Yoga: Mercury, Jupiter and Venus all in the 6th/7th/8th from the Moon
    if all(c.from_(p, "Moon") in (6, 7, 8) for p in ("Mercury", "Jupiter", "Venus")):
        add("Adhi Yoga", "Mercury, Jupiter and Venus occupy the 6th, 7th and 8th from the Moon")
    # 17 Amala Yoga: a natural benefic in the 10th from lagna or Moon
    amala = [p for p in ("Jupiter", "Venus", "Mercury") if c.house(p) == 10 or c.from_(p, "Moon") == 10]
    if amala:
        add("Amala Yoga", f"{', '.join(amala)} in the 10th from the lagna or Moon")

    # 18 Raja Yoga: kendra lord related to trikona lord
    seen = set()
    for k in KENDRAS:
        for t in TRIKONAS:
            a, b = c.lord(k), c.lord(t)
            rel = c.related(a, b)
            if rel and frozenset((a, b)) not in seen:
                seen.add(frozenset((a, b)))
                add("Raja Yoga", f"{ordinal(k)} lord {a} and {ordinal(t)} lord {b} by {rel}")
    # Yogakaraka: one planet ruling both a kendra (4/7/10) and a trikona (5/9)
    for planet in SEVEN:
        ruled = [h for h in range(1, 13) if c.lord(h) == planet]
        if any(h in (4, 7, 10) for h in ruled) and any(h in (5, 9) for h in ruled):
            add("Yogakaraka", f"{planet} rules houses {' and '.join(map(str, ruled))}")
    # 19 Dharma-Karmadhipati
    rel = c.related(c.lord(9), c.lord(10))
    if rel:
        add("Dharma-Karmadhipati Yoga", f"9th lord {c.lord(9)} and 10th lord {c.lord(10)} by {rel}")
    # 20 Dhana Yoga: lords of 2/11 related to lords of 1/5/9
    for w in (2, 11):
        for t in (1, 5, 9):
            rel = c.related(c.lord(w), c.lord(t))
            if rel:
                add("Dhana Yoga", f"{ordinal(w)} lord {c.lord(w)} and {ordinal(t)} lord {c.lord(t)} by {rel}")

    # 21-23 Viparita Raja Yogas: dusthana lords in dusthanas
    for h, name in ((6, "Harsha"), (8, "Sarala"), (12, "Vimala")):
        lord = c.lord(h)
        if c.house(lord) in DUSTHANAS:
            add(f"{name} Yoga (Viparita Raja)", f"{ordinal(h)} lord {lord} in the {ordinal(c.house(lord))} house")

    # 24 Neecha Bhanga: debilitated planet whose debilitation-sign lord or the planet exalted
    #    in that sign is in a kendra from the lagna or the Moon
    for planet in SEVEN:
        if c.p[planet]["dignity"] != "debilitated":
            continue
        deb_sign = DEBILITATION[planet]
        helpers = {SIGN_LORD[deb_sign]} | {q for q, s in EXALTATION.items() if s == deb_sign and q in SEVEN}
        for hlp in sorted(helpers - {planet}):
            if c.house(hlp) in KENDRAS or c.from_(hlp, "Moon") in KENDRAS:
                add("Neecha Bhanga Raja Yoga", f"debilitated {planet}; {hlp} is in a kendra from the lagna or Moon")
                break

    # 25 Parivartana (sign exchange)
    for a, b in combinations(SEVEN, 2):
        if c.exchange(a, b):
            add("Parivartana Yoga", f"{a} (in {c.p[a]['sign']}, house {c.house(a)}) and {b} (in {c.p[b]['sign']}, house {c.house(b)}) exchange signs")

    # 26 Lakshmi Yoga (simplified): 9th lord in own/exalted sign in a kendra or trikona
    l9 = c.lord(9)
    if c.strong_sign(l9) and c.house(l9) in set(KENDRAS + TRIKONAS):
        add("Lakshmi Yoga", f"9th lord {l9} {c.p[l9]['dignity']} in the {ordinal(c.house(l9))} house")
    # 27 Saraswati Yoga (simplified): Jupiter, Venus, Mercury in kendras/trikonas/2nd; Jupiter well placed
    good = {1, 2, 4, 5, 7, 9, 10}
    jup_ok = c.strong_sign("Jupiter") or SIGN_LORD[c.sign("Jupiter")] in FRIENDS["Jupiter"]
    if all(c.house(p) in good for p in ("Jupiter", "Venus", "Mercury")) and jup_ok:
        add("Saraswati Yoga", "Jupiter, Venus and Mercury in kendras, trikonas or the 2nd, with Jupiter well placed")

    # 28 Guru-Chandala, 29 Grahana
    if c.conj("Jupiter", "Rahu"):
        add("Guru-Chandala Yoga", f"Jupiter with Rahu in {c.p['Jupiter']['sign']}")
    for lum in ("Sun", "Moon"):
        for node in ("Rahu", "Ketu"):
            if c.conj(lum, node):
                add("Grahana Yoga", f"{lum} with {node} in {c.p[lum]['sign']}")
    # 30 Kala Sarpa: all seven planets on one side of the Rahu-Ketu axis
    rahu = c.p["Rahu"]["longitude"]
    rel_pos = [((c.p[p]["longitude"] - rahu) % 360) for p in SEVEN]
    if all(x < 180 for x in rel_pos) or all(x > 180 for x in rel_pos):
        add("Kala Sarpa Yoga", "all seven planets lie on one side of the Rahu-Ketu axis")
    # 31 Shakata: Moon in the 6th, 8th or 12th from Jupiter
    if c.from_("Moon", "Jupiter") in (6, 8, 12):
        add("Shakata Yoga", f"Moon in the {ordinal(c.from_('Moon', 'Jupiter'))} from Jupiter")
    # 32 Kuja Dosha (from lagna)
    if c.house("Mars") in (1, 2, 4, 7, 8, 12):
        add("Kuja Dosha", f"Mars in the {ordinal(c.house('Mars'))} house from the lagna")
    # 33 Chatussagara: all four kendras occupied
    if all(any(pl["house"] == k for pl in chart["planets"]) for k in KENDRAS):
        add("Chatussagara Yoga", "all four kendras are occupied")

    return found
