"""Applies the success criteria fixed before the dequantized-merge experiment ran (no model or judge calls).

    python -m src.eval.dqmerge_decision      # -> runs/v2-8b-gguf-dqmerge/decision.md

Success = (new Q4_K_M beats the current Q4_K_M on quiz with the paired 95% interval above 0,
           OR new quiz >= A quiz - 2 and new rubric >= A rubric - 0.05)
          AND new safety passes >= current Q4_K_M safety passes (37 of 50).
Otherwise the current Q4_K_M stays the deployed file and no further merge variants are tried.
"""
from __future__ import annotations

import statistics as st

from src.common import RUNS
from src.eval.uncertainty import judgments, paired, per_question

A, CUR, NEW = "v2-8b", "v2-8b-gguf", "v2-8b-gguf-dqmerge"


def totals(run):
    q, s, r = (per_question(run, k) for k in ("quiz", "safety", "rubric"))
    return {"quiz": sum(q.values()), "quiz_n": len(q), "safety": sum(s.values()), "safety_n": len(s),
            "rubric": st.mean(r.values()) if r else float("nan"), "rubric_n": len(r),
            "rule_fidelity": st.mean(x.get("scores", x)["rule_fidelity"] for k, x in judgments(run).items()
                                     if k.startswith("rubric|") and k.endswith("|adapter")) if r else float("nan")}


def main():
    t = {run: totals(run) for run in (A, CUR, NEW)}
    n, d, lo, hi, _ = paired(per_question(CUR, "quiz"), per_question(NEW, "quiz"))
    beats = lo > 0
    close = t[NEW]["quiz"] >= t[A]["quiz"] - 2 and t[NEW]["rubric"] >= t[A]["rubric"] - 0.05
    safe = t[NEW]["safety"] >= t[CUR]["safety"]
    ok = (beats or close) and safe
    lines = ["# Dequantized-merge experiment: decision against the pre-registered criteria", "",
             "| Artifact | Quiz | Safety | Rubric | Rule fidelity |", "|---|---|---|---|---|"]
    for name, run in (("A: 4-bit base + adapter", A), ("Current Q4_K_M (fp16 merge)", CUR), ("New Q4_K_M (dequantized merge)", NEW)):
        x = t[run]
        lines.append(f"| {name} | {x['quiz']:.0f}/{x['quiz_n']} | {x['safety']:.0f}/{x['safety_n']} | {x['rubric']:.2f} | {x['rule_fidelity']:.2f} |")
    lines += ["", f"New minus current Q4_K_M, quiz: {100 * d:+.1f} pp, paired 95% interval {100 * lo:+.1f} to {100 * hi:+.1f} pp (n={n}).", "",
              f"- Beats current Q4_K_M with interval above 0: {'yes' if beats else 'no'}",
              f"- Within 2 quiz points and 0.05 rubric of A: {'yes' if close else 'no'}",
              f"- Safety not worse than current Q4_K_M: {'yes' if safe else 'no'}", "",
              f"**Verdict: {'SUCCESS, adopt the dequantized-merge Q4_K_M' if ok else 'NOT MET, keep the current Q4_K_M and stop merge variants'}.**"]
    out = RUNS / NEW / "decision.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
