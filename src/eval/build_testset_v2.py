"""Stage 2B.1: a 300-item held-out test set from the 180 chunks that never fed the v4 rule base.

Reuses the Phase 1 teacher pipeline (src/dataset/generate.py: questions -> answers -> fact check), redirected to
data/eval_v2/ so nothing mixes with training data. Chart tasks get fresh synthetic charts with the v3 chart text.
Reference answers are written by the teacher with the hidden passage, as in Phase 1, and only fact-check passes are kept.

    python -m src.eval.build_testset_v2 all          # seeds -> questions -> answers -> factcheck -> assemble -> finalize (resumable)
    python -m src.eval.build_testset_v2 status
Output: evalsets/test_v2.jsonl (never trained on).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict

from src.chart.births import chart_for_seed
from src.chart.render import render_chart_text
from src.common import CHUNKS, DATA, EVALSETS, read_jsonl, write_jsonl
from src.dataset import generate, seeds as seeds_mod, teacher
from src.dataset.facts import _norm, too_close

EVAL2 = DATA / "eval_v2"
HELDOUT = DATA / "sft_v4" / "heldout_chunks.json"
OUT = EVALSETS / "test_v2.jsonl"
MIX = {"full_chart": 25, "placement": 45, "concept": 45, "comparison": 12, "remedies": 10, "uncertainty": 8, "safety": 5}
MAX_USES = 3
SEED = 2026


def _patch() -> None:
    """Point the shared pipeline at data/eval_v2/ (module globals, so every helper follows)."""
    generate.SFT = EVAL2
    teacher.BATCHES_LOG, teacher.RESULTS_DIR, teacher.REQUESTS_DIR = EVAL2 / "batches.jsonl", EVAL2 / "results", EVAL2 / "requests"
    EVAL2.mkdir(parents=True, exist_ok=True)


def build_seeds() -> list[dict]:
    held = set(json.load(open(HELDOUT, encoding="utf-8")))
    chunks = [c for c in read_jsonl(CHUNKS / "chunks.jsonl") if c["chunk_id"] in held and c["quality"] == "ok"]
    by_id = {c["chunk_id"]: c for c in chunks}
    rng, uses, seeds = random.Random(SEED), Counter(), []
    tasks_of: dict[str, set] = defaultdict(set)

    def sample(task):
        pool = [c for c in chunks if uses[c["chunk_id"]] < MAX_USES and seeds_mod.eligible(task, c) and task not in tasks_of[c["chunk_id"]]]
        if not pool:
            return None
        c = rng.choices(pool, weights=[1 / (1 + uses[x["chunk_id"]]) for x in pool])[0]
        uses[c["chunk_id"]] += 1
        tasks_of[c["chunk_id"]].add(task)
        return c

    def add(task, chunk_ids):
        seeds.append({"seed_id": f"e{len(seeds):04d}", "task": task, "chunk_ids": chunk_ids, "n_questions": 2})

    spec = lambda c: {t for t in c["topics"] if t.startswith(("planet:", "house:", "yoga:", "sign:"))}
    for task, n in MIX.items():
        misses = 0
        while sum(s["task"] == task for s in seeds) < n and misses < 60:
            if task == "comparison":
                a = sample("comparison")
                partners = [c for c in chunks if a and c["short"] != a["short"] and len(spec(a) & spec(c)) >= 1
                            and uses[c["chunk_id"]] < MAX_USES]
                if not a or not partners:
                    misses += 1
                    continue
                b = max(rng.sample(partners, min(10, len(partners))), key=lambda c: len(spec(a) & spec(c)))
                uses[b["chunk_id"]] += 1
                add("comparison", [a["chunk_id"], b["chunk_id"]])
                continue
            c = sample(task) or (sample("concept") if task in ("safety", "uncertainty", "remedies") else None)
            if c is None:
                misses += 1
                continue
            add(task if seeds_mod.eligible(task, c) else "concept", [c["chunk_id"]])
    # charts: fresh seeds, never the v1 test charts nor the v4 drill range
    used = {r.get("chart_seed") for r in read_jsonl(DATA / "sft_v2" / "test.jsonl") if r.get("chart_seed") is not None}
    used |= set(range(1_000_000, 1_000_400))
    for s in seeds:
        if s["task"] in seeds_mod.CHART_TASKS or (s["task"] == "safety" and rng.random() < 0.5):
            topics = sorted({t for cid in s["chunk_ids"] for t in by_id[cid]["topics"]})
            chart_seed, chart = seeds_mod.pick_chart(rng, topics, used)
            s["chart_seed"], s["chart_text"] = chart_seed, render_chart_text(chart, derived=True)
    rng.shuffle(seeds)
    write_jsonl(EVAL2 / "seeds.jsonl", seeds)
    print(f"{len(seeds)} seeds from {len(uses)} held-out chunks ->", EVAL2 / "seeds.jsonl", dict(Counter(s["task"] for s in seeds)))
    return seeds


def run_stage(stage: str, workers: int) -> None:
    reqs = generate.pending(stage, generate.build(stage, generate.load_seeds()))
    model = generate.DEFAULT_MODEL.get(stage)      # questions and fact check: Sonnet; answers: Opus (the back-end default)
    generate.run(stage, reqs, "claude", workers, model)


def finalize() -> None:
    train_qs = [_norm(r["messages"][1]["content"].split("Question: ")[-1]) for r in read_jsonl(DATA / "sft_v4" / "train.jsonl")]
    rows, dropped = [], Counter()
    for r in read_jsonl(EVAL2 / "generated.jsonl"):
        fc = r.get("factcheck") or {}
        if fc.get("verdict") != "pass":
            dropped["factcheck_fail_or_missing"] += 1
            continue
        q = r["messages"][1]["content"].split("Question: ")[-1]
        if too_close(q, train_qs):
            dropped["near_training_question"] += 1
            continue
        rows.append({"id": f"t2-{r['id']}", "task": r["task"], "chart_seed": r.get("chart_seed"), "source_chunks": r["source_chunks"],
                     "messages": r["messages"][:2], "reference": r["messages"][2]["content"]})
    write_jsonl(OUT, rows)
    print(f"test_v2: {len(rows)} items -> {OUT}; dropped {dict(dropped)}; by task {dict(Counter(r['task'] for r in rows))}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["seeds", "run", "assemble", "finalize", "status", "all"])
    ap.add_argument("stage", nargs="?", choices=generate.STAGES)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    _patch()
    if a.command == "seeds":
        build_seeds()
    elif a.command == "run":
        run_stage(a.stage, a.workers)
    elif a.command == "assemble":
        generate.assemble()
    elif a.command == "finalize":
        finalize()
    elif a.command == "status":
        generate.status()
    else:
        if not (EVAL2 / "seeds.jsonl").exists():
            build_seeds()
        for stage in generate.STAGES:
            run_stage(stage, a.workers)
        generate.assemble()
        finalize()


if __name__ == "__main__":
    main()
