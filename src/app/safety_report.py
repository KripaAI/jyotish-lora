"""Measure the safety layer.

    python -m src.app.safety_report dev       # tuning set: recall on the 335 generated sensitive prompts, false blocks on normal ones
    python -m src.app.safety_report heldout   # held-out: evalsets/safety_eval.jsonl (50), quiz (100), test questions (60)

dev: sensitive prompts = data/dpo/safety/questions.jsonl (labelled with a category; not the evaluation prompts);
     normal prompts   = user questions of the v2 train split (concept, placement, fact, full_chart, remedies, comparison,
                        uncertainty), which contain no sensitive request.
held-out: never used to write or tune a rule; run once at the end and reported as it comes out.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from src.app.safety import check_input, question_part
from src.common import DATA, EVALSETS, read_jsonl


def sensitive_dev():
    return [(m["text"], r["cat"]) for r in read_jsonl(DATA / "dpo" / "safety" / "questions.jsonl") for m in r["messages"]]


def normal_dev():
    rows = read_jsonl(DATA / "sft_v2" / "train.jsonl")
    out = [(question_part(r["messages"][1]["content"]), r["task"]) for r in rows
           if r["task"] in ("concept", "placement", "fact", "full_chart", "remedies", "comparison", "uncertainty")]
    extra = DATA / "dpo" / "normals" / "questions.jsonl"       # ordinary personal questions in the sensitive prompts' style
    if extra.exists():
        out += [(m["text"], "personal_normal") for r in read_jsonl(extra) for m in r["messages"]]
    return out


def run(show: int) -> None:
    sens, norm = sensitive_dev(), normal_dev()
    hit, by_cat, miss = 0, Counter(), []
    tot = Counter(c for _, c in sens)
    for text, cat in sens:
        v = check_input(text)
        if v.action == "block":
            hit += 1
            by_cat[cat] += 1
        else:
            miss.append((cat, text))
    print(f"SENSITIVE (dev): blocked {hit}/{len(sens)} = {hit / len(sens):.1%}")
    for c in tot:
        print(f"   {c:20s} {by_cat[c]:3d}/{tot[c]:3d}")
    fp = [(t, check_input(t)) for t, _ in norm]
    fp = [(t, v) for t, v in fp if v.action == "block"]
    print(f"NORMAL (dev): wrongly blocked {len(fp)}/{len(norm)} = {len(fp) / len(norm):.1%}")
    print("   by category:", dict(Counter(v.category for _, v in fp)))
    for t, v in fp[:show]:
        print("   FP [%s] %s | %s" % (v.category, v.reason[-50:], t[:110].replace("\n", " ")))
    for c, t in miss[:show]:
        print("   MISS [%s] %s" % (c, t[:140].replace("\n", " ")))


def heldout() -> None:
    safety = list(read_jsonl(EVALSETS / "safety_eval.jsonl"))
    quiz = list(read_jsonl(EVALSETS / "quiz.jsonl"))
    blocked = {s["id"]: check_input(s["prompt"]) for s in safety}
    n = sum(v.action == "block" for v in blocked.values())
    print(f"SAFETY EVAL (50): blocked {n}/50")
    print("   by category:", dict(Counter(s["category"] for s in safety if blocked[s["id"]].action == "block")),
          "of", dict(Counter(s["category"] for s in safety)))
    for s in safety:
        if blocked[s["id"]].action == "allow":
            print("   not blocked:", s["id"], s["category"])
    qfp = [q for q in quiz if check_input(q["question"]).action == "block"]
    print(f"QUIZ (100 ordinary fact questions): wrongly blocked {len(qfp)}")
    for q in qfp:
        print("   ", q["question"][:100])
    tests = [json.loads(l) for l in open(DATA / "sft_v2" / "test.jsonl", encoding="utf-8")]
    tfp = [t for t in tests if t["task"] != "safety" and check_input(t["messages"][1]["content"]).action == "block"]
    print(f"TEST questions (non-safety, {sum(t['task'] != 'safety' for t in tests)}): wrongly blocked {len(tfp)}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dev"
    run(int(sys.argv[2]) if len(sys.argv) > 2 else 12) if mode == "dev" else heldout()
