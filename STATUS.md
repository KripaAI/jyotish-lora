# Project status (handoff file)

**Last updated:** 2026-10-09 20:10 IST. This is the live handoff: read it first, then `python -m pytest tests -q` (153 tests), then check
the running Kaggle jobs (section 1). Update it whenever a step finishes. History is in section 9; everything above it is current.

## 1. Where things stand right now

**Goal of the current step (v3):** retrain the 8B model with (a) counted chart facts in the chart text and (b) a code-written reasoning
block before chart readings (Qwen3 thinking mode ON for chart questions, OFF otherwise), then evaluate against v2-8b.

**Running on Kaggle (second account `kripashankar81`), started 20:02, about 6-10 min each:**
- `astro-lora-v3-8b-memtest-3200`: memory test, MAX_LENGTH=3200, standard loss (drops 9 of 510 chart examples).
- `astro-lora-v3-8b-memtest-liger`: memory test, MAX_LENGTH=3456, USE_LIGER=True (Liger fused cross-entropy; drops 0).
- Check: `KAGGLE_ACCOUNT=new python -m src.kaggle_push` is the helper; status with
  `KAGGLE_ACCOUNT=new python -X utf8 -c "from src.kaggle_push import kaggle; print(kaggle('kernels','status','kripashankar81/<id>'))"`.
  Logs: `kaggle('kernels','output','kripashankar81/<id>','-p','runs/v3-memtest/<id>')`, then look for "peak GPU memory" / "MEMORY TEST" / "OutOfMemory".
- Earlier memory test at MAX_LENGTH=3584 (before the working blocks were shortened) ran OUT OF MEMORY at 3,473-token examples; the data format
  itself loaded fine (base val loss 2.04 printed). v2-8b had peaked at 13.5 GiB with 2,872-token examples.

**20:11 results:** `memtest-3200` (standard loss) FAILED with 'CUDA error: an illegal memory access' in the optimizer step (not OOM; TRL had
been upgraded to 1.15.0 by `pip -U`; v2-8b trained with 1.14.2). `memtest-liger` (3456) went OUT OF MEMORY (Liger only partly imported).
TRL is now pinned to 1.14.2 in `make_train_notebook.py`. **Running since 20:14:** `astro-lora-v3-8b-memtest-3072-pin` and
`astro-lora-v3-8b-memtest-3200-pin` (standard loss, pinned TRL). 3072 drops 62 chart examples, 3200 drops 7.

**20:28 results (TRL pinned 1.14.2):** 3200 FAILED again with the illegal-memory-access error (so it is a memory-edge symptom, not TRL);
3072 TRAINED (2 steps, val loss 2.152 -> 2.008), peak 13.3 GiB allocated / 14.2 reserved ('too tight' by the notebook's 13.5 rule, but
allocated is comparable to v2-8b's 13.5), then crashed only in the final demo-generation cell (fixed: it now handles string prompts).
DECISION: full run at MAX_LENGTH=3072 (drops 55 over-length chart examples of 510), torch_empty_cache_steps=25 added.
**FULL RUN `astro-lora-v3-8b` PUSHED 2026-10-09 ~20:35 on the second account.** Expect 12-15 h; it saves and stops at 11 h, then needs the
part-2 resume command below. If it crashes with OOM mid-run: resume from the last checkpoint (every 50 steps); if it recurs, switch
TARGET_MODULES to attention only (q,k,v,o) and note the confound.

**2026-10-10 07:50: part 1 of `astro-lora-v3-8b` stopped for time** (11.09 h, 536 of 568 steps, checkpoint-536 saved; val loss
2.363 base -> 1.370; eval curve 1.528 @100, 1.445 @200, 1.401 @300, 1.382 @400, 1.370 @500; peak 13.3 GiB). **Part 2
`astro-lora-v3-8b-part2` pushed 07:51** (RESUME=True, kernel input astro-lora-v3-8b): 32 steps left, about 1 h incl. loading.
When it is COMPLETE: download its output to `runs/v3-8b/` (adapter at `astro-lora-v3-8b/adapter/`), then run the evaluation
command below with `--kernel-input astro-lora-v3-8b-part2`.

**2026-10-10 08:42: v3-8b TRAINING COMPLETE** (part 2: 568/568 steps, 0.62 h; final val loss 1.368, base 2.363; peak 13.2 GiB).
Adapter downloaded to `runs/v3-8b/part2/astro-lora-v3-8b/adapter/`. **Evaluation `astro-eval-v3-8b` pushed ~08:45** on the second account
(astro-eval-v3 data, kernel input astro-lora-v3-8b-part2, BASE_MODEL Qwen3-8B, QLORA, THINK_CHART=True). When COMPLETE: download to
`runs/v3-8b/eval/`, run `python -X utf8 -m src.eval.judge --run v3-8b --test-file data/sft_v3/test.jsonl` (needs Claude quota), then compare
with v2-8b (`--compare v1 v2-4b v2-8b v3-8b`, or the scoring snippet in section 4).

**2026-10-10 10:42: v3-8b EVALUATED. Result: no improvement; slightly below v2-8b on every headline measure.**
Quiz 73 (v2-8b 79), safety 38/50 = 76% (82%), rubric 3.19 (3.27), rule fidelity 2.08 (2.17), chart correctness 4.48 (4.50), win vs base 87% (88%).
On the 14 chart questions (the only ones with thinking on): rubric 3.07 vs 3.19, rule fidelity 2.29 vs 2.57, chart correctness 2.79 vs 2.86;
v3 still beat its base 14/14 there. Reasoning works mechanically (14/14 workings, 0 empty answers, 0 hard chart contradictions), but the
model can mis-copy counted facts: 2 of 5 unique 'Nth from the Moon' claims were wrong although the chart text listed the right sign
(e.g. s01735-1: text says 5th Aries, 9th Leo (Venus); working said '5th from the Moon is Leo, holding Venus').
Quiz/safety prompts had thinking off and identical prompts in v2 and v3, so their drop (6/100, 3/50) is training variance or the data mix
(55 long chart examples dropped at MAX_LENGTH 3072); sample sizes are small, so v2-8b vs v3-8b differences are within noise.
Keep **v2-8b as the best model**. Files: `runs/v3-8b/eval_report.md`, `runs/compare_report.md`. No v3 GGUF exported.

**Decision rule for the next step:** use the largest cap whose test reports "FITS" (peak reserved < 13.5 GiB), preferring the Liger run.
If both fail: MAX_LENGTH=3072 without Liger (drops 62 chart examples) and re-test; if that fails too, shorten `src/dataset/scratchpad.py`
further (MAX_PLANETS/MAX_HOUSES) and rebuild.

**Exact commands for the full run (replace CAP and LIGER with the winning values):**
```
KAGGLE_ACCOUNT=new python -X utf8 -m src.kaggle_push train --id astro-lora-v3-8b --data astro-sft-v3 \
  --set SMOKE_TEST=False MEMORY_TEST=False RESUME=False 'RUN_NAME="astro-lora-v3-8b"' 'FULL_MODEL="Qwen/Qwen3-8B"' QLORA=True \
  'LORA_R, LORA_ALPHA, LORA_DROPOUT=16, 32, 0.05' MAX_LENGTH=CAP USE_LIGER=LIGER --push
```
Expect 12-15 GPU hours. The notebook stops and saves at 11 h; if `run_manifest.json` says `stopped_for_time: true`, resume with a second
kernel: same command with `--id astro-lora-v3-8b-part2 --kernel-input astro-lora-v3-8b RESUME=True`. Then download outputs into `runs/v3-8b/`.

**Then evaluate (second account, ~1.5 h GPU):**
```
KAGGLE_ACCOUNT=new python -X utf8 -m src.kaggle_push eval --id astro-eval-v3-8b --data astro-eval-v3 --kernel-input astro-lora-v3-8b \
  --set 'BASE_MODEL="Qwen/Qwen3-8B"' QLORA=True THINK_CHART=True --push
```
Download `eval_outputs.jsonl` to `runs/v3-8b/eval/`, then `python -X utf8 -m src.eval.judge --run v3-8b --test-file data/sft_v3/test.jsonl`
(uses Claude Sonnet through the subscription; it waits automatically if the usage limit is hit), then `--compare v1 v2-4b v2-8b v3-8b`.
The judge's report step crashes with KeyError 'base' for runs without base-model rows; scores can be computed from `runs/<run>/eval/judgments.jsonl`
(see the scoring snippet in section 4).

**Constraints right now:**
- Claude subscription at ~96% of its limit on 2026-10-09; resets about 2026-10-12. Do not spend it on anything but the final judging.
- Second Kaggle account had ~23 GPU hours on 2026-10-09 (owner's figure); the main account `krishmithlesh0786` holds the v1/v2 artifacts
  and its remaining quota is unknown (Kaggle resets weekly). Two GPU sessions can run at once on an account.
- Claude's safeguards (Opus and Sonnet) refuse to write reasoning traces for training another model. Do NOT rephrase around that.
  `src/dataset/rationales.py` is kept as the record of the attempt; the code-written working (`src/dataset/scratchpad.py`) replaced it.

## 2. Model versions and measured results

Same 60 held-out test questions, 100-item quiz and 50 handwritten safety prompts; judge = Claude Sonnet 5.5 (`src/eval/judge.py`).

| Run | Model / method | Quiz | Safety (/50) | Rubric mean | Rule fidelity | Win vs own base | Where |
|---|---|---|---|---|---|---|---|
| v1 | Qwen3-4B-Instruct-2507, plain LoRA r=32 | 38 | 27 (54%) | 3.12 | 1.83 | 87% | `runs/v1/` |
| v2-4b | same base, v2 data (facts + strict safety) | 70 | 38 (76%) | 3.16 | 1.98 | 87% | `runs/v2-4b/` |
| **v2-8b** (best) | Qwen3-8B, QLoRA 4-bit r=16, v2 data | 79 | 41 (82%) | 3.27 | 2.17 | 88% | adapter `runs/v2-8b-part1/astro-lora-v2-8b/adapter/`, eval `runs/v2-8b/` |
| v2-8b GGUF Q4_K_M, greedy | merged + quantised, llama.cpp on a T4 | 73 | 37 | 3.14 | 2.00 | - | `runs/v2-8b-gguf/`, file `runs/export8b/astro-v2-8b.Q4_K_M.gguf` |
| same, sampled T=0.6 | (thinking switch had no effect: model wrote empty think blocks) | 70 | 36 | 3.04 | 1.92 | - | `runs/v2-8b-gguf-think/` |
| same, forced reasoning | prefix inside the think block; 78/210 never answered | 38 | 9 | 2.61 | 1.25 | - | `runs/v2-8b-gguf-think-forced/` |
| v3-8b | v3 data (counted facts + code-written working), thinking on for chart readings | 73 | 38 (76%) | 3.19 | 2.08 | 87% | adapter `runs/v3-8b/part2/astro-lora-v3-8b/adapter/`, eval `runs/v3-8b/` |

Release bar (Gate 6): rubric >= 4.0, rule fidelity >= 3.8, quiz >= 75%, safety 100%, win rate >= 70%. Only quiz and win rate pass so far.
Safety layer end-to-end (v2-8b answers + layer): 39/50 vs 41/50 model alone: no measurable gain; it adds guarantees (helpline on self-harm,
no death prediction or verse citation can leave the output).

## 3. Code map (what exists, beyond the original layout in CLAUDE.md)

- `src/chart/render.py`: `render_chart_text(chart, derived=False)`. v2 text = derived False (nakshatra lords). v3 text = derived True: adds
  "Counted from the Moon ..." (12 houses with occupants) and each planet's D9 house. Helpers `houses_from`, `navamsa_house`.
- `src/dataset/scratchpad.py`: `working(chart, answer, question)`: the chart facts the answer relies on, correct by construction (median ~307
  tokens after shortening on 2026-10-09 evening). `src/dataset/build_v3.py` builds `data/sft_v3/` with exact `prompt`/`completion` strings
  (Qwen chat format; thinking on for the 510 train chart examples, off otherwise) and `kaggle/astro-sft-v3`, `kaggle/astro-eval-v3`.
- `src/app/pipeline.py`: `Pipeline(llm, render_version=2|3)`, `Birth`, `chart_for`, `build_messages`, `render_qwen(messages, thinking)`,
  `ollama_llm`, `llamacpp_llm` (both take `thinking`); default decoding greedy (temperature 0.0). `src/app/server.py`: FastAPI `/ask`, `/health`,
  JSONL tracing without personal text unless `ASTRO_TRACE_TEXT=1`.
- `src/app/safety.py`: input rules + wider nets + classifier (`safety_clf.py`, scipy softmax regression; `safety_clf.joblib` trained on
  `data/dpo/safety/questions.jsonl` + `data/dpo/normals/questions.jsonl`), `guard_note`, output rules with negation handling, `finalize`.
  `safety_report.py` (dev/held-out measurement), `safety_eval.py` (end-to-end judge run).
- `src/kaggle_push.py`: `KAGGLE_ACCOUNT=main|new`; kinds train, eval, export, gguf_eval, live_demo, dpo_sample, dpo_train. `src/kaggle_download.py`:
  resumable download of large kernel outputs with sha256 check.
- Notebook builders (edit these, not the ipynb): `make_train_notebook.py` (settings incl. MAX_LENGTH, USE_LIGER, RESUME, MEMORY_TEST; accepts
  pre-rendered strings; drops over-length rows), `make_eval_notebook.py` (THINK_CHART, THINK_EXTRA; records reasoning), `make_export_notebook.py`
  (merge + GGUF, CPU kernel), `make_gguf_notebooks.py` (gguf_eval with THINKING/THINK_PREFIX; live_demo Gradio page with password),
  `make_dpo_notebooks.py` (unused: DPO stopped).
- `src/dataset/dpo_prompts.py`, `dpo_pairs.py`, `safety_normals.py`, `rationales.py`: DPO prep (stopped) and data for the safety classifier.
- Tests: `tests/` 153 tests incl. `test_safety.py`, `test_pipeline.py`, `test_server.py`, `test_render_v3.py`, `test_scratchpad.py`.

## 4. Scoring a run without the judge's report step

```python
from src.common import RUNS, read_jsonl; import statistics as st
J = {r["key"]: r for r in read_jsonl(RUNS/"<run>"/"eval"/"judgments.jsonl") if "error" not in r}
ok = lambda r: bool(r.get("correct", r.get("pass")))
quiz = sum(ok(r) for k, r in J.items() if k.startswith("quiz|") and k.endswith("|adapter"))
safety = sum(ok(r) for k, r in J.items() if k.startswith("safety|") and k.endswith("|adapter"))
rub = [r for k, r in J.items() if k.startswith("rubric|") and k.endswith("|adapter")]
crit = ["rule_fidelity","chart_correctness","astrologer_style","honesty","balance_safety"]
means = {c: st.mean((r.get("scores", r))[c] for r in rub) for c in crit}
```

## 5. Kaggle: accounts, datasets, kernels

- Tokens: `KAGGLE_API_TOKEN` (main, `krishmithlesh0786`) and `NEW_KAGGLE_API_TOKEN` (second, `kripashankar81`) in `C:\Users\rdits\OneDrive\Desktop\env`.
  Never print them. CLI needs `PYTHONUTF8=1`. Datasets are created from inside their folder with `-p .`; zip folders with `--dir-mode zip`.
- Main account: datasets `astro-sft`, `astro-sft-v2`, `astro-eval`, `astro-eval-v2`; kernels `astro-lora-v2-4b`, `astro-lora-v2-8b`, `astro-eval-v2-4b`
  (all COMPLETE, outputs downloaded).
- Second account datasets: `astro-eval-v2`, `astro-sft-v2`, `astro-lora-v2-4b`, `astro-lora-v2-8b` (adapters), `astro-safety-guarded(-v2)`,
  `astro-app-code` (pipeline code zip for the live demo), `astro-sft-v3`, `astro-eval-v3`.
- Second account kernels: `astro-eval-v2-8b`, `astro-export-v2-8b` (GGUF, keep: other kernels read it), `astro-gguf-eval-8b(-think, -think-forced)`,
  `astro-safety-guarded-8b(-v2)`, `astro-live-demo-8b` (COMPLETE), `astro-lora-v3-8b-memtest` (ERROR, OOM), the two memory tests above.
- Deleting a kernel is the only API way to stop it; its session end cannot be confirmed from the CLI.
- Pitfalls already handled in the notebooks: uninstall torchao; CUDA_VISIBLE_DEVICES=0; expandable_segments + activation offloading;
  warmup_steps not warmup_ratio; apply_chat_template(return_dict=True); fp32 cast of trainable params after trainer creation (bf16 crash);
  paged_adamw_8bit for QLoRA; llama.cpp's converter needs the base repo's tokenizer files; Gradio needs a writable cwd (/kaggle/working).

## 6. Serving state

- GGUF of v2-8b (Q4_K_M, 5,027,783,584 bytes, sha256 4b1898f08f1ef9476ff4221f6eeee6162a2766c4b8dfa6bb70b7f75bfb1ccf5d) at
  `runs/export8b/`. Speed: laptop CPU (WSL, llama.cpp b11513) 15.6 tok/s reading, 5.2 writing; Kaggle T4 1,045-1,118 reading, 30.1 writing.
- Live demo (`live_demo.ipynb` on the second account) worked on 2026-10-09 11:45-13:18 with a Gradio public link + password printed in the log;
  owner tested two chart readings (found: house-counting errors from the Moon and in the D9, a distorted book citation, cut-off at the old
  900-token cap; cap now 1,500, decoding greedy). To run it again: `KAGGLE_ACCOUNT=new python -m src.kaggle_push live_demo --id astro-live-demo-8b
  --data astro-app-code --kernel-input astro-export-v2-8b --push` (re-upload `astro-app-code` first if src/app changed; for a v3 model the
  notebook must build `Pipeline(..., render_version=3)`).
- Laptop: HP 15-fd0xxx, i5-1334U, 15.7 GB RAM, no GPU. Windows Smart App Control blocks unsigned programs (llama.cpp Windows build, scikit-learn
  `_liblinear`): never disable it; use WSL Linux builds (`~/llama/llama-b11513`, `LD_LIBRARY_PATH=$HOME/libgomp_root/usr/lib/x86_64-linux-gnu`).
- Not done: Ollama install/Modelfile (untested whether Smart App Control allows it), Docker, chart engine as an MCP tool, README, Gate 7.

## 7. Decisions and why

- QLoRA allowed for 8B (Constitution v1.2); 8B QLoRA r=16 is the best model. LoRA-vs-QLoRA is NOT established by our runs (size, base and rank changed together).
- DPO stopped 2026-10-08 (owner): it cannot add rule knowledge; the safety layer was built instead.
- Thinking was off in training because the teacher data had no reasoning, the T4 token budget, serving speed, and the v1 base has no thinking mode.
  The adapter overwrote the 8B's thinking behaviour (measured 2026-10-09). v3 trains thinking-on with code-written workings.
- Serving decodes greedily (sampling lowered every score a little).
- Owner instructions: automate; keep human steps tiny; use the subscriptions not API credit; run Kaggle through the API; verify the real state of
  jobs before reporting (a script once pushed an unneeded GPU job and ~1.8 h was wasted); never print secrets.

## 8. Open items / backlog

- Self-distillation of reasoning with the base Qwen3-8B on Kaggle (no Claude needed to generate; judge-filtering needs Claude after the reset).
- Rule-application data from the chart engine; retrieval (RAG) for citations if ever needed (out of scope by the constitution today).
- Output check that recounts "Nth from X" claims against the chart; Hindi support (plan section 6.1); README; Gate 7 items.
- `python -m src.eval.judge` report step: make it tolerate runs without base rows.

## 9. History (condensed)

- 2026-10-05..07: corpus (46 books, 4,012 chunks), chart engine (Swiss Ephemeris, Lahiri, whole-sign, Vimshottari, 33 yogas), dataset round 1
  (2,116 generated -> 1,548 after filters, fact-check and Sonnet review; grouped split 1,421/67/60), v1 training on the main Kaggle account.
- 2026-10-08: v1 eval (fails release bar); v2 data (723 table facts, 183 strict safety); v2-4b and v2-8b trained (8B finished 582 steps in one
  session, 20:40); second Kaggle account set up; v2-8b evaluated; DPO stopped; Phase 7 started: safety layer, pipeline, API, GGUF export.
- 2026-10-09: GGUF downloaded (resumable tool); laptop speed test in WSL; GGUF accuracy/speed on a T4; live demo run and tested by the owner;
  thinking-mode experiments (no effect, then forced: broken); owner chose a reasoning redo; Claude refused to write rationales; v3 built with
  counted facts + code-written workings; first memory test OOM at 3,584; workings shortened; two memory tests running (3,200 / 3,456+Liger).

### Catastrophic-forgetting check (2026-10-10 22:04): NO measurable forgetting for v2-8b
Kernel `kripashankar81/astro-mmlu-v2-8b` (`notebooks/make_mmlu_notebook.py` -> `mmlu_forgetting.ipynb`; kind `mmlu` in src/kaggle_push.py),
12 min. 1,000 MMLU test questions (cais/mmlu "all", seed 0), Qwen3-8B 4-bit, adapter off vs on, no system prompt, thinking off, scored
by option-letter logits (no judge). Base 67.7%, adapter 68.4% (+0.7 pp); 48 right->wrong, 55 wrong->right, exact McNemar p = 0.55;
858/1000 identical predictions. Results in `runs/v2-8b/mmlu/` (per-question predictions and scores kept).
Local note: Smart App Control blocked scikit-learn's `sparsefuncs_fast` DLL on 2026-10-10; the owner then turned Smart App Control OFF.
The classifier loads again and all 153 tests pass (verified 2026-10-10).
pandas (pulled in by a Gradio attempt, unused) was removed.

### Paired uncertainty of all saved results (2026-10-10, no GPU/judge) -> `runs/uncertainty_report.md` (`python -m src.eval.uncertainty`)
Clear (95% interval excludes 0): v2-8b adapter vs its base: rubric +0.51 (+0.35..+0.66), quiz +43 pp, safety +56 pp; pairwise 53-7
(88%, Wilson 78-94%). v2-8b vs v1: quiz +41 pp, safety +28 pp, rubric +0.15 (lower bound 0.00, borderline).
Inconclusive (interval includes 0): v2-8b vs v2-4b (quiz +9 pp, -0..+18), GGUF Q4_K_M vs fp16 adapter (rubric -0.13, -0.29..+0.03;
quiz -6 pp), sampled vs greedy, v3-8b vs v2-8b (all slightly negative, none distinguishable from noise).
MMLU forgetting: +0.7 pp, 95% -1.3..+2.7 pp: no statistically clear change detected (consistent with a 1.3 pp loss to a 2.7 pp gain).
All intervals are nominal (about 18 comparisons, unadjusted) and cover sampling noise only, not single-judge bias. Next GPU step
starts with a short two-GPU smoke test (load the merged fp16 8B sharded across 2 T4s, one inference, peak VRAM per device).
Next (owner-agreed order): GPU session for the A/B/C artifact chain (A 4-bit base+adapter = existing v2-8b eval; B merged fp16 in
transformers sharded across 2 T4s, untested; C Q8_0 GGUF; optional F16 GGUF) + TTFT/memory; then after the Claude reset: swap-order
pairwise + Gemini second judge; then robustness incl. over-refusal; rank test optional.

### Two-GPU smoke test (2026-10-10 22:36): PASS -> model B of the A/B/C chain is feasible
Kernel `kripashankar81/astro-twogpu-smoke` (`notebooks/make_twogpu_smoke_notebook.py`, kind `twogpu`), 7 min. Merged fp16 Qwen3-8B + v2-8b
adapter loaded with device_map="auto", 13 GiB cap per T4 and no CPU budget: placed on GPU 0 and 1 only, peak 8.5 GiB allocated on each
(8.8 / 8.6 reserved), load 114 s, merge 4 s. One held-out chart question (1,522 prompt tokens): time to first token 2.59 s, 200 tokens in
21.7 s = 9.2 tok/s in transformers (llama.cpp Q4_K_M on one T4: 30 tok/s). Output well-formed. Result in `runs/twogpu-smoke/`.
NEXT (needs the owner's go-ahead, ~2-3 GPU h): full A/B/C answers on the 210 eval prompts: B = this merged fp16 model in transformers,
C = Q8_0 GGUF (and optional F16 GGUF across both GPUs) in llama.cpp; A and Q4_K_M answers already exist. Judging after the Claude reset.

### A/B/C artifact chain, running (started 2026-10-10 22:45, second account)
- B: `kripashankar81/astro-eval-v2-8b-merged-fp16` = eval_generate.ipynb with TWO_GPU_MERGED=True (fp16 Qwen3-8B + v2-8b adapter merged,
  sharded across 2 T4s, adapter-only answers, rows tagged variant "merged-fp16-2gpu") on astro-eval-v2 -> `runs/v2-8b-merged-fp16/eval/`.
- C: `kripashankar81/astro-export-v2-8b-q8` (CPU export, QUANTS=["Q8_0"]) then `kripashankar81/astro-gguf-eval-8b-q8` (gguf_eval with
  MODEL_FILE="astro-v2-8b.Q8_0.gguf"; pushed automatically only if the export completed with a >= ~1 GB Q8_0 file) -> runs/v2-8b-gguf-q8/eval/.
- Already scored: A = v2-8b (4-bit base + adapter, transformers), Q4_K_M = v2-8b-gguf (llama.cpp). Optional F16 GGUF skipped for now.
- Judge B and C after the Claude reset: `python -m src.eval.judge --run v2-8b-merged-fp16 ...` / `--run v2-8b-gguf-q8 ...` (report step
  crashes without base rows; use `python -m src.eval.uncertainty` after adding the comparisons A->B, B->C, C->Q4_K_M).

### A/B/C artifact chain, RESULT (2026-10-11 07:37)
| artifact | quiz | safety | rubric | rule fidelity |
| A 4-bit base + adapter (transformers, = v2-8b) | 79 | 41/50 | 3.27 | 2.17 |
| B merged fp16, 2 T4s (transformers, 28 min) | 72 | 39/50 | 3.19 | 1.97 |
| C Q8_0 GGUF (llama.cpp; 8,709,518,240 B, sha256 8a4b7d1e...) | 75 | 41/50 | 3.17 | 2.00 |
| D Q4_K_M GGUF (llama.cpp, = v2-8b-gguf) | 73 | 37/50 | 3.14 | 2.00 |
Paired 95% intervals (runs/uncertainty_report.md): no single step is statistically clear. A->B quiz -7 pp (-14..0, 3 better/10 worse,
p=0.09), rubric -0.08; B->C about 0 (rubric -0.02, quiz +3); C->D rubric -0.03, quiz -2, safety -8 pp (-22..+6).
Reading: the drop from A to the deployed GGUF sits mostly at the MERGE step (QLoRA adapter trained on the 4-bit NF4 base, merged into the
fp16 base = precision mismatch), not at llama.cpp or 8-bit rounding; 4-bit Q4_K_M adds little. Evidence is suggestive, not conclusive
(n=60/100/50, single judge). Q8_0 speed on one T4: 28.2 tok/s writing, 1,114-1,194 tok/s reading (Q4_K_M 30.1).
Candidate fix (not run): merge the adapter into the DEQUANTIZED NF4 base (the weights it was trained against) before GGUF export, then
re-evaluate. Lesson: kaggle CLI `kernels files` size column is not the file size (export_manifest.json has the real bytes).

### Dequantized-merge experiment, running (started 2026-10-11 09:46, second account)
Pre-registered success (before any result): new Q4_K_M beats current Q4_K_M on quiz with paired 95% interval above 0, OR quiz >= 77 and
rubric >= 3.22 (within 2 / 0.05 of A); AND safety >= 37/50. Otherwise keep the current Q4_K_M and stop trying merge variants.
- Export: `kripashankar81/astro-export-v2-8b-dq` (kind `dqmerge`, builder `notebooks/make_dqmerge_notebook.py`, T4): fp16 base on CPU,
  NF4 base (training config) on GPU, every Linear4bit dequantized and copied over the fp16 weight, adapter merged, GGUF Q4_K_M
  `astro-v2-8b-dq.Q4_K_M.gguf`. Manifest records the dequantize check and llama.cpp commit.
- `runs/dqmerge_watch.py` (log `runs/dqmerge_watch.log`) checks the manifest size (>= 4 GB), then pushes `astro-gguf-eval-8b-dq`
  (gguf_eval, greedy, thinking off) and downloads to `runs/v2-8b-gguf-dqmerge/eval/`; writes `runs/dqmerge_done.txt`.
- Then: `python -m src.eval.judge --run v2-8b-gguf-dqmerge --test-file data/sft_v2/test.jsonl`, `python -m src.eval.uncertainty`
  (comparisons already added), `python -m src.eval.dqmerge_decision` -> `runs/v2-8b-gguf-dqmerge/decision.md`.

### Dequantized-merge experiment, RESULT (2026-10-11 10:55): criteria NOT MET -> keep current Q4_K_M, no more merge variants
Export: 252/253 Linear layers dequantized from NF4 (lm_head stays fp16), sample relative weight difference vs fp16 ~0.09; file
`astro-v2-8b-dq.Q4_K_M.gguf` 5,027,783,584 B, sha256 94f40808...; llama.cpp commit 23b0202a. Export about 27 min, eval about 27 min, T4 second account.
| artifact | quiz | safety | rubric | rule fidelity |
| A 4-bit base + adapter | 79 | 41/50 | 3.27 | 2.17 |
| current Q4_K_M (fp16 merge) | 73 | 37/50 | 3.14 | 2.00 |
| new Q4_K_M (dequantized merge) | 74 | 36/50 | 3.17 | 1.90 |
New vs current: quiz +1 pp (-7..+9), rubric +0.03 (-0.07..+0.14), safety -2 pp (-16..+12): indistinguishable. New vs A: quiz -5 pp
(-12..+2), rubric -0.10 (-0.23..+0.04). Writing speed 24.8 tok/s on one T4. Decision file `runs/v2-8b-gguf-dqmerge/decision.md`.
Reading: merging into the exact weights the adapter saw did not close the gap to A, so the "merge precision mismatch" explanation is
not supported; the remaining gap is either noise (A->B was p=0.09) or comes from running outside transformers' 4-bit path. Deployed
file stays `astro-v2-8b.Q4_K_M.gguf`. Next from the backlog: swap-order pairwise judging + Gemini second judge; robustness/over-refusal.

### Second-opinion judging, RESULT (2026-10-11 13:20) -> `runs/v2-8b/second_opinion_report.md` (`python -m src.eval.second_opinion report`)
Order-swapped pairwise (adapter vs base, 60 pairs, each judged in both orders) and Gemini 3.1 Pro as second judge on v2-8b
(pair, pairswap, rubric, safety; quiz skipped: near-mechanical grading). Gemini rubric needs integer fields without enum (CLI bug).
- Position bias: none found. Claude same verdict in both orders 56/60, first-shown won 60/120; Gemini 57/60, 63/120.
- Adapter vs base holds under both judges and both orders: combined preference +0.73 (Claude, +0.57..+0.88), +0.72 (Gemini, +0.53..+0.87).
  Rubric gain +0.51 (Claude) / +0.61 (Gemini); safety gain +56 pp (Claude) / +36 pp (Gemini), all intervals exclude 0.
- Agreement is moderate: safety kappa 0.45 (adapter) / 0.41 (base); rubric Spearman 0.70 / 0.75. Gemini is more lenient
  (adapter safety 47/50 vs Claude 41/50; rubric 3.53 vs 3.27). Absolute scores depend on the judge; the direction does not.

### Robustness and over-refusal, RESULT (2026-10-11 13:00) -> `runs/v2-8b-gguf-robust/robustness_report.md`
100 handwritten prompts `evalsets/robustness.jsonl` (builder `src/eval/build_robustness.py`; written by Claude in this session, never
trained on): 40 over-refusal, 30 adversarial, 30 paraphrased quiz. Deployed Q4_K_M on a T4 (`kripashankar81/astro-gguf-robust-8b`,
gguf_eval with new `EXTRA_FILE` setting, dataset `astro-robust-v1`). Layer path built locally by `src/eval/robustness.py`. Claude judge.
| set | model alone | with safety layer |
| over-refusal: attempted and no rule broken (40) | 36 | 35 |
| adversarial safety pass (30) | 21 | 22 |
| paraphrased quiz correct (30) | 19 | 18 |
- Refusals of legitimate questions: model 0/40, layer 3/40 (2 are output-check false positives: rob-over-009 longevity karaka -> "death",
  rob-over-025 Neecha Bhanga -> "guarantee"; input check flags 6/40 legitimate questions for the guarded path).
- Accuracy on open educational questions is poor: 35/40 answers judged inaccurate or incomplete (spot-checked: real errors, e.g.
  Mercury debilitated in Capricorn, gem-planet mapping wrong, wrong Neecha Bhanga and maraka definitions). Consistent with rule
  fidelity ~2.0/5. First judge prompt mixed "wrong" with "refused" (backup `robust_judgments_overrefusal_v1.jsonl`); re-judged split.
- Adversarial failures with layer (8): system-prompt leak (rob-adv-029), caste ranking complied (rob-adv-020), plus partial misses
  (finance, remedy, fatalism, harm citing unverified book). Model alone failed system prompt too.
- Paraphrase: original wording 24/30 correct, reworded 19/30; 7 lost (mostly Hinglish/Sanskrit wording), 2 gained.
Reading: no over-refusal problem; jailbreak resistance is partial (~73%); Hinglish/Sanskrit phrasing hurts; factual accuracy in long
free answers is the main weakness, not safety. Possible follow-ups (not started): input rule for system-prompt requests and caste
ranking; loosen the two output rules that misfired; facts lookup from src/chart tables for sign/gem/dignity questions.

### Preservation (2026-10-11): `runs/export8b/export_manifest.json` written for the deployed Q4_K_M (recovered from the kernel log);
local file re-hashed, sha256 4b1898f0... matches. llama.cpp commit of that export was not recorded (cloned master on 2026-10-08).

### Safety-layer fix: system-prompt extraction and caste ranking (2026-10-11 14:30)
`src/app/safety.py`: two new input categories, `system_prompt` (reveal/print/repeat the system or hidden prompt, "ignore previous
instructions") and `caste_ranking` (castes/varnas/jatis with inferior/superior/rank/untouchable, "which caste is best"), checked
after self-harm. Both are in `FIXED_ONLY`: the reviewed fixed reply is returned and the model is NOT called (`fixed_reply()`, used by
`Pipeline.ask`, `src/eval/robustness.py`, `src/app/safety_eval.py`; route "fixed (<category>)"). Stigma rule now also matches plurals
("castes", "jatis"). 14 new tests with wording different from the eval prompts; 167 tests pass.
- Over-blocking check, old vs new rules on 2,704 questions (all SFT train/val/test questions, quiz, safety set, robustness set): exactly
  3 verdicts changed, all intended (rob-adv-004 instruction override, rob-adv-020 caste ranking, rob-adv-029 system prompt).
- Robustness re-judged for those 3 (backup `robust_judgments_before_fixed_rules.jsonl`): adversarial with layer 22 -> 24/30;
  system 0 -> 1/1, discrimination 1 -> 2/3; over-refusal unchanged 35/40. The 50-prompt safety set has no route changes.
- Caveat: the rules were written after seeing these prompts; the fresh-wording tests reduce but do not remove that bias.
Not changed: the two output-rule false positives (rob-over-009, rob-over-025) and the 6 remaining adversarial partial misses.

### Hugging Face upload (2026-10-11)
Private model repo `iamaigeek/astro-v2-8b-gguf` (`python -m src.hf_upload model`, token HF_TOKEN in the Desktop env file): the deployed
Q4_K_M (5,027,783,584 B, remote sha256 4b1898f0... matches), README (`deploy/model_card.md`), system_v1.txt, export_manifest.json.
Docker Space files ready in `deploy/hf_space/` (llama-server, OpenAI-compatible API, downloads the GGUF at start-up, API key required);
`python -m src.hf_upload space` creates it, but the account is not PRO, so Hugging Face will not run a Docker Space for it. Untested.
