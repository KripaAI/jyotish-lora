"""Stage 2B.2: quiz v2 = table-built items in new wording and Hinglish (graded by code) + Claude-written items from
held-out rules (graded by a judge). Eval only; never trained on.

    python -m src.eval.build_quiz_v2 claude        # one request per held-out rule pack (resumable)
    python -m src.eval.build_quiz_v2 finalize      # -> evalsets/quiz_v2_rules.jsonl
    python -m src.eval.build_quiz_v2 tables        # -> evalsets/quiz_v2_tables.jsonl (code)
    python -m src.eval.build_quiz_v2 assemble      # -> evalsets/quiz_v2.jsonl (both, with a "grader" field)
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter

from src.chart.constants import (
    DASHA_YEARS, DEBILITATION, EXALTATION, FIXED_KARAKAS, NAKSHATRA_LORD, NAKSHATRAS, OWN_SIGNS, PLANETS_SANSKRIT, SEVEN,
    SIGN_LORD, SIGNS, SIGNS_SANSKRIT, SPECIAL_ASPECTS, ordinal,
)
from src.common import DATA, EVALSETS, read_jsonl, write_jsonl
from src.dataset import backends, teacher
from src.dataset.facts import PANCHA, _norm, too_close
from src.dataset.facts_v4 import HI_PLANET, VARGA_USES
from src.dataset.rules import load_results

RESULTS = DATA / "eval_v2" / "quiz_results.jsonl"
OUT_RULES = EVALSETS / "quiz_v2_rules.jsonl"
OUT_TABLES = EVALSETS / "quiz_v2_tables.jsonl"
OUT = EVALSETS / "quiz_v2.jsonl"
MODEL = "claude-sonnet-5-5"
CATEGORIES = ["yoga", "placement", "lordship", "dasha", "nakshatra", "varga", "strength", "aspect", "karaka",
              "remedy", "compatibility", "prashna", "muhurta", "concept"]
SCHEMA = {"type": "object",
          "properties": {"items": {"type": "array", "items": {
              "type": "object",
              "properties": {"category": {"type": "string", "enum": CATEGORIES}, "question": {"type": "string"},
                             "answers": {"type": "array", "items": {"type": "string"}}, "basis": {"type": "string"}},
              "required": ["category", "question", "answers", "basis"], "additionalProperties": False}}},
          "required": ["items"], "additionalProperties": False}
SYSTEM = f"""You write short factual quiz questions for evaluating a Vedic astrology model. You receive RULE RECORDS extracted from classical or modern Jyotish texts (statement, conditions, text, tradition).

Write 3 to 6 quiz items from the records that state something specific and checkable. Each item:
- "question": one sentence a student could answer from memory of the tradition. Name the text or tradition when the rule is specific to it ("According to Phaladeepika, ..."). Never mention records, passages, chapters or verses.
- "answers": one or more acceptable short answers (a planet, a sign, a house number such as "7th", a yoga name, a number of years, or a phrase of at most 8 words). All listed answers must be correct and equivalent.
- "category": one of {", ".join(CATEGORIES)}.
- "basis": the record's statement you used, copied.
Skip records that are vague, that merely interpret a chart, that predict death, name diseases, or carry stigma, and skip trivial table facts (exaltation signs, sign lords, nakshatra lords, dasha years), which are tested elsewhere.
Return JSON: {{"items": [...]}}"""


# ------------------------------------------------------------------------------------------ Claude items (held-out rules)
def stage_claude(workers: int) -> None:
    packs = [r for r in load_results("heldout").values() if r.get("type") == "succeeded"]
    done = {r["custom_id"] for r in read_jsonl(RESULTS)} if RESULTS.exists() else set()
    todo = [r for r in packs if f"qz-{r['custom_id']}" not in done]
    print(f"{len(packs)} held-out rule packs, {len(todo)} to do", flush=True)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def one(r):
        rules = json.loads(r["text"]).get("rules", [])
        user = "RULE RECORDS\n\n" + "\n\n".join(
            f"[{i + 1}] statement: {g['statement']}\nconditions: {g['conditions']}\ntext: {g['text'] or '(not named)'}\ntradition: {g['tradition']}"
            for i, g in enumerate(rules))
        req = teacher.make_request(f"qz-{r['custom_id']}", SYSTEM, user, "medium", SCHEMA)
        row = backends.call_with_wait("claude", req, MODEL)
        row["item_ids"] = r.get("item_ids", [])
        return row

    with open(RESULTS, "a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        for n, fut in enumerate(as_completed([ex.submit(one, r) for r in todo]), 1):
            f.write(json.dumps(fut.result(), ensure_ascii=False) + "\n")
            f.flush()
            if n % 5 == 0 or n == len(todo):
                print(f"{n}/{len(todo)} packs", flush=True)


def finalize() -> None:
    old = [_norm(r["question"]) for r in read_jsonl(EVALSETS / "quiz.jsonl")]
    train_qs = [_norm(r["messages"][1]["content"]) for r in read_jsonl(DATA / "sft_v4" / "train.jsonl") if r["task"] in ("rule_qa", "fact_v4", "fact")]
    items, seen, dropped = [], set(), Counter()
    for r in read_jsonl(RESULTS):
        if r.get("type") != "succeeded":
            dropped["failed_pack"] += 1
            continue
        for it in json.loads(r["text"]).get("items", []):
            q, ans = it["question"].strip(), [a.strip() for a in it["answers"] if a.strip()]
            key = " ".join(sorted(_norm(q)))
            if not q or not ans or key in seen:
                dropped["empty_or_duplicate"] += 1
                continue
            if too_close(q, old) or too_close(q, train_qs):
                dropped["overlap"] += 1
                continue
            seen.add(key)
            items.append({"id": f"quiz2-{len(items):04d}", "category": it["category"], "question": q, "answers": ans,
                          "basis": it["basis"], "source_chunks": r.get("item_ids", []), "grader": "claude"})
    write_jsonl(OUT_RULES, items)
    print(f"quiz_v2_rules: {len(items)} items -> {OUT_RULES}; dropped {dict(dropped)}; {dict(Counter(i['category'] for i in items))}")


# ------------------------------------------------------------------------------------------ table items (code-graded)
def build_tables() -> list[dict]:
    """Table facts in wording the training set did not use verbatim: Hinglish, Sanskrit terms, indirect phrasing.
    Answers list every accepted spelling so the code grader can match any of them."""
    rng = random.Random(21)
    items = []
    add = lambda cat, q, answers: items.append({"category": cat, "question": q, "answers": answers, "grader": "code"})
    sk = lambda p: [p, PLANETS_SANSKRIT[p], HI_PLANET[p]]
    sg = lambda s: [s, SIGNS_SANSKRIT[SIGNS.index(s)]]
    for i in rng.sample(range(27), 14):
        n, lord = NAKSHATRAS[i], NAKSHATRA_LORD[i]
        add("nakshatra_lord_hi", rng.choice([f"{n} nakshatra ka swami kaun hai?", f"{n} ka dasha lord kaun sa graha hai?",
                                             f"Vimshottari mein {n} nakshatra kis graha ka hai?"]), sk(lord))
    for p in SEVEN:
        ex, de = SIGNS[EXALTATION[p]], SIGNS[DEBILITATION[p]]
        add("exaltation_hi", rng.choice([f"{HI_PLANET[p]} ki uccha rashi kaunsi hai?", f"{HI_PLANET[p]} kis rashi mein uccha hota hai?"]), sg(ex))
        add("debilitation_hi", rng.choice([f"{HI_PLANET[p]} ki neech rashi kaunsi hai?", f"In which rashi does {HI_PLANET[p]} become neecha?"]), sg(de))
        own = [SIGNS[s] for s in OWN_SIGNS[p]]
        add("own_sign_hi", f"{HI_PLANET[p]} kin rashiyon ka swami hai?", [" and ".join(own), " aur ".join(SIGNS_SANSKRIT[s] for s in OWN_SIGNS[p])] + (own if len(own) == 1 else []))
    for s in rng.sample(range(12), 8):
        add("sign_lord_hi", rng.choice([f"{SIGNS_SANSKRIT[s]} rashi ka swami kaun hai?", f"Who is the adhipati of {SIGNS_SANSKRIT[s]}?"]), sk(SIGN_LORD[s]))
    for p, y in DASHA_YEARS.items():
        add("dasha_years_hi", rng.choice([f"{HI_PLANET[p]} mahadasha kitne saal ki hoti hai?", f"{HI_PLANET[p]} ki Vimshottari dasha kitne varsh chalti hai?"]), [str(y), f"{y} years", f"{y} saal", f"{y} varsh"])
    for p, yoga in PANCHA.items():
        add("pancha_mahapurusha", rng.choice([f"{yoga} yoga kaun sa graha banata hai?", f"Which graha gives {yoga} yoga when strong in a kendra?"]), sk(p))
    for p, extra in SPECIAL_ASPECTS.items():
        special = [a for a in extra if a != 7]
        add("aspects", f"{HI_PLANET[p]} ki vishesh drishti kaun se bhav par padti hai (7th ke alawa)?",
            [f"{ordinal(special[0])} and {ordinal(special[1])}", f"{special[0]} and {special[1]}", f"{special[0]}, {special[1]}", f"{ordinal(special[0])}, {ordinal(special[1])}"])
    for q, a in [("Kendra bhav kaun kaun se hote hain?", ["1, 4, 7 and 10", "1st, 4th, 7th and 10th", "1, 4, 7, 10"]),
                 ("Trikona bhav kaun se hain?", ["1, 5 and 9", "1st, 5th and 9th", "1, 5, 9"]),
                 ("Dusthana bhav kaun se hain?", ["6, 8 and 12", "6th, 8th and 12th", "6, 8, 12"]),
                 ("Upachaya bhav kaun kaun se hain?", ["3, 6, 10 and 11", "3rd, 6th, 10th and 11th", "3, 6, 10, 11"]),
                 ("Maraka sthan kaun se bhav hain?", ["2 and 7", "2nd and 7th", "2, 7"]),
                 ("Vimshottari dasha ka poora chakra kitne varsh ka hai?", ["120", "120 years", "120 varsh", "120 saal"]),
                 ("Ashtakoota guna milan mein kul kitne gun hote hain?", ["36"]),
                 ("Ashtakoota mein sabse zyada ank kis koota ke hain?", ["Nadi", "Nadi (8)"]),
                 ("Bharat sarkar ka maanak ayanamsa kaunsa hai?", ["Lahiri", "Chitrapaksha", "Lahiri (Chitrapaksha)"]),
                 ("Janma ke samay kaunsi mahadasha chalti hai?", ["the lord of the Moon's birth nakshatra", "the Moon's nakshatra lord", "janma nakshatra lord"]),
                 ("Mangal dosha (Manglik) Mangal ke kin bhavon mein banta hai?", ["1, 2, 4, 7, 8 and 12", "1st, 2nd, 4th, 7th, 8th and 12th", "1, 2, 4, 7, 8, 12"])]:
        add("misc_hi", q, a)
    for code, name, use in rng.sample(VARGA_USES, 7):
        add("varga", f"{name} ({code}) chart kis vishay ke liye dekha jata hai?", [use.split(",")[0].split(" and ")[0].strip(), name, code])
    for p in rng.sample(list(FIXED_KARAKAS), 6):
        first = FIXED_KARAKAS[p].split(",")[0].strip()
        add("karaka_hi", f"{first.capitalize()} ka karak graha kaun hai?", sk(p))
    return items


def tables() -> None:
    old = [_norm(r["question"]) for r in read_jsonl(EVALSETS / "quiz.jsonl")]
    train_qs = [_norm(r["messages"][1]["content"]) for r in read_jsonl(DATA / "sft_v4" / "train.jsonl") if r["task"] in ("fact_v4", "fact")]
    rows, dropped = [], 0
    for it in build_tables():
        if too_close(it["question"], old) or too_close(it["question"], train_qs):
            dropped += 1
            continue
        rows.append({"id": f"quiz2t-{len(rows):04d}", **it})
    write_jsonl(OUT_TABLES, rows)
    print(f"quiz_v2_tables: {len(rows)} items -> {OUT_TABLES} (dropped {dropped} too close to a training or old quiz question)")


def assemble() -> None:
    rows = list(read_jsonl(OUT_TABLES)) + [{**r, "grader": r.get("grader", "claude")} for r in read_jsonl(OUT_RULES)]
    write_jsonl(OUT, rows)
    print(f"quiz_v2: {len(rows)} items -> {OUT}; graders {dict(Counter(r['grader'] for r in rows))}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["claude", "finalize", "tables", "assemble"])
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    {"claude": lambda: stage_claude(a.workers), "finalize": finalize, "tables": tables, "assemble": assemble}[a.command]()


if __name__ == "__main__":
    main()
