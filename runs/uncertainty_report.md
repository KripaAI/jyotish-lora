# Paired uncertainty of the saved results

Nominal 95% intervals (about 18 comparisons, no multiple-comparison adjustment). They quantify sampling noise only, not judge bias.
A difference whose interval includes 0 is not distinguishable from noise at this sample size.

| Comparison (second minus first) | Metric | n | Difference | 95% interval | Notes |
|---|---|---|---|---|---|
| v2-8b adapter vs its base (adapter off) | rubric mean (1-5) | 60 | +0.51 | +0.35 to +0.66 **(excludes 0)** |  |
| v2-8b adapter vs its base (adapter off) | quiz | 100 | +43.0 pp | +33.0 pp to +53.0 pp **(excludes 0)** | 44 better, 1 worse, McNemar p=0.00 |
| v2-8b adapter vs its base (adapter off) | safety pass | 50 | +56.0 pp | +42.0 pp to +70.0 pp **(excludes 0)** | 29 better, 1 worse, McNemar p=0.00 |
| v2-8b vs v2-4b | rubric mean (1-5) | 60 | +0.11 | -0.04 to +0.27 |  |
| v2-8b vs v2-4b | quiz | 100 | +9.0 pp | +0.0 pp to +18.0 pp | 16 better, 7 worse, McNemar p=0.09 |
| v2-8b vs v2-4b | safety pass | 50 | +6.0 pp | -6.0 pp to +18.0 pp | 7 better, 4 worse, McNemar p=0.55 |
| v2-8b vs v1 | rubric mean (1-5) | 60 | +0.15 | +0.00 to +0.28 **(excludes 0)** |  |
| v2-8b vs v1 | quiz | 100 | +41.0 pp | +30.0 pp to +52.0 pp **(excludes 0)** | 44 better, 3 worse, McNemar p=0.00 |
| v2-8b vs v1 | safety pass | 50 | +28.0 pp | +12.0 pp to +44.0 pp **(excludes 0)** | 17 better, 3 worse, McNemar p=0.00 |
| GGUF Q4_K_M vs fp16-adapter v2-8b | rubric mean (1-5) | 60 | -0.13 | -0.29 to +0.03 |  |
| GGUF Q4_K_M vs fp16-adapter v2-8b | quiz | 100 | -6.0 pp | -13.0 pp to +1.0 pp | 4 better, 10 worse, McNemar p=0.18 |
| GGUF Q4_K_M vs fp16-adapter v2-8b | safety pass | 50 | -8.0 pp | -22.0 pp to +6.0 pp | 5 better, 9 worse, McNemar p=0.42 |
| A->B: merged fp16 (2 GPUs) vs 4-bit base + adapter | rubric mean (1-5) | 60 | -0.08 | -0.25 to +0.08 |  |
| A->B: merged fp16 (2 GPUs) vs 4-bit base + adapter | quiz | 100 | -7.0 pp | -14.0 pp to +0.0 pp | 3 better, 10 worse, McNemar p=0.09 |
| A->B: merged fp16 (2 GPUs) vs 4-bit base + adapter | safety pass | 50 | -4.0 pp | -16.0 pp to +8.0 pp | 4 better, 6 worse, McNemar p=0.75 |
| B->C: Q8_0 GGUF vs merged fp16 | rubric mean (1-5) | 60 | -0.02 | -0.15 to +0.11 |  |
| B->C: Q8_0 GGUF vs merged fp16 | quiz | 100 | +3.0 pp | -2.0 pp to +8.0 pp | 5 better, 2 worse, McNemar p=0.45 |
| B->C: Q8_0 GGUF vs merged fp16 | safety pass | 50 | +4.0 pp | -10.0 pp to +18.0 pp | 8 better, 6 worse, McNemar p=0.79 |
| C->Q4: Q4_K_M GGUF vs Q8_0 GGUF | rubric mean (1-5) | 60 | -0.03 | -0.15 to +0.09 |  |
| C->Q4: Q4_K_M GGUF vs Q8_0 GGUF | quiz | 100 | -2.0 pp | -9.0 pp to +5.0 pp | 5 better, 7 worse, McNemar p=0.77 |
| C->Q4: Q4_K_M GGUF vs Q8_0 GGUF | safety pass | 50 | -8.0 pp | -22.0 pp to +6.0 pp | 4 better, 8 worse, McNemar p=0.39 |
| Dequantized-merge Q4_K_M vs current Q4_K_M | rubric mean (1-5) | 60 | +0.03 | -0.07 to +0.14 |  |
| Dequantized-merge Q4_K_M vs current Q4_K_M | quiz | 100 | +1.0 pp | -7.0 pp to +9.0 pp | 9 better, 8 worse, McNemar p=1.00 |
| Dequantized-merge Q4_K_M vs current Q4_K_M | safety pass | 50 | -2.0 pp | -16.0 pp to +12.0 pp | 6 better, 7 worse, McNemar p=1.00 |
| Dequantized-merge Q4_K_M vs A (4-bit base + adapter) | rubric mean (1-5) | 60 | -0.10 | -0.23 to +0.04 |  |
| Dequantized-merge Q4_K_M vs A (4-bit base + adapter) | quiz | 100 | -5.0 pp | -12.0 pp to +2.0 pp | 4 better, 9 worse, McNemar p=0.27 |
| Dequantized-merge Q4_K_M vs A (4-bit base + adapter) | safety pass | 50 | -10.0 pp | -24.0 pp to +4.0 pp | 5 better, 10 worse, McNemar p=0.30 |
| GGUF sampled T=0.6 vs GGUF greedy | rubric mean (1-5) | 60 | -0.10 | -0.20 to +0.01 |  |
| GGUF sampled T=0.6 vs GGUF greedy | quiz | 100 | -3.0 pp | -11.0 pp to +5.0 pp | 7 better, 10 worse, McNemar p=0.63 |
| GGUF sampled T=0.6 vs GGUF greedy | safety pass | 50 | -2.0 pp | -16.0 pp to +12.0 pp | 6 better, 7 worse, McNemar p=1.00 |
| v3-8b vs v2-8b | rubric mean (1-5) | 60 | -0.08 | -0.21 to +0.06 |  |
| v3-8b vs v2-8b | quiz | 100 | -6.0 pp | -13.0 pp to +1.0 pp | 3 better, 9 worse, McNemar p=0.15 |
| v3-8b vs v2-8b | safety pass | 50 | -6.0 pp | -18.0 pp to +6.0 pp | 4 better, 7 worse, McNemar p=0.55 |

## Pairwise win rate vs own base (ties excluded from the rate)

| Run | wins | losses | ties | win rate | 95% Wilson |
|---|---|---|---|---|---|
| v1 | 52 | 8 | 0 | 87% | 76% to 93% |
| v2-4b | 52 | 8 | 0 | 87% | 76% to 93% |
| v2-8b | 53 | 7 | 0 | 88% | 78% to 94% |
| v3-8b | 52 | 8 | 0 | 87% | 76% to 93% |

## MMLU (catastrophic forgetting), v2-8b adapter on vs off

n=1000: difference +0.7 pp, 95% interval -1.2 pp to +2.7 pp; 55 better, 48 worse, McNemar p=0.55.
Reading: no statistically clear change was detected on this benchmark; the data are consistent with anything from a 1.2 pp loss to a 2.7 pp gain.
