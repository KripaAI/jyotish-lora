"""Paired uncertainty for saved evaluation results (no model or judge calls).

    python -m src.eval.uncertainty      # -> runs/uncertainty_report.md

Every comparison is paired: the same question ids in both runs. Rubric (mean of the 5 criteria per question) uses a paired bootstrap
over questions; quiz, safety and MMLU (correct/incorrect per question) use the paired difference of proportions with a bootstrap
interval and an exact McNemar test; the pairwise win rate uses a Wilson interval on wins / (wins + losses).
"""
from __future__ import annotations

import json
import math
import random
import statistics as st

from src.common import RUNS, read_jsonl

CRIT = ["rule_fidelity", "chart_correctness", "astrologer_style", "honesty", "balance_safety"]
B = 10000
rng = random.Random(0)


def judgments(run):
    return {r["key"]: r for r in read_jsonl(RUNS / run / "eval" / "judgments.jsonl") if "error" not in r}


def per_question(run, kind, model="adapter"):
    out = {}
    if not (RUNS / run / "eval" / "judgments.jsonl").exists():
        return out
    for k, r in judgments(run).items():
        parts = k.split("|")
        if parts[0] != kind or len(parts) != 3 or parts[2] != model:
            continue
        if kind == "rubric":
            s = r.get("scores", r)
            out[parts[1]] = st.mean(s[c] for c in CRIT)
        else:
            out[parts[1]] = 1.0 if r.get("correct", r.get("pass")) else 0.0
    return out


def paired(a: dict, b: dict):
    ids = sorted(set(a) & set(b))
    d = [b[i] - a[i] for i in ids]
    boots = sorted(st.mean(rng.choices(d, k=len(d))) for _ in range(B))
    return len(ids), st.mean(d), boots[int(0.025 * B)], boots[int(0.975 * B)], d


def mcnemar(d):
    worse, better = sum(x < 0 for x in d), sum(x > 0 for x in d)
    m, k = worse + better, min(worse, better)
    return worse, better, (min(1.0, 2 * sum(math.comb(m, j) for j in range(k + 1)) / 2 ** m) if m else 1.0)


def wilson(w, n, z=1.96):
    if n == 0:
        return 0, 0, 0
    p = w / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, c - h, c + h


def fmt(x, pct=False):
    return f"{100 * x:+.1f} pp" if pct else f"{x:+.2f}"


def main():
    lines = ["# Paired uncertainty of the saved results", "",
             "Nominal 95% intervals (about 18 comparisons, no multiple-comparison adjustment). They quantify sampling noise only, not judge bias.",
             "A difference whose interval includes 0 is not distinguishable from noise at this sample size.", ""]
    comparisons = [("v2-8b adapter vs its base (adapter off)", "v2-8b", "base", "v2-8b", "adapter"),
                   ("v2-8b vs v2-4b", "v2-4b", "adapter", "v2-8b", "adapter"),
                   ("v2-8b vs v1", "v1", "adapter", "v2-8b", "adapter"),
                   ("GGUF Q4_K_M vs fp16-adapter v2-8b", "v2-8b", "adapter", "v2-8b-gguf", "adapter"),
                   ("A->B: merged fp16 (2 GPUs) vs 4-bit base + adapter", "v2-8b", "adapter", "v2-8b-merged-fp16", "adapter"),
                   ("B->C: Q8_0 GGUF vs merged fp16", "v2-8b-merged-fp16", "adapter", "v2-8b-gguf-q8", "adapter"),
                   ("C->Q4: Q4_K_M GGUF vs Q8_0 GGUF", "v2-8b-gguf-q8", "adapter", "v2-8b-gguf", "adapter"),
                   ("Dequantized-merge Q4_K_M vs current Q4_K_M", "v2-8b-gguf", "adapter", "v2-8b-gguf-dqmerge", "adapter"),
                   ("Dequantized-merge Q4_K_M vs A (4-bit base + adapter)", "v2-8b", "adapter", "v2-8b-gguf-dqmerge", "adapter"),
                   ("GGUF sampled T=0.6 vs GGUF greedy", "v2-8b-gguf", "adapter", "v2-8b-gguf-think", "adapter"),
                   ("v3-8b vs v2-8b", "v2-8b", "adapter", "v3-8b", "adapter")]
    lines += ["| Comparison (second minus first) | Metric | n | Difference | 95% interval | Notes |", "|---|---|---|---|---|---|"]
    for name, ra, ma, rb, mb in comparisons:
        for kind, label in (("rubric", "rubric mean (1-5)"), ("quiz", "quiz"), ("safety", "safety pass")):
            a, b = per_question(ra, kind, ma), per_question(rb, kind, mb)
            if not a or not b:
                continue
            n, m, lo, hi, d = paired(a, b)
            pct = kind != "rubric"
            note = ""
            if pct:
                w, bt, p = mcnemar(d)
                note = f"{bt} better, {w} worse, McNemar p={p:.2f}"
            flag = "" if lo <= 0 <= hi else " **(excludes 0)**"
            lines.append(f"| {name} | {label} | {n} | {fmt(m, pct)} | {fmt(lo, pct)} to {fmt(hi, pct)}{flag} | {note} |")

    lines += ["", "## Pairwise win rate vs own base (ties excluded from the rate)", "", "| Run | wins | losses | ties | win rate | 95% Wilson |", "|---|---|---|---|---|---|"]
    for run in ("v1", "v2-4b", "v2-8b", "v3-8b"):
        J = judgments(run)
        w = l = t = 0
        for k, r in J.items():
            if not k.startswith("pair|"):
                continue
            if r["winner"] == "tie":
                t += 1
            elif r["winner"] == r.get("adapter_is"):
                w += 1
            else:
                l += 1
        p, lo, hi = wilson(w, w + l)
        lines.append(f"| {run} | {w} | {l} | {t} | {100 * p:.0f}% | {100 * lo:.0f}% to {100 * hi:.0f}% |")

    mm = [json.loads(x) for x in open(RUNS / "v2-8b" / "mmlu" / "mmlu_results.jsonl", encoding="utf-8")]
    a = {str(r["row"]): float(r["pred_base"] == r["answer"]) for r in mm}
    b = {str(r["row"]): float(r["pred_adapter"] == r["answer"]) for r in mm}
    n, m, lo, hi, d = paired(a, b)
    w, bt, p = mcnemar(d)
    lines += ["", "## MMLU (catastrophic forgetting), v2-8b adapter on vs off", "",
              f"n={n}: difference {fmt(m, True)}, 95% interval {fmt(lo, True)} to {fmt(hi, True)}; {bt} better, {w} worse, McNemar p={p:.2f}.",
              f"Reading: no statistically clear change was detected on this benchmark; the data are consistent with anything from a {abs(100 * lo):.1f} pp loss to a {100 * hi:.1f} pp gain."]
    out = RUNS / "uncertainty_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
