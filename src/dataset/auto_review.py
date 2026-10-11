"""Model-assisted review of the human-review sample (a first pass, NOT the human review required by Constitution IV).

Fills data/reviews/review_batch.csv with approve/reject decisions from Claude Sonnet 5.5, judging each example as
TRAINING data (voice, soundness, safety, usefulness), a different lens from the factual fact check. Notes are prefixed
"auto-review" so a person can tell them apart and spot-check them. Existing decisions are never overwritten.

    python -m src.dataset.auto_review [--workers 4] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common import DATA, PROMPTS
from src.dataset import backends

REVIEW_CSV = DATA / "reviews" / "review_batch.csv"
MODEL = "claude-sonnet-5-5"
FIELDS = ["id", "task", "question", "answer", "factcheck_reason", "filter_warnings", "decision", "edited_answer", "notes"]

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject"]},
        "problems": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["decision", "problems", "reason"],
    "additionalProperties": False,
}

SYSTEM = """You are reviewing one example for a fine-tuning dataset that teaches a small model to answer as an experienced, responsible Vedic (Jyotish) astrologer. The example is a user message (sometimes with an attached chart computed by software) and the assistant reply the model will imitate. Facts have already been checked against source books; judge it as TRAINING data.

Reject the example if the reply has any of these problems:
- astrology that an informed Jyotishi would call wrong or distorted (a rule stated wrongly, a planet or house misused, a classical view misrepresented, a confident claim the tradition does not make);
- an invented rule or interpretation presented as established doctrine;
- fatalistic, fear-inducing or stigmatising content, or reinforcing a harmful belief instead of correcting it;
- a prediction of death or its timing, a medical diagnosis, legal or investment instructions, or remedies presented as guaranteed or as something to buy;
- failing to answer what the user asked, or answering a different question;
- generic filler that any chatbot would say, with no real astrological substance;
- the reply reveals it was written from hidden material ("the passage", "the excerpt", "the source you gave"), gives chapter or verse numbers, or quotes Sanskrit verses. NOTE: naming a book, author or tradition ("Phaladeepika says...", "in the Yavanajataka", "the Parashari view") is ALLOWED and encouraged; do not reject for that;
- a chart reading that does not use the chart's actual facts, or that adds computed facts the chart does not contain;
- a user message that is unrealistic, states chart details it could not know, or asks the assistant to calculate positions or dates.

Approve if the reply is accurate, balanced, in an experienced astrologer's voice, and useful, even if you would phrase some things differently. Interpretation framed as judgement ("I would read this as...") is fine. Do not reject over style preferences or length.

Return: decision (approve or reject), problems (short list, empty if none), and reason (one sentence)."""


def review_one(row: dict) -> dict:
    user = (f"TASK TYPE: {row['task']}\n\n<user_message>\n{row['question']}\n</user_message>\n\n"
            f"<assistant_reply>\n{row['answer']}\n</assistant_reply>")
    res = backends.call_with_wait("claude", {
        "custom_id": f"review-{row['id']}",
        "params": {"system": [{"text": SYSTEM}], "messages": [{"content": user}],
                   "output_config": {"effort": "medium", "format": {"schema": SCHEMA}}},
    }, MODEL)
    if res["type"] != "succeeded":
        return {"id": row["id"], "error": res.get("error", res["type"])}
    return {"id": row["id"], **json.loads(res["text"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    with open(REVIEW_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    backup = REVIEW_CSV.with_name("review_batch.before_auto_review.csv")
    if not backup.exists():
        shutil.copy(REVIEW_CSV, backup)

    todo = [r for r in rows if not r["decision"].strip()][: args.limit]
    print(f"reviewing {len(todo)} of {len(rows)} examples with {MODEL}", flush=True)
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(review_one, r): r["id"] for r in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                res = {"id": futs[fut], "error": str(e)[:200]}
            results[res["id"]] = res
            if n % 10 == 0 or n == len(todo):
                print(f"{n}/{len(todo)} done {dict(Counter(r.get('decision', 'error') for r in results.values()))}", flush=True)

    for r in rows:
        res = results.get(r["id"])
        if not res or "decision" not in res:
            continue
        r["decision"] = res["decision"]
        problems = "; ".join(res["problems"])
        r["notes"] = f"auto-review (Sonnet 5.5): {res['reason']}" + (f" | {problems}" if problems else "")
    with open(REVIEW_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    failed = [i for i, r in results.items() if "decision" not in r]
    print(f"wrote decisions to {REVIEW_CSV}; {len(failed)} failed (rerun to retry them)")
    print("AUTO_REVIEW_DONE")


if __name__ == "__main__":
    main()
