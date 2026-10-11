"""Shared paths, book metadata and small I/O helpers."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "JioAICloud-Download"
DATA = ROOT / "data"
RAW_TEXT = DATA / "raw_text"
CHUNKS = DATA / "chunks"
SFT = DATA / "sft"
PROMPTS = ROOT / "prompts"
EVALSETS = ROOT / "evalsets"
RUNS = ROOT / "runs"

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
QWEN_TOKENIZER = "Qwen/Qwen3-4B-Instruct-2507"

# use:
#   "all"        - usable for every task type
#   "concept"    - concept Q&A only (astronomy / history texts)
#   "safety"     - only as seed material for safety/redirect examples
#   "exclude"    - not used in v1 (reason given)
BOOKS: dict[str, dict] = {
    "arudha-pada":                            {"title": "Arudha Pada", "short": "Arudha Pada", "tradition": "Jaimini", "use": "all"},
    "ashtaka-varga":                          {"title": "Ashtakavarga", "short": "Ashtakavarga", "tradition": "Parashari", "use": "all"},
    "astrology-and-stock-market-forecasting": {"title": "Astrology and Stock Market Forecasting", "short": "Stock Market Forecasting", "tradition": "Financial astrology", "use": "safety"},
    "bhavartha-ratnakara":                    {"title": "Bhavartha Ratnakara", "short": "Bhavartha Ratnakara", "tradition": "Parashari", "use": "all"},
    "bhrigu-sutras":                          {"title": "Bhrigu Sutras", "short": "Bhrigu Sutras", "tradition": "Parashari", "use": "all"},
    "brihat-jataka":                          {"title": "Brihat Jataka", "short": "Brihat Jataka", "tradition": "Classical (Varahamihira)", "use": "all"},
    "brihat-parashara-hora-sastra":           {"title": "Brihat Parashara Hora Sastra", "short": "BPHS", "tradition": "Parashari", "use": "all"},
    "chamatkar-chintamani":                   {"title": "Chamatkar Chintamani", "short": "Chamatkar Chintamani", "tradition": "Classical", "use": "exclude", "reason": "Hindi in a legacy font encoding; v1 is English-only"},
    "crux-of-astrology":                      {"title": "Crux of Astrology", "short": "Crux of Astrology", "tradition": "Modern Vedic", "use": "all"},
    "daivajna-vallabha":                      {"title": "Daivajna Vallabha", "short": "Daivajna Vallabha", "tradition": "Classical (Varahamihira)", "use": "all"},
    "five-year-yuga-of-vedanga-jyotisa":      {"title": "The Five-Year Yuga of Vedanga Jyotisa", "short": "Vedanga Jyotisa", "tradition": "Vedanga astronomy", "use": "concept"},
    "garga-hora":                             {"title": "Garga Hora", "short": "Garga Hora", "tradition": "Classical", "use": "all"},
    "gem-healing-properties":                 {"title": "Gem Healing Properties", "short": "Gem Healing Properties", "tradition": "Gemstone lore", "use": "all"},
    "goravani-jyotish-manual":                {"title": "Goravani Jyotish Manual", "short": "Goravani Jyotish Manual", "tradition": "Modern Vedic", "use": "all"},
    "greatness-gayatri-jyotish":              {"title": "Greatness of Gayatri Jyotish", "short": "Gayatri Jyotish", "tradition": "Modern Vedic", "use": "all"},
    "horasara-of-prithuyasas":                {"title": "Horasara of Prithuyasas", "short": "Horasara", "tradition": "Classical", "use": "all"},
    "jaimini-sutras":                         {"title": "Jaimini Sutras", "short": "Jaimini Sutras", "tradition": "Jaimini", "use": "all"},
    "jataka-alankara":                        {"title": "Jataka Alankara", "short": "Jataka Alankara", "tradition": "Classical", "use": "all"},
    "jyotisha-siddhanta-sara":                {"title": "Jyotisha Siddhanta Sara", "short": "Siddhanta Sara", "tradition": "Siddhanta astronomy", "use": "concept"},
    "kalyana-varma-saravali":                 {"title": "Saravali of Kalyana Varma", "short": "Saravali", "tradition": "Classical", "use": "all"},
    "laghu-parashari-siddhanta":              {"title": "Laghu Parashari Siddhanta", "short": "Laghu Parashari", "tradition": "Parashari", "use": "all"},
    "lal-kitab-1941":                         {"title": "Lal Kitab (1941)", "short": "Lal Kitab", "tradition": "Lal Kitab", "use": "exclude", "reason": "Hindi in a legacy font encoding; v1 is English-only"},
    "lal-kitab-vol-1-1952":                   {"title": "Lal Kitab Vol. 1 (1952)", "short": "Lal Kitab", "tradition": "Lal Kitab", "use": "exclude", "reason": "Scanned Hindi; no Hindi OCR in v1"},
    "lal-kitab-vol-2-1952":                   {"title": "Lal Kitab Vol. 2 (1952)", "short": "Lal Kitab", "tradition": "Lal Kitab", "use": "exclude", "reason": "Scanned Hindi; no Hindi OCR in v1"},
    "lal-kitab-vol-3-1952":                   {"title": "Lal Kitab Vol. 3 (1952)", "short": "Lal Kitab", "tradition": "Lal Kitab", "use": "exclude", "reason": "Scanned Hindi; no Hindi OCR in v1"},
    "lessons-on-vedic-astrology-01":          {"title": "Lessons on Vedic Astrology, Part 1", "short": "Lessons on Vedic Astrology", "tradition": "Modern Vedic", "use": "all"},
    "lessons-on-vedic-astrology-02":          {"title": "Lessons on Vedic Astrology, Part 2", "short": "Lessons on Vedic Astrology", "tradition": "Modern Vedic", "use": "all"},
    "madhya-parashari":                       {"title": "Madhya Parashari", "short": "Madhya Parashari", "tradition": "Parashari", "use": "all"},
    "mantreswara-phaladeepika":               {"title": "Phaladeepika of Mantreswara", "short": "Phaladeepika", "tradition": "Classical", "use": "all"},
    "mathematics-of-astrology":               {"title": "Mathematics of Astrology", "short": "Mathematics of Astrology", "tradition": "Calculation", "use": "exclude", "reason": "Chart calculation is done by code, not the model (Constitution II)"},
    "muhurtha-jyotish":                       {"title": "Muhurtha Jyotish", "short": "Muhurtha", "tradition": "Muhurta", "use": "all"},
    "naksatras-compatibility-lagna-signs":    {"title": "Nakshatras, Compatibility and Lagna Signs", "short": "Nakshatras and Compatibility", "tradition": "Modern Vedic", "use": "all"},
    "parashara-light-manual-6":               {"title": "Parashara's Light 6 Manual", "short": "Parashara's Light Manual", "tradition": "Software manual", "use": "exclude", "reason": "Software user manual, not astrological teaching"},
    "prashna-tantra":                         {"title": "Prashna Tantra", "short": "Prashna Tantra", "tradition": "Prashna", "use": "all"},
    "prashnagnana-bhattotpala":               {"title": "Prashna Gnana of Bhattotpala", "short": "Prashna Gnana", "tradition": "Prashna", "use": "all"},
    "raman-how-to-judge-horoscope-1":         {"title": "How to Judge a Horoscope, Vol. 1 (B.V. Raman)", "short": "Raman, How to Judge a Horoscope", "tradition": "Modern Parashari (B.V. Raman)", "use": "all"},
    "raman-how-to-judge-horoscope-2":         {"title": "How to Judge a Horoscope, Vol. 2 (B.V. Raman)", "short": "Raman, How to Judge a Horoscope", "tradition": "Modern Parashari (B.V. Raman)", "use": "all"},
    "samhita-skanda":                         {"title": "Samhita Skanda", "short": "Samhita Skanda", "tradition": "Samhita (mundane)", "use": "all"},
    "sanketanidhi":                           {"title": "Sanketa Nidhi", "short": "Sanketa Nidhi", "tradition": "Classical", "use": "all"},
    "saturn-friend-and-guide":                {"title": "Saturn: Friend and Guide", "short": "Saturn: Friend and Guide", "tradition": "Modern Vedic", "use": "all"},
    "satya-jataka":                           {"title": "Satya Jataka", "short": "Satya Jataka", "tradition": "Classical", "use": "all"},
    "scientific-hindu-astrology-1":           {"title": "Scientific Hindu Astrology, Vol. 1", "short": "Scientific Hindu Astrology", "tradition": "Modern Vedic", "use": "all"},
    "scientific-hindu-astrology-2":           {"title": "Scientific Hindu Astrology, Vol. 2", "short": "Scientific Hindu Astrology", "tradition": "Modern Vedic", "use": "all"},
    "secrets-kerala-astrology":               {"title": "Secrets of Kerala Astrology", "short": "Kerala Astrology", "tradition": "Kerala", "use": "all"},
    "secrets-of-nadi-astrology":              {"title": "Secrets of Nadi Astrology", "short": "Nadi Astrology", "tradition": "Nadi", "use": "all"},
    "stri-jataka":                            {"title": "Stri Jataka", "short": "Stri Jataka", "tradition": "Classical", "use": "all"},
    "uttarakalamritam":                       {"title": "Uttara Kalamrita", "short": "Uttara Kalamrita", "tradition": "Classical (Kalidasa)", "use": "all"},
    "vedic-astrology-integrated-approach":    {"title": "Vedic Astrology: An Integrated Approach", "short": "Vedic Astrology: An Integrated Approach", "tradition": "Modern Vedic (P.V.R. Narasimha Rao)", "use": "all"},
    "vedic-astrology-rasi-characteristics":   {"title": "Vedic Astrology: Rasi Characteristics", "short": "Rasi Characteristics", "tradition": "Modern Vedic", "use": "all"},
    "vedic-cosmography-and-astronomy":        {"title": "Vedic Cosmography and Astronomy", "short": "Vedic Cosmography", "tradition": "Puranic cosmography", "use": "concept"},
    "yavanajataka-of-sphujidhivaja":          {"title": "Yavanajataka of Sphujidhvaja", "short": "Yavanajataka", "tradition": "Classical (Yavana)", "use": "all"},
    "yogakarakas":                            {"title": "Yogakarakas", "short": "Yogakarakas", "tradition": "Parashari", "use": "all"},
}


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=1)
def tokenizer():
    """Qwen tokenizer (fast, Rust) for token counts; falls back to a word-based estimate."""
    try:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        return Tokenizer.from_file(hf_hub_download(QWEN_TOKENIZER, "tokenizer.json"))
    except Exception:  # offline and not cached
        return None


def count_tokens(text: str) -> int:
    tok = tokenizer()
    if tok is None:
        return int(len(text.split()) * 1.35)
    return len(tok.encode(text).ids)
