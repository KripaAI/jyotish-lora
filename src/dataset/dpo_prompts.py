"""DPO step 1: the prompt pool for preference pairs.

The v2 evaluation showed what is left to fix: the adapters decline sensitive requests but then state wrong rules or
volunteer medical claims, and sometimes skip the referral to a professional. Preference pairs are built from the
model's own answers (rejected = a failing sample, chosen = a passing sample or the checked teacher answer), so the
prompts must be new: they must not be the evaluation prompts.

    python -m src.dataset.dpo_prompts safety      # new safety prompts + teacher answers + checks (reuses safety_v2)
    python -m src.dataset.dpo_prompts assemble    # -> data/dpo/prompts.jsonl (safety + rule/fact prompts)

Output rows: id, kind (safety | rule), cat, messages (system + user), reference (checked teacher answer), requirement.
"""
from __future__ import annotations

import random
import sys

from src.common import DATA, EVALSETS, PROMPTS, read_jsonl, write_jsonl
from src.dataset import safety_v2 as sv

DIR = DATA / "dpo"
OUT = DIR / "prompts.jsonl"
RULE_MIX = {"fact": 220, "concept": 150, "placement": 100}   # sampled from the v2 train split only
JACCARD = 0.5


def stage_safety() -> None:
    sv.DIR = DIR / "safety"
    sv.CATEGORIES = {c: (max(8, round(n * 1.6)), d, r) for c, (n, d, r) in sv.CATEGORIES.items()}
    for stage in (sv.stage_questions, sv.stage_answers, sv.stage_check):
        stage()


def _near(words: set, pool: list[set]) -> bool:
    return any(len(words & p) / max(len(words | p), 1) >= JACCARD for p in pool)


def assemble() -> None:
    system = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
    sv.DIR = DIR / "safety"
    sv.CATEGORIES = {c: (max(8, round(n * 1.6)), d, r) for c, (n, d, r) in sv.CATEGORIES.items()}
    seen = [sv._words(r["prompt"]) for r in read_jsonl(EVALSETS / "safety_eval.jsonl")]
    train = read_jsonl(DATA / "sft_v2" / "train.jsonl")
    for r in train:
        if r["task"] in ("safety", "safety_v2"):
            seen.append(sv._words(r["messages"][1]["content"]))

    answers, checks = sv._done(sv.DIR / "answers.jsonl"), sv._done(sv.DIR / "checks.jsonl")
    rows, dropped = [], 0
    for it in sv._items():
        a, c = answers.get(it["id"]), checks.get(it["id"])
        if not (a and c and c["pass"]):
            continue
        w = sv._words(it["text"])
        if _near(w, seen):
            dropped += 1
            continue
        seen.append(w)
        rows.append({"id": "dpo-" + it["id"], "kind": "safety", "cat": it["cat"],
                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": sv.user_message(it)}],
                     "reference": a["answer"], "requirement": sv.CATEGORIES[it["cat"]][2]})
    print(f"safety prompts: {len(rows)} kept, {dropped} dropped as close to eval/train safety prompts")

    rng = random.Random(11)
    for task, n in RULE_MIX.items():
        pool = [r for r in train if r["task"] == task]
        for r in rng.sample(pool, min(n, len(pool))):
            rows.append({"id": "dpo-" + r["id"], "kind": "rule", "cat": task, "messages": r["messages"][:-1],
                         "reference": r["messages"][-1]["content"], "requirement": ""})
    write_jsonl(OUT, rows)
    from collections import Counter
    print(len(rows), "prompts ->", OUT, dict(Counter((r["kind"], r["cat"]) for r in rows)))


if __name__ == "__main__":
    {"safety": stage_safety, "assemble": assemble}[sys.argv[1]]()
