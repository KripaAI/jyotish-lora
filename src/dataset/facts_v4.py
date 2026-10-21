"""v4: many more table-derived facts, in many more phrasings.

The v2 fact rows (facts.py) lifted the quiz from 38 to 70 on the same base model: facts stated directly, several times,
in varied wording were learned; facts that only appeared inside long answers were not. v4 applies that lesson to every
category the quiz still misses and to the wordings the robustness set showed the model cannot handle:

- Pancha Mahapurusha yogas with their planet (0-1 of 5 right in every run so far), yoga definitions, contrast questions
  ("Is Kemadruma a Pancha Mahapurusha yoga?" -> no), Vipareeta Raja yoga members.
- Dignities with wrong-sign contrast questions ("Is Mercury debilitated in Capricorn?" -> no, Pisces).
- Hinglish and Sanskrit-term phrasings (the paraphrased quiz dropped from 24/30 to 19/30, mostly on these).
- Vimshottari: first dasha at birth, cycle length; Lahiri = Chitrapaksha; varga uses; Ashtakoota points; Kuja dosha houses.

Every answer is correct by construction from src/chart/constants.py (covered by tests/test_chart_engine.py) or from
the small reference tables below. Questions too close to evalsets/quiz.jsonl are dropped, as in facts.py.

    python -m src.dataset.facts_v4        # -> data/sft_v4/facts_v4.jsonl
"""
from __future__ import annotations

import random
from collections import Counter

from src.chart.constants import (
    DASHA_ORDER, DASHA_YEARS, DEBILITATION, EXALTATION, FIXED_KARAKAS, NAKSHATRA_LORD, NAKSHATRAS, OWN_SIGNS,
    PLANETS_SANSKRIT, SEVEN, SIGN_LORD, SIGNS, SIGNS_SANSKRIT, SPECIAL_ASPECTS, ordinal,
)
from src.common import DATA, EVALSETS, PROMPTS, read_jsonl, write_jsonl
from src.dataset.facts import EXALT_DEGREE, GROUPS, PANCHA, YOGAS, P, join, too_close, _norm

OUT = DATA / "sft_v4" / "facts_v4.jsonl"
SEED = 11

# Hindi/Hinglish spellings used in questions (the answers stay in English with the Sanskrit term glossed)
HI_PLANET = {"Sun": "Surya", "Moon": "Chandra", "Mars": "Mangal", "Mercury": "Budh", "Jupiter": "Guru",
             "Venus": "Shukra", "Saturn": "Shani", "Rahu": "Rahu", "Ketu": "Ketu"}
HI_SIGN = dict(zip(SIGNS, SIGNS_SANSKRIT))
VARGA_USES = [
    ("D1", "Rasi", "the body, the overall life and the base reading of every matter"),
    ("D2", "Hora", "wealth and resources"),
    ("D3", "Drekkana", "siblings, courage and initiative"),
    ("D4", "Chaturthamsa", "property, home and fixed assets"),
    ("D7", "Saptamsa", "children and progeny"),
    ("D9", "Navamsa", "marriage, the spouse, dharma and the inner strength of every planet"),
    ("D10", "Dasamsa", "career, profession and public standing"),
    ("D12", "Dwadasamsa", "parents"),
    ("D16", "Shodasamsa", "vehicles, comforts and happiness"),
    ("D20", "Vimsamsa", "spiritual practice and worship"),
    ("D24", "Chaturvimsamsa", "education and learning"),
    ("D30", "Trimsamsa", "misfortunes, troubles and the moral character"),
    ("D60", "Shashtiamsa", "past-life karma and the finest judgement of every matter"),
]
ASHTAKOOTA = [("Varna", 1, "temperament and spiritual compatibility"), ("Vashya", 2, "mutual attraction and control"),
              ("Tara", 3, "birth-star compatibility and fortune"), ("Yoni", 4, "physical and instinctive compatibility"),
              ("Graha Maitri", 5, "friendship of the Moon-sign lords, mental compatibility"),
              ("Gana", 6, "temperament class: deva, manushya or rakshasa"),
              ("Bhakoot", 7, "Moon-sign distance, family welfare and prosperity"), ("Nadi", 8, "health and progeny")]
KUJA_HOUSES = [1, 2, 4, 7, 8, 12]
KUJA_NOTE = ("Classical and modern texts differ on the exact list (some omit the 2nd, some count from the Moon and Venus as "
             "well as the lagna), and they list many cancellations: Mars in its own or exaltation sign, Mars in the signs "
             "of Jupiter, both partners having the dosha, a strong Jupiter aspecting Mars, and more. It is one factor among "
             "many, never a verdict on a marriage.")
VIPAREETA = [("Harsha", 6), ("Sarala", 8), ("Vimala", 12)]


def build() -> list[tuple[str, str, str]]:
    rng = random.Random(SEED)
    out: list[tuple[str, str, str]] = []
    add = lambda cat, q, a: out.append((cat, q, a))

    # ---------------------------------------------------------------- Pancha Mahapurusha (ten phrasings each + contrasts)
    kendra = "a kendra (the 1st, 4th, 7th or 10th house) from the lagna"
    for planet, yoga in PANCHA.items():
        ans = (f"{yoga} yoga is formed by {P(planet)}: it arises when {P(planet)} occupies its own sign "
               f"({join([SIGNS[s] for s in OWN_SIGNS[planet]])}) or its exaltation sign ({SIGNS[EXALTATION[planet]]}) in {kendra}. "
               f"It is one of the five Pancha Mahapurusha yogas; the others are "
               f"{join([f'{y} ({p})' for p, y in PANCHA.items() if p != planet])}.")
        qs = [f"Which planet forms {yoga} yoga?", f"{yoga} yoga is caused by which graha?",
              f"What are the conditions for {yoga} yoga?", f"Define {yoga} yoga.",
              f"{yoga} yoga kaun sa graha banata hai?", f"{yoga} yoga kaise banta hai?",
              f"Is {yoga} yoga a Pancha Mahapurusha yoga, and which planet gives it?",
              f"In which signs and houses must {P(planet)} be for {yoga} yoga?",
              f"My astrologer said I have {yoga} yoga. Which planet is that about?",
              f"Quick check: {yoga} yoga = which planet?"]
        for q in qs:
            add("pancha_mahapurusha", q, ans)
        for other in [p for p in PANCHA if p != planet]:
            add("pancha_mahapurusha_contrast", rng.choice([f"Does {P(other)} form {yoga} yoga?", f"Is {yoga} yoga given by {other}?"]),
                f"No. {yoga} yoga belongs to {P(planet)}, not {P(other)}. {P(other, True)} in its own or exaltation sign in a kendra "
                f"gives {PANCHA[other]} yoga instead. {yoga} needs {P(planet)} in {join([SIGNS[s] for s in OWN_SIGNS[planet]])} "
                f"or {SIGNS[EXALTATION[planet]]} in {kendra}.")
    for q in ["Which planets can form a Pancha Mahapurusha yoga?", "Can the Sun or Moon form a Pancha Mahapurusha yoga?",
              "Panch Mahapurush yoga kaun kaun se graha se bante hain?", "List the five Mahapurusha yogas with their planets.",
              "Why are there only five Pancha Mahapurusha yogas?"]:
        add("pancha_mahapurusha", q,
            "Only the five non-luminary planets form Pancha Mahapurusha yogas: Mars gives Ruchaka, Mercury gives Bhadra, "
            "Jupiter gives Hamsa, Venus gives Malavya and Saturn gives Shasha. The Sun and Moon form none of them, and Rahu "
            "and Ketu own no signs, so they are excluded too. Each yoga needs its planet in its own or exaltation sign in a "
            "kendra from the lagna.")
    for name, cond in YOGAS:
        base = name.split(" (")[0]
        if base.startswith("Raja yoga"):
            continue
        add("yoga_contrast", rng.choice([f"Is {base} one of the Pancha Mahapurusha yogas?", f"{base}: is it a Mahapurusha yoga?"]),
            f"No. {base} is not a Pancha Mahapurusha yoga. In its common definition it forms when {cond}. The Pancha "
            f"Mahapurusha yogas are Ruchaka, Bhadra, Hamsa, Malavya and Shasha only.")
        for q in rng.sample([f"What is {base}?", f"When does {base} form?", f"{base} kya hota hai?", f"Which placement gives {base}?",
                             f"Explain the condition for {base}.", f"{base} kaise banta hai?"], 4):
            add("yoga_definition", q, f"In its common definition, {base} forms when {cond}. Texts differ in details and in the "
                                      f"cancellations, so the whole chart is judged before any result is read from it.")

    # Kemadruma gets extra contrast: the model confused it with Vipareeta Raja and Mahapurusha yogas
    kem = next(c for n, c in YOGAS if n.startswith("Kemadruma"))
    for q in ["Is Kemadruma yoga formed by the 8th lord in a dusthana?", "Does Kemadruma involve the 6th lord?",
              "Is Kemadruma a Raja yoga?", "Kemadruma yoga Chandra se related hai ya lagna se?",
              "Which planet is Kemadruma yoga about?"]:
        add("yoga_contrast", q, f"Kemadruma yoga is a Moon-based yoga, not a lordship yoga and not a Raja yoga. It forms when {kem}. "
                                f"It has well-known cancellations (Kemadruma bhanga): a planet in a kendra from the Moon or from the "
                                f"lagna, the Moon in a kendra from the lagna, or the Moon aspected by Jupiter, among others.")
    for yoga, house in VIPAREETA:
        for q in rng.sample([f"What is {yoga} yoga?", f"Which lord gives {yoga} yoga?", f"{yoga} yoga kaise banta hai?",
                             f"{yoga} yoga is which kind of Vipareeta Raja yoga?"], 3):
            add("vipareeta", q, f"{yoga} yoga is one of the three Vipareeta Raja yogas. It forms when the lord of the {ordinal(house)} "
                                f"house occupies the 6th, 8th or 12th house. The three are Harsha (6th lord), Sarala (8th lord) and "
                                f"Vimala (12th lord). Classical texts add conditions, such as the lord not joining other house lords.")
    for q in ["What is a Vipareeta Raja yoga?", "Vipareeta Raja yoga kya hai?", "Which lords form Vipareeta Raja yogas?",
              "Is a Vipareeta Raja yoga formed by a malefic in a kendra?"]:
        add("vipareeta", q, "A Vipareeta Raja yoga forms when the lord of a dusthana (the 6th, 8th or 12th house) is placed in a "
                            "dusthana (the 6th, 8th or 12th). The three named forms are Harsha (6th lord), Sarala (8th lord) and "
                            "Vimala (12th lord). It is not about malefics in kendras; it is about the dusthana lords losing their "
                            "power to harm by sitting in each other's houses.")

    # ---------------------------------------------------------------- dignities with Hinglish and contrast
    for p in SEVEN:
        ex, de = SIGNS[EXALTATION[p]], SIGNS[DEBILITATION[p]]
        hp = HI_PLANET[p]
        exa = (f"{P(p, True)} ({PLANETS_SANSKRIT[p]}) is exalted (uccha) in {ex} ({HI_SIGN[ex]}), deepest at {EXALT_DEGREE[p]}°. "
               f"Its debilitation (neecha) is the opposite sign, {de} ({HI_SIGN[de]}).")
        dea = (f"{P(p, True)} ({PLANETS_SANSKRIT[p]}) is debilitated (neecha) in {de} ({HI_SIGN[de]}), deepest at {EXALT_DEGREE[p]}°, "
               f"opposite its exaltation in {ex} ({HI_SIGN[ex]}). Neecha Bhanga conditions can cancel the debilitation.")
        for q in [f"{hp} ki uccha rashi kaunsi hai?", f"{hp} kis rashi mein uccha hota hai?", f"In which rashi is {hp} exalted?",
                  f"{hp} exalted kahan hota hai?", f"{p} uccha sign?"]:
            add("exaltation_hi", q, exa)
        for q in [f"{hp} ki neech rashi kaunsi hai?", f"{hp} kis rashi mein neech hota hai?", f"In which rashi does {hp} become neecha?",
                  f"{hp} debilitated kahan hota hai?", f"{p} is weakest in which sign?"]:
            add("debilitation_hi", q, dea)
        wrong = rng.sample([s for s in SIGNS if s not in (ex, de)], 2)
        for w in wrong:
            add("dignity_contrast", rng.choice([f"Is {p} debilitated in {w}?", f"Does {p} get debilitated in {w}?"]),
                f"No. {P(p, True)} is debilitated in {de}, not {w}. Its exaltation is {ex}. "
                + (f"In {w}, {P(p)} is in {'its own sign' if SIGNS.index(w) in OWN_SIGNS[p] else 'neither exaltation nor debilitation; its state there depends on its relationship with ' + SIGN_LORD[SIGNS.index(w)]}."))
            add("dignity_contrast", rng.choice([f"Is {p} exalted in {w}?", f"Does {p} get exalted in {w}?"]),
                f"No. {P(p, True)} is exalted in {ex}, not {w}. Its debilitation is {de}.")
        add("dignity_contrast", f"Is {p} exalted in {de}?", f"No, the opposite: {de} is {P(p)}'s sign of debilitation. Its exaltation sign is {ex}.")
        signs = [SIGNS[s] for s in OWN_SIGNS[p]]
        own = (f"{P(p, True)} ({PLANETS_SANSKRIT[p]}) owns {join([f'{s} ({HI_SIGN[s]})' for s in signs])}."
               + (" The Sun and Moon own one sign each; the other five planets own two." if len(signs) == 1 else ""))
        for q in [f"{hp} ki rashiyan kaunsi hain?", f"{hp} kis rashi ka swami hai?", f"Which rashis belong to {hp}?",
                  f"{hp} ki apni rashi kaunsi hai?", f"Own sign of {p}?"]:
            add("own_sign_hi", q, own)
        for w in rng.sample([s for s in SIGNS if SIGNS.index(s) not in OWN_SIGNS[p]], 2):
            add("own_sign_contrast", rng.choice([f"Does {p} own {w}?", f"Is {w} a sign of {p}?"]),
                f"No. {w} is ruled by {P(SIGN_LORD[SIGNS.index(w)])}. {P(p, True)} owns {join(signs)}.")

    # ---------------------------------------------------------------- sign lords and nakshatra lords in Hinglish
    for s, sign in enumerate(SIGNS):
        lord = SIGN_LORD[s]
        a = f"{sign} ({SIGNS_SANSKRIT[s]}) is ruled by {P(lord)} ({PLANETS_SANSKRIT[lord]})."
        for q in [f"{SIGNS_SANSKRIT[s]} rashi ka swami kaun hai?", f"{SIGNS_SANSKRIT[s]} ka lord kaun sa graha hai?",
                  f"Who rules {SIGNS_SANSKRIT[s]}?", f"{sign} rashi ka adhipati?"]:
            add("sign_lord_hi", q, a)
    for i, n in enumerate(NAKSHATRAS):
        lord = NAKSHATRA_LORD[i]
        gloss = f" ({PLANETS_SANSKRIT[lord]})" if PLANETS_SANSKRIT[lord] != lord else ""
        a = (f"{n} is ruled by {P(lord)}{gloss} in the Vimshottari scheme, so a Moon in {n} starts life in "
             f"{lord} mahadasha. That mahadasha lasts {DASHA_YEARS[lord]} years in full, but the balance remaining at birth "
             f"depends on how far the Moon had travelled through {n}.")
        for q in [f"{n} nakshatra ka swami kaun hai?", f"{n} ka dasha lord kaun hai?", f"{n} nakshatra kis graha ka hai?",
                  f"Vimshottari mein {n} ka swami?"]:
            add("nakshatra_lord_hi", q, a)
        others = [NAKSHATRAS[j] for j in range(27) if NAKSHATRA_LORD[j] == lord and j != i]
        wrong = rng.choice([p for p in DASHA_ORDER if p != lord])
        add("nakshatra_lord_contrast", rng.choice([f"Is {n} ruled by {wrong}?", f"Does {wrong} rule {n} nakshatra?"]),
            f"No. {n} is ruled by {P(lord)}, together with {join(others)}. {P(wrong, True)} rules "
            f"{join([NAKSHATRAS[j] for j in range(27) if NAKSHATRA_LORD[j] == wrong])}.")

    # ---------------------------------------------------------------- aspects, in the quiz's own wording family
    for p, extra in SPECIAL_ASPECTS.items():
        special = [a for a in extra if a != 7]
        a = (f"Besides the 7th, {P(p)} aspects the {join([ordinal(x) for x in special])} houses counted from itself. "
             f"These special aspects (vishesha drishti) belong to Mars (4th and 8th), Jupiter (5th and 9th) and Saturn (3rd and 10th); "
             f"the other planets have only the 7th aspect.")
        for q in [f"Besides the 7th house, which houses does {p} aspect?", f"What are the special aspects of {p}?",
                  f"{HI_PLANET[p]} ki drishti kaun kaun se bhav par padti hai?", f"{p} ki vishesh drishti kaunsi hai?",
                  f"Apart from the opposite house, where does {p} cast its glance?", f"{p} special aspects which houses?"]:
            add("aspects_special", q, a)
        for wrong in rng.sample([x for x in range(2, 13) if x not in extra], 2):
            add("aspects_contrast", f"Does {p} aspect the {ordinal(wrong)} house from itself?",
                f"No. {P(p, True)} aspects the {join([ordinal(x) for x in extra])} houses counted from itself; the {ordinal(wrong)} is not among them.")
    for p in [x for x in SEVEN if x not in SPECIAL_ASPECTS]:
        for q in [f"Does {p} have any special aspect?", f"Which houses does {p} aspect?", f"{HI_PLANET[p]} ki drishti kahan padti hai?"]:
            add("aspects_default", q, f"{P(p, True)} has only the 7th aspect, on the house opposite to it. Special aspects belong to "
                                      f"Mars (4th and 8th), Jupiter (5th and 9th) and Saturn (3rd and 10th) only.")

    # ---------------------------------------------------------------- Vimshottari
    order_text = ", ".join(DASHA_ORDER)
    first = ("The first mahadasha is that of the lord of the nakshatra the Moon occupies at birth (the janma nakshatra), "
             "not the Moon's own dasha. The balance of that dasha remaining at birth depends on how far the Moon had moved "
             f"through the nakshatra. The order then continues {order_text}.")
    for q in ["Which mahadasha starts at birth in Vimshottari?", "How is the first Vimshottari dasha decided?",
              "Janma ke samay kaunsi mahadasha chalti hai?", "Does everyone start life in Moon mahadasha?",
              "Vimshottari ki pehli dasha kaise tay hoti hai?", "What decides which dasha a person is born into?"]:
        add("dasha_first", q, first)
    cycle = (f"The full Vimshottari cycle is 120 years: {'; '.join(f'{p} {DASHA_YEARS[p]}' for p in DASHA_ORDER)}. "
             f"The order is {order_text}, after which it repeats.")
    for q in ["How long is the full Vimshottari dasha cycle?", "Vimshottari dasha ka total cycle kitne varsh ka hai?",
              "What is the sum of all Vimshottari mahadasha years?", "List the Vimshottari dasha years of all nine planets.",
              "Vimshottari mein kis graha ki dasha kitne saal ki hoti hai?"]:
        add("dasha_cycle", q, cycle)
    for p in DASHA_ORDER:
        for q in [f"{HI_PLANET[p]} mahadasha kitne saal ki hoti hai?", f"{HI_PLANET[p]} ki dasha kitne varsh chalti hai?",
                  f"How many years does {p} mahadasha run in Vimshottari?"]:
            add("dasha_years_hi", q, f"{P(p, True)} ({PLANETS_SANSKRIT[p]}) mahadasha lasts {DASHA_YEARS[p]} years in the "
                                     f"Vimshottari system, whose full cycle is 120 years.")

    # ---------------------------------------------------------------- vargas, ayanamsa, ashtakoota, kuja dosha, karakas
    for code, name, use in VARGA_USES:
        for q in rng.sample([f"What is the {code} chart used for?", f"Which matters does the {name} ({code}) show?",
                             f"{name} chart kis cheez ke liye dekhte hain?", f"Which varga is {code}?"], 3):
            add("varga_use", q, f"The {name} ({code}) divisional chart is used for {use}. Divisional charts refine what the "
                                f"Rasi chart shows; the Rasi chart is always read first.")
    for topic, code, name in [("career", "D10", "Dasamsa"), ("marriage", "D9", "Navamsa"), ("children", "D7", "Saptamsa"),
                              ("wealth", "D2", "Hora"), ("parents", "D12", "Dwadasamsa"), ("property", "D4", "Chaturthamsa"),
                              ("siblings", "D3", "Drekkana"), ("education", "D24", "Chaturvimsamsa")]:
        for q in [f"Which divisional chart is used for {topic}?", f"{topic} ke liye kaunsa varga chart dekha jata hai?",
                  f"Which varga do astrologers consult for {topic}?"]:
            add("varga_for_topic", q, f"For {topic} the {name} ({code}) is consulted, alongside the relevant house and its lord in "
                                      f"the Rasi chart. A divisional chart confirms or qualifies what the Rasi chart shows.")
    for q in ["Which ayanamsa is the Indian government standard?", "What is the Chitrapaksha ayanamsa?",
              "Lahiri ayanamsa kya hai?", "Which ayanamsa does the Indian national calendar use?",
              "Is Lahiri the same as Chitrapaksha ayanamsa?"]:
        add("ayanamsa", q, "The Lahiri ayanamsa, also called Chitrapaksha, is the standard adopted by the Indian Calendar Reform "
                           "Committee and used in the national ephemeris. It fixes the sidereal zodiac so that the star Chitra "
                           "(Spica) sits at 180°. Other ayanamsas (Raman, Krishnamurti, Yukteshwar) differ by up to about a degree.")
    total = sum(p for _, p, _ in ASHTAKOOTA)
    koota = (f"Ashtakoota (guna milan) scores eight factors from the two Moons' nakshatras and signs, totalling {total} points: "
             + "; ".join(f"{n} {p}" for n, p, _ in ASHTAKOOTA) + ". A score of 18 or more is traditionally called acceptable, "
             "but the score is only one part of compatibility judgement; the full charts, Kuja dosha, dasha periods and the "
             "people themselves matter more than the number.")
    for q in ["How is the guna matching score of 36 made up?", "What are the eight kootas in Ashtakoota matching?",
              "Guna milan mein kitne gun hote hain aur kaise?", "What does a guna score out of 36 measure?",
              "Which koota carries the most points?", "Is a guna score of 14 a disaster?"]:
        add("ashtakoota", q, koota)
    for n, pts, meaning in ASHTAKOOTA:
        add("ashtakoota_item", rng.choice([f"What does {n} koota measure?", f"{n} koota kitne point ka hota hai?"]),
            f"{n} koota carries {pts} point{'s' if pts > 1 else ''} of the {total} in Ashtakoota matching and relates to {meaning}.")
    kuja = (f"Kuja dosha (Mangal dosha, Manglik) is the common name for Mars in the {join([ordinal(h) for h in KUJA_HOUSES])} "
            f"house from the lagna. {KUJA_NOTE}")
    for q in ["Which houses of Mars cause Kuja dosha?", "What is Mangal dosha?", "Manglik dosha kin bhavon mein banta hai?",
              "What cancels Kuja dosha?", "Is Mars in the 7th the only Manglik placement?", "Mangal dosha ke nivaran kya hain?",
              "Does Mars in the 10th house make someone Manglik?"]:
        add("kuja_dosha", q, kuja)
    for p, k in FIXED_KARAKAS.items():
        for q in [f"{HI_PLANET[p]} kis cheez ka karak hai?", f"Which matters does {HI_PLANET[p]} signify as a karaka?",
                  f"{p} is the natural significator of what?"]:
            add("karaka_hi", q, f"As a natural (sthira) karaka, {P(p)} ({PLANETS_SANSKRIT[p]}) signifies {k}.")
    for topic, planet in [("father", "Sun"), ("mother", "Moon"), ("siblings", "Mars"), ("children", "Jupiter"),
                          ("spouse (for a man)", "Venus"), ("longevity", "Saturn"), ("speech and intellect", "Mercury"),
                          ("wisdom and the guru", "Jupiter"), ("courage", "Mars"), ("the mind", "Moon")]:
        for q in [f"Which planet is the karaka of {topic}?", f"{topic} ka karak graha kaun hai?", f"Who signifies {topic} in a chart?"]:
            add("karaka_topic", q, f"{P(planet, True)} ({PLANETS_SANSKRIT[planet]}) is the natural karaka of {topic}; its full "
                                   f"significations are {FIXED_KARAKAS[planet]}. The relevant house and its lord are judged alongside the karaka.")
    for name, hs in GROUPS.items():
        short = name.split(" (")[0]
        for q in [f"{short.capitalize()} kaun se bhav hote hain?", f"Which houses count as {short}?", f"List the {short} by number."]:
            add("house_groups_hi", q, f"The {name} are the {join([ordinal(x) for x in hs])} houses.")
    for h in range(1, 13):
        if h in GROUPS["upachaya houses (houses of growth)"]:
            continue
        add("house_groups_contrast", f"Is the {ordinal(h)} house an upachaya house?",
            f"No. The upachaya (growth) houses are the 3rd, 6th, 10th and 11th. The {ordinal(h)} is not one of them.")
    return out


def main() -> None:
    system = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
    quiz_qs = [_norm(r["question"]) for r in read_jsonl(EVALSETS / "quiz.jsonl")]
    rob = EVALSETS / "robustness.jsonl"
    if rob.exists():  # the paraphrased quiz items must stay unseen too
        quiz_qs += [_norm(r["prompt"]) for r in read_jsonl(rob) if r.get("kind") == "paraphrase" or "para" in r["id"]]
    seen, rows, dropped = set(), [], 0
    for n, (cat, q, a) in enumerate(build()):
        key = " ".join(sorted(_norm(q)))
        if key in seen or too_close(q, quiz_qs):
            dropped += 1
            continue
        seen.add(key)
        rows.append({"id": f"fact4-{n:04d}", "task": "fact_v4", "category": cat,
                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": q},
                                  {"role": "assistant", "content": a}]})
    write_jsonl(OUT, rows)
    print(f"wrote {len(rows)} fact_v4 examples -> {OUT} (dropped {dropped}: duplicate or too close to an eval question)")
    print(Counter(r["category"] for r in rows))


if __name__ == "__main__":
    main()
