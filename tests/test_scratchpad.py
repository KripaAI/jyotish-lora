"""The code-written working only states facts that are in the chart, and picks the ones the answer mentions."""
from datetime import date, datetime

from src.chart.constants import ordinal
from src.chart.engine import compute_chart
from src.chart.render import houses_from, navamsa_house
from src.dataset.filters import chart_contradictions, citation_issue, word_count
from src.dataset.scratchpad import working

CHART = compute_chart(datetime(1990, 5, 18, 2, 36), 5.5, 19.998, 73.79, date(2026, 10, 5))


def _p(name):
    return next(p for p in CHART["planets"] if p["name"] == name)


def test_mentioned_planets_houses_and_dasha_are_included():
    sat, h7 = _p("Saturn"), next(h for h in CHART["houses"] if h["house"] == 7)
    answer = "Saturn in your chart shapes marriage, and the 7th house matters here. Your Jupiter antardasha brings patience."
    w = working(CHART, answer)
    assert f"Saturn is in {sat['sign']} in the {ordinal(sat['house'])} house" in w
    assert f"The 7th house is {h7['sign']}, its lord {h7['lord']} is in the {ordinal(h7['lord_in_house'])}" in w
    assert CHART["dasha"]["maha"]["lord"] + " mahadasha" in w
    assert "The lagna is " + CHART["lagna"]["sign"] in w


def test_counts_from_the_moon_and_navamsa_come_from_the_engine():
    tenth = houses_from(CHART, "Moon")[9]
    w = working(CHART, "The 10th from the Moon shows the career, and the navamsa confirms it for Venus.")
    assert f"Counted from the Moon, the 10th is {tenth['sign']}" in w
    assert f"Venus is in {_p('Venus')['navamsa_sign']}, the {ordinal(navamsa_house(CHART, 'Venus'))} from the D9 lagna" in w


def test_working_never_contradicts_the_chart_and_has_no_citations():
    answers = ["Mars in the 10th house and Saturn in the 7th: the 4th lord matters, as does the 12th from the Moon in your Rahu dasha.",
               "Jupiter, Venus, Mercury, Sun, Mars, Saturn, Rahu and Ketu all matter here, in the 1st, 2nd, 5th, 9th and 11th houses.",
               "A plain concept answer that mentions nothing."]
    for a in answers:
        w = working(CHART, a)
        hard, _ = chart_contradictions(w, CHART)
        assert hard == [], (a, hard)
        assert not citation_issue(w)
        assert 25 <= word_count(w) <= 330, word_count(w)


def test_question_mentions_count_too():
    w = working(CHART, "A short answer.", question="What does the 9th from the Moon say about my father?")
    assert "Counted from the Moon, the 9th is" in w
