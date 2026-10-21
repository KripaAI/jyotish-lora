"""Build the v5 training data: a rebalanced mix after v4's failure.

v4 (103k rows, 95% short rule paraphrases sharing one template) learned facts but answered everything, including safety
requests, by reciting a classical rule in that template: Phase 1 safety fell from 82% (v2-8b) to 6%. v5 keeps the knowledge and
restores voice and safety by changing the mix:

    stream                                   rows (approx)   weight
    v3 conversational teacher answers         1,421           x3     (voice, long readings, thinking on for charts)
    v2 table facts + facts_v4                 723 + 727       x1, x2
    safety: Phase 1 safety + safety_v2        82 + 183        x3
    safety_v5 (local questions, reviewed replies)  ~1,500     x1
    chart drills                              2,000           x1
    rule_qa: ONE pair per rule, boilerplate closing removed   ~31,500   x1

Review edits/rejects from data/sft_v4 still apply. Validation and test keep the v1 ids.

    python -m src.dataset.build_v5       # -> data/sft_v5/{train,val,test}.jsonl, manifest.json
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter

from src.common import DATA, EVALSETS, ROOT, read_jsonl, sha256_file, write_jsonl
from src.dataset.build_v3 import render_row
from src.dataset.facts import _norm

V3, V4, V5 = DATA / "sft_v3", DATA / "sft_v4", DATA / "sft_v5"
CONVERSATIONAL = {"full_chart", "placement", "concept", "remedies", "comparison", "uncertainty"}
SEED = 13
# Closing sentences the paraphraser appended to almost every answer; v4 learned them as the shape of every reply.
BOILER = re.compile(r"(?:^|(?<=[.!?]))\s*[^.!?]*\b(?:whole|entire|overall|complete)\s+(?:birth\s+|natal\s+)?(?:chart|horoscope|configuration)\b[^.!?]*[.!?]"
                    r"|(?:^|(?<=[.!?]))\s*[^.!?]*\btendenc(?:y|ies)\b[^.!?]*\bcertaint(?:y|ies)\b[^.!?]*[.!?]", re.I)


def strip_boiler(answer: str) -> str:
    out = BOILER.sub("", answer).strip()
    return out if len(out.split()) >= 25 else answer      # keep the original if stripping would gut it


def main() -> None:
    rng = random.Random(SEED)
    rejects = set(json.loads((V4 / "review_rejects.json").read_text(encoding="utf-8"))) if (V4 / "review_rejects.json").exists() else set()
    edits = json.loads((V4 / "review_edits.json").read_text(encoding="utf-8")) if (V4 / "review_edits.json").exists() else {}
    v4_train = {r["id"]: r for r in read_jsonl(V4 / "train.jsonl")}     # already carries the review edits
    val, test = list(read_jsonl(V3 / "val.jsonl")), list(read_jsonl(V3 / "test.jsonl"))
    eval_q = {" ".join(sorted(_norm(r["messages"][1]["content"]))) for r in val + test}
    eval_q |= {" ".join(sorted(_norm(r["question"]))) for r in read_jsonl(EVALSETS / "quiz.jsonl")}

    train, mix = [], Counter()

    def add(row, times, label):
        for _ in range(times):
            train.append(row)
        mix[label] += times

    for r in read_jsonl(V3 / "train.jsonl"):
        if r["id"] in rejects:
            continue
        r = v4_train.get(r["id"], r)
        if r["task"] in CONVERSATIONAL:
            add(r, 3, "teacher_answers_x3")
        elif r["task"] in ("safety", "safety_v2"):
            add(r, 3, "phase1_safety_x3")
        else:                                    # v2 table facts
            add(r, 1, "facts_v2")

    for r in v4_train.values():
        if r["task"] == "fact_v4":
            add(r, 2, "facts_v4_x2")
        elif r["task"] == "drill":
            add(r, 1, "drills")

    by_rule: dict[str, list] = {}
    for r in read_jsonl(V4 / "rule_qa.jsonl"):
        if r["id"] not in rejects:
            by_rule.setdefault(r["rule_id"], []).append(r)
    for rid, pairs in sorted(by_rule.items()):
        hing = [p for p in pairs if p.get("language") == "hinglish"]
        pick = rng.choice(hing) if hing and rng.random() < 0.3 else rng.choice(pairs)
        answer = edits.get(pick["id"], pick["messages"][2]["content"])
        msgs = pick["messages"][:2] + [{"role": "assistant", "content": strip_boiler(answer)}]
        add(render_row({"id": pick["id"], "task": "rule_qa", "messages": msgs}), 1, "rule_qa_one_per_rule")

    for r in read_jsonl(V5 / "safety_fixed.jsonl"):
        key = " ".join(sorted(_norm(r["messages"][1]["content"])))
        if key in eval_q:
            continue
        add(render_row({"id": r["id"], "task": "safety_v5", "messages": r["messages"]}), 1, "safety_v5")

    rng.shuffle(train)
    assert all(r["prompt"].endswith("<|im_start|>assistant\n") == r["thinking"] for r in train)
    manifest = {"version": "v5", "mix": dict(mix),
                "why": "v4's 95% single-template paraphrase mix collapsed voice and safety (Phase 1 safety 82% -> 6%); v5 rebalances",
                "render": "as build_v3/build_v4", "splits": {}}
    for name, items in (("train", train), ("val", val), ("test", test)):
        path = V5 / f"{name}.jsonl"
        write_jsonl(path, items)
        manifest["splits"][name] = {"examples": len(items), "sha256": sha256_file(path),
                                    "tasks": dict(Counter(i["task"] for i in items)),
                                    "thinking_on": sum(bool(i.get("thinking")) for i in items)}
    manifest["system_prompt_sha256"] = sha256_file(ROOT / "prompts" / "system_v1.txt")
    (V5 / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total = len(train)
    print(f"v5 train {total} rows; mix:", {k: f"{v} ({v / total:.1%})" for k, v in mix.items()})


if __name__ == "__main__":
    main()
