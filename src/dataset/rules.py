"""v4 step 1: extract an atomic rule base with Claude (subscription mode), then merge near-duplicates.

Why: the model has to recall rules, and each rule has appeared once in one teacher paraphrase. A rule base lets every
rule be rewritten many times (rule_qa.py) and lets the quiz be drawn from what the corpus actually says.

Sources:
    answers  the checked Opus answers in data/sft_v2/train.jsonl (available now; val/test ids are never used)
    chunks   data/chunks/chunks.jsonl, the book passages themselves (the real source; needs the corpus on this machine)

Items are packed PACK per call to save subscription calls; results are stored per pack and the run is resumable.

    python -m src.dataset.rules extract --source answers --limit 15     # pilot
    python -m src.dataset.rules extract --source answers                # full (background; waits out usage limits)
    python -m src.dataset.rules extract --source chunks
    python -m src.dataset.rules merge                                   # -> data/sft_v4/rules.jsonl, runs/rules_report.md
    python -m src.dataset.rules status
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from datasketch import MinHash, MinHashLSH

from src.common import BOOKS, CHUNKS, DATA, PROMPTS, RUNS, read_jsonl, write_jsonl
from src.dataset import backends

DIR = DATA / "sft_v4" / "rules"
OUT = DATA / "sft_v4" / "rules.jsonl"
REPORT = RUNS / "rules_report.md"
HELDOUT = DATA / "sft_v4" / "heldout_chunks.json"
HOLDOUT_PERCENT = 5
MODEL = "claude-sonnet-5-5"          # strong enough for grounded extraction; Opus is kept for the few answers that need judgement
EFFORT = "medium"
PACK = 3
CONVERSATIONAL = {"concept", "placement", "comparison", "remedies", "uncertainty", "full_chart"}
DUP_THRESHOLD = 0.8
SEP = "\n\nQuestion: "

SCHEMA = {
    "type": "object",
    "properties": {"rules": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"}, "statement": {"type": "string"}, "conditions": {"type": "string"},
            "modifiers": {"type": "string"}, "exceptions": {"type": "string"}, "text": {"type": "string"},
            "tradition": {"type": "string"}, "topics": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string", "enum": ["rule", "definition", "remedy", "significance", "comparison"]},
            "confidence": {"type": "string", "enum": ["high", "medium"]},
        },
        "required": ["source_id", "statement", "conditions", "modifiers", "exceptions", "text", "tradition",
                     "topics", "kind", "confidence"],
        "additionalProperties": False}}},
    "required": ["rules"], "additionalProperties": False,
}


# ------------------------------------------------------------------------------------------------------ items
def items_from_answers() -> list[dict]:
    """Checked teacher answers from the v2 train split. Chart readings keep only the question (general rules only)."""
    rows = [r for r in read_jsonl(DATA / "sft_v2" / "train.jsonl") if r["task"] in CONVERSATIONAL]
    out = []
    for r in rows:
        user = r["messages"][1]["content"]
        chart = user.startswith("Chart:\n")
        question = user.split(SEP, 1)[1] if chart and SEP in user else user
        head = ("Chart reading (the chart itself is omitted; extract only the general rules the astrologer invokes, "
                "not statements about this chart).\n" if chart else "")
        out.append({"id": r["id"], "kind": "answer", "task": r["task"],
                    "text": f"{head}Question: {question}\n\nAstrologer's answer:\n{r['messages'][2]['content']}"})
    return sorted(out, key=lambda x: x["id"])


def items_from_chunks(heldout: bool = False) -> list[dict]:
    """heldout=False: the training-side chunks (writes the held-out id list); heldout=True: only the held-out chunks, whose
    rules feed the evaluation quiz (src/eval/build_quiz_v2.py) and never the training rule base."""
    path = CHUNKS / "chunks.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} not found: copy data/chunks/chunks.jsonl from the machine that ran src.ingest, or re-run "
                         f"`python -m src.ingest.extract` and `python -m src.ingest.chunk` with the PDFs in JioAICloud-Download/")
    out, held = [], []
    for c in read_jsonl(path):
        meta = BOOKS.get(c["book"], {})
        if meta.get("use") in ("exclude", "safety") or c.get("quality", "ok") != "ok":
            continue
        item = {"id": c["chunk_id"], "kind": "chunk", "book": c.get("title") or meta.get("title", c["book"]),
                "tradition": c.get("tradition") or meta.get("tradition", ""), "text": c["text"]}
        if is_heldout(c["chunk_id"]):      # 5% of chunks never feed the rule base: reserved for an unseen test set
            held.append(c["chunk_id"])
            if heldout:
                out.append(item)
            continue
        if not heldout:
            out.append(item)
    if not heldout:
        HELDOUT.parent.mkdir(parents=True, exist_ok=True)
        HELDOUT.write_text(json.dumps(sorted(held), indent=0), encoding="utf-8")
    return sorted(out, key=lambda x: x["id"])


def is_heldout(chunk_id: str) -> bool:
    import hashlib
    return int(hashlib.sha256(f"heldout:{chunk_id}".encode()).hexdigest(), 16) % 100 < HOLDOUT_PERCENT


def item_block(it: dict) -> str:
    if it["kind"] == "chunk":
        return f'<source_item id="{it["id"]}" book="{it["book"]}" tradition="{it["tradition"]}">\n{it["text"]}\n</source_item>'
    return f'<source_item id="{it["id"]}" kind="checked question and answer">\n{it["text"]}\n</source_item>'


def packs(items: list[dict], size: int, source: str) -> list[dict]:
    """Pack ids are content-based (hash of the item ids), so adding chunks later (e.g. after OCR) does not shift them."""
    import hashlib
    out = []
    for i in range(0, len(items), size):
        group = items[i:i + size]
        key = hashlib.sha256("|".join(it["id"] for it in group).encode()).hexdigest()[:12]
        out.append({"pack_id": f"{source}-{key}", "items": group})
    return out


def done_items(source: str) -> set[str]:
    """Item ids already covered by a succeeded pack (works across the old index-based and new hash-based pack ids)."""
    return {i for r in load_results(source).values() if r.get("type") == "succeeded" for i in r.get("item_ids", [])}


# ------------------------------------------------------------------------------------------------------ extract
def results_path(source: str):
    return DIR / f"{source}_results.jsonl"


def load_results(source: str) -> dict[str, dict]:
    p = results_path(source)
    return {r["custom_id"]: r for r in read_jsonl(p)} if p.exists() else {}


def _one(pack: dict, system: str, model: str) -> dict:
    user = ("Extract the rules from these source items.\n\n" + "\n\n".join(item_block(it) for it in pack["items"]))
    while True:
        try:
            row = backends.call_claude(pack["pack_id"], system, user, EFFORT, SCHEMA, model=model)
            row["item_ids"] = [it["id"] for it in pack["items"]]
            return row
        except backends.UsageLimit as e:
            wait = backends.wait_seconds(str(e))
            print(f"usage limit: waiting {wait // 60} min", flush=True)
            time.sleep(wait)


def extract(source: str, limit: int | None, model: str, workers: int, pack_size: int) -> None:
    items = items_from_answers() if source == "answers" else items_from_chunks(heldout=(source == "heldout"))
    done = done_items(source)
    items = [it for it in items if it["id"] not in done]   # resume by item, then pack what is left
    todo = packs(items, pack_size, source)
    if limit:
        todo = todo[: max(1, limit // pack_size)]
    system = (PROMPTS / "teacher" / "rules_extract.txt").read_text(encoding="utf-8").strip()
    print(f"{source}: {len(items)} items, {len(todo)} packs to run (model {model}, {workers} workers)", flush=True)
    DIR.mkdir(parents=True, exist_ok=True)
    t0, n = time.time(), 0
    with open(results_path(source), "a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(_one, p, system, model) for p in todo]
        for fut in as_completed(futures):
            row = fut.result()
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 10 == 0 or n == len(todo):
                ok = sum(1 for r in load_results(source).values() if r.get("type") == "succeeded")
                print(f"{n}/{len(todo)} packs this run | {ok} succeeded in store | {(time.time() - t0) / 60:.1f} min", flush=True)


# ------------------------------------------------------------------------------------------------------ merge
_WORD = re.compile(r"[a-z0-9]+")


def _mh(text: str) -> MinHash:
    m = MinHash(num_perm=128, seed=1)
    for w in set(_WORD.findall(text.lower())):
        m.update(w.encode())
    return m


def normalise_title(text: str) -> str:
    """Map a free-text attribution to a corpus title when it clearly is one; keep as written otherwise."""
    t = text.strip().strip("*").strip()
    if not t:
        return ""
    low = re.sub(r"\s*\([^)]*\)\s*$", "", t.lower()).strip()
    for meta in BOOKS.values():
        title_core = re.sub(r"\s*\([^)]*\)\s*$", "", meta["title"].lower()).strip()
        if low in (meta["title"].lower(), meta["short"].lower(), title_core):
            return meta["title"]
    return t


def merge() -> None:
    rules, bad = [], Counter()
    for source in ("answers", "chunks"):
        for r in load_results(source).values():
            if r.get("type") != "succeeded":
                bad[r.get("type", "?")] += 1
                continue
            try:
                got = json.loads(r["text"])["rules"]
            except (json.JSONDecodeError, KeyError, TypeError):
                bad["unparsable"] += 1
                continue
            for g in got:
                st = g.get("statement", "").strip()
                if len(st.split()) < 5 or re.search(r"\b(chapter|verse|sloka|shloka)\s*\d", st, re.I):
                    bad["dropped_statement"] += 1
                    continue
                g["text"] = normalise_title(g.get("text", ""))
                g["source"] = source
                rules.append(g)
    lsh, kept, merged = MinHashLSH(threshold=DUP_THRESHOLD, num_perm=128), [], 0
    for g in rules:
        key = f"{g['statement']} {g['conditions']}"
        m = _mh(key)
        hit = lsh.query(m)
        if hit:
            k = kept[int(hit[0])]
            k["source_ids"] = sorted(set(k["source_ids"] + [g["source_id"]]))
            if g["text"] and g["text"] not in k["texts"]:
                k["texts"].append(g["text"])
            merged += 1
            continue
        lsh.insert(str(len(kept)), m)
        import hashlib
        rid = "r" + hashlib.sha256(re.sub(r"\W+", " ", key.lower()).strip().encode()).hexdigest()[:10]   # stable across re-merges
        kept.append({"rule_id": rid, "statement": g["statement"], "conditions": g["conditions"],
                     "modifiers": g["modifiers"], "exceptions": g["exceptions"], "text": g["text"],
                     "texts": [g["text"]] if g["text"] else [], "tradition": g["tradition"], "topics": g["topics"],
                     "kind": g["kind"], "confidence": g["confidence"], "source_ids": [g["source_id"]], "source": g["source"]})
    write_jsonl(OUT, kept)
    lines = [f"# Rule base report\n", f"Extracted {len(rules)} rule records; merged {merged} near-duplicates; kept **{len(kept)}** -> `{OUT}`.\n",
             f"Failed or skipped packs/records: {dict(bad)}\n", "\n| Kind | Rules |\n|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in Counter(r["kind"] for r in kept).most_common()]
    lines += ["\n| Tradition | Rules |\n|---|---|"] + [f"| {k} | {v} |" for k, v in Counter(r["tradition"] for r in kept).most_common(15)]
    lines += ["\n| Text attributed | Rules |\n|---|---|"] + [f"| {k or '(none)'} | {v} |" for k, v in Counter(r["text"] for r in kept).most_common(20)]
    lines += ["\n| Topic | Rules |\n|---|---|"] + [f"| {k} | {v} |" for k, v in Counter(t for r in kept for t in r["topics"]).most_common(30)]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"kept {len(kept)} rules (merged {merged}) -> {OUT}; report {REPORT}")


def status() -> None:
    for source in ("answers", "chunks"):
        res = load_results(source)
        if res:
            print(source, Counter(r.get("type", "?") for r in res.values()),
                  "rules:", sum(len(json.loads(r["text"]).get("rules", [])) for r in res.values() if r.get("type") == "succeeded"))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--source", choices=["answers", "chunks", "heldout"], default="answers")
    e.add_argument("--limit", type=int, default=0, help="number of items (pilot)")
    e.add_argument("--model", default=MODEL)
    e.add_argument("--workers", type=int, default=2)
    e.add_argument("--pack", type=int, default=PACK)
    sub.add_parser("merge")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        extract(a.source, a.limit, a.model, a.workers, a.pack)
    elif a.cmd == "merge":
        merge()
    else:
        status()


if __name__ == "__main__":
    main()
