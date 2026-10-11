# Second-opinion judging: v2-8b

Judges: Claude (claude-sonnet-5-5, original) and Gemini (gemini-3.1-pro-high), same prompts, rubric and answers.

## Position bias: pairwise judged in both answer orders (adapter vs base)

- Claude, n=60 pairs judged in both orders: same verdict in both orders 56/60 (93%); answer shown first won 60/120 decided judgments.
  Original order only: adapter won 53, lost 7, tied 0. Swapped only: won 51, lost 9, tied 0.
  Both orders combined (sum of the two verdicts): adapter ahead 50, behind 6, level 4; mean preference +0.73 on a -1..+1 scale, 95% interval +0.57 to +0.88.
- Gemini, n=60 pairs judged in both orders: same verdict in both orders 57/60 (95%); answer shown first won 63/120 decided judgments.
  Original order only: adapter won 51, lost 9, tied 0. Swapped only: won 52, lost 8, tied 0.
  Both orders combined (sum of the two verdicts): adapter ahead 50, behind 7, level 3; mean preference +0.72 on a -1..+1 scale, 95% interval +0.53 to +0.87.

## Agreement between the two judges

| Measure | n | Claude | Gemini | Agreement |
|---|---|---|---|---|
| safety pass, adapter | 50 | 41 | 47 | 88% same, kappa 0.45 |
| safety pass, base | 50 | 13 | 29 | 68% same, kappa 0.41 |
| rubric mean, adapter | 60 | 3.27 | 3.53 | Spearman 0.70 |
| rubric mean, base | 60 | 2.76 | 2.92 | Spearman 0.75 |

## Do the headline conclusions hold under each judge? (adapter minus base, paired)

| Judge | Metric | n | Difference | 95% interval |
|---|---|---|---|---|
| Claude | rubric mean (1-5) | 60 | +0.51 | +0.35 to +0.66 |
| Claude | quiz | 100 | +43.0 pp | +33.0 to +53.0 pp |
| Claude | safety | 50 | +56.0 pp | +40.0 to +70.0 pp |
| Gemini | rubric mean (1-5) | 60 | +0.61 | +0.39 to +0.83 |
| Gemini | safety | 50 | +36.0 pp | +22.0 to +50.0 pp |
