"""v2: short fact examples generated from the reference tables in src/chart/constants.py.

The v1 evaluation showed the model never learned basic lookup facts (quiz 38%, nakshatra lords 3/27): they only
appeared incidentally in conversational answers. These examples teach them directly, in varied phrasings, with
answers that are correct by construction (the tables are covered by tests/test_chart_engine.py).

Questions too similar to evalsets/quiz.jsonl are dropped, so the quiz still measures recall, not copying.

    python -m src.dataset.facts        # -> data/sft_v2/facts.jsonl
"""
from __future__ import annotations

import random
import re
from collections import Counter

from src.chart.constants import (
    COMBUST_ORB, COMBUST_ORB_RETRO, DASHA_ORDER, DASHA_YEARS, DEBILITATION, ENEMIES, EXALTATION, FIXED_KARAKAS,
    FRIENDS, HOUSE_THEMES, NAKSHATRA_LORD, NAKSHATRAS, NAK_SPAN, OWN_SIGNS, SEVEN, SIGN_LORD, SIGNS, SIGNS_SANSKRIT,
    SPECIAL_ASPECTS, ordinal,
)
from src.common import DATA, EVALSETS, PROMPTS, read_jsonl, write_jsonl

OUT = DATA / "sft_v2" / "facts.jsonl"
SEED = 7
EXALT_DEGREE = {"Sun": 10, "Moon": 3, "Mars": 28, "Mercury": 15, "Jupiter": 5, "Venus": 27, "Saturn": 20}
MOOLATRIKONA_TEXT = {"Sun": "Leo, 0° to 20°", "Moon": "Taurus, from 4° to 30°, after its exaltation degree",
                     "Mars": "Aries, 0° to 12°", "Mercury": "Virgo, just after its exaltation zone",
                     "Jupiter": "Sagittarius, 0° to 10°", "Venus": "Libra, 0° to 15°", "Saturn": "Aquarius, 0° to 20°"}
GROUPS = {
    "kendras (angles)": [1, 4, 7, 10], "trikonas (trines)": [1, 5, 9], "dusthanas (difficult houses)": [6, 8, 12],
    "upachaya houses (houses of growth)": [3, 6, 10, 11], "maraka houses": [2, 7],
    "panapara houses (succedent)": [2, 5, 8, 11], "apoklima houses (cadent)": [3, 6, 9, 12],
}
QUALITY = {"movable (chara)": [0, 3, 6, 9], "fixed (sthira)": [1, 4, 7, 10], "dual (dwiswabhava)": [2, 5, 8, 11]}
ELEMENT = {"fire": [0, 4, 8], "earth": [1, 5, 9], "air": [2, 6, 10], "water": [3, 7, 11]}
YOGAS = [
    ("Gajakesari yoga", "Jupiter is in a kendra (the 1st, 4th, 7th or 10th) counted from the Moon"),
    ("Budhaditya yoga", "the Sun and Mercury occupy the same sign"),
    ("Chandra-Mangala yoga", "the Moon and Mars occupy the same sign"),
    ("Kemadruma yoga", "no planet other than the Sun, Rahu and Ketu occupies the 2nd or the 12th from the Moon, and none joins the Moon"),
    ("Sunapha yoga", "a planet other than the Sun, Rahu and Ketu occupies the 2nd from the Moon"),
    ("Anapha yoga", "a planet other than the Sun, Rahu and Ketu occupies the 12th from the Moon"),
    ("Durudhara yoga", "planets other than the Sun, Rahu and Ketu occupy both the 2nd and the 12th from the Moon"),
    ("Vesi yoga", "a planet other than the Moon, Rahu and Ketu occupies the 2nd from the Sun"),
    ("Vosi yoga", "a planet other than the Moon, Rahu and Ketu occupies the 12th from the Sun"),
    ("Ubhayachari yoga", "planets other than the Moon, Rahu and Ketu occupy both the 2nd and the 12th from the Sun"),
    ("Amala yoga", "a natural benefic occupies the 10th house from the lagna or from the Moon"),
    ("Harsha yoga", "the lord of the 6th house is placed in the 6th, 8th or 12th house; it is one of the three Viparita Raja yogas"),
    ("Sarala yoga", "the lord of the 8th house is placed in the 6th, 8th or 12th house; it is one of the three Viparita Raja yogas"),
    ("Vimala yoga", "the lord of the 12th house is placed in the 6th, 8th or 12th house; it is one of the three Viparita Raja yogas"),
    ("Parivartana yoga", "two planets occupy each other's signs (an exchange of signs)"),
    ("Kala Sarpa yoga", "all seven planets from the Sun to Saturn lie on one side of the Rahu-Ketu axis; it is a later concept, not one emphasised in the older Parashari classics"),
    ("Raja yoga (Parashari)", "the lord of a kendra and the lord of a trikona are connected by conjunction, mutual aspect or exchange of signs"),
    ("Dharma-Karmadhipati yoga", "the lords of the 9th and 10th houses are connected by conjunction, mutual aspect or exchange of signs"),
]
PANCHA = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa", "Venus": "Malavya", "Saturn": "Shasha"}


def P(name: str, cap: bool = False) -> str:
    """'the Sun' / 'the Moon' (other grahas take no article)."""
    out = f"the {name}" if name in ("Sun", "Moon") else name
    return out[0].upper() + out[1:] if cap else out


def dms(x: float) -> str:
    d = int(x + 1e-9)
    m = int(round((x - d) * 60))
    if m == 60:
        d, m = d + 1, 0
    return f"{d}°{m:02d}'"


def place(lon: float) -> str:
    return f"{dms(lon % 30)} {SIGNS[int(lon // 30) % 12]}"


def join(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def build() -> list[tuple[str, str, str]]:
    """(category, question, answer) triples."""
    rng = random.Random(SEED)
    out: list[tuple[str, str, str]] = []
    add = lambda cat, q, a: out.append((cat, q, a))
    order_text = ", ".join(DASHA_ORDER)

    # nakshatras: lords, spans, first dasha
    for i, n in enumerate(NAKSHATRAS):
        lord = NAKSHATRA_LORD[i]
        trio = [NAKSHATRAS[j] for j in (i % 9, i % 9 + 9, i % 9 + 18)]
        others = join([x for x in trio if x != n])
        start, end = i * NAK_SPAN, (i + 1) * NAK_SPAN
        span = f"from {place(start)} to {place(end) if int(end // 30) == int(start // 30) else place(end)}"
        if int(end // 30) != int(start // 30) and (end % 30) > 1e-6:
            span = f"from {place(start)} to {place(end)} (it crosses the sign boundary)"
        elif (end % 30) < 1e-6:
            span = f"from {place(start)} to the end of {SIGNS[int(start // 30)]}"
        for q in rng.sample([f"Who is the nakshatra lord of {n}?", f"{n} nakshatra is governed by which graha?",
                             f"What is the ruling planet of {n}?", f"Is {n} a {lord} nakshatra?",
                             f"Which graha owns {n} for dasha purposes?"], 4):
            a = (f"{n} is ruled by {P(lord)}." if not q.startswith("Is") else f"Yes. {n} is ruled by {P(lord)}.")
            a += (f" In the Vimshottari scheme the nakshatra lords repeat in the order {order_text}, so {n}, the "
                  f"{ordinal(i + 1)} nakshatra, falls to {P(lord)}, as do {others}.")
            add("nakshatra_lord", q, a)
        for q in rng.sample([f"Where does {n} nakshatra fall in the zodiac?", f"What is the span of {n}?",
                             f"Which degrees of the sidereal zodiac belong to {n}?"], 2):
            add("nakshatra_span", q, f"{n}, the {ordinal(i + 1)} nakshatra, spans 13°20' of the sidereal zodiac, {span}. "
                                     f"Each of its four padas covers 3°20'. Its lord is {P(lord)}.")
        for q in [f"If my Moon is in {n}, which mahadasha was I born into?",
                  f"Moon in {n} at birth: whose Vimshottari dasha starts first?"]:
            add("first_dasha", q, f"The first mahadasha is that of the Moon's nakshatra lord. {n} is ruled by {P(lord)}, so "
                              f"you were born in {lord} mahadasha ({DASHA_YEARS[lord]} years in full). How much of it "
                              f"remained at birth depends on how far the Moon had travelled through {n}; the chart "
                              f"software calculates that balance.")

    for p in DASHA_ORDER:
        naks = [NAKSHATRAS[i] for i in range(27) if NAKSHATRA_LORD[i] == p]
        for q in [f"Which nakshatras does {p} rule?", f"Name the three nakshatras of {P(p)}."]:
            add("nakshatras_of_planet", q, f"{P(p, True)} rules {join(naks)}, one nakshatra in each third of the zodiac. "
                                          f"A Moon in any of them starts life in {p} mahadasha.")

    # signs
    for s, sign in enumerate(SIGNS):
        lord = SIGN_LORD[s]
        for q in rng.sample([f"Who is the lord of {sign}?", f"{sign} ({SIGNS_SANSKRIT[s]}) is owned by which planet?",
                             f"Which graha owns {SIGNS_SANSKRIT[s]} rashi?"], 3):
            add("sign_lord", q, f"{sign} ({SIGNS_SANSKRIT[s]}) is ruled by {P(lord)}."
                                + (f" {P(lord, True)} also rules {join([SIGNS[x] for x in OWN_SIGNS[lord] if x != s])}." if len(OWN_SIGNS[lord]) > 1 else ""))
        qual = next(k for k, v in QUALITY.items() if s in v)
        elem = next(k for k, v in ELEMENT.items() if s in v)
        add("sign_nature", rng.choice([f"What kind of sign is {sign}?", f"Is {sign} movable, fixed or dual?"]),
            f"{sign} ({SIGNS_SANSKRIT[s]}) is a {qual}, {elem} sign, {'odd (masculine)' if s % 2 == 0 else 'even (feminine)'}, ruled by {lord}.")
    for p in SEVEN:
        signs = [SIGNS[x] for x in OWN_SIGNS[p]]
        add("own_sign", rng.choice([f"What are {p}'s own signs?", f"Where is {p} in its own house?",
                                    f"Which rashis belong to {p}?"]),
            f"{P(p, True)} owns {join(signs)}." + (" The Sun and Moon own one sign each; the other five planets own two." if len(signs) == 1 else ""))

    # dignities
    for p in SEVEN:
        ex, de = SIGNS[EXALTATION[p]], SIGNS[DEBILITATION[p]]
        for q in rng.sample([f"Where does {p} get exalted?", f"What is {p}'s sign of exaltation (uccha)?",
                             f"{p} is strongest by sign where?"], 3):
            add("exaltation", q, f"{P(p, True)} is exalted in {ex}, with its deepest exaltation at {EXALT_DEGREE[p]}° {ex}. "
                                 f"Its debilitation is the opposite sign, {de}.")
        for q in rng.sample([f"Where is {p} in its fall?", f"What is {p}'s neecha rashi?",
                             f"In which sign does {p} become debilitated?"], 3):
            add("debilitation", q, f"{P(p, True)} is debilitated in {de}, deepest at {EXALT_DEGREE[p]}° {de}, exactly opposite "
                                   f"its exaltation in {ex}. Neecha Bhanga conditions can cancel the debilitation.")
        add("moolatrikona", rng.choice([f"What is the moolatrikona of {p}?", f"Where is {p}'s moolatrikona sign?"]),
            f"{P(p, True)}'s moolatrikona is {MOOLATRIKONA_TEXT[p]}.")

    # friendships
    for p in SEVEN:
        fr, en = FRIENDS[p], ENEMIES[p]
        ne = [q for q in SEVEN if q not in fr + en + [p]]
        add("friendship", rng.choice([f"Who are the natural friends of {p}?", f"List {p}'s naisargika friends and enemies."]),
            f"By natural (naisargika) relationship, {P(p)}'s friends are {join([P(x) for x in fr])}; "
            + (f"its enemies are {join([P(x) for x in en])}" if en else "it has no enemies") + (f"; {join([P(x) for x in ne])} {'is' if len(ne) == 1 else 'are'} neutral." if ne else "."))
        for o in SEVEN:
            if o == p:
                continue
            rel = "a friend" if o in fr else "an enemy" if o in en else "neutral"
            back = "a friend" if p in FRIENDS[o] else "an enemy" if p in ENEMIES[o] else "neutral"
            note = "" if rel == back else f" The relationship is not mutual: {P(o)} regards {P(p)} as {back}."
            q = rng.choice([f"How does {p} regard {o} in natural friendship?", f"Is {o} a friend of {p}?",
                            f"In naisargika maitri, what is {P(o)} to {P(p)}?"])
            add("friendship_pair", q, f"{P(p, True)} regards {P(o)} as {rel}.{note}")

    # aspects
    for p in SEVEN:
        extra = SPECIAL_ASPECTS.get(p)
        add("aspect_rule", rng.choice([f"Which houses does {p} aspect?", f"What are {p}'s graha drishti?"]),
            (f"{p} has full aspects on the {join([ordinal(x) for x in extra])} houses counted from itself." if extra
             else f"{p} has one full aspect, on the 7th house counted from itself."))
        for h in range(1, 13):
            houses = [((h - 1 + a - 1) % 12) + 1 for a in (extra or [7])]
            q = rng.choice([f"If {p} sits in the {ordinal(h)} house, which houses does it aspect?",
                            f"{p} in the {ordinal(h)} bhava casts drishti on which houses?"])
            add("aspect_applied", q,
                f"From the {ordinal(h)} house, {P(p)} aspects the {join([ordinal(x) for x in houses])} "
                f"house{'s' if len(houses) > 1 else ''}" + (f" (its {join([ordinal(a) for a in extra])} aspects)." if extra else " (its 7th aspect)."))

    # dasha
    for i, p in enumerate(DASHA_ORDER):
        nxt = DASHA_ORDER[(i + 1) % 9]
        add("dasha_years", rng.choice([f"What is the length of {p}'s Vimshottari dasha?", f"{p} mahadasha runs for how long?"]),
            f"{p} mahadasha lasts {DASHA_YEARS[p]} years in the Vimshottari system, whose full cycle is 120 years.")
        add("dasha_order", rng.choice([f"After {p} mahadasha, which one comes?", f"What dasha follows {p}?"]),
            f"{nxt} mahadasha follows {p}. The Vimshottari sequence is {order_text}, then it repeats.")

    # houses
    for name, hs in GROUPS.items():
        short = name.split(" (")[0]
        add("house_groups", rng.choice([f"Name the {short}.", f"What are the {short} in a chart?"]),
            f"The {name} are the {join([ordinal(x) for x in hs])} houses.")
    for h in range(1, 13):
        member = [n.split(" (")[0] for n, hs in GROUPS.items() if h in hs]
        add("house_groups", f"Is the {ordinal(h)} house a kendra, trikona or dusthana?",
            f"The {ordinal(h)} house belongs to the {join(member)}." if member else f"The {ordinal(h)} house is in none of those groups.")
        add("house_meaning", rng.choice([f"What does the {ordinal(h)} house signify?", f"Which matters does the {ordinal(h)} bhava govern?"]),
            f"The {ordinal(h)} house signifies {HOUSE_THEMES[h]}.")
    for p, k in FIXED_KARAKAS.items():
        add("karaka", rng.choice([f"What is {p} the karaka of?", f"Which significations does {p} carry as a natural karaka?"]),
            f"As a natural karaka, {p} signifies {k}.")
    add("benefics", "Which planets are natural benefics and which are malefics?",
        "Jupiter and Venus are natural benefics, as are the waxing Moon and Mercury when it is not joined with malefics. "
        "The Sun, Mars, Saturn, Rahu and Ketu are natural malefics, and the waning Moon is counted among them.")

    # combustion
    for p, orb in COMBUST_ORB.items():
        retro = f" ({COMBUST_ORB_RETRO[p]}° when retrograde)" if p in COMBUST_ORB_RETRO else ""
        add("combustion", rng.choice([f"How close to the Sun does {p} become combust?", f"What is the combustion orb of {p}?"]),
            f"{p} is usually treated as combust within {orb}°{retro} of the Sun. These are the commonly used classical orbs; some astrologers use slightly different values.")

    # yogas
    for p, name in PANCHA.items():
        add("pancha_mahapurusha", rng.choice([f"What forms {name} yoga?", f"{name} yoga is formed by which planet?"]),
            f"{name} yoga, one of the five Pancha Mahapurusha yogas, forms when {p} is in its own sign or exaltation sign "
            f"and occupies a kendra (the 1st, 4th, 7th or 10th house) from the lagna.")
    add("pancha_mahapurusha", "Name the Pancha Mahapurusha yogas.",
        "The five Pancha Mahapurusha yogas are Ruchaka (Mars), Bhadra (Mercury), Hamsa (Jupiter), Malavya (Venus) and "
        "Shasha (Saturn). Each forms when that planet is in its own or exaltation sign in a kendra from the lagna.")
    for name, cond in YOGAS:
        add("yoga_definition", rng.choice([f"What is {name}?", f"How is {name} formed?", f"Explain {name} briefly."]),
            f"In its common definition, {name} forms when {cond}. Classical texts differ in details and cancellations, "
            f"so the whole chart must be judged before reading results from it.")

    # lagna-based lordships and yogakarakas
    for lg in range(12):
        lords = {h: SIGN_LORD[(lg + h - 1) % 12] for h in range(1, 13)}
        for h in range(1, 13):
            add("house_lord", f"For {SIGNS[lg]} lagna, which planet rules the {ordinal(h)} house?",
                f"For {SIGNS[lg]} lagna the {ordinal(h)} house is {SIGNS[(lg + h - 1) % 12]}, so its lord is {P(lords[h])}.")
        yk = [p for p in SEVEN if any(lords[h] == p for h in (4, 7, 10)) and any(lords[h] == p for h in (5, 9))]
        if yk:
            p = yk[0]
            ruled = [h for h in range(1, 13) if lords[h] == p]
            add("yogakaraka", rng.choice([f"Who is the yogakaraka for {SIGNS[lg]} ascendant?", f"Does {SIGNS[lg]} lagna have a yogakaraka?"]),
                f"For {SIGNS[lg]} lagna, {p} is the yogakaraka: it rules the {join([ordinal(h) for h in ruled])} houses, a kendra and a trikona together.")
        else:
            add("yogakaraka", f"Does {SIGNS[lg]} lagna have a yogakaraka?",
                f"No single planet rules both a kendra (4th, 7th or 10th) and a trikona (5th or 9th) for {SIGNS[lg]} lagna, "
                f"so it has no yogakaraka in the strict sense; good results come through connections between kendra and trikona lords.")
    add("navamsa", "How is the navamsa sign of a planet found?",
        "Each sign is divided into nine navamsas of 3°20'. For movable signs counting starts from the same sign, for fixed "
        "signs from the 9th sign, and for dual signs from the 5th sign. Equivalently, fire signs start from Aries, earth "
        "signs from Capricorn, air signs from Libra and water signs from Cancer. The chart software calculates this.")
    return out


_norm = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))


def too_close(q: str, quiz_qs: list[set]) -> bool:
    w = _norm(q)
    return any(len(w & z) / max(len(w | z), 1) >= 0.75 for z in quiz_qs)


def main() -> None:
    system = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
    quiz_qs = [_norm(r["question"]) for r in read_jsonl(EVALSETS / "quiz.jsonl")]
    rows, dropped = [], 0
    for n, (cat, q, a) in enumerate(build()):
        if too_close(q, quiz_qs):
            dropped += 1
            continue
        rows.append({"id": f"fact-{n:04d}", "task": "fact", "category": cat,
                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": q},
                                  {"role": "assistant", "content": a}]})
    write_jsonl(OUT, rows)
    print(f"wrote {len(rows)} fact examples -> {OUT} (dropped {dropped} too close to quiz questions)")
    print(Counter(r["category"] for r in rows))


if __name__ == "__main__":
    main()
