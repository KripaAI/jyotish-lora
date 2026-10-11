"""Phase 1.1-1.4: extract page text from the corpus PDFs, with OCR fallback.

Usage:
    python -m src.ingest.extract            # all books not yet extracted
    python -m src.ingest.extract --force    # re-extract everything
    python -m src.ingest.extract --book ashtaka-varga
"""
from __future__ import annotations

import argparse
import re
import io
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pymupdf

from src.common import BOOKS, PDF_DIR, RAW_TEXT, RUNS, TESSERACT_CMD, read_jsonl, write_jsonl

MIN_WORDS = 30
MIN_STOPWORD_RATIO = 0.12  # real English prose is ~0.3-0.5; broken font encodings are ~0
OCR_DPI = 300

_STOPWORDS = set(
    "the of and to in a is be will with by for as his he or are if that this it from on at not "
    "lord house planet native".split()
)


def english_quality(text: str) -> tuple[int, float]:
    """(number of alphabetic words, share of them that are common English words)."""
    toks = re.findall(r"[A-Za-z']+", text.lower())
    if not toks:
        return 0, 0.0
    return len(toks), sum(t in _STOPWORDS for t in toks) / len(toks)


def looks_like_words(text: str) -> bool:
    """True for real English words (even in lists/tables), False for legacy-font gibberish.

    English words of 3+ letters nearly always contain a vowel and rarely have a capital mid-word;
    Hindi text in legacy font encodings (e.g. 'lwjt dk', 'fQj') fails both tests.
    """
    toks = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) >= 3]
    if not toks:
        return False
    vowels = sum(bool(re.search("[aeiouyAEIOUY]", w)) for w in toks) / len(toks)
    mid_caps = sum(bool(re.search("[a-z][A-Z]", w)) for w in toks) / len(toks)
    return vowels >= 0.9 and mid_caps <= 0.05


def is_usable(text: str) -> bool:
    """Prose (enough common English words) or readable lists/tables of English words."""
    n, ratio = english_quality(text)
    return n >= MIN_WORDS and (ratio >= MIN_STOPWORD_RATIO or looks_like_words(text))


def _ocr_page(page: pymupdf.Page) -> str:
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang="eng", config="--psm 3")


def extract_book(slug: str) -> dict:
    pymupdf.TOOLS.mupdf_display_errors(False)
    t0 = time.time()
    doc = pymupdf.open(PDF_DIR / f"{slug}.pdf")
    rows, n_ocr, n_empty = [], 0, 0
    for i, page in enumerate(doc):
        text, method = page.get_text(sort=True), "text"
        if not is_usable(text):
            ocr = _ocr_page(page)
            if is_usable(ocr) or english_quality(ocr)[0] > english_quality(text)[0]:
                text, method = ocr, "ocr"
                n_ocr += 1
        if not is_usable(text):
            n_empty += 1
        rows.append({"book": slug, "page": i + 1, "text": text, "method": method})
    write_jsonl(RAW_TEXT / f"{slug}.jsonl", rows)
    return {"book": slug, "pages": len(rows), "ocr_pages": n_ocr, "empty_pages": n_empty,
            "words": sum(len(r["text"].split()) for r in rows), "seconds": round(time.time() - t0, 1)}


def write_report() -> None:
    lines = ["# Extraction report", "",
             "| Book | Use | Pages | OCR pages | Still unusable | Words |",
             "|---|---|---|---|---|---|"]
    tot = {"pages": 0, "ocr": 0, "empty": 0, "words": 0}
    samples = ["", "## Samples (3 pages per book, first 400 characters)", ""]
    for slug, meta in BOOKS.items():
        path = RAW_TEXT / f"{slug}.jsonl"
        if meta["use"] == "exclude":
            lines.append(f"| {slug} | excluded: {meta['reason']} | | | | |")
            continue
        if not path.exists():
            lines.append(f"| {slug} | {meta['use']} | not extracted | | | |")
            continue
        rows = list(read_jsonl(path))
        ocr = sum(r["method"] == "ocr" for r in rows)
        empty = sum(not is_usable(r["text"]) for r in rows)
        words = sum(len(r["text"].split()) for r in rows)
        for k, v in zip(tot, (len(rows), ocr, empty, words)):
            tot[k] += v
        flag = " ⚠" if empty / max(len(rows), 1) > 0.2 else ""
        lines.append(f"| {slug} | {meta['use']} | {len(rows)} | {ocr} | {empty}{flag} | {words:,} |")
        samples.append(f"### {slug}")
        for r in rows[len(rows) // 4 :: max(len(rows) // 3, 1)][:3]:
            snippet = " ".join(r["text"].split())[:400]
            samples.append(f"- p.{r['page']} ({r['method']}): {snippet}")
        samples.append("")
    usable = 1 - tot["empty"] / max(tot["pages"], 1)
    lines += ["", f"**Totals (included books):** {tot['pages']:,} pages, {tot['ocr']:,} OCR pages, "
              f"{tot['empty']:,} still unusable, {tot['words']:,} words. "
              f"**Usable pages: {usable:.1%}** (Gate 1 needs 90% or more). ⚠ = over 20% empty."]
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "extraction_report.md").write_text("\n".join(lines + samples), encoding="utf-8")
    print(f"report: {RUNS / 'extraction_report.md'} (usable pages {usable:.1%})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--book")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    slugs = [args.book] if args.book else [s for s, m in BOOKS.items() if m["use"] != "exclude"]
    todo = [s for s in slugs if args.force or not (RAW_TEXT / f"{s}.jsonl").exists()]
    print(f"extracting {len(todo)} books")
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(extract_book, s): s for s in todo}
        for fut in as_completed(futs):
            r = fut.result()
            print(f"  {r['book']}: {r['pages']} pages, {r['ocr_pages']} OCR, "
                  f"{r['empty_pages']} empty, {r['seconds']}s", flush=True)
    write_report()


if __name__ == "__main__":
    main()
