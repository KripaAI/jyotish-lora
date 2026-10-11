# Jyotish LoRA

LoRA fine-tune of Qwen3-4B-Instruct-2507 that answers like a Vedic astrologer, trained on Kaggle's free T4 from Q&A
generated out of 46 astrology books. **Read `STATUS.md` first**: it says what is done, where every artifact is and what
comes next. Update `STATUS.md` whenever a step finishes.

## Rules

- Governing docs: `docs/constitution.md` (non-negotiable rules), `docs/tech-spec.md`, `docs/implementation-plan.md`
  (phases, gates, backlog in section 6). The constitution wins in a conflict.
- The model never calculates charts; `src/chart/engine.py` does. Training and serving must use the same
  `prompts/system_v1.txt` and `src/chart/render.py:render_chart_text`.
- Never print secrets. API tokens live in `C:\Users\rdits\OneDrive\Desktop\env` (Kaggle: `KAGGLE_API_TOKEN`).

## Environment

- Python: `C:\Users\rdits\.venvs\astro\Scripts\python.exe` (3.11, outside OneDrive on purpose). Use `-X utf8` on Windows.
- Run modules from the project root: `python -m src.<package>.<module>`.
- Tests: `python -m pytest tests -q` (88 tests).
- Kaggle CLI: `C:\Users\rdits\.venvs\astro\Scripts\kaggle`, with `PYTHONUTF8=1`.

## Layout

- `src/ingest/` PDF extraction, OCR, chunking, topic tags
- `src/chart/` chart engine, yogas, render
- `src/dataset/` seeds, teacher back-ends (`backends.py` subscription CLIs, `teacher.py` Batches API), `generate.py`,
  `filters.py`, model review (`auto_review*.py`, `rereview.py`), `split.py`
- `src/eval/` quiz builder; `evalsets/` quiz (100) and handwritten safety prompts (50), never trained on
- `notebooks/make_train_notebook.py` builds `notebooks/train_lora.ipynb` (edit the builder, not the JSON)
- `data/` generated data (git-ignored); `runs/` reports, logs, trained adapters
