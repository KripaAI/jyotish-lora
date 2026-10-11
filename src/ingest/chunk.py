"""Phase 1.5-1.6: clean the extracted pages and pack them into 500-1,000-token chunks with topic tags.

Usage:
    python -m src.ingest.chunk
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from src.common import BOOKS, CHUNKS, RAW_TEXT, RUNS, count_tokens, read_jsonl, write_jsonl
from src.ingest.extract import english_quality, is_usable, looks_like_words
from src.ingest.topics import tag_topics

MIN_TOKENS, MAX_TOKENS, OVERLAP_TOKENS = 500, 1000, 100
BOILERPLATE_SHARE = 0.3

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "­": "", "​": ""}
_PAGE_NO = re.compile(r"^\W*(?:page\s*)?(?:\d{1,4}|[ivxlc]{1,7})\W*$", re.I)
_CHAPTER = re.compile(r"^\s*(?:chapter|ch\.|adhyaya|lesson|part)\s+([0-9]{1,3}|[IVXLC]{1,7})\b[\s.:-]*(.*)$", re.I)
_TERMINAL = tuple('.!?:;"”’)]')
_JUNK = re.compile(r"\bISBN\b|all rights reserved|printed (?:at|by)|published by|copyright ©|freely distributed", re.I)
# software-manual text (e.g. parts of the Goravani manual): 3+ UI words in a chunk
_SOFTWARE_UI = re.compile(r"\b(?:click|button|menu|dialog|screen|window|toolbar|mouse|keyboard|install|software|printer)\b", re.I)


def _norm_line(line: str) -> str:
    return re.sub(r"[\d\W]+", " ", line.lower()).strip()


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for a, b in _LIGATURES.items():
        text = text.replace(a, b)
    return text


def boilerplate_lines(pages: list[list[str]]) -> set[str]:
    """Normalised lines that repeat on many pages (running heads, footers, watermarks)."""
    counts: Counter = Counter()
    for lines in pages:
        counts.update({_norm_line(l) for l in lines if _norm_line(l)})
    limit = max(3, BOILERPLATE_SHARE * len(pages))
    return {l for l, n in counts.items() if n >= limit and len(l) < 120}


def paragraphs(pages: list[dict]) -> list[dict]:
    """Join page lines into paragraphs; returns [{text, page, chapter}]. Unusable pages are skipped."""
    page_lines = [[l.strip() for l in _clean(p["text"]).splitlines()] for p in pages]
    boiler = boilerplate_lines(page_lines)
    out, buf, chapter, buf_page = [], [], None, None

    def flush():
        nonlocal buf
        if buf:
            text = " ".join(buf)
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # line-break hyphenation
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                out.append({"text": text, "page": buf_page, "chapter": chapter})
        buf = []

    for page, lines in zip(pages, page_lines):
        if not is_usable(page["text"]):
            continue
        for line in lines:
            if not line or _PAGE_NO.match(line) or _norm_line(line) in boiler:
                continue
            m = _CHAPTER.match(line)
            if m and len(line) < 100:
                flush()
                chapter = m.group(1).upper() if not m.group(1).isdigit() else str(int(m.group(1)))
                buf_page = page["page"]
                buf.append(line)
                flush()
                continue
            if buf and buf[-1].endswith(_TERMINAL) and (line[0].isupper() or line[0].isdigit()):
                flush()
            if not buf:
                buf_page = page["page"]
            buf.append(line)
    flush()
    return out


def _split_long(text: str) -> list[str]:
    """Split an over-long paragraph at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts, cur = [], ""
    for s in sentences:
        if cur and count_tokens(cur + " " + s) > MAX_TOKENS:
            parts.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        parts.append(cur)
    return parts


def _tail(text: str, n_tokens: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    tail = ""
    for s in reversed(sentences):
        if count_tokens(s + " " + tail) > n_tokens:
            break
        tail = f"{s} {tail}".strip()
    return tail


def chunk_book(slug: str) -> list[dict]:
    meta = BOOKS[slug]
    paras = []
    for p in paragraphs(list(read_jsonl(RAW_TEXT / f"{slug}.jsonl"))):
        for part in (_split_long(p["text"]) if count_tokens(p["text"]) > MAX_TOKENS else [p["text"]]):
            paras.append({**p, "text": part, "tokens": count_tokens(part)})

    chunks, cur, cur_tokens = [], [], 0

    def emit():
        nonlocal cur, cur_tokens
        if not cur:
            return
        text = " ".join(p["text"] for p in cur)
        chunks.append({"text": text, "pages": [cur[0]["page"], cur[-1]["page"]],
                       "chapter": next((p["chapter"] for p in reversed(cur) if p["chapter"]), None)})
        overlap = _tail(text, OVERLAP_TOKENS)
        cur = [{**cur[-1], "text": overlap}] if overlap and overlap != text else []
        cur_tokens = count_tokens(overlap) if cur else 0

    prev_chapter = None
    for p in paras:
        if p["chapter"] != prev_chapter and cur_tokens >= MIN_TOKENS // 2:
            emit()
            cur, cur_tokens = [], 0  # no overlap across chapter boundaries
        prev_chapter = p["chapter"]
        if cur_tokens + p["tokens"] > MAX_TOKENS and cur_tokens >= MIN_TOKENS:
            emit()
        cur.append(p)
        cur_tokens += p["tokens"]
    if cur_tokens >= MIN_TOKENS // 2:
        emit()

    rows = []
    for i, c in enumerate(chunks):
        n_words, sw = english_quality(c["text"])
        digits = sum(ch.isdigit() for ch in c["text"]) / max(len(c["text"]), 1)
        quality = "ok"
        if _JUNK.search(c["text"]) or len(_SOFTWARE_UI.findall(c["text"])) >= 3 or digits > 0.12 or not (sw >= 0.15 or (sw >= 0.05 and looks_like_words(c["text"]))):
            quality = "low"
        rows.append({
            "chunk_id": f"{slug}-{i:04d}", "book": slug, "title": meta["title"], "short": meta["short"],
            "tradition": meta["tradition"], "use": meta["use"], "chapter": c["chapter"],
            "pages": c["pages"], "tokens": count_tokens(c["text"]), "quality": quality,
            "topics": tag_topics(c["text"]), "text": c["text"],
        })
    return rows


def main() -> None:
    all_rows, report = [], ["# Chunking report", "", "| Book | Chunks | OK quality | Low quality | Tokens (ok) | Chapters found |", "|---|---|---|---|---|---|"]
    for slug, meta in BOOKS.items():
        if meta["use"] == "exclude" or not (RAW_TEXT / f"{slug}.jsonl").exists():
            continue
        rows = chunk_book(slug)
        all_rows += rows
        ok = [r for r in rows if r["quality"] == "ok"]
        report.append(f"| {slug} | {len(rows)} | {len(ok)} | {len(rows) - len(ok)} | "
                      f"{sum(r['tokens'] for r in ok):,} | {len({r['chapter'] for r in rows if r['chapter']})} |")
        print(f"  {slug}: {len(rows)} chunks ({len(ok)} ok)", flush=True)
    n = write_jsonl(CHUNKS / "chunks.jsonl", all_rows)
    ok = [r for r in all_rows if r["quality"] == "ok"]
    topic_counts = Counter(t for r in ok for t in r["topics"])
    report += ["", f"**Total:** {n} chunks, {len(ok)} ok, {sum(r['tokens'] for r in ok):,} tokens in ok chunks.", "",
               "## Topic coverage (ok chunks)", "", "| Topic | Chunks |", "|---|---|"]
    report += [f"| {t} | {c} |" for t, c in sorted(topic_counts.items())]
    (RUNS / "chunking_report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"wrote {n} chunks -> {CHUNKS / 'chunks.jsonl'}; report -> {RUNS / 'chunking_report.md'}")


if __name__ == "__main__":
    main()
