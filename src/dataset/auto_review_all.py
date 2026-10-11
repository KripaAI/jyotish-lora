"""Model review (Claude Sonnet 5.5) of EVERY example in data/sft/filtered.jsonl, resumable.

Verdicts are appended to data/sft/auto_review.jsonl as they finish. Decisions already made in the 300-example
review sample (data/reviews/review_batch.csv) are reused. At the end it writes data/sft/auto_reviewed.jsonl (examples
the reviewer approved) and runs/auto_review_report.md. This is NOT the human review required by Constitution IV and it
does not touch reviewed.jsonl.

    python -m src.dataset.auto_review_all [--workers 4]
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common import RUNS, SFT, read_jsonl, write_jsonl
from src.dataset import auto_review

OUT = SFT / "auto_review.jsonl"


def append(row: dict) -> None:
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_done() -> dict[str, dict]:
    done: dict[str, dict] = {}
    if OUT.exists():
        for r in read_jsonl(OUT):
            if "decision" in r:
                done[r["id"]] = r
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    rows = list(read_jsonl(SFT / "filtered.jsonl"))
    done = load_done()

    # reuse the decisions from the 300-example sample
    if auto_review.REVIEW_CSV.exists():
        with open(auto_review.REVIEW_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r["decision"] in ("approve", "reject") and r["id"] not in done and r["notes"].startswith("auto-review"):
                    rec = {"id": r["id"], "decision": r["decision"], "reason": r["notes"], "source": "sample"}
                    append(rec)
                    done[r["id"]] = rec

    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(rows)} examples; {len(done)} already reviewed; reviewing {len(todo)} with {auto_review.MODEL}", flush=True)
    counts: Counter = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(auto_review.review_one, {"id": r["id"], "task": r["task"],
                                                     "question": r["messages"][1]["content"],
                                                     "answer": r["messages"][2]["content"]}): r["id"] for r in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                res = {"id": futs[fut], "error": str(e)[:200]}
            if "decision" in res:
                append({**res, "source": "all"})
                done[res["id"]] = res
            counts[res.get("decision", "error")] += 1
            if n % 10 == 0 or n == len(todo):
                print(f"{n}/{len(todo)} done {dict(counts)}", flush=True)

    kept = [r for r in rows if done.get(r["id"], {}).get("decision") == "approve"]
    missing = [r["id"] for r in rows if r["id"] not in done]
    write_jsonl(SFT / "auto_reviewed.jsonl", [{**r, "review": {"decision": "approve", "by": "Sonnet 5.5 (model, not human)"}} for r in kept])
    by_task_in, by_task_out = Counter(r["task"] for r in rows), Counter(r["task"] for r in kept)
    lines = ["# Model review report (Sonnet 5.5; NOT the human review)", "",
             f"Reviewed {len(rows) - len(missing)} of {len(rows)} examples; approved {len(kept)} "
             f"({len(kept) / max(len(rows), 1):.1%}); not yet reviewed: {len(missing)}.", "",
             "| Task | Input | Approved | Rejected |", "|---|---|---|---|"]
    lines += [f"| {t} | {n} | {by_task_out[t]} | {n - by_task_out[t]} |" for t, n in by_task_in.items()]
    (RUNS / "auto_review_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"approved {len(kept)} of {len(rows)} -> {SFT / 'auto_reviewed.jsonl'}; {len(missing)} unreviewed")
    print("AUTO_REVIEW_ALL_DONE")


if __name__ == "__main__":
    main()
