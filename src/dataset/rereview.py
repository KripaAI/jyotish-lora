"""Second look at model-review rejects, with the corpus book list supplied.

The first model review sometimes rejected answers for citing a "fabricated" title that is in fact one of the corpus
books (found by the owner's spot-check). This re-reviews every rejected example with the real titles and the example's
own source book given to the reviewer. New verdicts are appended to data/sft/auto_review.jsonl (the latest verdict per
example wins), then auto_reviewed.jsonl and the report are rebuilt.

    python -m src.dataset.rereview [--workers 4]
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common import BOOKS, CHUNKS, SFT, read_jsonl
from src.dataset import auto_review, auto_review_all, backends

TITLES = sorted({m["title"] for m in BOOKS.values() if m["use"] != "exclude"} |
                {m["short"] for m in BOOKS.values() if m["use"] != "exclude"})
NOTE = ("\n\nIMPORTANT CONTEXT: the dataset was built from these real books, so citing any of them by name is legitimate "
        "and must NOT be treated as an invented or dubious title: " + "; ".join(TITLES) + ". "
        "Judge whether the claims attributed to a book are plausible and sound, not whether you recognise the title.")


def review(row: dict, source_books: list[str]) -> dict:
    user = (f"TASK TYPE: {row['task']}\nSOURCE BOOK(S) THIS ANSWER WAS WRITTEN FROM: {', '.join(source_books)}\n\n"
            f"<user_message>\n{row['messages'][1]['content']}\n</user_message>\n\n"
            f"<assistant_reply>\n{row['messages'][2]['content']}\n</assistant_reply>")
    res = backends.call_with_wait("claude", {
        "custom_id": f"rereview-{row['id']}",
        "params": {"system": [{"text": auto_review.SYSTEM + NOTE}], "messages": [{"content": user}],
                   "output_config": {"effort": "medium", "format": {"schema": auto_review.SCHEMA}}},
    }, auto_review.MODEL)
    if res["type"] != "succeeded":
        return {"id": row["id"], "error": res.get("error", res["type"])}
    import json
    return {"id": row["id"], **json.loads(res["text"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    latest = auto_review_all.load_done()
    rows = {r["id"]: r for r in read_jsonl(SFT / "filtered.jsonl")}
    todo = [rows[i] for i, r in latest.items() if r["decision"] == "reject" and r.get("source") != "rereview" and i in rows]
    need = {c for r in todo for c in r["source_chunks"]}
    book_of = {c["chunk_id"]: c["title"] for c in read_jsonl(CHUNKS / "chunks.jsonl") if c["chunk_id"] in need}
    print(f"re-reviewing {len(todo)} rejected examples with the corpus book list", flush=True)

    counts: Counter = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(review, r, sorted({book_of.get(c, "?") for c in r["source_chunks"]})): r["id"] for r in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                res = {"id": futs[fut], "error": str(e)[:200]}
            if "decision" in res:
                auto_review_all.append({**res, "source": "rereview"})
            counts[res.get("decision", "error")] += 1
            if n % 10 == 0 or n == len(todo):
                print(f"{n}/{len(todo)} done {dict(counts)}", flush=True)
    rebuild_conservative()
    print("REREVIEW_DONE")


if __name__ == "__main__":
    main()


# ---------- conservative final decision ----------
# A second model look is partly a re-roll, so a reject is only overturned when the ORIGINAL reason was purely
# that a (real) book title looked fabricated; anything first rejected for a factual or doctrinal error stays out.
import re

_TITLE_ONLY = re.compile(r"fabricat|dubious[^.]{0,40}(book|title|citation|work|source)|unverif|"
                         r"invented[^.]{0,20}(book|title|citation|source)|questionable[^.]{0,20}(title|book|citation)|"
                         r"not a (real|known)[^.]{0,20}(book|title|work)", re.I)
_SUBSTANTIVE = re.compile(r"wrong|incorrect|error|misstat|mislabel|contradict|distort|overstat|invent(?!ed[^.]{0,20}(book|title|citation|source))|"
                          r"unsupported|doctrine|misapplie|misattribut|hidden|unnamed|leak", re.I)


# Verified by hand: rejected only because a real corpus title ("Vedic Astrology: Rasi Characteristics") was called fabricated.
OVERRIDES = {"s03078-0": "approve"}


def final_decisions() -> dict[str, str]:
    first, last = {}, {}
    for r in read_jsonl(SFT / "auto_review.jsonl"):
        if "decision" not in r:
            continue
        if r.get("source") != "rereview":
            first.setdefault(r["id"], r)
        last[r["id"]] = r
    out = {}
    for i, f in first.items():
        if f["decision"] == "approve":
            out[i] = "approve"
        elif last[i]["decision"] == "approve" and _TITLE_ONLY.search(f["reason"]) and not _SUBSTANTIVE.search(
                _TITLE_ONLY.sub("", f["reason"])):
            out[i] = "approve"  # rejected only for a real corpus title
        else:
            out[i] = "reject"
    out.update(OVERRIDES)
    return out


def rebuild_conservative() -> None:
    from src.common import RUNS, write_jsonl
    dec = final_decisions()
    rows = list(read_jsonl(SFT / "filtered.jsonl"))
    kept = [r for r in rows if dec.get(r["id"]) == "approve"]
    write_jsonl(SFT / "auto_reviewed.jsonl",
                [{**r, "review": {"decision": "approve", "by": "Sonnet 5.5 (model, not human); conservative re-review"}} for r in kept])
    tin, tout = Counter(r["task"] for r in rows), Counter(r["task"] for r in kept)
    lines = ["# Model review report (Sonnet 5.5; NOT the human review)", "",
             f"Approved {len(kept)} of {len(rows)} ({len(kept) / len(rows):.1%}) after the conservative re-review: a reject was "
             "overturned only when its original reason was purely a real corpus title being called fabricated.", "",
             "| Task | Input | Approved | Rejected |", "|---|---|---|---|"]
    lines += [f"| {t} | {n} | {tout[t]} | {n - tout[t]} |" for t, n in tin.items()]
    (RUNS / "auto_review_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"conservative: approved {len(kept)} of {len(rows)}")
