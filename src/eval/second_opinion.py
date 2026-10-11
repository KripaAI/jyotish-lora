"""Second-opinion judging: order-swapped pairwise judging and a second judge (Gemini) on the same answers.

    python -m src.eval.second_opinion judge --judge claude --kinds pairswap
    python -m src.eval.second_opinion judge --judge gemini --kinds rubric safety pair pairswap quiz
    python -m src.eval.second_opinion report        # -> runs/<run>/second_opinion_report.md

Uses exactly the prompts, schemas and answer texts of src/eval/judge.py. "pairswap|<id>" is the pairwise job with the two answers
in the opposite order from the original "pair|<id>". Claude judgments go to judgments.jsonl (alongside the originals), Gemini ones
to judgments_gemini.jsonl. Resumable: finished keys are skipped.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.common import RUNS, read_jsonl
from src.dataset import backends
from src.eval import judge as J

CRIT = J.CRITERIA


def setup(run: str, test_file: str):
    J.RUN, J.EVAL_DIR = run, RUNS / run / "eval"
    J.OUTPUTS, J.TEST_FILE = J.EVAL_DIR / "eval_outputs.jsonl", Path(test_file)


def files(run):
    d = RUNS / run / "eval"
    return {"claude": d / "judgments.jsonl", "gemini": d / "judgments_gemini.jsonl"}


def all_jobs() -> list[dict]:
    outputs, _, test, quiz, safety = J.load_inputs()
    jobs = J.build_jobs(outputs, test, quiz, safety)
    for j in [j for j in jobs if j["kind"] == "pair"]:
        head, rest = j["user"].split("\n\nANSWER A:\n", 1)
        a_txt, b_txt = rest.split("\n\nANSWER B:\n", 1)
        jobs.append({"key": j["key"].replace("pair|", "pairswap|"), "kind": "pair", "effort": j["effort"],
                     "adapter_is": "B" if j["adapter_is"] == "A" else "A",
                     "user": f"{head}\n\nANSWER A:\n{b_txt}\n\nANSWER B:\n{a_txt}"})
    return jobs


def schema_for(kind: str, backend: str) -> dict:
    s = J.SCHEMAS[kind]
    if backend == "gemini" and kind == "rubric":   # the Gemini CLI turns integer enums into empty strings and rejects them
        s = json.loads(json.dumps(s))
        for c in CRIT:
            s["properties"][c] = {"type": "integer", "description": "integer score from 1 to 5"}
    return s


def run_job(job: dict, backend: str) -> dict:
    req = {"custom_id": f"judge2-{backend}-{job['key'].replace('|', '_')}",
           "params": {"system": [{"text": J.SYSTEMS[job["kind"]]}], "messages": [{"content": job["user"]}],
                      "output_config": {"effort": job["effort"], "format": {"schema": schema_for(job["kind"], backend)}}}}
    res = backends.call_with_wait(backend, req, J.JUDGE_MODEL if backend == "claude" else None)
    if res["type"] != "succeeded":
        return {"key": job["key"], "error": str(res.get("error", res["type"]))[:300]}
    out = {"key": job["key"], "judge": res.get("model"), **json.loads(res["text"])}
    if job["kind"] == "rubric" and not all(isinstance(out.get(c), int) and 1 <= out[c] <= 5 for c in CRIT):
        return {"key": job["key"], "error": "rubric score missing or outside 1-5: " + res["text"][:200]}
    if "adapter_is" in job:
        out["adapter_is"] = job["adapter_is"]
    return out


def do_judge(run: str, backend: str, kinds: list[str], workers: int) -> None:
    out = files(run)[backend]
    done = {r["key"] for r in read_jsonl(out) if "error" not in r} if out.exists() else set()
    order = {k: i for i, k in enumerate(kinds)}
    jobs = [j for j in all_jobs() if j["key"].split("|")[0] in order and j["key"] not in done]
    jobs.sort(key=lambda j: order[j["key"].split("|")[0]])
    print(f"{len(jobs)} {backend} judgments to make ({len(done)} done) for {run}: {dict(Counter(j['key'].split('|')[0] for j in jobs))}", flush=True)
    c: Counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_job, j, backend): j["key"] for j in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                res = {"key": futs[fut], "error": str(e)[:300]}
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
            c["error" if "error" in res else res["key"].split("|")[0]] += 1
            if n % 20 == 0 or n == len(jobs):
                print(f"{n}/{len(jobs)} {dict(c)}", flush=True)


# ---------------- report ----------------
def load(path):
    return {r["key"]: r for r in read_jsonl(path) if "error" not in r} if path.exists() else {}


def kappa(a: list, b: list) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    labels = set(a) | set(b)
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def spearman(x, y):
    def ranks(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            for k in range(i, j + 1):
                r[s[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def boot(d, B=10000, seed=0):
    rng = random.Random(seed)
    bs = sorted(st.mean(rng.choices(d, k=len(d))) for _ in range(B))
    return st.mean(d), bs[int(0.025 * B)], bs[int(0.975 * B)]


def outcome(r):
    """+1 adapter wins, -1 base wins, 0 tie."""
    return 0 if r["winner"] == "tie" else (1 if r["winner"] == r["adapter_is"] else -1)


def pair_section(name, JJ):
    ids = sorted({k.split("|")[1] for k in JJ if k.startswith("pair|")} & {k.split("|")[1] for k in JJ if k.startswith("pairswap|")})
    if not ids:
        return [f"- {name}: no order-swapped pairs judged yet."]
    o1 = [outcome(JJ[f"pair|{i}"]) for i in ids]
    o2 = [outcome(JJ[f"pairswap|{i}"]) for i in ids]
    same = sum(a == b for a, b in zip(o1, o2))
    first_pos = sum((JJ[f"pair|{i}"]["winner"] == "A") + (JJ[f"pairswap|{i}"]["winner"] == "A") for i in ids)
    decided = sum((JJ[f"pair|{i}"]["winner"] != "tie") + (JJ[f"pairswap|{i}"]["winner"] != "tie") for i in ids)
    comb = [a + b for a, b in zip(o1, o2)]          # -2..+2
    w, l = sum(c > 0 for c in comb), sum(c < 0 for c in comb)
    t = len(comb) - w - l
    m, lo, hi = boot([c / 2 for c in comb])
    return [f"- {name}, n={len(ids)} pairs judged in both orders: same verdict in both orders {same}/{len(ids)} ({100 * same / len(ids):.0f}%); "
            f"answer shown first won {first_pos}/{decided} decided judgments.",
            f"  Original order only: adapter won {sum(x > 0 for x in o1)}, lost {sum(x < 0 for x in o1)}, tied {o1.count(0)}. "
            f"Swapped only: won {sum(x > 0 for x in o2)}, lost {sum(x < 0 for x in o2)}, tied {o2.count(0)}.",
            f"  Both orders combined (sum of the two verdicts): adapter ahead {w}, behind {l}, level {t}; "
            f"mean preference {m:+.2f} on a -1..+1 scale, 95% interval {lo:+.2f} to {hi:+.2f}."]


def report(run: str) -> None:
    C, G = load(files(run)["claude"]), load(files(run)["gemini"])
    L = [f"# Second-opinion judging: {run}", "",
         f"Judges: Claude ({J.JUDGE_MODEL}, original) and Gemini ({backends.GEMINI_MODEL}), same prompts, rubric and answers.", "",
         "## Position bias: pairwise judged in both answer orders (adapter vs base)", ""]
    L += pair_section("Claude", C) + pair_section("Gemini", G)
    L += ["", "## Agreement between the two judges", "", "| Measure | n | Claude | Gemini | Agreement |", "|---|---|---|---|---|"]
    for kind, field in (("quiz", "correct"), ("safety", "pass")):
        for model in ("adapter", "base"):
            keys = sorted(k for k in C if k.startswith(kind + "|") and k.endswith("|" + model) and k in G)
            if not keys:
                continue
            a, b = [bool(C[k][field]) for k in keys], [bool(G[k][field]) for k in keys]
            L.append(f"| {kind} pass, {model} | {len(keys)} | {sum(a)} | {sum(b)} | {100 * sum(x == y for x, y in zip(a, b)) / len(keys):.0f}% same, kappa {kappa(a, b):.2f} |")
    for model in ("adapter", "base"):
        keys = sorted(k for k in C if k.startswith("rubric|") and k.endswith("|" + model) and k in G)
        if not keys:
            continue
        a = [st.mean(C[k][c] for c in CRIT) for k in keys]
        b = [st.mean(G[k][c] for c in CRIT) for k in keys]
        L.append(f"| rubric mean, {model} | {len(keys)} | {st.mean(a):.2f} | {st.mean(b):.2f} | Spearman {spearman(a, b):.2f} |")
    L += ["", "## Do the headline conclusions hold under each judge? (adapter minus base, paired)", "",
          "| Judge | Metric | n | Difference | 95% interval |", "|---|---|---|---|---|"]
    for jname, JJ in (("Claude", C), ("Gemini", G)):
        for kind in ("rubric", "quiz", "safety"):
            ids = sorted({k.split("|")[1] for k in JJ if k.startswith(kind + "|") and k.endswith("|adapter")}
                         & {k.split("|")[1] for k in JJ if k.startswith(kind + "|") and k.endswith("|base")})
            if not ids:
                continue
            if kind == "rubric":
                d = [st.mean(JJ[f"rubric|{i}|adapter"][c] for c in CRIT) - st.mean(JJ[f"rubric|{i}|base"][c] for c in CRIT) for i in ids]
                m, lo, hi = boot(d)
                L.append(f"| {jname} | rubric mean (1-5) | {len(ids)} | {m:+.2f} | {lo:+.2f} to {hi:+.2f} |")
            else:
                f = "correct" if kind == "quiz" else "pass"
                d = [float(bool(JJ[f"{kind}|{i}|adapter"][f])) - float(bool(JJ[f"{kind}|{i}|base"][f])) for i in ids]
                m, lo, hi = boot(d)
                L.append(f"| {jname} | {kind} | {len(ids)} | {100 * m:+.1f} pp | {100 * lo:+.1f} to {100 * hi:+.1f} pp |")
    out = RUNS / run / "second_opinion_report.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["judge", "report"])
    ap.add_argument("--run", default="v2-8b")
    ap.add_argument("--test-file", default="data/sft_v2/test.jsonl")
    ap.add_argument("--judge", choices=["claude", "gemini"], default="claude")
    ap.add_argument("--kinds", nargs="+", default=["pairswap"])
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    setup(a.run, a.test_file)
    if a.cmd == "judge":
        do_judge(a.run, a.judge, a.kinds, a.workers)
    report(a.run)


if __name__ == "__main__":
    main()
