"""Phase 3.7: automatic filters over data/sft/generated.jsonl.

Drops an example when: the fact check failed or is missing, it cites chapters/verses or "the passage",
a chart claim contradicts the chart engine, the length is out of range, it is not English,
or it near-duplicates an earlier example.

Usage:
    python -m src.dataset.filters        # -> data/sft/filtered.jsonl, runs/filter_report.md
"""
from __future__ import annotations

import json
import re
from collections import Counter

from datasketch import MinHash, MinHashLSH
from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

from src.chart.constants import PLANETS
from src.common import RUNS, SFT, read_jsonl, write_jsonl

DetectorFactory.seed = 0
LENGTH = {"safety": (60, 300), "uncertainty": (100, 500), "full_chart": (200, 850), "remedies": (120, 850)}  # words; others use DEFAULT_LENGTH
DEFAULT_LENGTH = (120, 700)
DUP_THRESHOLD = 0.8

_P = "|".join(PLANETS)
CITATION = re.compile(
    r"\b(?:chapter|ch\.|adhyaya)\s*[0-9IVXL]+\b|\b(?:verse|verses|sloka|slokas|shloka|shlokas|stanza)\s*\d+"
    r"|\bthe (?:source )?passage\b|\bthe (?:provided|given) (?:text|passage|excerpt)\b|\bthe excerpt\b"
    r"|[ऀ-ॿ]{3,}", re.I)
HOUSE_CLAIM = re.compile(
    rf"\b({_P})\b(?P<mid>[^.;:\n]{{0,40}}?)\b(?:is |are )?(?:in|occupies|occupying|placed in|posited in|sits in|sitting in|located in)"
    rf" (?:the |your |its )?(\d{{1,2}})(?:st|nd|rd|th) house\b(?!\s+(?:from|counted|reckoned))", re.I)
LORD_CLAIM = re.compile(rf"\b(?:your |the )?(\d{{1,2}})(?:st|nd|rd|th)[- ]lord,?\s+(?:is\s+)?({_P})\b", re.I)
WORD = re.compile(r"\w+")


def citation_issue(text: str) -> bool:
    return bool(CITATION.search(text))


def chart_contradictions(text: str, chart: dict) -> tuple[list[str], list[str]]:
    """(hard contradictions, soft warnings). Lord claims and possessive house claims are hard;
    other house claims may be general rules quoted inside a reading, so they are only warnings."""
    house_of = {p["name"]: p["house"] for p in chart["planets"]}
    lords = {h["house"]: h["lord"] for h in chart["houses"]}
    hard, soft = [], []
    for m in HOUSE_CLAIM.finditer(text):
        planet, mid, house = m.group(1).title(), m.group("mid"), int(m.group(3))
        if re.search(rf"\b(?:{_P})\b", mid, re.I) or not 1 <= house <= 12:
            continue  # another planet sits between: the house belongs to that one
        if house_of[planet] != house:
            claim = m.group(0)
            context = text[max(0, m.start() - 12) : m.end()]  # catches "your Saturn in the 7th house"
            (hard if re.search(r"\byour\b", context, re.I) else soft).append(claim)
    for m in LORD_CLAIM.finditer(text):
        house, planet = int(m.group(1)), m.group(2).title()
        if 1 <= house <= 12 and lords[house] != planet:
            hard.append(m.group(0))
    return hard, soft


def word_count(text: str) -> int:
    return len(WORD.findall(text))


def is_english(text: str) -> bool:
    try:
        return detect(text) == "en"
    except LangDetectException:
        return False


def minhash(text: str) -> MinHash:
    words = WORD.findall(text.lower())
    m = MinHash(num_perm=128, seed=1)
    for i in range(max(len(words) - 4, 1)):
        m.update(" ".join(words[i : i + 5]).encode())
    return m


def check(row: dict, chart: dict | None) -> tuple[str | None, list[str]]:
    """Return (drop reason or None, warnings)."""
    answer = row["messages"][2]["content"]
    fc = row.get("factcheck")
    if fc is None:
        return "no fact check", []
    if fc.get("verdict") != "pass":
        return "fact check failed", []
    if citation_issue(answer):
        return "citation or source mention", []
    warnings: list[str] = []
    if chart is not None:
        hard, soft = chart_contradictions(answer, chart)
        warnings = soft
        if hard or len(soft) >= 2:
            return "chart contradiction", warnings
    lo, hi = LENGTH.get(row["task"], DEFAULT_LENGTH)
    if not lo <= word_count(answer) <= hi:
        return "length out of range", warnings
    if not is_english(answer):
        return "not English", warnings
    return None, warnings


def earlier_chart_errors() -> dict[str, list[str]]:
    """Chart errors found by earlier fact-check runs (archived as results/factcheck_*.jsonl), keyed by example id.

    Chart contradictions are objective, so an error found by ANY check drops the example, even when a later
    check with more lenient interpretation rules passed it.
    """
    out: dict[str, list[str]] = {}
    for path in sorted((SFT / "results").glob("factcheck_*.jsonl")):
        for r in read_jsonl(path):
            if r.get("type") != "succeeded":
                continue
            try:
                errs = json.loads(r["text"]).get("chart_errors") or []
            except (json.JSONDecodeError, AttributeError):
                continue
            if errs:
                out.setdefault(r["custom_id"][2:], []).extend(errs)  # "f-<id>" -> "<id>"
    return out


def main() -> None:
    from src.chart.births import chart_for_seed   # lazy: the regexes above are imported on machines without pyswisseph (Kaggle)
    rows = list(read_jsonl(SFT / "generated.jsonl"))
    lsh = MinHashLSH(threshold=DUP_THRESHOLD, num_perm=128)
    kept, reasons, warned = [], Counter(), 0
    charts: dict[int, dict] = {}
    prior_chart_errors = earlier_chart_errors()
    for r in rows:
        chart = None
        if r.get("chart_seed") is not None:
            chart = charts.setdefault(r["chart_seed"], chart_for_seed(r["chart_seed"]))
        reason, warnings = check(r, chart)
        if reason is None and r["id"] in prior_chart_errors:
            reason = "chart error (earlier check)"
        if reason is None:
            mh = minhash(r["messages"][1]["content"][-600:] + " " + r["messages"][2]["content"])
            if lsh.query(mh):
                reason = "near duplicate"
            else:
                lsh.insert(r["id"], mh)
        if reason:
            reasons[reason] += 1
            continue
        warned += bool(warnings)
        kept.append({**r, "filter_warnings": warnings})
    write_jsonl(SFT / "filtered.jsonl", kept)

    from src.dataset.seeds import TASKS   # lazy: seeds pulls in the chart engine, which Kaggle kernels do not have
    before, after = Counter(r["task"] for r in rows), Counter(r["task"] for r in kept)
    total = max(len(kept), 1)
    lines = ["# Filter report", "", f"Input: {len(rows)} examples. Kept: {len(kept)} "
             f"({len(kept) / max(len(rows), 1):.1%}). Kept with soft chart warnings: {warned}.", "",
             "| Drop reason | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in reasons.most_common()]
    lines += ["", "| Task | Generated | Kept | Kept share | Target share | Within ±3%? |", "|---|---|---|---|---|---|"]
    for t, (share, _) in TASKS.items():
        s = after[t] / total
        lines.append(f"| {t} | {before[t]} | {after[t]} | {s:.1%} | {share:.0%} | {'yes' if abs(s - share) <= 0.03 else 'NO'} |")
    (RUNS / "filter_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"kept {len(kept)}/{len(rows)} -> {SFT / 'filtered.jsonl'}; report -> {RUNS / 'filter_report.md'}")


if __name__ == "__main__":
    main()
