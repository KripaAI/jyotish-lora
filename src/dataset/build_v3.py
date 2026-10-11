"""Build the v3 training data: v2 examples with the v3 chart text (counted facts) and, for chart examples, a code-written
reasoning block, so the model is trained with Qwen3's thinking mode ON for chart readings and OFF for everything else.

Rows carry the exact text the model trains on ("prompt", "completion"), rendered with the same Qwen chat format the serving
code uses (src/app/pipeline.py:render_qwen), so training and serving cannot drift:
  thinking on : prompt ends "<|im_start|>assistant\\n", completion = "<think>\\n{working}\\n</think>\\n\\n{answer}<|im_end|>"
  thinking off: prompt ends "<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n", completion = "{answer}<|im_end|>"
Validation and test keep exactly the v1/v2 example ids (chart text re-rendered to v3), so versions compare fairly.

    python -m src.dataset.build_v3     # -> data/sft_v3/{train,val,test}.jsonl, manifest.json, kaggle/astro-sft-v3, kaggle/astro-eval-v3
"""
from __future__ import annotations

import json
import shutil
from collections import Counter

from src.app.pipeline import render_qwen
from src.chart.births import chart_for_seed
from src.chart.render import render_chart_text
from src.common import DATA, EVALSETS, ROOT, SFT, read_jsonl, sha256_file, write_jsonl
from src.dataset.build_v2 import SEP, assign_splits
from src.dataset.scratchpad import working

V2, V3 = DATA / "sft_v2", DATA / "sft_v3"
KAGGLE_SFT, KAGGLE_EVAL = ROOT / "kaggle" / "astro-sft-v3", ROOT / "kaggle" / "astro-eval-v3"
OWNER = "kripashankar81"


def render_row(row: dict) -> dict:
    """v3 messages (chart text re-rendered) plus the training strings. Chart examples think; the rest do not."""
    msgs = [dict(m) for m in row["messages"]]
    chart = None
    if row.get("chart_seed") is not None:
        chart = chart_for_seed(row["chart_seed"])
        user = msgs[1]["content"]
        assert user.startswith("Chart:\n") and SEP in user, row["id"]
        question = user.split(SEP, 1)[1]
        msgs[1]["content"] = f"Chart:\n{render_chart_text(chart, derived=True)}{SEP}{question}"
    answer = msgs[2]["content"]
    think = chart is not None
    prompt = render_qwen(msgs[:2], thinking=think)
    if think:
        w = working(chart, answer, msgs[1]["content"].split(SEP, 1)[1])
        completion = f"<think>\n{w}\n</think>\n\n{answer}<|im_end|>"
    else:
        completion = f"{answer}<|im_end|>"
    return {"id": row["id"], "task": row["task"], "thinking": think, "messages": msgs, "prompt": prompt, "completion": completion}


def main() -> None:
    base = list(read_jsonl(SFT / "auto_reviewed.jsonl"))
    split_of = assign_splits(base)
    out = {"train": [], "val": [], "test": []}
    for r in base:
        s = split_of[r["id"]]
        keep = render_row(r)
        if s == "test":
            keep.update({"source_chunks": r["source_chunks"], "chart_seed": r.get("chart_seed")})
        out[s].append(keep)
    for name, task in (("facts.jsonl", "fact"), ("safety_v2.jsonl", "safety_v2")):
        for r in read_jsonl(V2 / name):
            out["train"].append(render_row({"id": r["id"], "task": task, "messages": r["messages"]}))

    v1_val = {r["id"] for r in read_jsonl(SFT / "val.jsonl")}
    v1_test = {r["id"] for r in read_jsonl(SFT / "test.jsonl")}
    assert {r["id"] for r in out["val"]} == v1_val, "val split differs from v1"
    assert {r["id"] for r in out["test"]} == v1_test, "test split differs from v1"
    assert all(r["prompt"].endswith("<|im_start|>assistant\n") == r["thinking"] for rows in out.values() for r in rows)

    manifest = {"version": "v3", "source": "auto_reviewed.jsonl + facts + safety_v2, chart text v3 (counted facts), "
                "code-written working in <think> for chart examples (thinking on), thinking off otherwise",
                "render": "render_chart_text(derived=True); prompt/completion strings in the Qwen3 chat format of src/app/pipeline.py",
                "splits": {}}
    for name, items in out.items():
        path = V3 / f"{name}.jsonl"
        write_jsonl(path, items)
        manifest["splits"][name] = {"examples": len(items), "sha256": sha256_file(path),
                                    "tasks": dict(Counter(i["task"] for i in items)),
                                    "thinking_on": sum(i["thinking"] for i in items)}
    manifest["system_prompt_sha256"] = sha256_file(ROOT / "prompts" / "system_v1.txt")
    (V3 / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    KAGGLE_SFT.mkdir(parents=True, exist_ok=True)
    for f in ("train.jsonl", "val.jsonl", "manifest.json"):
        shutil.copy(V3 / f, KAGGLE_SFT / f)
    (KAGGLE_SFT / "dataset-metadata.json").write_text(json.dumps(
        {"title": "astro-sft-v3", "id": f"{OWNER}/astro-sft-v3", "licenses": [{"name": "other"}]}, indent=2), encoding="utf-8")
    KAGGLE_EVAL.mkdir(parents=True, exist_ok=True)
    write_jsonl(KAGGLE_EVAL / "test.jsonl", [{k: v for k, v in r.items() if k not in ("prompt", "completion")} for r in out["test"]])
    for f in ("quiz.jsonl", "safety_eval.jsonl"):
        shutil.copy(EVALSETS / f, KAGGLE_EVAL / f)
    shutil.copy(ROOT / "prompts" / "system_v1.txt", KAGGLE_EVAL / "system_v1.txt")
    (KAGGLE_EVAL / "dataset-metadata.json").write_text(json.dumps(
        {"title": "astro-eval-v3", "id": f"{OWNER}/astro-eval-v3", "licenses": [{"name": "other"}]}, indent=2), encoding="utf-8")
    print(json.dumps({k: (v["examples"], v["thinking_on"]) for k, v in manifest["splits"].items()}), manifest["splits"]["train"]["tasks"])


if __name__ == "__main__":
    main()
