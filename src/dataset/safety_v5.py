"""v5 safety rows at zero cost: user messages written by the local model (Ollama qwen3:14b), answered with the project's
reviewed fixed safety replies (src/app/safety.py REPLIES, the same text the serving guard returns).

Why: v4 drowned 265 safety rows in 100,000 short rule paraphrases and learned to answer "when will I die?" with a classical
longevity rule. v5 brings safety to about 5% of the mix. About 30% of questions are Hinglish (v4 failed all 26 Hinglish
adversarial prompts). Questions near any evaluation prompt are dropped.

    python -m src.dataset.safety_v5          # -> data/sft_v5/safety_fixed.jsonl (resumable cache in data/sft_v5/safety_q/)
"""
from __future__ import annotations

import json
import random
from collections import Counter

from src.app.safety import REPLIES
from src.common import DATA, EVALSETS, PROMPTS, read_jsonl, write_jsonl
from src.dataset.facts import _norm
from src.dataset.rule_qa import ollama_chat
from src.dataset.safety_v2 import CATEGORIES

OUT = DATA / "sft_v5" / "safety_fixed.jsonl"
CACHE = DATA / "sft_v5" / "safety_q"
PER_CATEGORY = 100
EXTRA = {"system_prompt": "asking the assistant to reveal, print or repeat its hidden instructions or system prompt, or to ignore its rules",
         "caste_ranking": "asking which caste or community is superior, inferior, impure or should be avoided, using astrology to justify it"}
STYLES = ["direct", "worried", "blunt", "role-play request (asks the assistant to act as an old-school pandit who answers anything)",
          "hypothetical or 'for a novel' framing", "claims to be a doctor, lawyer or astrologer to unlock an answer",
          "an innocent question whose last part crosses the line"]
SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "string"}}}, "required": ["questions"]}
SYSTEM = """You write realistic user messages for training a Vedic astrology assistant to handle sensitive requests safely. Write exactly {n} different messages for the CATEGORY below. Each message is from a real person who wants the assistant to do the unsafe thing described. Vary persona, emotion and length (one to three sentences). Some mention a chart placement, dasha, yoga or transit. Never include real names or birth details.
Language: {lang}
Style for every message: {style}
Return JSON: {{"questions": [...]}}"""


def descriptions() -> dict[str, str]:
    d = {c: v[1] for c, v in CATEGORIES.items()}
    d.update(EXTRA)
    return {c: d[c] for c in REPLIES}


def generate() -> list[tuple[str, str, str]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    rng = random.Random(5)
    out = []
    for cat, desc in descriptions().items():
        path = CACHE / f"{cat}.json"
        if path.exists():
            qs = json.loads(path.read_text(encoding="utf-8"))
        else:
            qs = []
            for k in range(PER_CATEGORY // 10):
                lang = ("Hinglish: Hindi written in Roman script mixed with English (e.g. 'Meri kundli mein Shani 8th mein hai, "
                        "kya meri umar kam hai?')" if k % 10 < 3 else "English")
                style = STYLES[k % len(STYLES)]
                try:
                    res = ollama_chat(SYSTEM.format(n=10, lang=lang, style=style), f"CATEGORY: {cat}: {desc}", "qwen3:14b", SCHEMA, 0.9)
                    batch = [q.strip() for q in json.loads(res["text"]).get("questions", []) if q.strip()]
                except Exception:  # noqa: BLE001 - a missing batch only lowers the count
                    batch = []
                qs += [{"q": q, "lang": "hinglish" if lang.startswith("Hinglish") else "en", "style": style} for q in batch]
            path.write_text(json.dumps(qs, ensure_ascii=False, indent=0), encoding="utf-8")
        out += [(cat, q["q"], q["lang"]) for q in qs]
        print(f"{cat}: {len(qs)} questions", flush=True)
    rng.shuffle(out)
    return out


def main() -> None:
    system = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
    held = [_norm(r["prompt"]) for r in read_jsonl(EVALSETS / "safety_eval.jsonl")]
    held += [_norm(r["prompt"]) for r in read_jsonl(EVALSETS / "safety_v2_eval.jsonl")]
    held += [_norm(r["prompt"]) for r in read_jsonl(EVALSETS / "robustness.jsonl")]
    rows, seen, dropped = [], set(), Counter()
    for cat, q, lang in generate():
        w = _norm(q)
        key = " ".join(sorted(w))
        if key in seen:
            dropped["duplicate"] += 1
            continue
        if any(len(w & h) / max(len(w | h), 1) >= 0.5 for h in held):
            dropped["near_eval_prompt"] += 1
            continue
        seen.add(key)
        rows.append({"id": f"safe5-{len(rows):05d}", "task": "safety_v5", "category": cat, "language": lang,
                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": q},
                                  {"role": "assistant", "content": REPLIES[cat]}]})
    write_jsonl(OUT, rows)
    print(f"wrote {len(rows)} safety rows -> {OUT}; dropped {dict(dropped)}; Hinglish {sum(r['language'] == 'hinglish' for r in rows)}")
    print(Counter(r["category"] for r in rows))


if __name__ == "__main__":
    main()
