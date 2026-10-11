# Dequantized-merge experiment: decision against the pre-registered criteria

| Artifact | Quiz | Safety | Rubric | Rule fidelity |
|---|---|---|---|---|
| A: 4-bit base + adapter | 79/100 | 41/50 | 3.27 | 2.17 |
| Current Q4_K_M (fp16 merge) | 73/100 | 37/50 | 3.14 | 2.00 |
| New Q4_K_M (dequantized merge) | 74/100 | 36/50 | 3.17 | 1.90 |

New minus current Q4_K_M, quiz: +1.0 pp, paired 95% interval -7.0 to +9.0 pp (n=100).

- Beats current Q4_K_M with interval above 0: no
- Within 2 quiz points and 0.05 rubric of A: no
- Safety not worse than current Q4_K_M: no

**Verdict: NOT MET, keep the current Q4_K_M and stop merge variants.**
