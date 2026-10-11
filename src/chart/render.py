"""render_chart_text: the ONE function that turns chart JSON into prompt text.

It is used both when generating training data and when serving, so the model always sees the
same format (Tech Spec 5.3). Change it only together with a new dataset version.
v2 (2026-10-08): nakshatra lords added, so readings take them from the chart instead of memory.
v3 (2026-10-09): counted facts added (`derived=True`): the twelve houses counted from the Moon with their occupants, and each
planet's house in the navamsa counted from the D9 lagna. The v2-8b model miscounted exactly these when asked, so the engine
now states them; a model served with v3 text must have been trained on v3 text (Pipeline(render_version=3)).
"""
from __future__ import annotations

from datetime import date

from src.chart.constants import NAKSHATRA_LORD, NAKSHATRAS, SIGNS, ordinal


def _dms(deg: float) -> str:
    d = int(deg)
    m = int(round((deg - d) * 60))
    if m == 60:
        d, m = d + 1, 0
    return f"{d}°{m:02d}'"


def houses_from(chart: dict, planet: str) -> list[dict]:
    """The twelve houses counted from a planet's sign: [{house, sign, occupants}], house 1 = the planet's own sign."""
    start = SIGNS.index(next(p for p in chart["planets"] if p["name"] == planet)["sign"])
    out = []
    for k in range(12):
        sign = SIGNS[(start + k) % 12]
        out.append({"house": k + 1, "sign": sign, "occupants": [p["name"] for p in chart["planets"] if p["sign"] == sign]})
    return out


def navamsa_house(chart: dict, planet: str) -> int:
    """A planet's house in the navamsa, counted from the D9 lagna."""
    p = next(p for p in chart["planets"] if p["name"] == planet)
    return (SIGNS.index(p["navamsa_sign"]) - SIGNS.index(chart["navamsa_lagna"])) % 12 + 1


def render_chart_text(chart: dict, derived: bool = False) -> str:
    lg = chart["lagna"]
    lagna_lord = next(p for p in chart["planets"] if p["name"] == lg["lord"])
    birth_year = int(chart["birth"]["local_datetime"][:4])
    as_of = date.fromisoformat(chart["dasha"]["as_of"])
    lines = [
        "Birth chart (sidereal zodiac, Lahiri ayanamsa, whole-sign houses)",
        f"Born: {birth_year} (age {as_of.year - birth_year} as of {as_of.isoformat()})",
        f"Lagna: {lg['sign']} {_dms(lg['degree'])} ({lg['nakshatra']} pada {lg['pada']}, "
        f"nakshatra lord {NAKSHATRA_LORD[NAKSHATRAS.index(lg['nakshatra'])]}); "
        f"lagna lord {lg['lord']} in the {ordinal(lagna_lord['house'])} house",
        "",
        "Planets:",
    ]
    for p in chart["planets"]:
        flags = []
        if p["dignity"] != "-":
            flags.append(p["dignity"])
        if p["retrograde"] and p["name"] not in ("Rahu", "Ketu"):
            flags.append("retrograde")
        if p["combust"]:
            flags.append("combust")
        extra = f", {', '.join(flags)}" if flags else ""
        lines.append(f"- {p['name']}: {p['sign']} {_dms(p['degree'])}, {ordinal(p['house'])} house, "
                     f"{p['nakshatra']} pada {p['pada']} (nakshatra lord {p['nakshatra_lord']}){extra}")
    lines += ["", "Houses (sign, lord -> where the lord sits, occupants):"]
    for h in chart["houses"]:
        occ = ", ".join(h["occupants"]) or "empty"
        lines.append(f"- {ordinal(h['house'])}: {h['sign']}, lord {h['lord']} -> {ordinal(h['lord_in_house'])}; {occ}")
    lines += ["", "Aspects (graha drishti on houses):"]
    for p in chart["planets"]:
        if p["name"] in ("Rahu", "Ketu"):
            continue
        lines.append(f"- {p['name']} aspects the " + ", ".join(ordinal(h) for h in p["aspects_houses"]))
    lines += ["", "Yogas detected:"]
    lines += [f"- {y['name']}: {y['detail']}" for y in chart["yogas"]] or ["- none of the tracked yogas"]
    if derived:
        moon = houses_from(chart, "Moon")
        parts = [f"{ordinal(h['house'])} {h['sign']}" + (f" ({', '.join(h['occupants'])})" if h["occupants"] else "") for h in moon]
        lines += ["", f"Counted from the Moon (Chandra lagna, Moon in {moon[0]['sign']}): " + ", ".join(parts)]
        nav = "; ".join(f"{p['name']} {p['navamsa_sign']} {ordinal(navamsa_house(chart, p['name']))}" for p in chart["planets"])
        lines += ["", f"Navamsa (D9): lagna {chart['navamsa_lagna']}; planets with their D9 house counted from it: {nav}"]
    else:
        nav = "; ".join(f"{p['name']} {p['navamsa_sign']}" for p in chart["planets"])
        lines += ["", f"Navamsa (D9): lagna {chart['navamsa_lagna']}; {nav}"]
    d = chart["dasha"]
    nxt = ", then ".join(f"{m['lord']} from {m['start']}" for m in d["next_mahas"])
    lines += ["", f"Vimshottari dasha (as of {d['as_of']}): {d['maha']['lord']} mahadasha "
              f"({d['maha']['start']} to {d['maha']['end']}), {d['antar']['lord']} antardasha "
              f"({d['antar']['start']} to {d['antar']['end']}). Next: {nxt}."]
    return "\n".join(lines)
