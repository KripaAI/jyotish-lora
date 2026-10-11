# Jyotish LoRA

A LoRA fine-tune of Qwen3-4B-Instruct-2507 that answers like a Vedic astrologer. See
[docs/constitution.md](docs/constitution.md), [docs/tech-spec.md](docs/tech-spec.md) and
[docs/implementation-plan.md](docs/implementation-plan.md).

## Setup

```bash
py -3.11 -m venv C:\Users\rdits\.venvs\astro      # kept outside OneDrive on purpose
C:\Users\rdits\.venvs\astro\Scripts\python -m pip install -r requirements.txt
```

Tesseract 5 is expected at `C:\Program Files\Tesseract-OCR\tesseract.exe`. Run every command from the
project root with the venv's Python (`python` below).

## Phase 1: corpus

```bash
python -m src.ingest.extract        # PDF text + OCR -> data/raw_text/, runs/extraction_report.md (~15 min)
python -m src.ingest.chunk          # clean + chunk + topic tags -> data/chunks/chunks.jsonl, runs/chunking_report.md
```

## Phase 2: chart engine

```python
from datetime import datetime
from src.chart.engine import compute_chart
from src.chart.render import render_chart_text
print(render_chart_text(compute_chart(datetime(1990, 5, 18, 2, 36), 5.5, 19.998, 73.79)))
```

## Phase 3: dataset

First plan the seeds and build the quiz (both modes):

```bash
python -m src.dataset.seeds                                   # plan 3,100 seeds -> data/sft/seeds.jsonl
python -m src.eval.build_quiz                                 # evalsets/quiz.jsonl
```

Then run the teacher LLMs in one of two ways:

- **Subscription mode (default, no API key):** Claude Sonnet 5.5 (Claude Code, Claude Pro login) writes questions, Claude Opus 5.5 writes answers, and Gemini 3.1 Pro through the Antigravity CLI (`agy`, Google login) does the fact checks.

  Usage limits are handled by waiting and retrying. Stop with Ctrl+C at any time; re-running continues where it left off.

```bash
python -m src.dataset.generate run questions --limit 40      # pilot; drop --limit for the full set
python -m src.dataset.generate run answers  --limit 40
python -m src.dataset.generate run factcheck --limit 40
python -m src.dataset.generate run answers --retry           # redo failed requests
```

- **API mode (needs ANTHROPIC_API_KEY; costs money):** the Message Batches commands below.

```bash
# Pilot first (~100 examples, a few dollars). Add --dry-run to inspect requests without sending.
python -m src.dataset.generate submit questions --limit 40
python -m src.dataset.generate collect questions
python -m src.dataset.generate submit answers
python -m src.dataset.generate collect answers
python -m src.dataset.generate submit factcheck
python -m src.dataset.generate collect factcheck
python -m src.dataset.generate status                         # progress + cost so far

# Full run: the same six commands without --limit (only missing items are sent).

python -m src.dataset.generate assemble                       # -> data/sft/generated.jsonl
python -m src.dataset.filters                                 # -> data/sft/filtered.jsonl, runs/filter_report.md
python -m src.dataset.review_export export                    # -> data/reviews/review_batch.csv (fill in Excel)
python -m src.dataset.review_export import                    # -> data/sft/reviewed.jsonl, runs/review_report.md
python -m src.dataset.split                                   # -> data/sft/train|val|test.jsonl + manifest.json
```

## Tests

```bash
python -m pytest tests -q
```
