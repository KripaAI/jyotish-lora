"""Build the v4 training data: the v3 rows (teacher answers with v3 chart text, facts, strict safety) plus the v4 streams:

    facts_v4.jsonl   table facts in many phrasings incl. Hinglish and contrast questions   (src/dataset/facts_v4.py)
    drills.jsonl     chart copying drills and engine-grounded yoga rows                    (src/dataset/drills.py)
    rule_qa.jsonl    paraphrased Q&A per extracted rule, code-checked                      (src/dataset/rules.py, rule_qa.py)

Rows carry the exact training strings ("prompt", "completion") in the Qwen3 chat format of src/app/pipeline.py, exactly as
build_v3 does: thinking ON with a code-written working for chart rows, OFF otherwise. Validation and test keep the v1 ids.

    python -m src.dataset.build_v4      # -> data/sft_v4/{train,val,test}.jsonl, manifest.json, kaggle/astro-sft-v4
"""
from __future__ import annotations

import json
import shutil
from collections import Counter

from src.common import DATA, EVALSETS, ROOT, read_jsonl, sha256_file, write_jsonl
from src.dataset.build_v3 import render_row
from src.dataset.facts import _norm

V3, V4 = DATA / "sft_v3", DATA / "sft_v4"
KAGGLE_SFT = ROOT / "kaggle" / "astro-sft-v4"
OWNER = "kripashankar81"
STREAMS = ["facts_v4.jsonl", "drills.jsonl", "rule_qa.jsonl"]


def main() -> None:
    train = [dict(r) for r in read_jsonl(V3 / "train.jsonl")]
    val, test = list(read_jsonl(V3 / "val.jsonl")), list(read_jsonl(V3 / "test.jsonl"))
    rejects_path, edits_path = V4 / "review_rejects.json", V4 / "review_edits.json"   # from src/dataset/review_v4.py import
    rejects = set(json.loads(rejects_path.read_text(encoding="utf-8"))) if rejects_path.exists() else set()
    edits = json.loads(edits_path.read_text(encoding="utf-8")) if edits_path.exists() else {}
    v3_edited = 0
    kept_v3 = []
    for r in train:                       # review verdicts apply to the carried-over v3 rows too
        if r["id"] in rejects:
            continue
        if r["id"] in edits:          # keep prompt and any <think> block; swap only the answer text
            new = edits[r["id"]]
            think = r["completion"].split("</think>")[0] + "</think>\n\n" if r.get("thinking") else ""
            r = {**r, "messages": r["messages"][:2] + [{"role": "assistant", "content": new}], "completion": f"{think}{new}<|im_end|>"}
            v3_edited += 1
        kept_v3.append(r)
    train = kept_v3
    seen_q = {" ".join(sorted(_norm(r["messages"][1]["content"]))) for r in train if r["task"] in ("fact", "safety_v2")}
    eval_q = {" ".join(sorted(_norm(r["messages"][1]["content"]))) for r in val + test}
    eval_q |= {" ".join(sorted(_norm(r["question"]))) for r in read_jsonl(EVALSETS / "quiz.jsonl")}
    added, dropped = Counter(), Counter()
    added["human_edit_v3_rows"] = v3_edited
    for name in STREAMS:
        path = V4 / name
        if not path.exists():
            print("missing stream, skipped:", path)
            continue
        for r in read_jsonl(path):
            if r["id"] in rejects:
                dropped["human_reject"] += 1
                continue
            if r["id"] in edits:
                r = {**r, "messages": r["messages"][:2] + [{"role": "assistant", "content": edits[r["id"]]}]}
                added["human_edit"] += 1
            key = " ".join(sorted(_norm(r["messages"][1]["content"].split("Question: ")[-1])))
            if r.get("chart_seed") is not None:   # the same drill question on a different chart is a different example
                key = f"{r['chart_seed']}|{key}"
            if key in seen_q or key in eval_q:
                dropped[r["task"]] += 1
                continue
            seen_q.add(key)
            rendered = render_row({"id": r["id"], "task": r["task"], "messages": r["messages"], "chart_seed": r.get("chart_seed")})
            train.append(rendered)
            added[r["task"]] += 1
    assert all(r["prompt"].endswith("<|im_start|>assistant\n") == r["thinking"] for r in train)
    manifest = {"version": "v4",
                "source": "sft_v3 rows + facts_v4 (table facts, Hinglish, contrast) + drills (chart copying, engine-grounded yogas) "
                          "+ rule_qa (local-model paraphrases of Claude-extracted rules, code-checked)",
                "render": "render_chart_text(derived=True); prompt/completion strings as in build_v3 (thinking on for chart rows)",
                "added": dict(added), "dropped_as_duplicate_or_eval_overlap": dict(dropped), "splits": {}}
    for name, items in (("train", train), ("val", val), ("test", test)):
        path = V4 / f"{name}.jsonl"
        write_jsonl(path, items)
        manifest["splits"][name] = {"examples": len(items), "sha256": sha256_file(path),
                                    "tasks": dict(Counter(i["task"] for i in items)),
                                    "thinking_on": sum(bool(i.get("thinking")) for i in items)}
    manifest["system_prompt_sha256"] = sha256_file(ROOT / "prompts" / "system_v1.txt")
    (V4 / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    KAGGLE_SFT.mkdir(parents=True, exist_ok=True)
    for f in ("train.jsonl", "val.jsonl", "manifest.json"):
        shutil.copy(V4 / f, KAGGLE_SFT / f)
    (KAGGLE_SFT / "dataset-metadata.json").write_text(json.dumps(
        {"title": "astro-sft-v4", "id": f"{OWNER}/astro-sft-v4", "licenses": [{"name": "other"}]}, indent=2), encoding="utf-8")
    print(json.dumps({k: v["examples"] for k, v in manifest["splits"].items()}), "added", dict(added), "dropped", dict(dropped))


if __name__ == "__main__":
    main()
