"""v4 step 2: many paraphrased question-answer pairs per rule, written by a LOCAL open model and checked by code.

The local model (Qwen3 14B through Ollama on the workstation GPU) only rewrites: it receives one rule record (statement,
conditions, modifiers, exceptions, text, tradition) and writes k Q&A pairs in varied wording, at least one in Hinglish.
It never authors a rule. A code check then rejects any pair that names a planet, sign, house, nakshatra, yoga or book
that the record does not contain, that cites chapters or verses, that drops the attribution, or that is the wrong length.
This is the zero-cost version of "5 to 8 paraphrases per fact" (Allen-Zhu and Li; Ovadia et al.).

    python -m src.dataset.rule_qa generate --limit 20            # pilot
    python -m src.dataset.rule_qa generate                       # full, resumable
    python -m src.dataset.rule_qa build                          # -> data/sft_v4/rule_qa.jsonl, runs/rule_qa_report.md
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.chart.constants import NAKSHATRAS, PLANETS, PLANETS_SANSKRIT, SIGNS, SIGNS_SANSKRIT
from src.common import BOOKS, DATA, EVALSETS, PROMPTS, RUNS, read_jsonl, write_jsonl
from src.dataset.facts import _norm, too_close
from src.dataset.filters import CITATION

RULES = DATA / "sft_v4" / "rules.jsonl"
SAMPLES = DATA / "sft_v4" / "rule_qa" / "samples.jsonl"
OUT = DATA / "sft_v4" / "rule_qa.jsonl"
REPORT = RUNS / "rule_qa_report.md"
OLLAMA = "http://localhost:11434"
MODEL = "qwen3:14b"
K = 4
WORDS = (40, 220)

SCHEMA = {"type": "object",
          "properties": {"pairs": {"type": "array", "items": {
              "type": "object",
              "properties": {"question": {"type": "string"}, "answer": {"type": "string"},
                             "language": {"type": "string", "enum": ["en", "hinglish"]}},
              "required": ["question", "answer", "language"], "additionalProperties": False}}},
          "required": ["pairs"], "additionalProperties": False}

SYSTEM = """You write question-and-answer pairs for training a Vedic astrology assistant. You are given ONE RULE RECORD extracted from a classical or modern Jyotish text. Your job is to restate that rule in several different ways, not to add anything to it.

Write {k} pairs:
- Questions: every question must be about THIS rule's own subject (its planets, houses, signs, yoga or concept). They should sound like different real people (a worried client, a beginner, an advanced student, a sceptic). Vary length and wording; do not reuse the same opening. One question must ask why the rule holds or when it does not apply. At least one question must be in Hinglish: Hindi written in Roman script mixed with English words, using Hindi planet names (Surya, Chandra, Mangal, Budh, Guru, Shukra, Shani) and words like "bhav", "rashi", "kya hota hai", "kaise". Never mention the record or that you were given anything.
- Answers: ALWAYS in English (also when the question is in Hinglish), 60 to 180 words, in the voice of an experienced astrologer. State the rule, its conditions, what modifies it and any exception, exactly as the record gives them. Attribute it by name to the text or tradition given in the record ("Phaladeepika holds that...", "in the Parashari view..."), but vary where in the answer the attribution appears and how the answer opens. Use Sanskrit terms with short glosses. End with a balanced note: the whole chart must be judged and astrology describes tendencies, not certainties.
- Never add planets, signs, houses, nakshatras, yogas, texts, authors or results that are not in the record. Never quote verses, never give chapter or verse numbers, never predict death, illness, legal or financial outcomes.

Return JSON: {{"pairs": [{{"question": ..., "answer": ..., "language": "en" | "hinglish"}}]}}"""

_ORD = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")
_PLANET = re.compile(r"\b(" + "|".join(PLANETS + [v for v in PLANETS_SANSKRIT.values() if v not in PLANETS] + ["Budh", "Mangal", "Chandra", "Surya", "Shani", "Shukra", "Guru"]) + r")\b")
_SIGN = re.compile(r"\b(" + "|".join(SIGNS + SIGNS_SANSKRIT) + r")\b")
_NAK = re.compile(r"\b(" + "|".join(NAKSHATRAS) + r")\b")
_YOGA = re.compile(r"\b([A-Z][a-zA-Z-]+(?: [A-Z][a-zA-Z-]+)?) [Yy]oga\b")
_PL_CANON = {**{p: p for p in PLANETS}, **{v: k for k, v in PLANETS_SANSKRIT.items()},
             "Budh": "Mercury", "Mangal": "Mars", "Chandra": "Moon", "Surya": "Sun", "Shani": "Saturn", "Shukra": "Venus", "Guru": "Jupiter"}
_SG_CANON = {**{s: s for s in SIGNS}, **dict(zip(SIGNS_SANSKRIT, SIGNS))}
GROUP_HOUSES = {"kendra": {1, 4, 7, 10}, "trikona": {1, 5, 9}, "dusthana": {6, 8, 12}, "trik": {6, 8, 12},
                "upachaya": {3, 6, 10, 11}, "maraka": {2, 7}, "angle": {1, 4, 7, 10}, "trine": {1, 5, 9}}
TITLES = sorted({m["title"] for m in BOOKS.values()} | {m["short"] for m in BOOKS.values()}, key=len, reverse=True)
# Constitution Principle V: the classics predict death, name diseases and carry gender/caste stigma; none of that may be
# trained in as a rule the model states. Pairs matching these are rejected (reason "safety"); there is data to spare.
SAFETY_BLOCK = re.compile(
    r"\b(die|dies|died|dying|death|dead|killed|kills|demise|fatal|lifespan|life[- ]span|ayurdaya|maraka|alpayu|"
    r"balarishta|arishta|short[- ]lived|long[- ]lived|mortality|suicid\w*|longevity|ayus|ayur|years of life|span of life|"
    r"life of \d+|lives? (?:up )?to \d+|\d+ years of age|wounds?|boils|ulcers?|fistula|"
    r"cancer|tumou?r|leprosy|leper|leprous|tuberculosis|consumption|epilep\w*|insan\w*|madness|lunatic|lunacy|"
    r"blind|deaf|dumb|lame|cripple\w*|impoten\w*|venereal|syphil\w*|piles|"
    r"unchaste|adulter\w*|prostitut\w*|harlot|courtesan|widow\w*|barren|sterile|ugly|deformed|"
    r"low[- ]caste|outcaste|chandala|shudra|mleccha|untouchable|wicked woman|bad woman|loose woman|"
    r"kill|murder\w*|poison\w*|execution|hanged|imprison\w*)\b", re.I)
HINGLISH = re.compile(r"\b(hai|hain|ho|hota|hoti|hote|mein|me|ka|ki|ke|ko|se|aur|sakta|sakti|nahi|nahin|kya|toh|agar|lekin|"
                      r"jab|bhav|rashi|wala|wale|karta|karti|hoga|hogi|jata|jati|dekha|yeh|woh|uska|uski)\b", re.I)
STOPWORDS = set("the a an and or of in on to is are be by for with from its it this that as when if not no which who what "
                "how why does do can will their there these those into than then also one two three house houses planet planets "
                "sign signs chart native person gives give given result results".split())


def rule_text(rule: dict) -> str:
    return " ".join(str(rule.get(k, "")) for k in ("statement", "conditions", "modifiers", "exceptions", "text", "tradition"))


def entities(text: str) -> dict[str, set]:
    houses = {int(m.group(1)) for m in _ORD.finditer(text) if 1 <= int(m.group(1)) <= 12}
    for word, hs in GROUP_HOUSES.items():
        if re.search(rf"\b{word}s?\b", text, re.I):
            houses |= hs
    return {"planets": {_PL_CANON[m.group(1)] for m in _PLANET.finditer(text)},
            "signs": {_SG_CANON[m.group(1)] for m in _SIGN.finditer(text)},
            "nakshatras": {m.group(1) for m in _NAK.finditer(text)},
            "houses": houses,
            "yogas": {m.group(1).lower().split()[-1] for m in _YOGA.finditer(text)},
            "titles": {t for t in TITLES if t.lower() in text.lower()}}


# Sentences that explain WHY a rule holds ("These signs are linked with intellectual expansion...") are the paraphraser's own
# gloss unless the rule record says so. Such a sentence is removed when most of its content words are absent from the record.
EXPLAIN = re.compile(r"\b(because|since|due to|as (?:it|they|this)|linked (?:with|to)|associated with|symboli[sz]\w*|"
                     r"represents?|signif(?:y|ies)|aligns? (?:well )?with|in line with|reflects?|embod\w+|is known for|"
                     r"nature of|which means|this means|this is why|that is why|owing to|stems from|rooted in)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_WORD = re.compile(r"[a-z]+")
GLOSS_OK = set("kendra kendras trikona trikonas dusthana dusthanas upachaya angle angles trine trines house houses bhava "
               "lagna ascendant lord lords planet planets sign signs mahadasha antardasha dasha period periods".split())
BOILER = set("the a an and or of in on to is are be by for with from its it this that as when if not no which who what how why "
             "does do can will their there these those into than then also chart whole must judged astrology describes "
             "tendencies tendency certainties certainty rather however although while such other more most very well "
             "important remember overall".split())


def strip_elaboration(rule: dict, answer: str, max_novel: float = 0.5) -> tuple[str, int]:
    """(answer without unsupported explanatory sentences, number removed). The first sentence is always kept."""
    known = set(_WORD.findall(rule_text(rule).lower())) | GLOSS_OK
    sents, kept, removed = _SENT.split(answer.strip()), [], 0
    for i, s in enumerate(sents):
        if i > 0 and EXPLAIN.search(s):
            words = [w for w in _WORD.findall(s.lower()) if len(w) > 3 and w not in BOILER]
            if words and sum(w not in known for w in words) / len(words) > max_novel:
                removed += 1
                continue
        kept.append(s)
    return " ".join(kept), removed


def check_pair(rule: dict, question: str, answer: str) -> str:
    """'' when the pair passes, else the reason it fails."""
    n = len(answer.split())
    if not WORDS[0] <= n <= WORDS[1]:
        return "length"
    if CITATION.search(answer) or CITATION.search(question):
        return "citation"
    if SAFETY_BLOCK.search(answer) or SAFETY_BLOCK.search(question):
        return "safety"
    if re.search(r"\b(the record|the rule record|given rule|provided rule|as given)\b", answer, re.I):
        return "leak"
    if len(HINGLISH.findall(answer)) >= 3:
        return "answer_not_english"
    allowed, said, asked = entities(rule_text(rule)), entities(answer), entities(question)
    for key in ("planets", "signs", "nakshatras", "yogas", "titles"):
        if said[key] - allowed[key]:
            return f"extra_{key}"
    if said["houses"] - allowed["houses"]:
        return "extra_houses"
    for key in ("planets", "signs", "nakshatras", "yogas", "houses"):
        if asked[key] - allowed[key]:
            return "question_off_rule"
    if not (_norm(question) & (_norm(rule["statement"]) - STOPWORDS)):
        return "question_off_rule"
    text, trad = rule.get("text", ""), rule.get("tradition", "")
    names = [x for x in (text, trad) if x]
    if names and not any(x.lower().split()[0] in answer.lower() for x in names):
        return "no_attribution"
    return ""


# ------------------------------------------------------------------------------------------------------ generate
def ollama_chat(system: str, user: str, model: str, schema: dict, temperature: float = 0.8, host: str = OLLAMA) -> dict:
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False, "think": False, "format": schema,
            "options": {"temperature": temperature, "num_ctx": 4096, "num_predict": 1600}}
    req = urllib.request.Request(f"{host}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    return {"text": d["message"]["content"], "eval_count": d.get("eval_count", 0), "eval_s": d.get("eval_duration", 0) / 1e9}


def llamacpp_chat(system: str, user: str, model: str, schema: dict, temperature: float = 0.8, host: str = "http://127.0.0.1:8080") -> dict:
    """Same call against a llama.cpp `llama-server` (OpenAI-compatible, JSON-schema constrained output); used on Kaggle T4s.
    Thinking is switched off both ways Qwen3 understands: the chat-template flag and the /no_think soft switch."""
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user + "\n/no_think"}],
            "temperature": temperature, "max_tokens": 1600, "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "pairs", "schema": schema}}}
    req = urllib.request.Request(f"{host}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read())
    text = re.sub(r"<think>.*?</think>", "", d["choices"][0]["message"]["content"], flags=re.S).strip()
    return {"text": text, "eval_count": d.get("usage", {}).get("completion_tokens", 0), "eval_s": 0.0}


BACKENDS = {"ollama": ollama_chat, "llamacpp": llamacpp_chat}


def in_shards(rule_id: str, shards: str) -> bool:
    """'0,1/8' keeps rules whose stable hash falls in shards 0 or 1 of 8; '' keeps everything.
    Shards partition the rule base so the workstation and several Kaggle kernels can work on disjoint slices."""
    if not shards:
        return True
    import hashlib
    idx, n = shards.split("/")
    want = {int(i) for i in idx.split(",")}
    return int(hashlib.sha256(rule_id.encode()).hexdigest(), 16) % int(n) in want


def rule_block(rule: dict) -> str:
    fields = [("Statement", rule["statement"]), ("Conditions", rule["conditions"]), ("Modifies the result", rule["modifiers"]),
              ("Exceptions", rule["exceptions"]), ("Text", rule["text"] or "(not named; attribute to the tradition)"),
              ("Tradition", rule["tradition"])]
    return "RULE RECORD\n" + "\n".join(f"{k}: {v}" for k, v in fields if v)


def _one(rule: dict, k: int, model: str, backend: str = "ollama", host: str | None = None) -> dict:
    try:
        chat = BACKENDS[backend]
        res = chat(SYSTEM.format(k=k), rule_block(rule), model, SCHEMA, **({"host": host} if host else {}))
        pairs = json.loads(res["text"]).get("pairs", [])
        return {"rule_id": rule["rule_id"], "model": model, "pairs": pairs, "eval_count": res["eval_count"], "eval_s": res["eval_s"]}
    except Exception as e:  # noqa: BLE001 - recorded, retried on the next run
        return {"rule_id": rule["rule_id"], "model": model, "error": str(e)[:300]}


def read_samples(path) -> list[dict]:
    """Tolerant reader: another process may be appending a partial last line."""
    out = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def generate(limit: int, k: int, model: str, workers: int, backend: str = "ollama", host: str | None = None,
             shards: str = "", rules_path=None, samples_path=None, max_hours: float = 0.0, done_from: list | None = None) -> None:
    rules_path, samples_path = rules_path or RULES, samples_path or SAMPLES
    rules = [r for r in read_jsonl(rules_path) if in_shards(r["rule_id"], shards)]
    done = {r["rule_id"] for r in read_samples(samples_path) if "pairs" in r}
    for extra in done_from or []:          # e.g. the workstation's samples, so a Kaggle shard skips what is already done
        done |= {r["rule_id"] for r in read_samples(extra) if "pairs" in r}
    kind_rank = {"rule": 0, "definition": 0, "significance": 1, "comparison": 1, "remedy": 2}
    todo = sorted((r for r in rules if r["rule_id"] not in done),      # most valuable rules first: the run takes hours
                  key=lambda r: (r.get("confidence") != "high", kind_rank.get(r.get("kind"), 3), r["rule_id"]))
    if limit:
        todo = todo[:limit]
    print(f"{len(rules)} rules in shards '{shards or 'all'}', {len(done)} done, {len(todo)} to generate with {backend} {model} "
          f"(k={k}, {workers} workers)", flush=True)
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    t0, n, toks = time.time(), 0, 0
    with open(samples_path, "a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(_one, r, k, model, backend, host) for r in todo]
        for fut in as_completed(futures):
            row = fut.result()
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            toks += row.get("eval_count", 0)
            if n % 25 == 0 or n == len(todo):
                el = time.time() - t0
                print(f"{n}/{len(todo)} rules | {toks / max(el, 1):.0f} tok/s overall | {el / 60:.1f} min | "
                      f"eta {(len(todo) - n) * el / n / 60:.0f} min", flush=True)
            if max_hours and time.time() - t0 > max_hours * 3600:
                print(f"STOPPED FOR TIME after {n} rules; rerun to continue", flush=True)
                for fu in futures:
                    fu.cancel()
                break


def merge_samples(paths: list) -> None:
    """Fold sample files from other machines (Kaggle shards) into the main samples file, one row per rule."""
    have = {r["rule_id"] for r in read_samples(SAMPLES) if "pairs" in r}
    added = 0
    with open(SAMPLES, "a", encoding="utf-8") as f:
        for p in paths:
            for r in read_samples(p):
                if "pairs" in r and r["rule_id"] not in have:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    have.add(r["rule_id"])
                    added += 1
    print(f"merged {added} new rule samples into {SAMPLES}; {len(have)} rules sampled in total")


# ------------------------------------------------------------------------------------------------------ build
def build() -> None:
    system = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
    rules = {r["rule_id"]: r for r in read_jsonl(RULES)}
    eval_qs = [_norm(r["question"]) for r in read_jsonl(EVALSETS / "quiz.jsonl")]
    rob = EVALSETS / "robustness.jsonl"
    if rob.exists():
        eval_qs += [_norm(r["prompt"]) for r in read_jsonl(rob)]
    rows, reasons, seen, per_rule = [], Counter(), set(), Counter()
    samples = []
    with open(SAMPLES, encoding="utf-8") as f:      # tolerant: the generator may be appending a partial last line
        for line in f:
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                reasons["partial_line"] += 1
    def accept(rule_id: str, i: int, q: str, a: str, lang: str) -> bool:
        key = " ".join(sorted(_norm(q)))
        if key in seen:
            reasons["duplicate_question"] += 1
            return False
        if too_close(q, eval_qs):
            reasons["eval_overlap"] += 1
            return False
        seen.add(key)
        per_rule[rule_id] += 1
        rows.append({"id": f"rq-{rule_id}-{i}", "task": "rule_qa", "rule_id": rule_id, "language": lang,
                     "source_ids": rules[rule_id]["source_ids"],
                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": q},
                                  {"role": "assistant", "content": a}]})
        return True

    for s in samples:
        rule = rules.get(s["rule_id"])
        if not rule or "pairs" not in s:
            reasons["no_pairs"] += 1
            continue
        good_answers, hinglish_orphans = [], []
        for i, p in enumerate(s["pairs"]):
            q, a = p.get("question", "").strip(), p.get("answer", "").strip()
            if not q or not a:
                reasons["empty"] += 1
                continue
            a, n_removed = strip_elaboration(rule, a)
            if n_removed:
                reasons["elaboration_sentences_removed"] += n_removed
            why = check_pair(rule, q, a)
            if why == "answer_not_english" and HINGLISH.search(q):
                hinglish_orphans.append((i, q))    # the question is good; the model answered in Hinglish against instructions
                continue
            if why:
                reasons[why] += 1
                continue
            if accept(s["rule_id"], i, q, a, p.get("language", "en")):
                good_answers.append(a)
        # Rescue: a Hinglish question gets the rule's best accepted English answer (same rule, same content).
        for i, q in hinglish_orphans:
            if good_answers and check_pair(rule, q, good_answers[0]) == "":
                if accept(s["rule_id"], i, q, good_answers[0], "hinglish"):
                    reasons["hinglish_rescued"] += 1
            else:
                reasons["answer_not_english"] += 1
    write_jsonl(OUT, rows)
    total = len(rows) + sum(v for k, v in reasons.items() if k not in ("elaboration_sentences_removed", "hinglish_rescued"))
    lines = [f"# Rule Q&A report\n", f"Kept **{len(rows)}** pairs of {total} ({100 * len(rows) / max(total, 1):.0f}%) for "
             f"{len(per_rule)} rules (mean {len(rows) / max(len(per_rule), 1):.1f} per rule); "
             f"Hinglish {sum(r['language'] == 'hinglish' for r in rows)}.\n", "\n| Reject reason | Count |\n|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in reasons.most_common()]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"kept {len(rows)} pairs -> {OUT}; rejects {dict(reasons)}; report {REPORT}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--limit", type=int, default=0)
    g.add_argument("--k", type=int, default=K)
    g.add_argument("--model", default=MODEL)
    g.add_argument("--workers", type=int, default=1)
    g.add_argument("--backend", choices=sorted(BACKENDS), default="ollama")
    g.add_argument("--host", default=None, help="server URL (default: local Ollama, or http://127.0.0.1:8080 for llamacpp)")
    g.add_argument("--shards", default="", help="e.g. '0,1,2,3/8': only rules hashing into these shards")
    g.add_argument("--rules", default=None, help="rules.jsonl path (default data/sft_v4/rules.jsonl)")
    g.add_argument("--samples", default=None, help="output samples path (default data/sft_v4/rule_qa/samples.jsonl)")
    g.add_argument("--max-hours", type=float, default=0.0, help="stop cleanly after this many hours (Kaggle's 12 h limit)")
    g.add_argument("--done-from", nargs="*", default=None, help="other sample files whose rules are skipped")
    m = sub.add_parser("merge-samples")
    m.add_argument("paths", nargs="+")
    sub.add_parser("build")
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        from pathlib import Path
        generate(a.limit, a.k, a.model, a.workers, a.backend, a.host, a.shards,
                 Path(a.rules) if a.rules else None, Path(a.samples) if a.samples else None, a.max_hours,
                 [Path(p) for p in a.done_from] if a.done_from else None)
    elif a.cmd == "merge-samples":
        from pathlib import Path
        merge_samples([Path(p) for p in a.paths])
    else:
        build()


if __name__ == "__main__":
    main()
