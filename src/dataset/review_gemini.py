"""Model review of the 200-row v4 sample (data/reviews/review_v4.csv) by Gemini, at the owner's direction (2026-10-20),
in place of the person-review of constitution IV.2. Recorded as a documented exception in docs/constitution.md.

Gemini is independent of both the rule extractor (Claude) and the paraphraser (local Qwen3 14B). Each row is shown with the
evidence it was built from: the rule record and its source passage for rule_qa rows, the chart text for chart rows.
Verdicts are written into the CSV's verdict / edited_answer / note columns, so `python -m src.dataset.review_v4 import` and
`build_v4` apply them exactly as they would a human's.

    python -m src.dataset.review_gemini run [--model gemini-3.5-flash] [--workers 3]   # resumable
    python -m src.dataset.review_gemini run --backend claude                           # fallback for rows Gemini could not review

Fallback (owner's instruction, 2026-10-20): if the Gemini free tier runs out, the remaining rows are reviewed by Claude Opus 5.5
through the subscription CLI (src/dataset/backends.call_claude), with the same prompt, evidence and schema.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common import CHUNKS, DATA, read_jsonl
from src.dataset.review_v4 import CSV

KEY_FILE = r"C:\Users\mobirizer\.gemini_env"
RESULTS = DATA / "reviews" / "review_v4_gemini.jsonl"
MODEL = "gemini-3.1-pro-preview"
SCHEMA = {"type": "object",
          "properties": {"verdict": {"type": "string", "enum": ["approve", "edit", "reject"]},
                         "reason": {"type": "string"},
                         "edited_answer": {"type": "string"}},
          "required": ["verdict", "reason", "edited_answer"]}
SYSTEM = """You are the human-review stand-in for a training dataset that teaches a small model to answer like a careful Vedic (Jyotish) astrologer. You review ONE training example: the user question, the assistant answer, and the EVIDENCE the example was built from (a rule record and the book passage it was extracted from, or the computed chart). The model will learn to imitate the answer, so errors become model errors.

Decide:
- "approve": the answer is correct against the evidence and standard Jyotish, answers the question, attributes views to the right text or tradition, and follows the safety rules.
- "edit": the answer is mostly right but has a fixable problem (a wrong detail, a misattribution, a missing condition, an answer that does not quite fit the question). Write the corrected full answer in edited_answer, in the same voice and similar length, changing only what is needed.
- "reject": the answer is wrong at its core, contradicts the evidence or the chart, invents a rule or a book, cites chapters or verses, or breaks a safety rule (predicts death or its timing, diagnoses illness, gives legal/investment/trading instructions, pushes remedies as guaranteed, carries caste, gender or birth-star stigma, or is fatalistic).

Standard Jyotish knowledge beyond the evidence is fine if it is correct. Judge content, not style. Answers must be in English (the question may be Hinglish). Give a one-sentence reason. edited_answer is "" unless the verdict is "edit"."""


def gemini(model: str, user: str, key: str) -> dict:
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.0}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            return json.loads(d["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 7:
                time.sleep(min(60 * (attempt + 1), 300))   # free-tier rate limits: wait and retry
                continue
            raise


CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_SCHEMA = {**SCHEMA, "additionalProperties": False}


def claude(user: str, custom_id: str) -> dict:
    from src.dataset import backends
    req = {"custom_id": custom_id, "params": {"system": [{"text": SYSTEM}], "messages": [{"content": user}],
                                              "output_config": {"effort": "medium", "format": {"schema": CLAUDE_SCHEMA}}}}
    row = backends.call_with_wait("claude", req, CLAUDE_MODEL)
    if row["type"] != "succeeded":
        raise RuntimeError(row.get("error", row["type"]))
    return json.loads(row["text"])


def evidence_for(row_id: str, task: str, train: dict, rules: dict, chunks: dict) -> str:
    r = train.get(row_id, {})
    user = r.get("messages", [{}, {}])[1].get("content", "") if r else ""
    parts = []
    if task == "rule_qa" and r.get("rule_id") in rules:
        rule = rules[r["rule_id"]]
        parts.append("RULE RECORD\n" + "\n".join(f"{k}: {rule.get(k, '')}" for k in ("statement", "conditions", "modifiers", "exceptions", "text", "tradition")))
        for cid in rule.get("source_ids", [])[:1]:
            if cid in chunks:
                parts.append(f"SOURCE PASSAGE ({chunks[cid]['title']})\n{chunks[cid]['text'][:6000]}")
    if user.startswith("Chart:"):
        parts.append("CHART (computed by software, always correct)\n" + user.split("\n\nQuestion: ")[0][len("Chart:\n"):])
    if not parts:
        parts.append("No source record: judge against standard Jyotish (this row was generated from the engine's reference tables or an earlier checked teacher answer).")
    return "\n\n".join(parts)


def run(model: str, workers: int, backend: str = "gemini") -> None:
    key = open(KEY_FILE, encoding="utf-8").read().split("=", 1)[1].strip()
    if backend == "claude":
        model = CLAUDE_MODEL
    rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))
    train = {}
    for name in ("rule_qa.jsonl", "facts_v4.jsonl", "drills.jsonl", "train.jsonl"):
        p = DATA / "sft_v4" / name
        ids = {r["id"] for r in rows}
        for r in read_jsonl(p):
            if r["id"] in ids and r["id"] not in train:
                train[r["id"]] = r
    rules = {r["rule_id"]: r for r in read_jsonl(DATA / "sft_v4" / "rules.jsonl")}
    chunks = {c["chunk_id"]: c for c in read_jsonl(CHUNKS / "chunks.jsonl")}
    done = {r["id"]: r for r in read_jsonl(RESULTS) if "error" not in r} if RESULTS.exists() else {}
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(rows)} rows, {len(todo)} to review with {model}", flush=True)

    def one(row):
        ev = evidence_for(row["id"], row["task"], train, rules, chunks)
        user = f"{ev}\n\nUSER QUESTION\n{row['question']}\n\nASSISTANT ANSWER\n{row['answer']}"
        try:
            v = claude(user, f"review-{row['id']}") if backend == "claude" else gemini(model, user, key)
            return {"id": row["id"], "model": model, **v}
        except Exception as e:  # noqa: BLE001 - retried on the next run
            return {"id": row["id"], "model": model, "error": str(e)[:300]}

    with open(RESULTS, "a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        for n, fut in enumerate(as_completed([ex.submit(one, r) for r in todo]), 1):
            res = fut.result()
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()
            if n % 10 == 0 or n == len(todo):
                print(f"{n}/{len(todo)}", flush=True)
    done = {r["id"]: r for r in read_jsonl(RESULTS) if "error" not in r}
    for row in rows:
        v = done.get(row["id"])
        if v:
            who = "Claude" if v["model"].startswith("claude") else "Gemini"
            row["verdict"], row["note"] = v["verdict"], f"[{who} {v['model']}] {v['reason']}"
            row["edited_answer"] = v.get("edited_answer", "") if v["verdict"] == "edit" else ""
    with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "task", "question", "answer", "verdict", "edited_answer", "note"])
        w.writeheader()
        w.writerows(rows)
    missing = sum(1 for r in rows if r["id"] not in done)
    print(f"verdicts written into {CSV}; {missing} rows without a verdict (rerun to retry)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run"])
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--backend", choices=["gemini", "claude"], default="gemini")
    a = ap.parse_args(argv)
    run(a.model, a.workers, a.backend)


if __name__ == "__main__":
    main()
