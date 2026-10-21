# Jyotish LoRA: Project Constitution

| | |
|---|---|
| **Project** | Jyotish LoRA: a Vedic astrologer model built by LoRA fine-tuning an open LLM |
| **Version** | 1.2 |
| **Date** | 2026-10-05 |
| **Owner** | iamaigeek@gmail.com |
| **Related** | [Technical Specification](tech-spec.md) · [Implementation Plan](implementation-plan.md) |

---

## 1. Purpose

This project fine-tunes an open-weight language model with **LoRA** so that it reasons, speaks and structures answers like an experienced Vedic (Jyotish) astrologer. The knowledge it learns comes from training data built from 52 classical and modern astrology texts. **The model works on its own, with no RAG (retrieval) at answer time.**

This constitution sets the rules that cannot be broken. The Technical Specification and the Implementation Plan must follow it. If they conflict, this document wins.

## 2. Mission statement

> Build a small, free-to-train model that reads a birth chart the way a careful Jyotishi would: it follows the classical rules, it states plainly when traditions disagree, and it never pretends to know the future.

## 3. Core principles

### Principle I: Grounding in the classical texts

1. Interpretations must follow the rules in the source corpus (BPHS, Brihat Jataka, Phaladeepika, Saravali, Jaimini Sutras, Lal Kitab, B.V. Raman, etc.).
2. Every assistant answer in the training data must be written from a **specific source passage** (seen by the teacher LLM when drafting), so the knowledge the model learns traces back to the corpus.
3. Since there is no retrieval at answer time, the model attributes views at the level of **tradition or text** (for example, "in the Parashari system" or "Phaladeepika holds…"). It must **not** quote shlokas or give chapter or verse numbers, because it cannot check them.
4. When traditions disagree (for example, Parashari vs. Jaimini, or classical vs. Lal Kitab), the model presents each view and attributes it. It does not merge them silently.
5. The model must never make up shlokas, chapter numbers, yoga definitions or book names.

### Principle II: Calculation belongs to code, not the model

1. Planetary longitudes, lagna, house cusps, nakshatras, divisional charts and dasha periods are **always** computed by a deterministic ephemeris engine (Swiss Ephemeris via `pyswisseph`, sidereal zodiac, Lahiri ayanamsa by default).
2. The LLM **interprets** chart facts. It never calculates them. Training data must never teach the model to derive positions from birth date and time.
3. Every chart in the training data must come from the ephemeris engine. Chart data that is hand-written or produced by an LLM is not allowed.

### Principle III: Plain LoRA on free hardware

1. The default training method is **plain LoRA**: full-precision (fp16) frozen base weights with trainable low-rank adapters. **QLoRA** (a 4-bit frozen base with the same adapters) is allowed when a larger base model (8B or more) would not otherwise fit the free GPU; such runs are compared against the plain-LoRA model on the same evaluation before either is adopted. Full fine-tuning remains out of scope. Preference training (DPO) may follow supervised training in a later version.
2. Training must fit the **Kaggle free tier**: one NVIDIA T4 (about 15 GB of memory), fp16 only (no bf16), sessions of 12 hours or less, and about 30 GPU hours per week.
3. The base model must be an open-weight instruct model with a permissive license. The default is **Qwen3-4B-Instruct-2507** (Apache 2.0).

### Principle IV: Data quality over quantity

1. 2,000 to 5,000 carefully checked examples are preferred over a large noisy dataset.
2. At least 5% of the generated examples (and at least 200) must be **reviewed by a person** before each training run.
3. Duplicate, near-duplicate, off-topic and factually wrong examples must be removed.
4. The evaluation set is held out and must **never** be used for training.

### Principle V: Responsible astrology

1. The model presents astrology as a **traditional interpretive system**, not as proven science, and does not claim certainty about future events.
2. The model **must not**:
   - predict death, the timing of death, or fatal accidents;
   - diagnose illness or advise against medical treatment;
   - give specific legal, investment or trading instructions (including from the stock-market forecasting text);
   - use fear to push remedies, gemstones or paid rituals;
   - encourage discrimination based on caste, gender, *Manglik* status or similar labels.
3. For health, legal, financial or mental-health questions, the model gives the traditional view at most in general terms and **directs the user to a qualified professional**.
4. Remedies (mantras, charity, gemstones, Lal Kitab *upayas*) are offered as optional and traditional, and never as guaranteed fixes.
5. These behaviours must be taught explicitly with refusal and redirection examples in the training data.

### Principle VI: Copyright and licensing

1. The source PDFs are used **only** to build training data for personal and research use.
2. Large verbatim passages from copyrighted modern works must not be copied into assistant answers in the training data. Short quotations with citations are acceptable.
3. Before the model, adapter or dataset is **published**, the copyright status of each source text must be reviewed. Copyrighted sources must be removed or replaced if needed.
4. The terms of any teacher LLM used to generate data must be checked to confirm they allow training other models on its outputs.

### Principle VII: Privacy

1. Real birth details (name, date, time, place) of real people must not appear in the training data. Synthetic birth data is used instead.
2. Logs from the serving system must not keep users' birth data beyond the session unless the user has consented.

### Principle VIII: Reproducibility

1. Every training run is recorded with: dataset version (hash), base model ID and revision, LoRA configuration, hyperparameters, random seed, and Kaggle notebook version.
2. All data processing is done by scripts in the repository, never by hand-editing generated files.
3. Adapters are versioned (`astro-lora-v1`, `v2`, and so on) and are never overwritten.

### Principle IX: Evaluate before release

1. A new adapter replaces the current model only if it **beats both** (a) the base model given the same system prompt and (b) the previous adapter on the evaluation suite.
2. Any regression in safety tests (Principle V) blocks release, whatever the other scores are.

## 4. Scope

| In scope (v1) | Out of scope (v1) |
|---|---|
| Vedic/Jyotish interpretation (Parashari, Jaimini, Lal Kitab, Nadi basics, Prashna, Muhurta) | Western/tropical astrology |
| Interpreting single natal charts | Synastry/compatibility scoring beyond basic Ashtakoota explanations |
| Explaining concepts and comparing texts | Training on images or chart diagrams |
| Remedies (with safety framing) | Trading or investment signals |
| English output using Sanskrit terms | Full Hindi/Sanskrit output (planned for a future version) |
| Knowledge learned into the LoRA weights | **RAG / retrieval** of source passages, during training or at answer time |
| Attribution at the level of tradition or text | Exact shloka quotes and chapter or verse citations |

## 5. Definitions

- **Base model**: the frozen pre-trained instruct LLM (Qwen3-4B-Instruct-2507).
- **Adapter**: the trained LoRA weights (matrices A and B) applied on top of the base model.
- **Chart facts**: structured output from the ephemeris engine (JSON).
- **Source passage**: a chunk of corpus text the teacher LLM reads while drafting an answer. It is **not** included in the training example.
- **Teacher LLM**: a strong LLM used offline to draft assistant answers for training examples.

## 6. Governance

1. **Changes:** This constitution changes only through a written revision. Raise the version number and note the change in the change log below.
2. **Compliance check:** Each phase gate in the Implementation Plan includes a check against these principles.
3. **Exceptions:** Any exception must be documented with its reason and an expiry date.

### Recorded exceptions

| Date | Principle | Exception | Reason | Expiry |
|---|---|---|---|---|
| 2026-10-20 | IV.2 (human review of at least 200 examples before a training run) | The 200-row v4 sample (`data/reviews/review_v4.csv`) was reviewed by a model, Gemini 3.5 Flash (`src/dataset/review_gemini.py`), at the owner's direction, instead of by a person; rows Gemini's free tier could not cover fall back to Claude Opus 5.5 on the subscription. Gemini is independent of the rule extractor (Claude) and the paraphraser (local Qwen3 14B) and saw each row's source evidence. | Owner decision to proceed without waiting for a manual review. | Before any public release (Stage 2F), a person reviews at least 200 rows of the final training set. |

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-05 | First version |
| 1.1 | 2026-10-05 | RAG moved out of scope; Principle I changed to attribution by tradition or text without chapter or verse citations; Principle IX baseline is now the base model without RAG |
| 1.2 | 2026-10-08 | Principle III: QLoRA allowed for larger base models (v2 experiment with Qwen3-8B); DPO noted as a possible later step |
