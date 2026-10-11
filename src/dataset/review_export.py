"""Phase 3.8: human review.

    python -m src.dataset.review_export export     # -> data/reviews/review_batch.csv (5% sample, at least 300)
    (open the CSV in Excel; set decision to approve / edit / reject; put a corrected reply in edited_answer)
    python -m src.dataset.review_export import     # applies decisions -> data/sft/reviewed.jsonl
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter

from src.common import DATA, RUNS, SFT, read_jsonl, write_jsonl

REVIEW_CSV = DATA / "reviews" / "review_batch.csv"
SHARE, MINIMUM = 0.05, 300
FIELDS = ["id", "task", "question", "answer", "factcheck_reason", "filter_warnings",
          "decision", "edited_answer", "notes"]


def export() -> None:
    rows = list(read_jsonl(SFT / "filtered.jsonl"))
    rng = random.Random(7)
    n = min(len(rows), max(MINIMUM, round(SHARE * len(rows))))
    # stratify by task so every task type is reviewed
    by_task: dict[str, list] = {}
    for r in rows:
        by_task.setdefault(r["task"], []).append(r)
    sample = []
    for t, items in by_task.items():
        k = max(5, round(n * len(items) / len(rows)))
        sample += rng.sample(items, min(k, len(items)))
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEW_CSV, "w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel reads UTF-8
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sample:
            w.writerow({"id": r["id"], "task": r["task"], "question": r["messages"][1]["content"],
                        "answer": r["messages"][2]["content"],
                        "factcheck_reason": (r.get("factcheck") or {}).get("reason", ""),
                        "filter_warnings": " | ".join(r.get("filter_warnings", [])),
                        "decision": "", "edited_answer": "", "notes": ""})
    print(f"exported {len(sample)} examples -> {REVIEW_CSV}")


def import_() -> None:
    with open(REVIEW_CSV, encoding="utf-8-sig", newline="") as f:
        reviews = {r["id"]: r for r in csv.DictReader(f)}
    undecided = [i for i, r in reviews.items() if r["decision"].strip().lower() not in ("approve", "edit", "reject")]
    if undecided:
        raise SystemExit(f"{len(undecided)} rows have no decision (approve/edit/reject), e.g. {undecided[:3]}")
    decisions = Counter(r["decision"].strip().lower() for r in reviews.values())
    out = []
    for row in read_jsonl(SFT / "filtered.jsonl"):
        rv = reviews.get(row["id"])
        if rv:
            d = rv["decision"].strip().lower()
            if d == "reject":
                continue
            if d == "edit" and rv["edited_answer"].strip():
                row["messages"][2]["content"] = rv["edited_answer"].strip()
            row["review"] = {"decision": d, "notes": rv["notes"]}
        out.append(row)
    write_jsonl(SFT / "reviewed.jsonl", out)
    rate = decisions["reject"] / max(len(reviews), 1)
    gate = "PASS" if rate < 0.10 else "FAIL - fix the teacher prompts and regenerate the affected batch"
    report = (f"# Human review\n\nReviewed {len(reviews)}: {dict(decisions)}.\n\n"
              f"Rejection rate {rate:.1%} (Gate 3 needs under 10%): **{gate}**.\n")
    (RUNS / "review_report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["export", "import"])
    a = ap.parse_args()
    export() if a.command == "export" else import_()
