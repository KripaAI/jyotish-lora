"""Constitution IV.2: at least 200 training rows reviewed by a person before a training run.

    python -m src.dataset.review_v4 export     # -> data/reviews/review_v4.csv (200 rows, stratified by stream)
    python -m src.dataset.review_v4 import     # reads the verdict column; rejected ids go to data/sft_v4/review_rejects.json
                                               # and build_v4 drops them; writes runs/review_v4_report.md

Fill the CSV in Excel: verdict = approve | edit | reject; put a corrected answer in `edited_answer` for `edit`, a short reason in `note`.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter

from src.common import DATA, RUNS, read_jsonl

CSV = DATA / "reviews" / "review_v4.csv"
REJECTS = DATA / "sft_v4" / "review_rejects.json"
EDITS = DATA / "sft_v4" / "review_edits.json"
TRAIN = DATA / "sft_v4" / "train.jsonl"
QUOTA = {"rule_qa": 110, "fact_v4": 20, "drill": 25, "concept": 10, "placement": 10, "full_chart": 10, "safety_v2": 10, "remedies": 5}


def export() -> None:
    rows = list(read_jsonl(TRAIN))
    rng = random.Random(42)
    picked = []
    for task, n in QUOTA.items():
        pool = [r for r in rows if r["task"] == task]
        picked += rng.sample(pool, min(n, len(pool)))
    CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "task", "question", "answer", "verdict", "edited_answer", "note"])
        for r in picked:
            q = r["messages"][1]["content"]
            q = q.split("Question: ")[-1] if q.startswith("Chart:") else q
            w.writerow([r["id"], r["task"], q, r["messages"][2]["content"], "", "", ""])
    print(f"{len(picked)} rows -> {CSV}; by stream {dict(Counter(r['task'] for r in picked))}")


def refresh() -> None:
    """After a data rebuild: put the current answer text into the review CSV for the same ids. A row whose id no longer
    exists is replaced by a random row of the same stream. Model verdicts made on changed text are discarded."""
    rows = {r["id"]: r for r in read_jsonl(TRAIN)}
    by_task: dict[str, list] = {}
    for r in rows.values():
        by_task.setdefault(r["task"], []).append(r)
    old = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))
    rng, used, out, changed, replaced = random.Random(7), {r["id"] for r in old}, [], set(), 0
    for row in old:
        r = rows.get(row["id"])
        if r is None:
            r = rng.choice([x for x in by_task[row["task"]] if x["id"] not in used])
            used.add(r["id"])
            replaced += 1
        q = r["messages"][1]["content"]
        q = q.split("Question: ")[-1] if q.startswith("Chart:") else q
        a = r["messages"][2]["content"]
        if r["id"] != row["id"] or a != row["answer"]:
            changed.add(r["id"])
            row = {"id": r["id"], "task": r["task"], "question": q, "answer": a, "verdict": "", "edited_answer": "", "note": ""}
        out.append(row)
    with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "task", "question", "answer", "verdict", "edited_answer", "note"])
        w.writeheader()
        w.writerows(out)
    res = DATA / "reviews" / "review_v4_gemini.jsonl"
    if res.exists():
        keep = [l for l in open(res, encoding="utf-8") if json.loads(l)["id"] not in changed and "error" not in json.loads(l)]
        res.write_text("".join(keep), encoding="utf-8")
    print(f"refreshed {CSV}: {len(changed)} rows changed ({replaced} replaced); kept model verdicts only for unchanged rows")


def import_() -> None:
    rejects, edits, verdicts = [], {}, Counter()
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            v = (row.get("verdict") or "").strip().lower()
            verdicts[v or "(blank)"] += 1
            if v == "reject":
                rejects.append(row["id"])
            elif v == "edit" and row.get("edited_answer", "").strip():
                edits[row["id"]] = row["edited_answer"].strip()
    REJECTS.write_text(json.dumps(sorted(rejects), indent=0), encoding="utf-8")
    EDITS.write_text(json.dumps(edits, indent=1, ensure_ascii=False), encoding="utf-8")
    reviewed = sum(v for k, v in verdicts.items() if k != "(blank)")
    rate = len(rejects) / max(reviewed, 1)
    lines = [f"# Human review v4 ({reviewed} rows reviewed)", "", f"Verdicts: {dict(verdicts)}", "",
             f"Reject rate {rate:.0%} (Gate A requires under 10%): {'PASS' if reviewed >= 200 and rate < 0.10 else 'NOT MET'}.",
             f"{len(rejects)} rejected ids and {len(edits)} edits are applied by `python -m src.dataset.build_v4`."]
    (RUNS / "review_v4_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["export", "refresh", "import"])
    a = ap.parse_args(argv)
    {"export": export, "refresh": refresh, "import": import_}[a.command]()


if __name__ == "__main__":
    main()
