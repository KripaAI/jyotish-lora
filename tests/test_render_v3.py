"""v3 chart text: the counted facts are right, and the v2 text is unchanged when derived=False."""
from datetime import date, datetime

import pytest

from src.chart.constants import SIGNS
from src.chart.engine import compute_chart
from src.chart.render import houses_from, navamsa_house, render_chart_text

IST = 5.5
CHARTS = [compute_chart(datetime(1990, 5, 18, 2, 36), IST, 19.998, 73.79, date(2026, 10, 5)),
          compute_chart(datetime(1984, 11, 3, 18, 10), IST, 28.614, 77.209, date(2026, 10, 5)),
          compute_chart(datetime(2001, 2, 25, 9, 5), IST, 13.083, 80.271, date(2026, 10, 5))]


@pytest.mark.parametrize("chart", CHARTS)
def test_houses_from_the_moon_count_round_the_zodiac(chart):
    moon = next(p for p in chart["planets"] if p["name"] == "Moon")
    rows = houses_from(chart, "Moon")
    assert rows[0]["sign"] == moon["sign"] and "Moon" in rows[0]["occupants"]
    i = SIGNS.index(moon["sign"])
    for r in rows:
        assert r["sign"] == SIGNS[(i + r["house"] - 1) % 12]
        assert set(r["occupants"]) == {p["name"] for p in chart["planets"] if p["sign"] == r["sign"]}
    # the 10th from the Moon is nine signs on; the 7th is opposite
    assert rows[9]["sign"] == SIGNS[(i + 9) % 12] and rows[6]["sign"] == SIGNS[(i + 6) % 12]


@pytest.mark.parametrize("chart", CHARTS)
def test_navamsa_house_counts_from_the_d9_lagna(chart):
    lag = SIGNS.index(chart["navamsa_lagna"])
    for p in chart["planets"]:
        h = navamsa_house(chart, p["name"])
        assert 1 <= h <= 12 and SIGNS[(lag + h - 1) % 12] == p["navamsa_sign"]


def test_known_count():
    """Moon in Pisces: the 10th from the Moon is Sagittarius (the v2-8b model said Leo)."""
    chart = next((c for c in CHARTS if next(p for p in c["planets"] if p["name"] == "Moon")["sign"] == "Pisces"), None)
    if chart is None:
        pytest.skip("no sample chart with the Moon in Pisces")
    assert houses_from(chart, "Moon")[9]["sign"] == "Sagittarius"


@pytest.mark.parametrize("chart", CHARTS)
def test_v3_text_adds_only_the_derived_lines(chart):
    v2, v3 = render_chart_text(chart), render_chart_text(chart, derived=True)
    assert "Counted from the Moon" not in v2 and "from the D9 lagna" not in v2
    assert "Counted from the Moon (Chandra lagna, Moon in" in v3
    moon_line = next(l for l in v3.splitlines() if l.startswith("Counted from the Moon"))
    rows = houses_from(chart, "Moon")
    for r in rows:
        assert f"{r['house']}" in moon_line and r["sign"] in moon_line
    assert "10th " + rows[9]["sign"] in moon_line
    from src.chart.constants import ordinal
    for p in chart["planets"]:
        assert f"{p['name']} {p['navamsa_sign']} {ordinal(navamsa_house(chart, p['name']))}" in v3
    # everything else is identical
    strip = lambda t: [l for l in t.splitlines() if l and not l.startswith(("Counted from the Moon", "Navamsa (D9)"))]
    assert strip(v2) == strip(v3)
