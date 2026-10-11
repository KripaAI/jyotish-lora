"""Phase 2.8: chart engine tests.

Astronomical checks use widely published sidereal (Lahiri) ingress dates; each date is tested a day
or more either side of the ingress so the result does not depend on the exact minute.
"""
from datetime import date, datetime

import pytest

from src.chart.constants import DASHA_YEARS, SIGNS
from src.chart.engine import (
    _angle, assemble_chart, compute_chart, dignity, julian_day_ut, nakshatra, navamsa_sign,
    sidereal_positions,
)
from src.chart.render import render_chart_text

IST = 5.5
DELHI = (28.614, 77.209)


def sign_of(planet: str, y, m, d, h=12, tz=IST) -> str:
    lon, _ = sidereal_positions(julian_day_ut(datetime(y, m, d, h), tz))[planet]
    return SIGNS[int(lon // 30)]


# ---------- ayanamsa and well-known sidereal ingresses ----------

def test_lahiri_ayanamsa_j2000():
    chart = compute_chart(datetime(2000, 1, 1, 12), 0, *DELHI)
    assert chart["settings"]["ayanamsa_value"] == pytest.approx(23.853, abs=0.01)


@pytest.mark.parametrize("planet,before,after,sign_before,sign_after", [
    ("Sun", (2024, 1, 13), (2024, 1, 16), "Sagittarius", "Capricorn"),   # Makara Sankranti 15 Jan 2024
    ("Sun", (2024, 4, 12), (2024, 4, 15), "Pisces", "Aries"),            # Mesha Sankranti 13 Apr 2024
    ("Saturn", (2020, 1, 20), (2020, 1, 28), "Sagittarius", "Capricorn"),  # Saturn ingress 24 Jan 2020
    ("Saturn", (2023, 1, 14), (2023, 1, 20), "Capricorn", "Aquarius"),   # Saturn ingress 17 Jan 2023
    ("Jupiter", (2014, 6, 1), (2014, 7, 1), "Gemini", "Cancer"),         # Jupiter ingress 19 Jun 2014
    ("Rahu", (2023, 9, 15), (2023, 11, 30), "Aries", "Pisces"),          # Rahu ingress 30 Oct 2023
])
def test_known_ingresses(planet, before, after, sign_before, sign_after):
    assert sign_of(planet, *before) == sign_before
    assert sign_of(planet, *after) == sign_after


def test_ketu_opposite_rahu():
    pos = sidereal_positions(julian_day_ut(datetime(1985, 3, 3, 3, 3), IST))
    assert _angle(pos["Rahu"][0], pos["Ketu"][0]) == pytest.approx(180, abs=1e-6)


def test_full_moon_opposition():
    pos = sidereal_positions(julian_day_ut(datetime(2024, 10, 17, 11, 26), 0))  # full moon
    assert _angle(pos["Sun"][0], pos["Moon"][0]) > 178


@pytest.mark.parametrize("dt,place", [
    (datetime(2024, 1, 20, 7, 20), DELHI),            # sunrise in Delhi
    (datetime(2024, 6, 21, 6, 5), (19.076, 72.878)),  # sunrise in Mumbai
])
def test_lagna_at_sunrise_is_sun_sign(dt, place):
    chart = compute_chart(dt, IST, *place)
    sun = next(p for p in chart["planets"] if p["name"] == "Sun")
    assert chart["lagna"]["sign"] == sun["sign"]
    assert sun["house"] == 1


# ---------- nakshatra, navamsa, dignity ----------

@pytest.mark.parametrize("lon,name,pada,lord", [
    (0.0, "Ashwini", 1, "Ketu"), (13.34, "Bharani", 1, "Venus"), (40.01, "Rohini", 1, "Moon"),
    (359.99, "Revati", 4, "Mercury"), (120.01, "Magha", 1, "Ketu"), (126.67, "Magha", 3, "Ketu"),
])
def test_nakshatra(lon, name, pada, lord):
    assert nakshatra(lon) == (name, pada, lord)


@pytest.mark.parametrize("lon,sign", [
    (0.0, "Aries"), (3.34, "Taurus"), (30.0, "Capricorn"), (60.0, "Libra"),
    (90.0, "Cancer"), (29.99, "Sagittarius"), (359.99, "Pisces"),
])
def test_navamsa(lon, sign):
    assert SIGNS[navamsa_sign(lon)] == sign


@pytest.mark.parametrize("planet,lon,expected", [
    ("Sun", 10, "exalted"), ("Sun", 190, "debilitated"), ("Sun", 130, "moolatrikona"),
    ("Sun", 145, "own sign"), ("Moon", 33, "exalted"), ("Moon", 100, "own sign"),
    ("Jupiter", 95, "exalted"), ("Jupiter", 275, "debilitated"), ("Saturn", 285, "own sign"),
    ("Saturn", 310, "moolatrikona"), ("Mars", 70, "enemy sign"), ("Jupiter", 15, "friendly sign"),
    ("Venus", 255, "neutral sign"), ("Rahu", 40, "exalted"), ("Rahu", 100, "-"),
])
def test_dignity(planet, lon, expected):
    assert dignity(planet, lon) == expected


def test_combustion_and_retrograde_flags():
    # Mercury 5° from the Sun -> combust; Saturn with negative speed -> retrograde
    chart = make_chart({"Sun": 100, "Mercury": 105, "Saturn": 250}, asc=95, speeds={"Saturn": -0.05})
    p = {x["name"]: x for x in chart["planets"]}
    assert p["Mercury"]["combust"] and not p["Saturn"]["combust"]
    assert p["Saturn"]["retrograde"] and not p["Mercury"]["retrograde"]


# ---------- Vimshottari dasha ----------

def test_dasha_years_total_120():
    assert sum(DASHA_YEARS.values()) == 120


def test_dasha_balance_at_nakshatra_start():
    # Moon at 0° Aries (start of Ashwini) -> full 7 years of Ketu remain at birth
    chart = make_chart({"Moon": 0.0001}, asc=0, as_of=date(2000, 3, 1), birth=datetime(2000, 1, 1))
    d = chart["dasha"]
    assert d["balance_at_birth"]["lord"] == "Ketu"
    assert d["balance_at_birth"]["years"] == pytest.approx(7, abs=0.01)
    assert d["maha"]["lord"] == "Ketu" and d["antar"]["lord"] == "Ketu"
    assert d["next_mahas"][0]["lord"] == "Venus"


def test_dasha_midway():
    # Moon halfway through Rohini (Moon's nakshatra): 5 of 10 years remain; as of +6y -> Mars maha
    chart = make_chart({"Moon": 40 + 13.3333 / 2}, asc=0, as_of=date(2006, 2, 1), birth=datetime(2000, 1, 1))
    assert chart["dasha"]["balance_at_birth"]["lord"] == "Moon"
    assert chart["dasha"]["balance_at_birth"]["years"] == pytest.approx(5, abs=0.01)
    assert chart["dasha"]["maha"]["lord"] == "Mars"


# ---------- yogas: helper ----------

DEFAULT = {"Sun": 5, "Moon": 125, "Mars": 245, "Mercury": 20, "Jupiter": 185, "Venus": 335,
           "Saturn": 75, "Rahu": 160}


def make_chart(overrides: dict, asc: float, speeds: dict | None = None, as_of=date(2026, 10, 5),
               birth=datetime(1990, 1, 1)) -> dict:
    lons = {**DEFAULT, **overrides}
    pos = {p: (lon % 360, (speeds or {}).get(p, 1.0)) for p, lon in lons.items()}
    pos["Ketu"] = ((pos["Rahu"][0] + 180) % 360, pos["Rahu"][1])
    pos["Rahu"] = (pos["Rahu"][0], -0.05)
    return assemble_chart(pos, asc, birth, as_of)


def yoga_names(chart) -> set[str]:
    return {y["name"] for y in chart["yogas"]}


S = lambda sign, deg=15: SIGNS.index(sign) * 30 + deg  # sign name -> longitude

# (yoga name, chart that has it, chart that does not). Lagna is Aries unless asc is given.
YOGA_CASES = [
    ("Ruchaka Yoga", dict(o={"Mars": S("Capricorn")}), dict(o={"Mars": S("Taurus")})),
    ("Bhadra Yoga", dict(o={"Mercury": S("Gemini")}, asc=S("Virgo")), dict(o={"Mercury": S("Leo")}, asc=S("Virgo"))),
    ("Hamsa Yoga", dict(o={"Jupiter": S("Cancer")}), dict(o={"Jupiter": S("Leo")})),
    ("Malavya Yoga", dict(o={"Venus": S("Libra")}), dict(o={"Venus": S("Virgo")})),
    ("Shasha Yoga", dict(o={"Saturn": S("Capricorn")}), dict(o={"Saturn": S("Aquarius")})),
    ("Gajakesari Yoga", dict(o={"Moon": S("Taurus"), "Jupiter": S("Leo")}), dict(o={"Moon": S("Taurus"), "Jupiter": S("Gemini")})),
    ("Budhaditya Yoga", dict(o={"Sun": S("Leo", 5), "Mercury": S("Leo", 20)}), dict(o={"Sun": S("Leo"), "Mercury": S("Virgo")})),
    ("Chandra-Mangala Yoga", dict(o={"Moon": S("Aries", 2), "Mars": S("Aries", 20)}), dict(o={"Moon": S("Aries"), "Mars": S("Taurus")})),
    ("Sunapha Yoga", dict(o={"Moon": S("Leo"), "Mars": S("Virgo"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                     dict(o={"Moon": S("Leo"), "Mars": S("Aries"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Anapha Yoga", dict(o={"Moon": S("Leo"), "Mars": S("Cancer"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                    dict(o={"Moon": S("Leo"), "Mars": S("Aries"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Durudhara Yoga", dict(o={"Moon": S("Leo"), "Mars": S("Cancer"), "Mercury": S("Virgo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                       dict(o={"Moon": S("Leo"), "Mars": S("Cancer"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Kemadruma Yoga", dict(o={"Moon": S("Leo"), "Mars": S("Aries"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                       dict(o={"Moon": S("Leo"), "Mars": S("Virgo"), "Mercury": S("Aries"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Vesi Yoga", dict(o={"Sun": S("Leo"), "Mars": S("Virgo"), "Mercury": S("Leo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                  dict(o={"Sun": S("Leo"), "Mars": S("Aries"), "Mercury": S("Leo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Vosi Yoga", dict(o={"Sun": S("Leo"), "Mars": S("Cancer"), "Mercury": S("Leo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                  dict(o={"Sun": S("Leo"), "Mars": S("Aries"), "Mercury": S("Leo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Ubhayachari Yoga", dict(o={"Sun": S("Leo"), "Mars": S("Cancer"), "Mercury": S("Virgo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")}),
                         dict(o={"Sun": S("Leo"), "Mars": S("Cancer"), "Mercury": S("Leo"), "Jupiter": S("Aries"), "Venus": S("Aries"), "Saturn": S("Aries")})),
    ("Adhi Yoga", dict(o={"Moon": S("Aries"), "Mercury": S("Virgo"), "Jupiter": S("Libra"), "Venus": S("Scorpio")}),
                  dict(o={"Moon": S("Aries"), "Mercury": S("Virgo"), "Jupiter": S("Libra"), "Venus": S("Aries")})),
    ("Amala Yoga", dict(o={"Venus": S("Capricorn"), "Moon": S("Aries")}), dict(o={"Venus": S("Gemini"), "Jupiter": S("Taurus"), "Mercury": S("Taurus"), "Moon": S("Aries")})),
    # Aries lagna: 10th lord Saturn + 9th lord Jupiter conjunct -> Raja Yoga and Dharma-Karmadhipati
    ("Raja Yoga", dict(o={"Saturn": S("Gemini"), "Jupiter": S("Gemini", 20)}), dict(o={"Saturn": S("Gemini"), "Jupiter": S("Leo")}), "10th lord Saturn and 9th lord Jupiter"),
    ("Dharma-Karmadhipati Yoga", dict(o={"Saturn": S("Gemini"), "Jupiter": S("Gemini", 20)}), dict(o={"Saturn": S("Gemini"), "Jupiter": S("Leo")})),
    ("Yogakaraka", dict(o={}, asc=S("Taurus")), dict(o={}, asc=S("Aries"))),  # Saturn for Taurus lagna
    # Aries lagna: 2nd lord Venus + 5th lord Sun conjunct
    ("Dhana Yoga", dict(o={"Venus": S("Leo", 20), "Sun": S("Leo")}), dict(o={"Venus": S("Virgo"), "Sun": S("Leo")}), "2nd lord Venus and 5th lord Sun"),
    ("Harsha Yoga (Viparita Raja)", dict(o={"Mercury": S("Scorpio")}), dict(o={"Mercury": S("Gemini")})),       # 6th lord Mercury in 8th
    ("Sarala Yoga (Viparita Raja)", dict(o={"Mars": S("Pisces")}), dict(o={"Mars": S("Leo")})),                 # 8th lord Mars in 12th
    ("Vimala Yoga (Viparita Raja)", dict(o={"Jupiter": S("Virgo")}), dict(o={"Jupiter": S("Leo")})),            # 12th lord Jupiter in 6th
    # Sun debilitated in Libra; Venus (lord of Libra) in a kendra from lagna
    ("Neecha Bhanga Raja Yoga", dict(o={"Sun": S("Libra"), "Venus": S("Cancer"), "Saturn": S("Gemini")}),
                                dict(o={"Sun": S("Libra"), "Venus": S("Leo"), "Saturn": S("Gemini"), "Moon": S("Aries")})),
    ("Parivartana Yoga", dict(o={"Sun": S("Cancer"), "Moon": S("Leo")}), dict(o={"Sun": S("Cancer"), "Moon": S("Virgo")}), "Sun (in Cancer"),
    ("Lakshmi Yoga", dict(o={"Jupiter": S("Sagittarius")}), dict(o={"Jupiter": S("Gemini")})),   # 9th lord Jupiter own sign in 9th
    ("Saraswati Yoga", dict(o={"Jupiter": S("Cancer"), "Venus": S("Libra"), "Mercury": S("Leo")}),
                       dict(o={"Jupiter": S("Cancer"), "Venus": S("Libra"), "Mercury": S("Virgo")})),
    ("Guru-Chandala Yoga", dict(o={"Jupiter": S("Virgo"), "Rahu": S("Virgo", 2)}), dict(o={"Jupiter": S("Virgo"), "Rahu": S("Leo")})),
    ("Grahana Yoga", dict(o={"Sun": S("Leo"), "Rahu": S("Leo", 2)}), dict(o={"Sun": S("Taurus"), "Moon": S("Cancer"), "Rahu": S("Leo")})),
    ("Kala Sarpa Yoga", dict(o={"Rahu": 1, "Sun": 20, "Moon": 40, "Mars": 60, "Mercury": 80, "Jupiter": 100, "Venus": 120, "Saturn": 170}),
                        dict(o={"Rahu": 1, "Sun": 20, "Moon": 40, "Mars": 60, "Mercury": 80, "Jupiter": 100, "Venus": 120, "Saturn": 250})),
    ("Shakata Yoga", dict(o={"Jupiter": S("Aries"), "Moon": S("Virgo")}), dict(o={"Jupiter": S("Aries"), "Moon": S("Leo")})),
    ("Kuja Dosha", dict(o={"Mars": S("Libra")}), dict(o={"Mars": S("Leo")})),
    ("Chatussagara Yoga", dict(o={"Sun": S("Aries"), "Moon": S("Cancer"), "Mars": S("Libra"), "Saturn": S("Capricorn")}),
                          dict(o={"Sun": S("Aries"), "Moon": S("Cancer"), "Mars": S("Libra"), "Saturn": S("Leo"), "Jupiter": S("Leo"), "Venus": S("Leo"), "Mercury": S("Leo"), "Rahu": S("Leo")})),
]


@pytest.mark.parametrize("case", YOGA_CASES, ids=[c[0] for c in YOGA_CASES])
def test_yoga_positive_and_negative(case):
    name, pos, neg, detail = (*case, "")[:4]
    matches = lambda chart: [y for y in chart["yogas"] if y["name"] == name and detail in y["detail"]]
    yes = make_chart(pos["o"], asc=pos.get("asc", S("Aries")))
    no = make_chart(neg["o"], asc=neg.get("asc", S("Aries")))
    assert matches(yes), [y["name"] for y in yes["yogas"]]
    assert not matches(no), [y for y in no["yogas"] if y["name"] == name]


def test_all_33_yogas_have_tests():
    assert len({c[0] for c in YOGA_CASES}) == 34  # 33 yogas + Yogakaraka marker


def test_render_contains_core_sections():
    text = render_chart_text(compute_chart(datetime(1990, 5, 18, 2, 36), IST, 19.998, 73.79, date(2026, 10, 5)))
    for part in ("Lagna:", "Planets:", "Houses", "Aspects", "Yogas detected:", "Navamsa (D9)", "Vimshottari dasha"):
        assert part in text
