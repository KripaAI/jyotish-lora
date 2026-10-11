"""v3: a code-written reasoning block ("working") for chart-based training examples.

Claude's safeguards decline to write reasoning traces for training another model, so the engine writes them. The working is
not free reasoning: it is the set of chart facts the final answer relies on, copied from the chart dict, so every statement
is correct by construction. The model learns to collect the relevant facts before it writes, which is where its counting
errors happened (houses from the Moon, navamsa houses).

working(chart, answer, question) -> str   (plain prose, 60-330 words)
"""
from __future__ import annotations

import re

from src.chart.constants import PLANETS, SIGNS, ordinal
from src.chart.render import houses_from, navamsa_house

_ORD = r"(1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|11th|12th|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)"
_WORD_NUM = {w: i + 1 for i, w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
                                               "ninth", "tenth", "eleventh", "twelfth"])}
_PLANET_RE = re.compile(r"\b(" + "|".join(PLANETS) + r")\b")
_HOUSE_RE = re.compile(r"\b" + _ORD + r"\b(?=\s+(?:house|bhava|lord))", re.I)
_FROM_MOON_RE = re.compile(r"\b" + _ORD + r"\b\s+(?:house\s+)?from\s+(?:the\s+|your\s+)?Moon\b", re.I)
_DASHA_RE = re.compile(r"\b(dasha|dasa|mahadasha|antardasha|bhukti|period)\b", re.I)
_NAV_RE = re.compile(r"\b(navamsa|navamsha|D-?9)\b", re.I)
MAX_PLANETS, MAX_HOUSES = 4, 3      # the T4 ran out of memory at 3,473 tokens: keep the working under ~300 tokens


def _num(tok: str) -> int:
    t = tok.lower()
    return _WORD_NUM[t] if t in _WORD_NUM else int(re.match(r"\d+", t).group(0))


def _mentions(text: str):
    planets = []
    for m in _PLANET_RE.finditer(text):
        if m.group(1) not in planets:
            planets.append(m.group(1))
    houses = []
    for m in _HOUSE_RE.finditer(text):
        n = _num(m.group(1))
        if 1 <= n <= 12 and n not in houses:
            houses.append(n)
    from_moon = []
    for m in _FROM_MOON_RE.finditer(text):
        n = _num(m.group(1))
        if n not in from_moon:
            from_moon.append(n)
    return planets, houses, from_moon, bool(_DASHA_RE.search(text)), bool(_NAV_RE.search(text))


def _planet_line(p: dict) -> str:
    flags = [f for f, on in ((p["dignity"], p["dignity"] != "-"), ("retrograde", p["retrograde"] and p["name"] not in ("Rahu", "Ketu")),
                             ("combust", p["combust"])) if on]
    extra = f", {', '.join(flags)}" if flags else ""
    return f"{p['name']} is in {p['sign']} in the {ordinal(p['house'])} house{extra}"


def working(chart: dict, answer: str, question: str = "") -> str:
    planets, houses, from_moon, dasha, nav = _mentions(answer)
    q_planets, q_houses, q_from_moon, q_dasha, q_nav = _mentions(question)
    for p in q_planets:
        if p not in planets:
            planets.append(p)
    for h in q_houses:
        if h not in houses:
            houses.append(h)
    for h in q_from_moon:
        if h not in from_moon:
            from_moon.append(h)
    dasha, nav = dasha or q_dasha, nav or q_nav
    by_name = {p["name"]: p for p in chart["planets"]}
    by_house = {h["house"]: h for h in chart["houses"]}
    lg = chart["lagna"]

    s = [f"The lagna is {lg['sign']}, and its lord {lg['lord']} sits in the {ordinal(by_name[lg['lord']]['house'])} house."]
    moon = by_name["Moon"]
    s.append(f"The Moon is in {moon['sign']} in the {ordinal(moon['house'])} house.")
    for name in planets[:MAX_PLANETS]:
        if name not in ("Moon",) and name in by_name:
            s.append(_planet_line(by_name[name]) + ".")
    for n in houses[:MAX_HOUSES]:
        h = by_house[n]
        occ = ", ".join(h["occupants"]) or "no planet"
        s.append(f"The {ordinal(n)} house is {h['sign']}, its lord {h['lord']} is in the {ordinal(h['lord_in_house'])}, "
                 f"and it holds {occ}.")
    if from_moon:
        rows = houses_from(chart, "Moon")
        for n in from_moon[:3]:
            r = rows[n - 1]
            occ = ", ".join(r["occupants"]) or "no planet"
            s.append(f"Counted from the Moon, the {ordinal(n)} is {r['sign']}, holding {occ}.")
    if nav:
        names = [p for p in planets[:3] if p in by_name] or ["Moon"]
        s.append(f"In the navamsa the lagna is {chart['navamsa_lagna']}; " + "; ".join(
            f"{p} is in {by_name[p]['navamsa_sign']}, the {ordinal(navamsa_house(chart, p))} from the D9 lagna" for p in names) + ".")
    ynames = [y["name"] for y in chart["yogas"] if y["name"].split()[0].lower() in answer.lower()]
    for y in chart["yogas"]:
        if y["name"] in ynames[:2]:
            s.append(f"The chart shows {y['name']}: {y['detail']}.")
    if dasha:
        d = chart["dasha"]
        s.append(f"The running period is {d['maha']['lord']} mahadasha ({d['maha']['start']} to {d['maha']['end']}) with "
                 f"{d['antar']['lord']} antardasha ({d['antar']['start']} to {d['antar']['end']}).")
    s.append("These are the facts the reading rests on; the result describes tendencies, not certainties.")
    return " ".join(s)
