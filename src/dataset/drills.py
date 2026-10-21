"""v4: chart copying drills and engine-grounded rule-application rows, correct by construction.

The v3 evaluation showed the model mis-copying facts that were printed in the chart text (2 of 5 "Nth from the Moon" claims
wrong although the text listed the right sign). These rows train the one skill that no teacher can get wrong: read a
fact out of the chart block and state it. Every answer is composed by code from the chart dict, with the v3 chart text
(derived=True) in the user turn, exactly as Pipeline(render_version=3) serves it.

Two kinds of row per chart:
- drills: one factual question each (house from the Moon, lord placement, occupants, aspects on a house, dignity flags,
  current dasha, navamsa position, lagna lord) with a short answer that quotes the chart.
- yoga rows: "My chart shows X, what forms it here?" answered from the engine's detail plus the common definition.

Seeds start at DRILL_SEED_BASE so they never collide with the seeds used for the v1-v3 teacher examples.

    python -m src.dataset.drills --charts 400        # -> data/sft_v4/drills.jsonl
"""
from __future__ import annotations

import argparse
import random
from collections import Counter

from src.chart.births import chart_for_seed
from src.chart.constants import ordinal
from src.chart.render import houses_from, navamsa_house, render_chart_text
from src.common import DATA, PROMPTS, SFT, read_jsonl, write_jsonl
from src.dataset.facts import YOGAS, P, join

OUT = DATA / "sft_v4" / "drills.jsonl"
DRILL_SEED_BASE = 1_000_000
SEP = "\n\nQuestion: "
YOGA_DEF = {n.split(" (")[0].lower(): c for n, c in YOGAS}
TENDENCY = "What this means for you depends on the whole chart; it describes a tendency, not a certainty."


def _by(chart: dict):
    return {p["name"]: p for p in chart["planets"]}, {h["house"]: h for h in chart["houses"]}


def _flags(p: dict) -> str:
    out = []
    if p["dignity"] != "-":
        out.append(p["dignity"])
    if p["retrograde"] and p["name"] not in ("Rahu", "Ketu"):
        out.append("retrograde")
    if p["combust"]:
        out.append("combust")
    return out and f" ({', '.join(out)})" or ""


def drills_for(chart: dict, rng: random.Random, n: int) -> list[tuple[str, str, str]]:
    """(kind, question, answer) for one chart; n questions sampled from the templates below."""
    by_name, by_house = _by(chart)
    lg = chart["lagna"]
    moon_rows = houses_from(chart, "Moon")
    moon_sign = moon_rows[0]["sign"]
    cands: list[tuple[str, str, str]] = []

    for p in rng.sample([x for x in by_name if x != "Moon"], 3):
        row = next(r for r in moon_rows if p in r["occupants"])
        others = [o for o in row["occupants"] if o != p]
        cands.append(("from_moon", rng.choice([f"Which house from the Moon is {p} in?", f"Counted from my Moon, where does {p} fall?",
                                                f"{p} is in which bhava from Chandra lagna?"]),
                      f"Your Moon is in {moon_sign}, so counting from the Moon, {p} in {by_name[p]['sign']} is in the "
                      f"{ordinal(row['house'])} house from the Moon" + (f", together with {join(others)}" if others else "")
                      + f". From the lagna it is in the {ordinal(by_name[p]['house'])} house."))
    for h in rng.sample(range(1, 13), 3):
        hh = by_house[h]
        occ = join(hh["occupants"]) if hh["occupants"] else "no planet"
        cands.append(("lord_placement", rng.choice([f"Who is my {ordinal(h)} lord and where is it placed?",
                                                     f"Where does the lord of my {ordinal(h)} house sit?",
                                                     f"Mere {ordinal(h)} bhav ka swami kahan baitha hai?"]),
                      f"Your {ordinal(h)} house is {hh['sign']}, so its lord is {P(hh['lord'])}. {P(hh['lord'], True)} is placed in "
                      f"{by_name[hh['lord']]['sign']} in your {ordinal(hh['lord_in_house'])} house{_flags(by_name[hh['lord']])}. "
                      f"The {ordinal(h)} house itself holds {occ}."))
        cands.append(("occupants", rng.choice([f"Which planets are in my {ordinal(h)} house?", f"Is my {ordinal(h)} house occupied?",
                                                f"What sits in the {ordinal(h)} bhava of my chart?"]),
                      (f"Your {ordinal(h)} house ({hh['sign']}) holds {occ}." if hh["occupants"] else
                       f"Your {ordinal(h)} house ({hh['sign']}) is empty; its lord {P(hh['lord'])} is in the {ordinal(hh['lord_in_house'])} house, "
                       f"and an empty house is judged through its lord and the aspects on it.")
                      + (f" It is aspected by {join(hh['aspected_by'])}." if hh["aspected_by"] else " No planet aspects it by graha drishti.")))
        cands.append(("aspects_on_house", rng.choice([f"Which planets aspect my {ordinal(h)} house?",
                                                       f"Is there any drishti on my {ordinal(h)} house?"]),
                      (f"By graha drishti, your {ordinal(h)} house ({hh['sign']}) is aspected by {join(hh['aspected_by'])}."
                       if hh["aspected_by"] else f"No planet casts a graha drishti on your {ordinal(h)} house ({hh['sign']}).")
                      + (f" It holds {occ}." if hh["occupants"] else "")))
    for p in rng.sample(list(by_name), 2):
        pp = by_name[p]
        state = pp["dignity"] if pp["dignity"] != "-" else "neither exalted, debilitated nor in its own sign"
        cands.append(("dignity", rng.choice([f"Is {p} strong by sign in my chart?", f"What is the dignity of my {p}?",
                                              f"Is my {p} exalted, debilitated or in its own sign?"]),
                      f"Your {p} is in {pp['sign']} at {pp['degree']:.2f}°, in the {ordinal(pp['house'])} house, in {pp['nakshatra']} "
                      f"(lord {pp['nakshatra_lord']}). By sign it is {state}"
                      + (", retrograde" if pp["retrograde"] and p not in ("Rahu", "Ketu") else "")
                      + (", and combust (close to the Sun)" if pp["combust"] else "") + f". {TENDENCY}"))
        cands.append(("navamsa", rng.choice([f"Where is {p} in my navamsa?", f"In the D9, which house does {p} occupy?"]),
                      f"In your navamsa (D9) the lagna is {chart['navamsa_lagna']}, and {p} is in {pp['navamsa_sign']}, the "
                      f"{ordinal(navamsa_house(chart, p))} house from the D9 lagna. In the Rasi chart it is in {pp['sign']}, the "
                      f"{ordinal(pp['house'])} house."))
    d = chart["dasha"]
    cands.append(("dasha", rng.choice(["Which dasha am I running now?", "What are my current mahadasha and antardasha?",
                                        "Meri abhi kaunsi dasha chal rahi hai?"]),
                  f"As of {d['as_of']}, you are in {d['maha']['lord']} mahadasha ({d['maha']['start']} to {d['maha']['end']}) with "
                  f"{d['antar']['lord']} antardasha ({d['antar']['start']} to {d['antar']['end']}). The next mahadasha is "
                  f"{d['next_mahas'][0]['lord']}, from {d['next_mahas'][0]['start']}."))
    ll = by_name[lg["lord"]]
    cands.append(("lagna_lord", rng.choice(["Where is my lagna lord?", "Which planet rules my ascendant and where is it?",
                                             "Mera lagnesh kahan baitha hai?"]),
                  f"Your lagna is {lg['sign']} ({lg['nakshatra']} pada {lg['pada']}), so the lagna lord is {P(lg['lord'])}. It is placed "
                  f"in {ll['sign']} in your {ordinal(ll['house'])} house{_flags(ll)}, in {ll['nakshatra']} nakshatra."))
    names = [y["name"] for y in chart["yogas"]]
    cands.append(("yoga_list", rng.choice(["Which yogas are present in my chart?", "Does my chart have any notable yogas?"]),
                  (f"The chart engine flags {join(names)}. " + " ".join(f"{y['name']}: {y['detail']}." for y in chart["yogas"][:4])
                   if names else "None of the tracked yogas is flagged in your chart. That is common and is not a weakness in itself; "
                                 "the houses, their lords and the dasha carry the reading.") + f" {TENDENCY}"))
    rng.shuffle(cands)
    out, kinds = [], Counter()
    for k, q, a in cands:
        if kinds[k] < 2 and len(out) < n:
            out.append((k, q, a))
            kinds[k] += 1
    return out


def yoga_rows(chart: dict, rng: random.Random) -> list[tuple[str, str, str]]:
    rows = []
    for y in chart["yogas"][:1]:
        base = y["name"].lower().replace(" yoga", "")
        definition = next((c for k, c in YOGA_DEF.items() if k.startswith(base.split()[0])), None)
        q = rng.choice([f"My chart shows {y['name']}. What forms it here?", f"The chart lists {y['name']}: which placements make it?"])
        a = f"In your chart {y['name']} is formed as follows: {y['detail']}."
        if definition:
            a += f" In its common definition, {y['name']} forms when {definition}."
        a += (" Whether it gives full results depends on the strength of the planets involved, aspects on them and the "
              "dasha periods that activate them. " + TENDENCY)
        rows.append(("yoga_detail", q, a))
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--charts", type=int, default=400)
    ap.add_argument("--per-chart", type=int, default=4)
    args = ap.parse_args(argv)
    system = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
    test_seeds = set()
    for name in ("test.jsonl",):
        for path in (DATA / "sft_v2" / name, SFT / name):
            if path.exists():
                test_seeds |= {r.get("chart_seed") for r in read_jsonl(path) if r.get("chart_seed") is not None}
    rows, kinds = [], Counter()
    for i in range(args.charts):
        seed = DRILL_SEED_BASE + i
        assert seed not in test_seeds
        chart = chart_for_seed(seed)
        text = render_chart_text(chart, derived=True)
        rng = random.Random(seed)
        for k, q, a in drills_for(chart, rng, args.per_chart) + yoga_rows(chart, rng):
            rows.append({"id": f"drill-{seed}-{len(rows):05d}", "task": "drill", "kind": k, "chart_seed": seed,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": f"Chart:\n{text}{SEP}{q}"},
                                      {"role": "assistant", "content": a}]})
            kinds[k] += 1
    write_jsonl(OUT, rows)
    print(f"wrote {len(rows)} drill rows from {args.charts} charts -> {OUT}")
    print(kinds)


if __name__ == "__main__":
    main()
