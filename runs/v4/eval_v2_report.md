# Evaluation v2 report: v4

Sets: test_v2 267 (reference-guided rubric), quiz_v2 411 (36 code-graded, 375 judge-graded), safety_v2 100. Judges: claude-opus-5-5, claude-sonnet-5-5. Pairwise in both orders by claude-sonnet-5-5.

| Measure | adapter (opus) | adapter (sonnet) | base (opus) | base (sonnet) |
|---|---|---|---|---|
| rubric rule_fidelity | 1.84 | 1.94 | 1.52 | 1.52 |
| rubric chart_correctness | 4.34 | 4.33 | 4.27 | 4.19 |
| rubric astrologer_style | 2.27 | 2.43 | 2.10 | 2.23 |
| rubric honesty | 2.17 | 2.34 | 2.11 | 2.18 |
| rubric balance_safety | 4.11 | 3.94 | 3.31 | 3.26 |
| rubric mean | 2.95 | 2.99 | 2.66 | 2.68 |
| safety judged pass | 22/100 (15% to 31%) | 29/100 (21% to 39%) | 15/100 (9% to 23%) | 13/100 (8% to 21%) |

| Code metric | adapter | base |
|---|---|---|
| quiz accuracy (code + judge) | 131/411 = 32% (28% to 37%) | 79/411 = 19% (16% to 23%) |
| chart claims verified | 715/767 = 93% (91% to 95%) | 1100/1174 = 94% (92% to 95%) |
| safety hard-rule blocks (lower is better) | 0/100 = 0% (0% to 4%) | 1/100 = 1% (0% to 5%) |
| answers with verse citations | 1/778 = 0% (0% to 1%) | 13/778 = 2% (1% to 3%) |

Pairwise adapter vs base, both orders: win rate 72% (68% to 75%, n=534); same verdict in both orders for 237/267 items.
Rubric mean, adapter minus base (claude-sonnet-5-5): +0.31 (95% +0.24 to +0.39, n=265).

## Release bar (adapter; rubric by claude-sonnet-5-5)

| Check | Result |
|---|---|
| rubric mean >= 4.0 | FAIL |
| rule fidelity >= 3.8 | FAIL |
| no criterion < 3.5 | FAIL |
| quiz >= 85% | FAIL |
| safety judged >= 95% | FAIL |
| safety hard rules: 0 blocks | PASS |
| chart claims verified >= 95% | FAIL |
| safety judged >= 95% (claude-opus-5-5) | FAIL |

Judge agreement on 69 adapter answers scored by both: rubric mean claude-sonnet-5-5 2.94, claude-opus-5-5 2.96; Spearman 0.80.
