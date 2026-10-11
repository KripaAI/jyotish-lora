"""Build the v2 training data: v1 examples (chart text re-rendered with nakshatra lords) + fact examples + strict
safety examples. Validation and test keep exactly the v1 examples, so v1 and v2 compare fairly.

    python -m src.dataset.build_v2        # -> data/sft_v2/{train,val,test}.jsonl, manifest.json, and kaggle/astro-sft-v2/
"""
from __future__ import annotations

import json
import shutil
from collections import Counter

from src.chart.births import chart_for_seed
from src.chart.render import render_chart_text
from src.common import DATA, ROOT, SFT, read_jsonl, sha256_file, write_jsonl
from src.dataset.split import _UnionFind, bucket

V2 = DATA / "sft_v2"
KAGGLE = ROOT / "kaggle" / "astro-sft-v2"
SEP = "\n\nQuestion: "


def rerender(row: dict) -> dict:
    """Replace the chart block of a chart-based user message with the v2 rendering (answer untouched)."""
    if row.get("chart_seed") is None:
        return row
    user = row["messages"][1]["content"]
    assert user.startswith("Chart:\n") and SEP in user, row["id"]
    question = user.split(SEP, 1)[1]
    new_user = f"Chart:\n{render_chart_text(chart_for_seed(row['chart_seed']))}{SEP}{question}"
    msgs = [dict(m) for m in row["messages"]]
    msgs[1]["content"] = new_user
    return {**row, "messages": msgs}


def assign_splits(rows: list[dict]) -> dict[str, str]:
    """Same grouping and hashing as src/dataset/split.py, so v1 and v2 splits match."""
    uf = _UnionFind()
    for r in rows:
        keys = [f"chunk:{c}" for c in r["source_chunks"]]
        if r.get("chart_seed") is not None:
            keys.append(f"chart:{r['chart_seed']}")
        for k in keys[1:]:
            uf.union(keys[0], k)
    return {r["id"]: bucket(uf.find(f"chunk:{r['source_chunks'][0]}")) for r in rows}


def main() -> None:
    base = [rerender(r) for r in read_jsonl(SFT / "auto_reviewed.jsonl")]
    split_of = assign_splits(base)
    facts = list(read_jsonl(V2 / "facts.jsonl"))
    safety = list(read_jsonl(V2 / "safety_v2.jsonl"))

    out = {"train": [], "val": [], "test": []}
    for r in base:
        s = split_of[r["id"]]
        keep = {"id": r["id"], "task": r["task"], "messages": r["messages"]}
        if s == "test":
            keep.update({"source_chunks": r["source_chunks"], "chart_seed": r.get("chart_seed")})
        out[s].append(keep)
    out["train"] += [{"id": r["id"], "task": "fact", "messages": r["messages"]} for r in facts]
    out["train"] += [{"id": r["id"], "task": "safety_v2", "messages": r["messages"]} for r in safety]

    # v1 and v2 must evaluate on the same examples
    v1_val = {r["id"] for r in read_jsonl(SFT / "val.jsonl")}
    v1_test = {r["id"] for r in read_jsonl(SFT / "test.jsonl")}
    assert {r["id"] for r in out["val"]} == v1_val, "val split differs from v1"
    assert {r["id"] for r in out["test"]} == v1_test, "test split differs from v1"

    manifest = {"version": "v2", "source": "auto_reviewed.jsonl (chart text re-rendered with nakshatra lords) + facts + safety_v2",
                "review": "model review (Claude Sonnet 5.5); facts are generated from tested reference tables; safety_v2 checked by Sonnet",
                "splits": {}}
    for name, items in out.items():
        path = V2 / f"{name}.jsonl"
        write_jsonl(path, items)
        manifest["splits"][name] = {"examples": len(items), "sha256": sha256_file(path),
                                    "tasks": dict(Counter(i["task"] for i in items))}
    manifest["system_prompt_sha256"] = sha256_file(ROOT / "prompts" / "system_v1.txt")
    (V2 / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    KAGGLE.mkdir(parents=True, exist_ok=True)
    for f in ("train.jsonl", "val.jsonl", "manifest.json"):
        shutil.copy(V2 / f, KAGGLE / f)
    (KAGGLE / "dataset-metadata.json").write_text(json.dumps(
        {"title": "astro-sft-v2", "id": "krishmithlesh0786/astro-sft-v2", "licenses": [{"name": "other"}]}, indent=2), encoding="utf-8")
    print(json.dumps({k: v["examples"] for k, v in manifest["splits"].items()}), manifest["splits"]["train"]["tasks"])


if __name__ == "__main__":
    main()
