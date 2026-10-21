"""v4 data streams: facts are right by construction, drills quote the chart, the rule Q&A checker rejects invention."""
import random
import re

from src.chart.births import chart_for_seed
from src.chart.constants import DEBILITATION, EXALTATION, NAKSHATRA_LORD, NAKSHATRAS, SIGNS, ordinal
from src.chart.render import houses_from
from src.dataset import facts_v4, drills
from src.dataset.facts import PANCHA
from src.dataset.rule_qa import check_pair, entities
from src.dataset.rules import normalise_title

FACTS = facts_v4.build()


def test_facts_v4_volume_and_no_citations():
    assert len(FACTS) > 600
    assert not any(re.search(r"\b(chapter|verse|sloka|shloka)\s*\d", a, re.I) for _, _, a in FACTS)


def test_pancha_mahapurusha_answers_name_the_right_planet():
    for planet, yoga in PANCHA.items():
        rows = [a for c, q, a in FACTS if c == "pancha_mahapurusha" and yoga in q]
        assert rows and all(f"{yoga} yoga is formed by" in a and planet in a.split(":")[0] for a in rows)


def test_dignity_contrast_answers_are_consistent_with_tables():
    for c, q, a in FACTS:
        if c != "dignity_contrast":
            continue
        planet = next(p for p in EXALTATION if p in q)
        assert a.startswith("No")
        assert SIGNS[DEBILITATION[planet]] in a and SIGNS[EXALTATION[planet]] in a


def test_nakshatra_hinglish_rows_name_the_lord():
    for c, q, a in FACTS:
        if c == "nakshatra_lord_hi":
            n = next(x for x in sorted(NAKSHATRAS, key=len, reverse=True) if x in q)
            assert NAKSHATRA_LORD[NAKSHATRAS.index(n)] in a


def test_drills_quote_the_chart():
    for seed in (drills.DRILL_SEED_BASE, drills.DRILL_SEED_BASE + 7):
        chart = chart_for_seed(seed)
        by_name = {p["name"]: p for p in chart["planets"]}
        by_house = {h["house"]: h for h in chart["houses"]}
        rows = drills.drills_for(chart, random.Random(seed), 12)
        for kind, q, a in rows:
            if kind == "from_moon":
                planet = next(p for p in by_name if p != "Moon" and p in q)
                row = next(r for r in houses_from(chart, "Moon") if planet in r["occupants"])
                assert f"{ordinal(row['house'])} house from the Moon" in a
            if kind == "lord_placement":
                h = int(re.search(r"(\d+)(?:st|nd|rd|th)", q).group(1))
                assert by_house[h]["lord"] in a and ordinal(by_house[h]["lord_in_house"]) in a
            if kind == "dasha":
                assert chart["dasha"]["maha"]["lord"] in a and chart["dasha"]["antar"]["lord"] in a


def test_check_pair_accepts_a_faithful_paraphrase_and_rejects_invention():
    rule = {"statement": "Saturn in the 7th house delays marriage.", "conditions": "especially when Saturn is not in its own sign",
            "modifiers": "A benefic aspect from Jupiter softens the delay.", "exceptions": "", "text": "Phaladeepika", "tradition": "Parashari"}
    good = ("Phaladeepika holds that Saturn (Shani) in the 7th house tends to delay marriage, especially when Saturn is not in its own "
            "sign. A benefic aspect from Jupiter softens the delay. This is a tendency read from one placement; the lord of the 7th, "
            "the navamsa and the running dasha must be judged before any conclusion. Astrology describes tendencies, not certainties, "
            "and a delay is not a denial.")
    assert check_pair(rule, "Does Shani in the 7th delay shaadi?", good) == ""
    q = "What does Saturn in the 7th house do to marriage?"
    assert check_pair(rule, q, good.replace("Jupiter", "Venus")) == "extra_planets"
    assert check_pair(rule, q, good.replace("7th house", "7th house (chapter 12, verse 3)")) == "citation"
    assert check_pair(rule, q, "Too short.") == "length"
    assert check_pair(rule, q, good.replace("Phaladeepika", "The texts")) == "no_attribution"
    assert check_pair(rule, q, good + " It also brings Mars into the 8th house.") in ("extra_planets", "extra_houses")
    assert check_pair(rule, "Mangal 4th bhav mein ho to kya hota hai?", good) == "question_off_rule"
    hinglish_answer = "Shani 7th bhav mein ho to shaadi mein deri hoti hai, lekin Guru ki drishti se yeh kam ho jata hai. " * 6
    assert check_pair(rule, q, hinglish_answer) == "answer_not_english"


def test_check_pair_rejects_death_disease_and_stigma_rules():
    rule = {"statement": "Saturn alone in the 3rd from Lagna Pada spares the native while the co-born will die.", "conditions": "",
            "modifiers": "", "exceptions": "", "text": "Brihat Parashara Hora Sastra", "tradition": "Jaimini"}
    base = ("Brihat Parashara Hora Sastra holds that Saturn (Shani) alone in the 3rd from the Lagna Pada {x}. Jaimini authors weigh "
            "the whole chart before reading this; astrology describes tendencies, not certainties, and such statements are "
            "read symbolically today rather than as predictions about any person's life or family.")
    ok = base.format(x="shapes the native's relationship with siblings")
    assert check_pair(rule, "Saturn alone in the 3rd from Lagna Pada?", ok) == ""
    assert check_pair(rule, "Saturn alone in the 3rd from Lagna Pada?", base.format(x="means the co-born will die")) == "safety"
    assert check_pair(rule, "Saturn alone in the 3rd from Lagna Pada?", base.format(x="brings leprosy")) == "safety"
    assert check_pair(rule, "Saturn alone in the 3rd from Lagna Pada?", base.format(x="makes the wife unchaste")) == "safety"


def test_rule_qa_imports_without_the_chart_engine():
    """Kaggle kernels run the generator without pyswisseph: the import chain must not reach the chart engine."""
    import subprocess
    import sys

    code = "import sys; sys.modules['swisseph'] = None; import src.dataset.rule_qa; print('ok')"
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-800:]


def test_strip_elaboration_removes_unsupported_explanations_only():
    from src.dataset.rule_qa import strip_elaboration
    rule = {"statement": "Rahu gives favourable results in Aquarius and Pisces.", "conditions": "", "modifiers": "",
            "exceptions": "", "text": "Crux of Astrology", "tradition": "Modern Vedic"}
    ans = ("The Crux of Astrology explains that Rahu tends to give favourable results in Aquarius or Pisces. "
           "These signs are linked with intellectual expansion and transformation, which align well with Rahu's nature of illusion. "
           "The result also depends on Rahu's strength. The whole chart must be judged; astrology describes tendencies.")
    out, n = strip_elaboration(rule, ans)
    assert n == 1 and "intellectual expansion" not in out and out.startswith("The Crux of Astrology")
    assert "strength" in out and "tendencies" in out


def test_safety_block_catches_longevity_and_illness_phrasing():
    rule = {"statement": "The 8th lord in a Kendra with a weak Ascendant lord gives 30 years of life.", "conditions": "",
            "modifiers": "", "exceptions": "", "text": "Jataka Alankara", "tradition": "Classical"}
    ans = ("Jataka Alankara holds that the 8th lord in a Kendra with a weak Ascendant lord gives 30 years of life. " * 3)
    assert check_pair(rule, "What does the 8th lord in a Kendra give?", ans) == "safety"


def test_fact_rows_state_the_dasha_balance():
    rows = [a for c, q, a in FACTS if c == "nakshatra_lord_hi"]
    assert rows and all("balance remaining at birth" in a for a in rows)


def test_entities_expand_house_groups():
    e = entities("Jupiter in a kendra from the Moon")
    assert e["houses"] == {1, 4, 7, 10} and e["planets"] == {"Jupiter", "Moon"}


def test_normalise_title_maps_short_names():
    assert normalise_title("BPHS") == "Brihat Parashara Hora Sastra"
    assert normalise_title("Phaladeepika") == "Phaladeepika of Mantreswara"
    assert normalise_title("Some Unknown Book") == "Some Unknown Book"
