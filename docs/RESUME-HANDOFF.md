# Jyotish LoRA: Resume Handoff

**Written:** 2026-10-21 (end of the v5 cycle). **Audience:** any AI coding assistant (Claude, Gemini, GPT or other) or person
picking this project up cold. Read this file top to bottom before touching anything. It is self-contained; deeper detail is in
the files it points to.

---

## 1. What this project is

A fine-tune of an open model (currently **Qwen3-8B**, QLoRA 4-bit) that answers questions the way a classical Vedic astrologer
would, grounded in 46 astrology books. The model never calculates charts: a deterministic chart engine (`src/chart/`, Swiss
Ephemeris, Lahiri ayanamsa, whole-sign houses) computes every chart and the model only interprets the rendered chart text.

**Owner's hard constraints (do not break):**

1. **Zero budget.** No paid APIs, no paid GPUs, no cloud credit. Allowed: the owner's Claude subscription (via the `claude -p`
   CLI, used sparingly), Gemini free tier, Kaggle free GPUs (two accounts), and the local GPU (RTX 5070 Ti, 16 GB).
2. **Never print or copy secrets** (API tokens). Use the env files by path only (section 4).
3. **Evaluation sets are never trained on** (`evalsets/`, `data/sft_v4/heldout_chunks.json`).
4. **Safety may never regress.** No death or lifespan prediction, no medical diagnosis, no trading advice, no caste or gender
   stigma, helpline on self-harm, no invented verse citations.
5. Governing documents, in order of authority: `docs/constitution.md` > `docs/tech-spec.md` > `docs/implementation-plan.md`.
   Live state: `STATUS.md` (section 0 is current). Update `STATUS.md` whenever a step finishes.

---

## 2. History in one page

| Phase / version | What was done | Outcome |
|---|---|---|
| Phase 1, v1 (Oct 5-8) | Qwen3-4B LoRA on 1,421 teacher Q&A rows, Kaggle T4 | quiz 38%, safety 54%: fails release bar |
| v2-4b / **v2-8b** (Oct 8) | + 723 table facts, strict safety rows; 8B QLoRA r=16 | **v2-8b = best overall model so far** (quiz 79%, safety 82%, rubric 3.27, rule fidelity 2.17) |
| v3-8b (Oct 9-10) | counted chart facts + code-written reasoning | no gain; v2-8b kept |
| Serving (Oct 9-11) | GGUF export, safety layer, FastAPI, robustness tests, HF private upload | v2-8b Q4_K_M GGUF is the deployed file |
| Phase 2 start (Oct 18-20) | Production-grade programme: rule extraction (37,029 atomic rules by Claude), local paraphrasing to 98k Q&A pairs (Ollama + Kaggle), eval v2 sets, 200-row model review | data v4 built (103,359 rows) |
| v4 (Oct 20-21) | 8B QLoRA r=32 on v4 data, local GPU, crash-safe supervisor | facts up, but **safety collapsed to 6%** and voice became templated (95% of rows were one-template paraphrases) |
| **v5** (Oct 21) | Rebalanced mix (41,985 rows): one paraphrase per rule, teacher answers x3, 1,465 new safety rows, drills, facts; LR 1.5e-4 | **best on facts; level with v2-8b on quality/style; weaker on safety** |

### Current scores (judge: Claude Sonnet 5.5 unless noted)

Phase 1 evaluation sets (60 test questions, 100-item quiz, 50 safety prompts):

| Measure | v2-8b | v4 | v5 | Release bar |
|---|---|---|---|---|
| Quiz | 79% | 94% | **96%** | >= 75% |
| Safety | **82%** | 6% | 60% | 100% hard rules, >= 95% judged |
| Rubric mean (1-5) | 3.27 | 3.06 | 3.18 | >= 4.0 |
| Rule fidelity (1-5) | 2.17 | 2.00 | 2.00 | >= 3.8 |
| Astrologer style | 3.10 | 2.55 | 3.05 | >= 3.5 |

Phase 2 evaluation sets (v5 vs untrained Qwen3-8B base): rubric 3.24 vs 2.68 (+0.56, 95% CI +0.49..+0.64), pairwise win vs base
87%, adversarial safety 56% (Sonnet) / 52% (Opus), table-fact quiz 72%, held-out rule quiz ~29%, chart claims verified 94%,
0 verse citations, 0 hard-rule blocks.

**Honest one-line summary:** v5 is better than v4 and the untrained base, and the best model on factual knowledge; it is not
yet better than v2-8b overall because safety is 60% vs 82%. **v2-8b stays the deployed model.**

---

## 3. Where everything is

### Code (all under the project root `C:\Users\mobirizer\Desktop\jyotish-lora`)

| Area | Files |
|---|---|
| Chart engine | `src/chart/engine.py`, `render.py` (`render_chart_text`), yogas |
| PDF ingest / OCR | `src/ingest/extract.py` (RapidOCR fallback), chunking |
| Data v4/v5 streams | `src/dataset/facts_v4.py` (table facts), `drills.py` (chart-copy drills), `rules.py` (Claude rule extraction), `rule_qa.py` (paraphrase + checks), `safety_v5.py` (safety rows), `build_v4.py`, `build_v5.py` |
| Review | `src/dataset/review_v4.py`, `review_gemini.py` (Gemini, falls back to Claude) |
| Evaluation v2 | `src/eval/build_testset_v2.py`, `build_quiz_v2.py`, `build_safety_v2.py`, `claims.py` (chart-claim checker), `run_eval_v2.py` (dataset / judge / report) |
| Phase 1 judge | `src/eval/judge.py` |
| Training (local) | `src/train/train_local.py` (Unsloth QLoRA), `eval_generate_local.py`, `supervisor.py` (auto-restart), `run_v4.py` (LR sweep) |
| Serving | `src/app/pipeline.py`, `server.py` (FastAPI), `safety.py` (input/output rules, fixed replies) |
| Kaggle | `src/kaggle_push.py`, notebook builders in `notebooks/make_*.py` (edit builders, never the .ipynb) |
| Docs | `docs/constitution.md`, `tech-spec.md`, `implementation-plan.md`, `production-review.pdf`, `v4-progress-log.pdf`, this file; `python docs/make_pdfs.py` rebuilds all PDFs |

### Data and artifacts (git-ignored; exist **only on this workstation**)

| What | Path |
|---|---|
| Book PDFs (52) | `C:\Users\mobirizer\Desktop\codebackup\learning\Astrobook\Astro_book` (junction `JioAICloud-Download/`) |
| Rules (37,029) | `data/sft_v4/rules.jsonl`; held-out chunk list `data/sft_v4/heldout_chunks.json` |
| v4 training data | `data/sft_v4/` (103,359 rows) |
| v5 training data | `data/sft_v5/` (41,985 rows; safety rows `safety_fixed.jsonl`) |
| Evaluation sets | `evalsets/` (test_v2 267, quiz_v2 411, safety_v2_eval 100; Phase 1 quiz/safety/robustness) |
| v5 adapter | `runs/v5/adapter` (final), `runs/v5/best_adapter`; report `runs/v5/eval_v2_report.md`; Phase 1 eval `runs/v5-p1/` |
| v4 adapter | `runs/v4/`; report `runs/v4/eval_v2_report.md` |
| v2-8b (deployed) | adapter `runs/v2-8b-part1/astro-lora-v2-8b/adapter/`; GGUF `runs/export8b/astro-v2-8b.Q4_K_M.gguf` |
| Base scores | `runs/baseline-8b/` |

**Git warning:** the repository has only one commit. Everything from Phase 2 (the files above under `src/dataset/`,
`src/eval/*_v2*`, `src/train/`, evalsets, docs) is **uncommitted**. First action on resuming should be a commit (after a
quick `git status` review, excluding `unsloth_compiled_cache/`), so the work is not lost.

---

## 4. Environment on this workstation

| Item | Value |
|---|---|
| OS / GPU | Windows 11 Pro, RTX 5070 Ti 16 GB (compute 12.0, bf16), no WSL |
| Data/eval venv | `C:\Users\mobirizer\.venvs\astro\Scripts\python.exe` (Python 3.11) |
| Training venv | `C:\Users\mobirizer\.venvs\train\Scripts\python.exe` (torch 2.11 cu128, Unsloth 2026.10.7, TRL 1.15, transformers 5.17, PEFT 0.21) |
| Local LLM | Ollama with `qwen3:14b` (`OLLAMA_NUM_PARALLEL=4`) |
| Kaggle tokens | `C:\Users\mobirizer\.kaggle_env` (`KAGGLE_API_TOKEN`, `NEW_KAGGLE_API_TOKEN`); pass `KAGGLE_ENV_FILE` to the pusher |
| Gemini key | `C:\Users\mobirizer\.gemini_env` (free tier; quota runs out quickly) |
| Claude | subscription CLI `claude -p` (no API credit). Watch weekly usage; judging is the main consumer |
| Do not read | `jyotish-lora/env` (owner's general secrets file, unrelated) |

Note: `CLAUDE.md` describes the owner's *other* laptop (paths under `C:\Users\rdits\...`); on this workstation use the paths
above. Always run Python with `-X utf8` and modules as `python -m src.<package>.<module>` from the project root.

**Health check:** `C:\Users\mobirizer\.venvs\astro\Scripts\python.exe -X utf8 -m pytest tests -q` (183 tests pass).

---

## 5. How to do the common things

**Train a model locally (crash-safe):**
```
C:\Users\mobirizer\.venvs\train\Scripts\python.exe -X utf8 -m src.train.supervisor install --job v5   # starts at every logon
C:\Users\mobirizer\.venvs\train\Scripts\python.exe -X utf8 -m src.train.supervisor run --job v5       # the loop (run detached)
C:\Users\mobirizer\.venvs\train\Scripts\python.exe -X utf8 -m src.train.supervisor status --job v5
```
For a new run, add a job entry to `JOBS` in `src/train/supervisor.py` (e.g. `v6` with `--data sft_v6`). The supervisor resumes
from the latest checkpoint after any crash, rolls back once on divergence, stops on a crash loop. Run `uninstall` when done.
Settings that worked: batch 4 x grad-accum 2, LR 1.5e-4, max_grad_norm 0.5, one epoch, save every 150 steps, keep 3. About
4.5-5 h for ~42k rows.

**Evaluate a trained adapter:** copy `runs/after_training_v5.cmd` and change the run name. It generates answers (training venv),
judges with the economy plan (Sonnet headline, Opus on a sample, base answers reused from `baseline-8b`), writes
`runs/<run>/eval_v2_report.md`, and judges the Phase 1 sets into `runs/<run>-p1/`.

**Rebuild training data:** `python -m src.dataset.build_v5` (astro venv). Rebuild PDFs: `python docs/make_pdfs.py`.

---

## 6. What is left to do (in order)

### Next step: v6, fix safety without losing v5's knowledge
v5 learned the generic fixed safety replies from `src/app/safety.py` and now refuses to predict death or diagnose, but misses
the *question-specific* part a good answer needs (e.g. explain what a maraka is without predicting death, name the
cancellation rules, say "see a doctor promptly").

1. For each safety category, write down what a good answer must contain (the requirements already exist in the safety eval
   categories, `evalsets/safety_v2_eval.jsonl` style; do not copy its prompts).
2. Have the local model (Ollama `qwen3:14b`) draft a question-specific answer for each of the ~1,465 safety questions in
   `data/sft_v5/safety_q`, meeting the requirement; reject drafts that fail `check_output` in `src/app/safety.py`; have Claude
   check a sample of ~100 (cheap).
3. Build `data/sft_v6/` = v5 mix with the new safety answers replacing the generic replies (new `src/dataset/build_v6.py`).
4. Train `v6` with v5's settings; evaluate as in section 5.
5. **Success test:** Phase 1 safety >= 82% AND quiz >= 90% AND rubric >= 3.2. If met, v6 replaces v2-8b as the best model.

### After that (Phase 2 plan, `docs/implementation-plan.md`)
- **Stage 2D, verifier loop** for rule fidelity (stuck at 2.0-2.2 in every version): rejection-sampling fine-tune with chart
  engine verification, then ORPO/DPO preference pairs. If rule fidelity still does not move, consider retrieval at answer time
  (a constitution change; owner decides).
- **Stage 2E, serving:** deterministic fact lookup in the prompt, output recount of chart claims, learned guard model, export
  test (GGUF vs adapter).
- **Stage 2F, release:** copyright/licence review of the books, red-team, model card and README, monitoring, **human review of
  200 training rows by a person** (the model review done in Phase 2 is a recorded constitution exception that expires before any
  public release).

### Release bar still to reach
Rubric >= 4.0, rule fidelity >= 3.8, safety 100% on hard rules and >= 95% judged, quiz >= 75%, win rate >= 70%. Today only quiz
and win rate pass.

---

## 7. Lessons that must not be relearned

- **Data mix decides behaviour.** v4 had 95% single-template rows and the model answered everything in that template, including
  safety questions. Keep any single stream well below half the mix; keep teacher answers and safety rows upweighted.
- **Facts stated directly and repeatedly are learned** (quiz 38% -> 96%). Long free-form rule fidelity is not fixed by more
  paraphrase data.
- **Training instability:** LR 2e-4 diverged once at step 4,950 on v4; LR 1.5e-4 with gradient clipping 0.5 was stable.
- **Crashes:** power cuts happen on this machine. Resume with full optimizer state (`--resume-mode full`) matches an
  uninterrupted run. Always set `FOR_DISABLE_CONSOLE_CTRL_HANDLER=1` and `PYTHONUNBUFFERED=1` for detached training.
- **Claude cost:** judging is the main Claude spend. Use the economy plan (`--economy --reuse-base baseline-8b --headline sonnet`),
  Gemini free tier where it works, and local Ollama for any bulk generation.
- Claude refuses to write reasoning traces for training another model; do not rephrase around that. Use code-written working instead.
- Kaggle T4 is ~4x slower than the workstation; use it only for parallel offload.
- Windows: `schtasks` needs admin, so auto-start uses a VBS launcher in the user's Startup folder.

---

## 8. Resume checklist (do these first)

1. Read this file, then `STATUS.md` section 0, then skim `docs/implementation-plan.md` Phase 2.
2. Run the test suite (section 4). Confirm `nvidia-smi` shows the GPU and `ollama list` shows `qwen3:14b`.
3. `git status`; commit the Phase 2 work if still uncommitted.
4. Check nothing is still running: `supervisor status --job v5` should show finished, no training processes.
5. Ask the owner whether to start v6 (section 6), and check their Claude usage before any judging.
6. When a step finishes: update `STATUS.md`, then `python docs/make_pdfs.py` to refresh the PDFs.
