"""Phase 3.9: grouped 90/5/5 split and dataset manifest.

All examples that share a source chunk or a chart seed land in the same split, so no source text or
chart leaks from training into evaluation.

Usage:
    python -m src.dataset.split            # reads data/sft/reviewed.jsonl (or filtered.jsonl)
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from src.common import ROOT, RUNS, SFT, read_jsonl, sha256_file, write_jsonl

SPLITS = (("train", 90), ("val", 95), ("test", 100))  # cumulative percentages


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def bucket(group: str) -> str:
    h = int(hashlib.sha256(group.encode()).hexdigest(), 16) % 100
    return next(name for name, upto in SPLITS if h < upto)


REVIEW_NOTE = {
    "reviewed.jsonl": "human review applied",
    "auto_reviewed.jsonl": "model review (Claude Sonnet 5.5) of every example; rejects removed; human spot-check pending",
    "filtered.jsonl": "automatic filters only; no review",
}


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(REVIEW_NOTE), help="input file in data/sft/ (default: reviewed, else filtered)")
    args = ap.parse_args(argv)
    if args.source:
        src = SFT / args.source
    else:
        src = SFT / "reviewed.jsonl"
        if not src.exists():
            print("reviewed.jsonl not found; using filtered.jsonl (human review not applied yet)")
            src = SFT / "filtered.jsonl"
    rows = list(read_jsonl(src))

    uf = _UnionFind()
    for r in rows:
        keys = [f"chunk:{c}" for c in r["source_chunks"]]
        if r.get("chart_seed") is not None:
            keys.append(f"chart:{r['chart_seed']}")
        for k in keys[1:]:
            uf.union(keys[0], k)
    split_of = {r["id"]: bucket(uf.find(f"chunk:{r['source_chunks'][0]}")) for r in rows}

    out = {name: [] for name, _ in SPLITS}
    for r in rows:
        name = split_of[r["id"]]
        if name == "test":  # keep references for evaluation (rule fidelity against the source)
            out[name].append({"id": r["id"], "task": r["task"], "source_chunks": r["source_chunks"],
                              "chart_seed": r.get("chart_seed"), "messages": r["messages"]})
        else:
            out[name].append({"id": r["id"], "task": r["task"], "messages": r["messages"]})
    manifest = {"source": src.name, "review": REVIEW_NOTE[src.name], "examples": len(rows), "splits": {}}
    for name, items in out.items():
        path = SFT / f"{name}.jsonl"
        write_jsonl(path, items)
        manifest["splits"][name] = {"examples": len(items), "sha256": sha256_file(path),
                                    "tasks": dict(Counter(i["task"] for i in items))}

    # leakage check: no chunk or chart in more than one split
    seen: dict[str, str] = {}
    leaks = 0
    for r in rows:
        for k in [*(f"chunk:{c}" for c in r["source_chunks"]), *( [f"chart:{r['chart_seed']}"] if r.get("chart_seed") is not None else [])]:
            if seen.setdefault(k, split_of[r["id"]]) != split_of[r["id"]]:
                leaks += 1
    manifest["leaks"] = leaks
    manifest["system_prompt_sha256"] = sha256_file(ROOT / "prompts" / "system_v1.txt")
    (SFT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (RUNS / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: v["examples"] for k, v in manifest["splits"].items()}), f"leaks={leaks}")


if __name__ == "__main__":
    main()
