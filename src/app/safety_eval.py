"""End-to-end safety evaluation: the 50 handwritten safety prompts through the whole pipeline, scored by the same judge.

    python -m src.app.safety_eval --run v2-8b

For each prompt: the input check runs first. If it flags the prompt, the model's answer is the one written with the safety note
in its instructions (runs/<run>/guarded/samples.jsonl); otherwise it is the plain recorded answer (runs/<run>/eval/eval_outputs.jsonl,
adapter on). Either goes through the output check (fixed fallback if a rule matches) and the self-harm helpline rule. Every final reply is judged with src/eval/judge.py's safety
judge (same prompt and model as the model-only evaluation). Output: runs/<run>/safety_layer_report.md
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from src.app.safety import check_input, finalize, fixed_reply
from src.common import EVALSETS, RUNS, read_jsonl
from src.eval import judge


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="v2-8b")
    a = ap.parse_args()
    safety = {r["id"]: r for r in read_jsonl(EVALSETS / "safety_eval.jsonl")}
    model_answers = {r["id"]: r["answer"] for r in read_jsonl(RUNS / a.run / "eval" / "eval_outputs.jsonl")
                     if r["set"] == "safety" and r["model"] == "adapter"}
    model_only = {r["key"].split("|")[1]: r for r in read_jsonl(RUNS / a.run / "eval" / "judgments.jsonl")
                  if r["key"].startswith("safety|") and r["key"].endswith("|adapter")}

    guarded = {r["id"]: r["answers"][0] for r in read_jsonl(RUNS / a.run / "guarded" / "samples.jsonl")}
    rows, jobs = [], []
    for sid, s in safety.items():
        vin = check_input(s["prompt"])
        raw = guarded[sid] if vin.action == "block" else model_answers[sid]   # flagged: the answer written with the safety note
        fixed = fixed_reply(vin)
        reply, route = (fixed, f"fixed ({vin.category})") if fixed is not None else finalize(raw, vin)
        rows.append({"id": sid, "category": s["category"], "route": route, "reply": reply})
        jobs.append({"key": f"safety|{sid}|layer", "kind": "safety", "effort": "medium",
                     "user": f"CATEGORY: {s['category']}\nREQUEST: {s['prompt']}\nA CORRECT RESPONSE MUST: {s['must']}\n\nREPLY:\n{reply}"})

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(judge.run_job, jobs))
    verdict = {r["key"].split("|")[1]: r for r in results}
    errors = [r for r in results if "error" in r]
    assert not errors, errors[:2]
    out = RUNS / a.run
    (out / "safety_layer_judgments.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8")

    n_pass = sum(bool(verdict[r["id"]].get("pass")) for r in rows)
    n_model_only = sum(bool(v.get("correct", v.get("pass"))) for v in model_only.values())
    lines = [f"# Safety layer, end to end ({a.run})", "",
             f"- Model alone: {n_model_only}/{len(rows)} pass",
             f"- With the safety layer: {n_pass}/{len(rows)} pass",
             f"- Routed: {sum(r['route'].startswith('input') for r in rows)} blocked at input, "
             f"{sum(r['route'].startswith('output') for r in rows)} blocked at output, "
             f"{sum(r['route'] == 'model' for r in rows)} answered by the model", "", "## Failures", ""]
    for r in rows:
        v = verdict[r["id"]]
        if not v.get("pass"):
            lines += [f"- **{r['id']}** ({r['category']}, {r['route']}): {safety[r['id']]['prompt']}",
                      f"  - judge: {v.get('reason', '')[:400]}", f"  - reply: {r['reply'][:300].replace(chr(10), ' ')}"]
    (out / "safety_layer_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8]))


if __name__ == "__main__":
    main()
