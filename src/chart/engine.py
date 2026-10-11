"""Phase 2: deterministic sidereal chart engine (Swiss Ephemeris, Lahiri ayanamsa, whole-sign houses).

The LLM never computes any of this (Constitution II); it only interprets the output.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import swisseph as swe

from src.chart.constants import (
    COMBUST_ORB, COMBUST_ORB_RETRO, DASHA_ORDER, DASHA_YEARS, DEBILITATION, DEFAULT_ASPECTS,
    ENEMIES, EXALTATION, FRIENDS, MOOLATRIKONA, NAK_SPAN, NAKSHATRA_LORD, NAKSHATRAS, OWN_SIGNS,
    PLANETS, SIGN_LORD, SIGNS, SPECIAL_ASPECTS,
)

YEAR_DAYS = 365.25
_SWE_IDS = {"Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY,
            "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE}
# Moshier ephemeris is built in (no data files) and accurate to about an arc-second for these bodies.
_FLAGS = swe.FLG_MOSEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)


def julian_day_ut(dt_local: datetime, tz_offset_hours: float) -> float:
    ut = dt_local - timedelta(hours=tz_offset_hours)
    return swe.julday(ut.year, ut.month, ut.day, ut.hour + ut.minute / 60 + ut.second / 3600)


def sidereal_positions(jd_ut: float) -> dict[str, tuple[float, float]]:
    """{planet: (sidereal longitude, speed in deg/day)}; Ketu = Rahu + 180."""
    out = {}
    for name, pid in _SWE_IDS.items():
        xx, _ = swe.calc_ut(jd_ut, pid, _FLAGS)
        out[name] = (xx[0] % 360, xx[3])
    out["Ketu"] = ((out["Rahu"][0] + 180) % 360, out["Rahu"][1])
    return out


def ascendant(jd_ut: float, lat: float, lon: float) -> float:
    _, ascmc = swe.houses_ex(jd_ut, lat, lon, b"W", swe.FLG_SIDEREAL)
    return ascmc[0] % 360


def nakshatra(lon: float) -> tuple[str, int, str]:
    idx = int(lon // NAK_SPAN)
    pada = int((lon % NAK_SPAN) // (NAK_SPAN / 4)) + 1
    return NAKSHATRAS[idx], pada, NAKSHATRA_LORD[idx]


def navamsa_sign(lon: float) -> int:
    # Continuous rule: equivalent to movable/fixed/dual starting from the 1st/9th/5th sign.
    return int(lon * 9 // 30) % 12


def dignity(planet: str, lon: float) -> str:
    sign, deg = int(lon // 30), lon % 30
    if EXALTATION.get(planet) == sign:
        return "exalted"
    if DEBILITATION.get(planet) == sign:
        return "debilitated"
    if planet in MOOLATRIKONA:
        mt_sign, a, b = MOOLATRIKONA[planet]
        if sign == mt_sign and a <= deg < b:
            return "moolatrikona"
    if sign in OWN_SIGNS.get(planet, []):
        return "own sign"
    if planet in FRIENDS:
        lord = SIGN_LORD[sign]
        if lord in FRIENDS[planet]:
            return "friendly sign"
        if lord in ENEMIES[planet]:
            return "enemy sign"
        return "neutral sign"
    return "-"  # Rahu/Ketu outside exaltation/debilitation


def _angle(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def vimshottari(moon_lon: float, birth: datetime, as_of: date) -> dict:
    idx = int(moon_lon // NAK_SPAN)
    elapsed = (moon_lon % NAK_SPAN) / NAK_SPAN
    first = NAKSHATRA_LORD[idx]
    start = birth - timedelta(days=elapsed * DASHA_YEARS[first] * YEAR_DAYS)
    order = DASHA_ORDER[DASHA_ORDER.index(first):] + DASHA_ORDER[:DASHA_ORDER.index(first)]

    mahas = []
    t = start
    for cycle in range(2):  # 240 years covers any lifetime
        for lord in order:
            end = t + timedelta(days=DASHA_YEARS[lord] * YEAR_DAYS)
            mahas.append((lord, t, end))
            t = end
    as_of_dt = datetime(as_of.year, as_of.month, as_of.day)
    i = next(k for k, (_, s, e) in enumerate(mahas) if s <= as_of_dt < e)
    maha, m_start, m_end = mahas[i]

    a_order = DASHA_ORDER[DASHA_ORDER.index(maha):] + DASHA_ORDER[:DASHA_ORDER.index(maha)]
    t = m_start
    antar = None
    for lord in a_order:
        end = t + timedelta(days=DASHA_YEARS[maha] * DASHA_YEARS[lord] / 120 * YEAR_DAYS)
        if t <= as_of_dt < end:
            antar = (lord, t, end)
        t = end
    fmt = lambda d: d.strftime("%Y-%m-%d")
    return {
        "system": "Vimshottari",
        "as_of": as_of.isoformat(),
        "balance_at_birth": {"lord": first, "years": round((1 - elapsed) * DASHA_YEARS[first], 2)},
        "maha": {"lord": maha, "start": fmt(m_start), "end": fmt(m_end)},
        "antar": {"lord": antar[0], "start": fmt(antar[1]), "end": fmt(antar[2])},
        "next_mahas": [{"lord": l, "start": fmt(s), "end": fmt(e)} for l, s, e in mahas[i + 1 : i + 3]],
    }


def compute_chart(dt_local: datetime, tz_offset: float, lat: float, lon: float,
                  as_of: date | None = None) -> dict:
    jd = julian_day_ut(dt_local, tz_offset)
    chart = assemble_chart(sidereal_positions(jd), ascendant(jd, lat, lon), dt_local, as_of)
    chart["birth"].update({"tz_offset": tz_offset, "lat": lat, "lon": lon})
    chart["settings"]["ayanamsa_value"] = round(swe.get_ayanamsa_ut(jd), 4)
    return chart


def assemble_chart(pos: dict[str, tuple[float, float]], asc: float, dt_local: datetime,
                   as_of: date | None = None) -> dict:
    """Build the chart dict from sidereal positions {planet: (longitude, speed)} and the ascendant.

    Split out from compute_chart so tests can construct charts with chosen placements.
    """
    as_of = as_of or date.today()
    lagna_sign = int(asc // 30)

    def house_of(lon_: float) -> int:
        return (int(lon_ // 30) - lagna_sign) % 12 + 1

    sun_lon = pos["Sun"][0]
    planets = []
    for p in PLANETS:
        plon, speed = pos[p]
        nak, pada, nak_lord = nakshatra(plon)
        retro = p in ("Rahu", "Ketu") or speed < 0
        combust = False
        if p in COMBUST_ORB:
            orb = COMBUST_ORB_RETRO.get(p, COMBUST_ORB[p]) if speed < 0 else COMBUST_ORB[p]
            combust = _angle(plon, sun_lon) < orb
        house = house_of(plon)
        aspects = SPECIAL_ASPECTS.get(p, DEFAULT_ASPECTS)
        planets.append({
            "name": p, "longitude": round(plon, 4), "sign": SIGNS[int(plon // 30)],
            "degree": round(plon % 30, 2), "house": house, "nakshatra": nak, "pada": pada,
            "nakshatra_lord": nak_lord, "dignity": dignity(p, plon),
            "retrograde": retro, "combust": combust,
            "aspects_houses": sorted(((house - 1 + a - 1) % 12) + 1 for a in aspects),
            "navamsa_sign": SIGNS[navamsa_sign(plon)],
        })

    by_name = {p["name"]: p for p in planets}
    houses = []
    for h in range(1, 13):
        sign = (lagna_sign + h - 1) % 12
        lord = SIGN_LORD[sign]
        houses.append({
            "house": h, "sign": SIGNS[sign], "lord": lord, "lord_in_house": by_name[lord]["house"],
            "occupants": [p["name"] for p in planets if p["house"] == h],
            "aspected_by": [p["name"] for p in planets if h in p["aspects_houses"]],
        })

    nak, pada, _ = nakshatra(asc)
    chart = {
        "birth": {"local_datetime": dt_local.isoformat(timespec="minutes")},
        "settings": {"zodiac": "sidereal", "ayanamsa": "Lahiri", "houses": "whole sign", "node": "mean"},
        "lagna": {"sign": SIGNS[lagna_sign], "degree": round(asc % 30, 2), "longitude": round(asc, 4),
                  "nakshatra": nak, "pada": pada, "lord": SIGN_LORD[lagna_sign]},
        "planets": planets,
        "houses": houses,
        "navamsa_lagna": SIGNS[navamsa_sign(asc)],
        "dasha": vimshottari(pos["Moon"][0], dt_local, as_of),
    }
    from src.chart.yogas import detect_yogas  # local import: yogas depend on the chart dict
    chart["yogas"] = detect_yogas(chart)
    return chart
