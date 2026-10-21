# Jyotish LoRA: Implementation Plan

| | |
|---|---|
| **Version** | 2.0 |
| **Date** | 2026-10-19 |
| **Governed by** | [Project Constitution](constitution.md) |
| **Implements** | [Technical Specification](tech-spec.md) |
| **Evidence** | [Production review](production-review.pdf) (2026-10-18); live status in `STATUS.md` section 0 and [v4 progress log](v4-progress-log.pdf) |
| **Supersedes** | Version 1.2 (2026-10-05), whose phases 0 to 7 are recorded below as Phase 1 |

---

## How to read this plan

The project has two phases.

- **Phase 1 (5 to 11 October 2026)** built the first model end to end: corpus, chart engine, dataset, four LoRA/QLoRA adapters, evaluation, export and a safety layer. It produced a working prototype that **fails the release bar on rule fidelity and safety**. Section 1 records what was done, the measured results and the lessons, so nobody has to re-learn them.
- **Phase 2 (from 18 October 2026)** is the programme to make the model production grade. It follows the evidence in the production review: rebuild the training data so that every rule is seen many times in many wordings, move computable facts into code, grow the evaluation set until differences are measurable, add a verifier-driven refinement stage, and finish the serving, safety and release work. **Phase 2 spends no money**: Claude Pro subscription, the owner's RTX 5070 Ti, Kaggle's free tier and code only.

Every stage ends at a **gate**: a checklist that must pass before the next stage starts. Gates are numbered 1 to 7 in Phase 1 (the original numbering, still referenced in `STATUS.md` and the run reports) and A to F in Phase 2.

---

## Phase 1: the first model, as executed (2026-10-05 to 2026-10-11)

### 1.1 What was built

| Stage | Goal | What happened | Gate |
|---|---|---|---|
| 0 Setup | Reproducible skeleton | Python 3.11 venv, Tesseract, Kaggle account, teacher LLM chosen (Claude Opus 5.5 by subscription, no API key) | Passed except the terms check on training with Claude and Gemini outputs (task 0.7, still open) |
| 1 Corpus | Clean chunks from 52 PDFs | 46 books (6 excluded: 5 Hindi, 1 software manual), 6,129 pages, 893 OCR pages, 99.0% usable, 4,012 quality chunks with topic tags | **Gate 1 passed** |
| 2 Chart engine | Deterministic chart facts | Swiss Ephemeris, Lahiri, whole-sign houses, Vimshottari, D9, 33 rule-based yogas, synthetic births from 153 cities, 79 tests; `render_chart_text` shared by training and serving | **Gate 2 passed**, one item open: hand check of 10 charts against Jagannatha Hora |
| 3 Dataset | About 6,000 checked examples | 879 of 3,100 planned seeds used; Sonnet wrote questions, Opus answers, Gemini and Sonnet fact-checked; 2,116 generated, 1,885 after filters, 1,548 after model review; split 1,421 / 67 / 60 by chunk and chart seed. v2 added 723 table facts and 183 strict safety rows: 2,327 training rows | Gate 3 **not met**: 1,548 against 5,000 planned; human review 5 rows against 200 required |
| 4 Smoke test | Pipeline works | Qwen3-1.7B, 200 rows, 30 steps on a Kaggle T4; resume from checkpoint verified | **Gate 4 passed** |
| 5 Training | First adapters | v1 and v2-4b: Qwen3-4B-Instruct-2507, plain LoRA r=32, alpha 64, all seven projections, 2 epochs, LR 2e-4, max 3,072 tokens, 5 to 7 h. v2-8b and v3-8b: Qwen3-8B, QLoRA NF4 r=16, paged 8-bit AdamW, about 12 h in two 11-hour kernels. Validation loss fell from 2.9 to 1.5 (4B) and 2.36 to 1.37 (8B) | **Gate 5 passed** for every run |
| 6 Evaluation | Release thresholds | Claude Sonnet judge on 60 test answers, 100-item quiz, 50 safety prompts; order-swapped pairwise; Gemini second judge; paired bootstrap intervals; 1,000-item MMLU forgetting check; 100-prompt robustness set | **Gate 6 failed** for all four adapters (see 1.2) |
| 7 Export and app | Runs locally | Merge to fp16, GGUF Q4_K_M (5.0 GB) and Q8_0; llama.cpp 30 tok/s on a T4, 5 tok/s on a laptop CPU; `src/app` pipeline, regex safety layer with fixed replies, FastAPI server, Kaggle live demo, private Hugging Face repo | Gate 7 **not reached**: Ollama Modelfile, README, end-to-end test not done |

### 1.2 Results against the release bar

Same 60 test answers, 100 quiz items and 50 safety prompts for every run; judge Claude Sonnet 5.5.

| Run | Base and method | Quiz /100 | Safety /50 | Rubric mean | Rule fidelity | Win vs base |
|---|---|---|---|---|---|---|
| v1 | Qwen3-4B, LoRA r=32, 1,421 rows | 38 | 27 | 3.12 | 1.83 | 87% |
| v2-4b | same base, 2,327 rows (facts + strict safety) | 70 | 38 | 3.16 | 1.98 | 87% |
| **v2-8b** (best) | Qwen3-8B, QLoRA r=16, 2,327 rows | **79** | **41** | **3.27** | **2.17** | **88%** |
| v3-8b | v2 data with counted chart facts and code-written reasoning | 73 | 38 | 3.19 | 2.08 | 87% |
| v2-8b Q4_K_M GGUF (deployed) | merged and quantised | 73 | 37 | 3.14 | 2.00 | |
| **Release bar** | | **75** | **50** | **4.0** | **3.8** | **70%** |

Only the quiz and the win rate pass. The adapter clearly beats its base (rubric +0.51, interval +0.35 to +0.66; both judges and both answer orders agree; no measurable MMLU forgetting). Nothing after v2-4b is distinguishable from noise with 60 test items.

### 1.3 What Phase 1 taught

1. **Facts stated directly and repeatedly are learned; rules seen once are not.** The 723 table-fact rows lifted the quiz from 38 to 70 on the same base. Everything else in the data showed each classical rule once, in one teacher paraphrase, and rule fidelity stayed near 2 of 5: invented methods, swapped yoga definitions, misattributed books.
2. **A bigger base, thinking mode and counted facts in the prompt did not move the scores** beyond noise. The data recipe, not the model, was the limit.
3. **The model mis-copies facts that are in the prompt** (2 of 5 "Nth from the Moon" claims wrong in v3). Copying has to be trained, and claims have to be verified in code.
4. **Safety misses are content, not refusal**: the model declines correctly and then adds a health claim, a market-timing method or a longevity result. A regex layer did not raise the pass rate and added false positives.
5. **The evaluation set is too small to steer by**: three of four iterations were inconclusive, and the two judges differ by 0.26 rubric and 6 safety points on absolute scores.
6. **Export loses a little**: fp16 merge, then Q8 and Q4, cost about 6 quiz points in total, each step within noise; a dequantised merge did not help.
7. **Wording matters**: Hinglish and Sanskrit-term paraphrases of quiz questions dropped accuracy from 24 to 19 of 30.

### 1.4 Phase 1 items carried into Phase 2

- Hand check of 10 charts against Jagannatha Hora (Gate 2).
- Human review of 200 examples before a training run (constitution IV.2; 5 were reviewed).
- Terms check for training on Claude and Gemini outputs, and the copyright review of the 46 texts before anything is published (constitution VI; task 0.7).
- README, Ollama Modelfile, end-to-end laptop test (Gate 7).

---

## Phase 2: production-grade programme (from 2026-10-18)

### 2.0 Principles

1. **Zero cash cost.** Claude Pro subscription for tasks that need a strong model (rule extraction, judging, a few hundred full readings); the local open model (Qwen3 14B through Ollama on the owner's RTX 5070 Ti) for bulk rewriting; code for everything that can be computed; Kaggle free tier or the local GPU for training.
2. **Data first, yardstick second, GPU last.** Three of four Phase 1 runs were wasted because the data could not teach the rules and the test set could not show it.
3. **Correct by construction wherever possible.** Facts, chart claims and reasoning blocks come from the engine, never from a model.
4. **Nothing reaches training without a check**: entity containment against its source record, English-only answers, a safety block, the citation ban, attribution present, no overlap with any evaluation set.
5. **Gates and one readable signal per change.** No training run starts before Gate B; no release before Gate D and F.

### Stage 2A: Data v4 (in progress; detail in `STATUS.md` section 0)

**Goal:** 25,000 or more checked training rows in which every rule appears 3 to 8 times in different wording.

| # | Task | Output | State (2026-10-19) |
|---|---|---|---|
| A.1 | Workstation environment: Python 3.11 venv, tests, Ollama with 4 parallel slots | 176 tests pass; 155 to 240 tok/s local generation | Done |
| A.2 | Corpus on the workstation: junction to the PDFs, extraction with RapidOCR (pip, no admin), chunking, 5% of chunks held out for a future unseen test set | 4,169 chunks from 45 books, 99.0% usable; 180 held-out chunks | Done |
| A.3 | `facts_v4.py`: table facts in 10 phrasings incl. Hinglish, contrast questions, Pancha Mahapurusha, yoga definitions, vargas, Ashtakoota, Kuja dosha, Vimshottari basics | 737 rows | Done |
| A.4 | `drills.py`: chart copying drills (house from the Moon, lord placement, occupants, aspects, dignity, dasha, D9) and engine-grounded yoga rows, v3 chart text, code-written working | 2,000 rows from 400 charts | Done |
| A.5 | `rules.py`: Claude extracts atomic rules (statement, conditions, modifiers, exceptions, text, tradition) from the 1,339 checked answers and every quality chunk, 3 items per call; merge near-duplicates; content-hashed ids | 37,029 rules (8,833 from answers, 28,982 from chunks) | Done |
| A.6 | `rule_qa.py generate`: the local model (workstation GPU) plus four Kaggle T4 kernels rewrite each rule as 4 Q&A pairs, at least one question in Hinglish, high-confidence rules first | 36,998 of 37,029 rules sampled (20 Oct 03:10) | Done |
| A.7 | `rule_qa.py build`: checks (containment, English answers with Hinglish rescue, safety block for death, disease and stigma, citation ban, attribution, on-rule question, dedupe, eval overlap) | 99,474 pairs kept of 164,975 (60%), 17,456 Hinglish | Done |
| A.8 | `build_v4.py`: assemble v3 rows + A.3 + A.4 + A.7 into prompt/completion strings (thinking on for chart rows), v1 val and test unchanged; Kaggle upload folder; applies human rejects and edits from A.9 | 104,528 training rows, about 55M tokens | Done (20 Oct 03:15) |
| A.9 | Human review of 200 rows, stratified across streams (constitution IV.2): `review_v4 export` wrote `data/reviews/review_v4.csv`; `review_v4 import` applies verdicts | review CSV written; decisions pending | **Needs owner** |
| A.10 | Known-vs-unknown screen: ask the base model one question per fact or rule; give unknown items 6 to 8 paraphrases, known 2; turn uncovered topics into abstention rows | per-rule paraphrase counts, abstention rows | Next (`ollama pull qwen3:8b`, free) |
| A.11 | General replay: 10 to 20% permissively licensed general instruction data, so a 10x larger domain set does not erode general ability or thinking mode | replay rows | Next |

**Gate A**
- [ ] 25,000 or more rows after checks; every quiz category covered by 5 or more phrasings.
- [ ] Human review of 200 rows with under 10% rejects.
- [ ] Zero overlap with quiz, robustness, validation and test questions (automatic).
- [ ] No row states a death or death-timing result, a disease diagnosis or a stigma (automatic block plus the review).
- [ ] Dataset hash recorded in the manifest.

### Stage 2B: Evaluation v2

**Goal:** a test suite that can resolve a 0.3 rubric change and a 5-point quiz change.

| # | Task | Output | State (20 Oct 2026) |
|---|---|---|---|
| B.1 | Held-out test set from the 196 held-out chunks (questions and Opus reference answers via Claude, fact-checked, never trained on) | `evalsets/test_v2.jsonl`, 267 items | Done |
| B.2 | Quiz v2: Claude-written items with exact answers from held-out rules (judge-graded) plus table items in Hinglish and new wording (code-graded) | `evalsets/quiz_v2.jsonl`, 411 items | Done |
| B.3 | 100 new adversarial safety prompts, 15 categories x 6 styles, written before any Phase 2 training run; the 50 handwritten prompts stay | `evalsets/safety_v2_eval.jsonl` | Done |
| B.4 | Code metrics: chart-claim verification against the chart dict, citation regex, safety hard rules | `src/eval/claims.py`, `src/eval/run_eval_v2.py` | Done (v2-8b sanity check: base 96%, adapter 88% of claims verified) |
| B.5 | Judge protocol: Claude Opus 5.5 primary, Claude Sonnet 5.5 second (Phase 1 continuity), pairwise in both orders, reference-guided grading, intervals, release-bar table | `src/eval/run_eval_v2.py` | Done |
| B.6 | 60-item human calibration set rated by the owner; judge agreement reported | `runs/judge_calibration.md` | **Needs owner** |
| B.7 | Pre-registered thresholds and minimum detectable effect, fixed before the first v4 run | `runs/preregistration_v4.md` | Done |

**Gate B**
- [ ] 300 test items, 300 quiz items, 150 safety prompts, none overlapping training.
- [ ] Judge-human agreement measured on 60 items; minimum detectable rubric effect 0.3 or better at 80% power.
- [ ] Thresholds written down before training.

### Stage 2C: Training v4

**Goal:** the first adapter trained on v4 data, chosen on the metrics that matter.

| # | Task | Output |
|---|---|---|
| C.1 | Training script on Unsloth for the owner's RTX 5070 Ti (bf16, 4-bit base, rsLoRA, completion-only loss, quiz callback keeps the best checkpoint); Kaggle (tokens for two accounts are on the workstation) stays the alternative with `fp16=True, bf16=False` | `src/train/train_local.py`, `src/train/eval_generate_local.py`; smoke test started 20 Oct 03:15 |
| C.2 | Base smoke tests, 200 steps each: Qwen3-8B QLoRA, Qwen3.5-4B plain LoRA fp16, Qwen3.5-9B QLoRA (only if bitsandbytes and llama.cpp support it) | pick by quiz and chart-claim rate |
| C.3 | Learning-rate sweep 2e-4, 5e-4, 1e-3 for 300 steps each | best LR |
| C.4 | Full run: r=32, alpha=64, rsLoRA, dropout 0, weight decay 0.01, all seven projections, max 4,096 tokens, batch 4 x accumulation 2; one epoch over all 104k rows first (fresh data beats repetition; about 12 h on the 5070 Ti for Qwen3-8B 4-bit, measured 3.35 s per step), a second epoch only if the quiz callback is still rising; thinking on with the code-written working for the 2,510 chart rows | `astro-lora-v4` adapter and manifest |
| C.5 | Callback: greedy-decode 100 quiz items every 200 steps; choose the checkpoint on quiz and chart-claim rate, not on validation loss | checkpoint choice recorded |
| C.6 | Full Stage 2B evaluation of the chosen checkpoint against base and v2-8b | `runs/v4/eval_report.md` |

**Results so far (21 Oct 2026):** v4 (103k rows, 95% single-template paraphrases) learned facts but collapsed safety (Phase 1
safety 6%) and voice. v5 (42k rows, rebalanced: one paraphrase per rule, teacher answers x3, safety 5%) is the best model on
facts (Phase 1 quiz 96% vs v2-8b 79%) with voice restored (style 3.05 vs 3.10) and a clear gain over the base (rubric +0.56,
win 87%), but Phase 1 safety is 60% vs v2-8b's 82% (generic safety replies miss prompt-specific requirements) and rule fidelity
is unchanged (2.0). Gate C is not met. Next: question-specific safety training data, then Stage 2D for rule fidelity.

**Gate C**
- [ ] Quiz 85% or more; rule fidelity 3.3 or more; safety 95% or more (judged, both judges).
- [ ] Every headline metric better than v2-8b with a paired interval that excludes zero.
- [ ] No MMLU regression beyond 2 points.

### Stage 2D: Verifier loop

**Goal:** reach the release bar by sharpening consistency, using the chart engine as the reward.

| # | Task | Output |
|---|---|---|
| D.1 | Rejection-sampling fine-tuning: 4 samples per chart prompt at T=0.7 from v4, keep the best engine-verified and judge-approved answer, train one more epoch | `astro-lora-v4-rft` |
| D.2 | Preference stage: about 2,000 pairs, chosen = verified consistent, rejected = contradicts the chart or invents a book; ORPO or DPO (no reference model on a T4) | `astro-lora-v4-pref` |
| D.3 | Optional GRPO with a programmatic reward (claim consistency plus mild format and length terms, no harsh penalties), only if a 4B base was chosen or the local GPU fits it | `astro-lora-v4-grpo` |

**Gate D (release bar, measurement redefined in 2.7)**
- [ ] 95% or more of chart claims verify in code.
- [ ] Rubric mean 4.0 or more; rule fidelity 3.8 or more; no criterion below 3.5.
- [ ] Safety: 100% on the hard rules by code and classifier; 95% or more judged by both judges.
- [ ] Pairwise win rate 70% or more against the base; no regression against v4.

### Stage 2E: Serving facts and guards

| # | Task | Output |
|---|---|---|
| E.1 | Deterministic lookup block in the prompt for concept and placement questions (sign lords, dignities, nakshatra lords, aspects, yoga definitions from the engine tables); constitution v1.3 clarifies that this is not retrieval of passages | `src/app/pipeline.py`, constitution 1.3 |
| E.2 | Output recount of every chart claim against the chart dict; one regeneration on failure, then the fixed reply | `src/app/safety.py` |
| E.3 | Learned guard: Qwen3Guard 0.6B (Apache 2.0, 119 languages) on input and output beside the regex rules; the old scipy classifier becomes a fallback | guard module and tests |
| E.4 | Export test: runtime LoRA in llama.cpp against the fp16 merge on the full eval; ship whichever scores higher; Q8_0 for GPU hosts, Q4_K_M for the laptop | `runs/v4/export_report.md` |
| E.5 | Safety policy document from which the eval prompts, fixed replies and guard thresholds derive | `docs/safety-policy.md` |

**Gate E**
- [ ] Hard safety rules 100% by code on the 150-prompt set; over-refusal of legitimate questions 5% or less.
- [ ] Deployed artifact within noise of the adapter on quiz and rubric.

### Stage 2F: Release readiness

| # | Task | Output |
|---|---|---|
| F.1 | Copyright review of the 46 texts and terms check for Claude and Gemini outputs (constitution VI; Phase 1 task 0.7) | decision recorded; weights and data stay private until it passes |
| F.2 | Red-team exercise per the NIST Generative AI Profile; explicit tests for OWASP LLM01 prompt injection and LLM07 system-prompt leakage; findings logged with fixes | `runs/redteam_v4.md` |
| F.3 | Model card, README with usage and limits, disclaimer on every answer, Ollama Modelfile | `deploy/model_card.md`, `README.md` |
| F.4 | Monitoring: latency, tokens, guard route, verifier result, model hashes; alerts on refusal drift and verifier failures; rollback flag | `src/app/server.py` |
| F.5 | 30-prompt human regression review; hand check of 10 charts against Jagannatha Hora (Phase 1 carry-over) | notes |
| F.6 | End-to-end laptop test (Phase 1 Gate 7) | test log |

**Gate F:** F.1 passed, F.2 findings closed, Gates D and E met, no regression against the previous version.

### 2.7 Release bar, measurement redefined

Two Phase 1 thresholds were not measurable as written and are redefined, not relaxed:

- **Safety 100%** is split into hard rules enforced and measured by code and the guard model (no death or timing prediction, no diagnosis, no trading instructions, helpline on self-harm, no verse citations, no stigma), which must be 100%, and a judged rubric that must reach 95% under both judges.
- **Rule fidelity 3.8** is scored against the reference answer with reference-guided grading, which cuts judge error on checkable content from about 70% to 15% in published tests.

### 2.8 Compute and cost

| Stage | GPU hours | Where | Cash |
|---|---|---|---|
| 2A Data v4 | 0 Kaggle; about 30 h local GPU for paraphrases | workstation (Ollama), Claude subscription | 0 |
| 2B Evaluation v2 | 3 | Kaggle T4 or local | 0 |
| 2C Training v4 | about 30 (smoke 3, sweep 6, full 20, eval 1) | local RTX 5070 Ti or Kaggle T4 (two accounts, about 60 h per week) | 0 |
| 2D Verifier loop | about 20 | local or Kaggle | 0 |
| 2E Serving tests | 5 | Kaggle T4 or local | 0 |
| 2F Release | 0 | laptop | 0 |

---

## 3. Roles

| Role | Responsibility |
|---|---|
| Owner | Decisions at every gate, human review (A.9, B.6, F.5), licence review (F.1), Kaggle token if Kaggle is used |
| Claude Code | Scripts, notebooks, checks, evaluation tooling, this plan and `STATUS.md` |
| Claude (subscription) | Rule extraction, a few hundred full readings, judging |
| Local open model (Qwen3 14B via Ollama) | Bulk rewriting of rules into Q&A pairs; never authors a rule |
| Gemini (Antigravity CLI, when installed) | Second judge on a 100-item subset |
| Chart engine | Every chart fact, every claim verification, every reward |

## 4. Definition of done (v4)

1. `astro-lora-v4` (or its RFT or preference successor) passes Gates D, E and F.
2. All artifacts (dataset hash, adapter, manifest, eval report, export report, red-team log) are in `runs/v4/`.
3. The constitution compliance checklist below is complete.

### Constitution compliance checklist

- [ ] I. Every training answer traces to a source record (rule record, table or chart); no verse citations or invented sources in evaluation.
- [ ] II. All charts and all claim checks come from `src/chart`; the model calculates nothing.
- [ ] III. LoRA or QLoRA on free hardware; full fine-tuning not used.
- [ ] IV. Human review of 200 rows done; evaluation sets held out; 5% of chunks never used for training.
- [ ] V. Safety hard rules 100% by code; judged safety 95% or more; disclaimer shown.
- [ ] VI. Model, adapter and data private until the licence and terms review passes.
- [ ] VII. Synthetic birth data only; server logs strip personal text by default.
- [ ] VIII. Run manifests complete for every run; rule ids and dataset hashes recorded.
- [ ] IX. Beats the base model and v2-8b with intervals that exclude zero; no safety regression.

## 5. Backlog (after v4)

- **Hindi output** (Devanagari or Hinglish answers): recover the 5 excluded Hindi books (legacy-font converter for Lal Kitab 1941 and Chamatkar Chintamani; Hindi OCR for the three scanned Lal Kitab volumes), amend the constitution for bilingual scope, generate Hindi Q&A, train and evaluate bilingually. Note that Qwen3's tokenizer spends about 4.8 tokens per Devanagari word against 1.3 for English.
- Retrieval of passages at inference, only if Gate D is missed after one verifier round; this is a constitution change, not a training change.
- Tesseract instead of RapidOCR for the scanned pages, if the owner approves the installer's admin prompt.
- Chart engine as an MCP tool for other assistants.

## 6. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-05 | First plan: phases 0 to 7, gates, GPU budget |
| 1.1 | 2026-10-05 | RAG out of scope; attribution by tradition or text |
| 1.2 | 2026-10-05 | QLoRA allowed for 8B; DPO noted as a later step |
| 2.0 | 2026-10-19 | Phases 0 to 7 recorded as Phase 1 with results and lessons; Phase 2 production-grade programme (stages 2A to 2F) added on the evidence of the production review; zero-cost constraint; release-bar measurement redefined; backlog trimmed |
