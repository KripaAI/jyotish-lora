"""Phase 3: plan generation seeds (which chunk(s), task type and chart each example comes from).

Usage:
    python -m src.dataset.seeds            # writes data/sft/seeds.jsonl and runs/seeds_report.md
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict

from src.chart.births import chart_for_seed
from src.chart.render import render_chart_text
from src.common import CHUNKS, RUNS, SFT, read_jsonl, write_jsonl

SEED = 42
TARGET_EXAMPLES = 7500  # raw; about 6,000 remain after filtering (Tech Spec 5.4.1)
TASKS = {  # task: (share of examples, questions per seed)
    "concept": (0.30, 3), "placement": (0.22, 3), "full_chart": (0.25, 2), "comparison": (0.08, 2),
    "remedies": (0.07, 2), "uncertainty": (0.03, 2), "safety": (0.05, 2),
}
CHART_TASKS = {"full_chart", "remedies"}
SAFETY_CHART_SHARE = 0.5
MAX_USES_PER_CHUNK = 2
CHART_CANDIDATES = 12
CORE_TOPICS = ([f"house:{i}" for i in range(1, 13)] +
               [f"planet:{p}" for p in ("sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn", "rahu", "ketu")] +
               [f"sign:{s}" for s in ("aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio",
                                      "sagittarius", "capricorn", "aquarius", "pisces")] +
               ["dasha", "yoga:raja", "yoga:dhana", "yoga:gajakesari", "yoga:viparita", "yoga:neechabhanga",
                "yoga:panchamahapurusha", "nakshatra", "divisional", "transit", "ashtakavarga", "jaimini", "prashna",
                "muhurta", "compatibility", "remedy"])
CORE_MIN_SEEDS = 6


def eligible(task: str, c: dict) -> bool:
    t = set(c["topics"])
    if task in ("concept", "uncertainty"):
        return c["use"] in ("all", "concept")
    if c["use"] == "safety":
        return task == "safety"
    if c["use"] != "all":
        return False
    if task == "placement":
        return any(x.startswith("planet:") for x in t) and any(x.startswith(("house:", "sign:")) for x in t)
    if task == "full_chart":
        return any(x.startswith(("house:", "yoga:")) for x in t) or bool(t & {"dasha", "marriage", "career", "wealth", "children"})
    if task == "remedies":
        return bool(t & {"remedy", "gemstone"})
    if task == "safety":
        return bool(t & {"longevity", "health", "speculation", "litigation"}) or "yoga:kalasarpa" in t
    return task == "comparison"


def chart_score(chart: dict, topics: set[str]) -> float:
    """How well a candidate chart matches a chunk's topics, so the passage's rules apply to it."""
    score = 0.0
    houses = {int(t.split(":")[1]) for t in topics if t.startswith("house:")}
    signs = {t.split(":")[1] for t in topics if t.startswith("sign:")}
    planets = {t.split(":")[1] for t in topics if t.startswith("planet:")}
    for p in chart["planets"]:
        name = p["name"].lower()
        if name in planets:
            score += 2 * (p["house"] in houses) + (p["sign"].lower() in signs)
    yogas = {y["name"].lower().replace("-", "").replace(" ", "") for y in chart["yogas"]}
    for t in topics:
        if t.startswith("yoga:") and any(t[5:] in y for y in yogas):
            score += 3
    if "dasha" in topics and chart["dasha"]["maha"]["lord"].lower() in planets:
        score += 1
    return score


def pick_chart(rng: random.Random, topics: list[str], used: set[int]) -> tuple[int, dict]:
    best = None
    for _ in range(CHART_CANDIDATES):
        s = rng.randrange(10**9)
        while s in used:
            s = rng.randrange(10**9)
        chart = chart_for_seed(s)
        sc = chart_score(chart, set(topics))
        if best is None or sc > best[0]:
            best = (sc, s, chart)
    used.add(best[1])
    return best[1], best[2]


def main() -> None:
    rng = random.Random(SEED)
    chunks = [c for c in read_jsonl(CHUNKS / "chunks.jsonl") if c["quality"] == "ok"]
    by_id = {c["chunk_id"]: c for c in chunks}
    book_size = Counter(c["book"] for c in chunks)
    weight = {c["chunk_id"]: 1 / math.sqrt(book_size[c["book"]]) for c in chunks}  # big books don't dominate
    uses: Counter = Counter()
    used_pairs: set[tuple[str, str]] = set()

    def sample(task: str, need_topic: str | None = None) -> dict | None:
        pool = [c for c in chunks if uses[c["chunk_id"]] < MAX_USES_PER_CHUNK and eligible(task, c)
                and (need_topic is None or need_topic in c["topics"])
                and not any(s["task"] == task and c["chunk_id"] in s["chunk_ids"] for s in seeds_for_chunk[c["chunk_id"]])]
        if not pool:
            return None
        c = rng.choices(pool, weights=[weight[x["chunk_id"]] / (1 + uses[x["chunk_id"]]) for x in pool])[0]
        uses[c["chunk_id"]] += 1
        return c

    seeds: list[dict] = []
    seeds_for_chunk: dict[str, list[dict]] = defaultdict(list)

    def add(task: str, chunk_ids: list[str]):
        s = {"seed_id": f"s{len(seeds):05d}", "task": task, "chunk_ids": chunk_ids, "n_questions": TASKS[task][1]}
        seeds.append(s)
        for cid in chunk_ids:
            seeds_for_chunk[cid].append(s)

    targets = {t: round(TARGET_EXAMPLES * share / q) for t, (share, q) in TASKS.items()}

    # 1. coverage pass: make sure every core topic is seeded
    for topic in CORE_TOPICS:
        for _ in range(CORE_MIN_SEEDS):
            task = rng.choice(["concept", "placement", "full_chart"])
            c = sample(task, topic) or sample("concept", topic)
            if c:
                add(task if eligible(task, c) else "concept", [c["chunk_id"]])

    # 2. comparison pairs: two books sharing at least two specific topics
    spec = lambda c: {t for t in c["topics"] if t.startswith(("planet:", "house:", "yoga:", "sign:"))}
    while sum(s["task"] == "comparison" for s in seeds) < targets["comparison"]:
        a = sample("comparison")
        if a is None:
            break
        partners = [c for c in chunks if c["short"] != a["short"] and c["use"] == "all"
                    and len(spec(a) & spec(c)) >= 2 and uses[c["chunk_id"]] < MAX_USES_PER_CHUNK
                    and tuple(sorted((a["chunk_id"], c["chunk_id"]))) not in used_pairs]
        if not partners:
            continue
        b = max(rng.sample(partners, min(20, len(partners))), key=lambda c: len(spec(a) & spec(c)))
        uses[b["chunk_id"]] += 1
        used_pairs.add(tuple(sorted((a["chunk_id"], b["chunk_id"]))))
        add("comparison", [a["chunk_id"], b["chunk_id"]])

    # 3. fill each task to its target
    for task in TASKS:
        if task == "comparison":
            continue
        misses = 0
        while sum(s["task"] == task for s in seeds) < targets[task] and misses < 50:
            c = sample(task)
            if c is None:
                misses += 1
                continue
            add(task, [c["chunk_id"]])

    # 4. attach charts
    used_chart_seeds: set[int] = set()
    for s in seeds:
        if s["task"] in CHART_TASKS or (s["task"] == "safety" and rng.random() < SAFETY_CHART_SHARE):
            topics = sorted({t for cid in s["chunk_ids"] for t in by_id[cid]["topics"]})
            chart_seed, chart = pick_chart(rng, topics, used_chart_seeds)
            s["chart_seed"] = chart_seed
            s["chart"] = chart
            s["chart_text"] = render_chart_text(chart)

    rng.shuffle(seeds)
    write_jsonl(SFT / "seeds.jsonl", seeds)

    # report
    task_counts = Counter(s["task"] for s in seeds)
    exp = {t: task_counts[t] * TASKS[t][1] for t in TASKS}
    total = sum(exp.values())
    topic_cov = Counter(t for s in seeds for cid in s["chunk_ids"] for t in by_id[cid]["topics"])
    book_cov = Counter(by_id[cid]["book"] for s in seeds for cid in s["chunk_ids"])
    lines = ["# Seed plan report", "", f"{len(seeds)} seeds -> about {total} raw examples "
             f"({len(chunks)} usable chunks; {len(uses)} used).", "",
             "| Task | Seeds | Questions per seed | Expected examples | Share | Target share |", "|---|---|---|---|---|---|"]
    for t, (share, q) in TASKS.items():
        lines.append(f"| {t} | {task_counts[t]} | {q} | {exp[t]} | {exp[t] / max(total, 1):.1%} | {share:.0%} |")
    lines += ["", f"Charts attached: {sum('chart' in s for s in seeds)}", "",
              "## Core topic coverage (seeds whose chunks carry the topic)", "", "| Topic | Seeds |", "|---|---|"]
    lines += [f"| {t} | {topic_cov[t]}{' ⚠' if topic_cov[t] < 10 else ''} |" for t in CORE_TOPICS]
    lines += ["", "## Books used", "", "| Book | Seed chunks |", "|---|---|"]
    lines += [f"| {b} | {n} |" for b, n in book_cov.most_common()]
    (RUNS / "seeds_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(seeds)} seeds (~{total} examples) -> {SFT / 'seeds.jsonl'}; report -> {RUNS / 'seeds_report.md'}")


if __name__ == "__main__":
    main()
