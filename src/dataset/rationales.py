"""v3: a reasoning passage for each conversational training example, written by the teacher (Claude Opus).

The v2-8b adapter lost Qwen3's thinking behaviour because every training example had an empty reasoning block. v3 trains
with thinking ON for chart, placement, concept, comparison, remedies and uncertainty examples: the completion becomes
<think>rationale</think> + the checked answer. Fact and safety examples stay thinking-off (mixed-mode training keeps both).

The rationale is written from the v3 chart text (with the counted facts) and the final answer, so it can only use facts the
model will see in the prompt. Checks: length, no citations, no hard chart contradictions (src/dataset/filters.py).

    python -m src.dataset.rationales [--limit N] [--workers 4]     # -> data/sft_v3/rationales.jsonl (resumable)
"""
from __future__ import annotations

import argparse
import json

from src.chart.births import chart_for_seed
from src.chart.render import render_chart_text
from src.common import DATA, PROMPTS, SFT, read_jsonl
from src.dataset import safety_v2 as sv
from src.dataset.build_v2 import SEP, assign_splits
from src.dataset.filters import chart_contradictions, citation_issue, word_count

OUT = DATA / "sft_v3" / "rationales.jsonl"
THINK_TASKS = {"full_chart", "placement", "concept", "comparison", "remedies", "uncertainty"}
OPUS = sv.OPUS
MIN_WORDS, MAX_WORDS = 80, 330

SYSTEM = """You write the private reasoning that an experienced Vedic astrologer would go through BEFORE giving the reply below. The reasoning will train a small model to think before it answers, so it must be the working behind this exact reply, not a new reply.

Rules:
- Write in the first person, present tense, as thinking ("The question is about... The 10th from the Moon is... So the rule that applies is..."). Plain prose, no headings, no bullet points, no markdown.
- Use ONLY facts that appear in the chart text (if there is one) and in the reply. Never add a placement, aspect, dasha date, yoga or book claim that is not already there.
- When a house is counted from the Moon, from another planet, or in the navamsa, quote the counted fact from the chart text explicitly ("the chart text lists the 10th from the Moon as Sagittarius") instead of counting in your head.
- Name the classical rule or principle the reply relies on and the tradition it belongs to, in the same words the reply uses. Do not quote shlokas or give chapter or verse numbers.
- Note any caution the reply gives (tendencies not certainties, see a professional) as part of the reasoning.
- End with one sentence stating the conclusion the reply reaches.
- Length 120 to 300 words. Output only the reasoning text."""


def jobs_for(limit: int | None):
    base = list(read_jsonl(SFT / "auto_reviewed.jsonl"))
    split_of = assign_splits(base)
    jobs = []
    for r in base:
        if split_of[r["id"]] != "train" or r["task"] not in THINK_TASKS:
            continue
        user = r["messages"][1]["content"]
        chart = None
        if r.get("chart_seed") is not None:
            chart = chart_for_seed(r["chart_seed"])
            assert user.startswith("Chart:\n") and SEP in user, r["id"]
            user = f"Chart:\n{render_chart_text(chart, derived=True)}{SEP}{user.split(SEP, 1)[1]}"
        jobs.append({"key": r["id"], "task": r["task"], "user": user, "answer": r["messages"][2]["content"], "chart": chart})
    return jobs[:limit] if limit else jobs


def check(rationale: str, chart: dict | None) -> list[str]:
    problems = []
    n = word_count(rationale)
    if not MIN_WORDS <= n <= MAX_WORDS:
        problems.append(f"length {n}")
    if citation_issue(rationale):
        problems.append("citation")
    if any(line.lstrip().startswith(("#", "-", "*", "•")) for line in rationale.splitlines()):
        problems.append("markdown")
    if chart is not None:
        hard, _ = chart_contradictions(rationale, chart)
        if hard:
            problems.append("chart: " + "; ".join(hard[:3]))
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    jobs = jobs_for(a.limit)
    print(len(jobs), "examples need a rationale", flush=True)

    def fn(j):
        res = sv._call(f"rat-{j['key']}", SYSTEM, f"USER MESSAGE:\n{j['user']}\n\nREPLY:\n{j['answer']}", OPUS, "medium")
        if res["type"] != "succeeded":
            return None
        text = res["text"].strip()
        return {"key": j["key"], "task": j["task"], "rationale": text, "problems": check(text, j["chart"]), "words": word_count(text)}

    sv._run(jobs, OUT, fn, workers=a.workers)
    rows = list(read_jsonl(OUT)) if OUT.exists() else []
    bad = [r for r in rows if r["problems"]]
    print(f"{len(rows)} rationales, {len(bad)} with problems:", {p.split(":")[0] for r in bad for p in r["problems"]})


if __name__ == "__main__":
    main()
