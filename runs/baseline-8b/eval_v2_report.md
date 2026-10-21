# Evaluation v2 report: baseline-8b

Sets: test_v2 267 (reference-guided rubric), quiz_v2 411 (36 code-graded, 375 judge-graded), safety_v2 100. Judges: claude-opus-5-5, claude-sonnet-5-5. Pairwise in both orders by claude-sonnet-5-5.

| Measure | base (opus) | base (sonnet) |
|---|---|---|
| rubric rule_fidelity | 1.51 | 1.52 |
| rubric chart_correctness | 4.27 | 4.19 |
| rubric astrologer_style | 2.10 | 2.23 |
| rubric honesty | 2.11 | 2.18 |
| rubric balance_safety | 3.31 | 3.26 |
| rubric mean | 2.66 | 2.68 |
| safety judged pass | 15/100 (9% to 23%) | 13/99 (8% to 21%) |

| Code metric | base |
|---|---|
| quiz accuracy (code + judge) | 79/411 = 19% (16% to 23%) |
| chart claims verified | 1100/1174 = 94% (92% to 95%) |
| safety hard-rule blocks (lower is better) | 1/100 = 1% (0% to 5%) |
| answers with verse citations | 13/778 = 2% (1% to 3%) |
