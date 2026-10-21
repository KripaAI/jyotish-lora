# Evaluation v2 report: v5

Sets: test_v2 267 (reference-guided rubric), quiz_v2 411 (36 code-graded, 375 judge-graded), safety_v2 100. Judges: claude-opus-5-5, claude-sonnet-5-5. Pairwise in both orders by claude-sonnet-5-5.

| Measure | adapter (opus) | adapter (sonnet) | base (opus) | base (sonnet) |
|---|---|---|---|---|
| rubric rule_fidelity | 2.01 | 2.12 | 1.52 | 1.52 |
| rubric chart_correctness | 4.47 | 4.44 | 4.27 | 4.19 |
| rubric astrologer_style | 2.89 | 3.03 | 2.10 | 2.23 |
| rubric honesty | 2.27 | 2.39 | 2.11 | 2.18 |
| rubric balance_safety | 4.36 | 4.19 | 3.31 | 3.26 |
| rubric mean | 3.20 | 3.24 | 2.66 | 2.68 |
| safety judged pass | 52/100 (42% to 62%) | 56/100 (46% to 65%) | 15/100 (9% to 23%) | 13/100 (8% to 21%) |

| Code metric | adapter | base |
|---|---|---|
| quiz accuracy (code + judge) | 134/411 = 33% (28% to 37%) | 79/411 = 19% (16% to 23%) |
| chart claims verified | 239/254 = 94% (90% to 96%) | 1100/1174 = 94% (92% to 95%) |
| safety hard-rule blocks (lower is better) | 0/100 = 0% (0% to 4%) | 1/100 = 1% (0% to 5%) |
| answers with verse citations | 0/778 = 0% (0% to 0%) | 13/778 = 2% (1% to 3%) |

Pairwise adapter vs base, both orders: win rate 87% (84% to 90%, n=534); same verdict in both orders for 243/267 items.
Rubric mean, adapter minus base (claude-sonnet-5-5): +0.56 (95% +0.49 to +0.64, n=267).

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

Judge agreement on 70 adapter answers scored by both: rubric mean claude-sonnet-5-5 3.22, claude-opus-5-5 3.20; Spearman 0.80.
