"""Phase 3.3: rule-fidelity quiz (100 short questions with known answers), built from the reference
tables so every answer is correct by construction. Eval only; never used for training.

    python -m src.eval.build_quiz     # -> evalsets/quiz.jsonl
"""
from __future__ import annotations

import random

from src.chart.constants import (
    DASHA_YEARS, DEBILITATION, EXALTATION, NAKSHATRA_LORD, NAKSHATRAS, OWN_SIGNS, SEVEN, SIGN_LORD, SIGNS,
)
from src.common import EVALSETS, write_jsonl


def build() -> list[dict]:
    items = []
    add = lambda cat, q, answers: items.append({"category": cat, "question": q, "answers": answers})
    for p in SEVEN:
        add("exaltation", f"In which sign is {p} exalted?", [SIGNS[EXALTATION[p]]])
        add("debilitation", f"In which sign is {p} debilitated?", [SIGNS[DEBILITATION[p]]])
    for p in SEVEN:
        own = [SIGNS[s] for s in OWN_SIGNS[p]]
        add("own_sign", f"Which sign(s) does {p} own?", own)
    for s in SIGNS:
        add("sign_lord", f"Which planet rules {s}?", [SIGN_LORD[SIGNS.index(s)]])
    for p, y in DASHA_YEARS.items():
        add("dasha_years", f"How many years does the Vimshottari mahadasha of {p} last?", [str(y)])
    rng = random.Random(3)
    for i in rng.sample(range(27), 27):
        add("nakshatra_lord", f"Which planet rules the nakshatra {NAKSHATRAS[i]} in the Vimshottari scheme?", [NAKSHATRA_LORD[i]])
    fixed = [
        ("pancha_mahapurusha", "Which planet forms Ruchaka yoga when in its own or exaltation sign in a kendra?", ["Mars"]),
        ("pancha_mahapurusha", "Which planet forms Bhadra yoga when in its own or exaltation sign in a kendra?", ["Mercury"]),
        ("pancha_mahapurusha", "Which planet forms Hamsa yoga when in its own or exaltation sign in a kendra?", ["Jupiter"]),
        ("pancha_mahapurusha", "Which planet forms Malavya yoga when in its own or exaltation sign in a kendra?", ["Venus"]),
        ("pancha_mahapurusha", "Which planet forms Shasha yoga when in its own or exaltation sign in a kendra?", ["Saturn"]),
        ("aspects", "Besides the 7th, which houses does Mars aspect (counted from itself)?", ["4th and 8th", "4 and 8"]),
        ("aspects", "Besides the 7th, which houses does Jupiter aspect (counted from itself)?", ["5th and 9th", "5 and 9"]),
        ("aspects", "Besides the 7th, which houses does Saturn aspect (counted from itself)?", ["3rd and 10th", "3 and 10"]),
        ("houses", "Which houses are the kendras (angles)?", ["1, 4, 7 and 10"]),
        ("houses", "Which houses are the trikonas (trines)?", ["1, 5 and 9"]),
        ("houses", "Which houses are the dusthanas?", ["6, 8 and 12"]),
        ("houses", "Which houses are the upachaya houses?", ["3, 6, 10 and 11"]),
        ("houses", "Which house is the primary house of marriage and spouse?", ["7th"]),
        ("houses", "Which house is the primary house of career and status?", ["10th"]),
        ("houses", "Which house is the primary house of children?", ["5th"]),
        ("houses", "Which house signifies longevity?", ["8th"]),
        ("yogas", "What forms Gajakesari yoga?", ["Jupiter in a kendra from the Moon"]),
        ("yogas", "What is Kemadruma yoga?", ["no planets in the 2nd and 12th from the Moon"]),
        ("yogas", "What forms Budhaditya yoga?", ["Sun and Mercury together in one sign"]),
        ("yogas", "What is a Viparita Raja yoga?", ["lords of the 6th, 8th or 12th placed in the 6th, 8th or 12th"]),
        ("dasha", "What is the total length of the Vimshottari dasha cycle?", ["120 years"]),
        ("dasha", "In Vimshottari, which mahadasha follows the Venus mahadasha?", ["Sun"]),
        ("dasha", "Which mahadasha starts at birth in Vimshottari?", ["the lord of the Moon's birth nakshatra"]),
        ("karakas", "Which planet is the natural significator (karaka) of the father?", ["Sun"]),
        ("karakas", "Which planet is the natural significator (karaka) of the mother?", ["Moon"]),
        ("karakas", "Which planet is the natural significator of children and wisdom?", ["Jupiter"]),
        ("vargas", "Which divisional chart is used chiefly for marriage and the strength of planets?", ["Navamsa (D9)"]),
        ("vargas", "Which divisional chart is used for career?", ["Dasamsa (D10)"]),
        ("misc", "Which ayanamsa is the Indian government standard (Chitrapaksha)?", ["Lahiri"]),
        ("misc", "How many nakshatras are used in Vedic astrology for dasha calculation?", ["27"]),
        ("misc", "Which planets are natural benefics?", ["Jupiter, Venus, Mercury and Moon"]),
    ]
    for cat, q, a in fixed:
        add(cat, q, a)
    return items[:100]


if __name__ == "__main__":
    items = build()
    for i, it in enumerate(items):
        it["id"] = f"quiz-{i:03d}"
    n = write_jsonl(EVALSETS / "quiz.jsonl", items)
    print(f"wrote {n} quiz items -> {EVALSETS / 'quiz.jsonl'}")
