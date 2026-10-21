---
base_model: Qwen/Qwen3-8B
library_name: peft
pipeline_tag: text-generation
tags:
- lora
- qlora
- unsloth
- vedic-astrology
---

# astro-v5-8b-lora (private research adapter)

A QLoRA adapter for **Qwen3-8B** that answers questions in the voice of a classical Vedic (Jyotish) astrologer. Research
artifact, not a released product: kept private until a licence review of the source books is complete.

## How it was trained
- Base: Qwen/Qwen3-8B loaded in 4-bit NF4 (Unsloth `unsloth/Qwen3-8B-unsloth-bnb-4bit`); rsLoRA r=32, alpha=64, all 7 projections.
- Data: 41,985 rows (v5 mix): one paraphrased Q&A per atomic rule extracted from 46 classical texts, teacher-written answers,
  table facts, chart-reading drills and 1,465 safety rows. Completion-only loss; one epoch; LR 1.5e-4; max_grad_norm 0.5; 4.9 h on an RTX 5070 Ti.
- Prompt format: Qwen3 chat format with the system prompt in `system_v1.txt`. Chart questions need chart text rendered by the
  project's chart engine (the model never calculates charts).

## Evaluation (judge: Claude Sonnet 5.5)
| Measure | v5 (this) | previous best v2-8b |
|---|---|---|
| Fact quiz (100) | 96% | 79% |
| Safety prompts (50) | 60% | 82% |
| Rubric mean (1-5) | 3.18 | 3.27 |
| Rule fidelity (1-5) | 2.00 | 2.17 |

On a 267-question held-out test: rubric 3.24 vs 2.68 for the untrained base; preferred over the base in 87% of pairwise comparisons.

## Limits
- Weaker on sensitive questions than v2-8b: serve it only behind the project's safety layer (`src/app/safety.py`).
- Long free-form answers are often imprecise about classical rules (rule fidelity about 2/5).
- Astrology is not a predictive science. Answers must not be used for medical, legal, financial or life-and-death decisions.

## Usage
```python
from unsloth import FastLanguageModel
model, tok = FastLanguageModel.from_pretrained("<this repo>", load_in_4bit=True, max_seq_length=4096)
```
