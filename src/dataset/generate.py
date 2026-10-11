"""Phase 3.4-3.6: generate the dataset with the teacher LLMs in three stages.

    questions -> answers -> factcheck -> assemble

Subscription mode (no API key; default split: Claude Sonnet 5.5 writes questions, Claude Opus 5.5 writes answers, Gemini fact-checks).
Each run only does what is still missing, so stopping (Ctrl+C) and re-running is safe:
    python -m src.dataset.generate run questions --limit 40       # pilot: 40 seeds ~ 100 examples
    python -m src.dataset.generate run answers
    python -m src.dataset.generate run factcheck
    python -m src.dataset.generate run answers --backend gemini   # override the back-end for a stage
    python -m src.dataset.generate run answers --retry            # redo requests that failed

API mode (Message Batches; needs ANTHROPIC_API_KEY). Each submit only sends what is still missing:
    python -m src.dataset.generate submit questions --limit 40 [--dry-run]   # pilot: 40 seeds ~ 100 examples
    python -m src.dataset.generate collect questions
    python -m src.dataset.generate submit answers
    python -m src.dataset.generate collect answers
    python -m src.dataset.generate submit factcheck
    python -m src.dataset.generate collect factcheck
    python -m src.dataset.generate assemble        # -> data/sft/generated.jsonl
    python -m src.dataset.generate status          # batches, progress and cost so far
    python -m src.dataset.generate retry <stage>   # resubmit refused/errored/expired requests once
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from src.common import CHUNKS, PROMPTS, SFT, read_jsonl, write_jsonl
from src.dataset import teacher

STAGES = ("questions", "answers", "factcheck")
# Questions moved to Claude Sonnet 5.5 after Gemini's quota ran out early in round 1 (option A).
# Fact check moved from Gemini to Claude Sonnet 5.5 as well (Gemini quota too small); still a different model from the Opus 5.5 writer.
DEFAULT_BACKEND = {"questions": "claude", "answers": "claude", "factcheck": "claude"}
DEFAULT_MODEL = {"questions": "claude-sonnet-5-5", "factcheck": "claude-sonnet-5-5"}  # answers: Opus 5.5 (back-end default)
HIGH_EFFORT_TASKS = {"full_chart", "comparison", "remedies"}

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "properties": {"question": {"type": "string"}},
        "required": ["question"], "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False,
}
FACTCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "chart_errors": {"type": "array", "items": {"type": "string"}},
        "citation_issue": {"type": "boolean"},
        "safety_issue": {"type": "boolean"},
        "answers_question": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reason": {"type": "string"},
    },
    "required": ["unsupported_claims", "chart_errors", "citation_issue", "safety_issue",
                 "answers_question", "verdict", "reason"],
    "additionalProperties": False,
}


def _prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8").strip()


def system_prompt_v1() -> str:
    return _prompt("system_v1.txt")


def task_guide(task: str) -> str:
    return _prompt(f"teacher/tasks/{task}.txt")


def load_seeds() -> list[dict]:
    return list(read_jsonl(SFT / "seeds.jsonl"))


def load_chunks(ids: set[str]) -> dict[str, dict]:
    return {c["chunk_id"]: c for c in read_jsonl(CHUNKS / "chunks.jsonl") if c["chunk_id"] in ids}


def passages_block(seed: dict, chunks: dict[str, dict]) -> str:
    out = []
    for cid in seed["chunk_ids"]:
        c = chunks[cid]
        chapter = f' chapter="{c["chapter"]}"' if c["chapter"] else ""
        out.append(f'<source_passage book="{c["title"]}" tradition="{c["tradition"]}"{chapter}>\n'
                   f'{c["text"]}\n</source_passage>')
    return "\n\n".join(out)


def student_message(seed: dict, question: str) -> str:
    """The user turn exactly as the fine-tuned model sees it (training and serving)."""
    if seed.get("chart_text"):
        return f"Chart:\n{seed['chart_text']}\n\nQuestion: {question}"
    return question


def select(seeds: list[dict], limit: int | None) -> list[dict]:
    """Stratified subset: each task gets a share of `limit` proportional to its seed count."""
    if not limit:
        return seeds
    by_task = defaultdict(list)
    for s in seeds:
        by_task[s["task"]].append(s)
    quota = {t: max(1, round(limit * len(v) / len(seeds))) for t, v in by_task.items()}
    return [s for t, v in by_task.items() for s in v[: quota[t]]]


def questions_for(seed: dict, q_results: dict) -> list[str]:
    r = q_results.get(f"q-{seed['seed_id']}")
    if not r:
        return []
    try:
        qs = [q["question"].strip() for q in json.loads(r["text"])["questions"] if q["question"].strip()]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
    return qs[: seed["n_questions"]]


# ---------- request builders ----------

def build_questions(seeds, chunks) -> list[dict]:
    system = _prompt("teacher/questions.txt")
    reqs = []
    for s in seeds:
        user = [passages_block(s, chunks), f"<task>{s['task']}</task>"]
        if s.get("chart_text"):
            user.append(f"<chart>\n{s['chart_text']}\n</chart>")
        user.append(f"Write {s['n_questions']} user messages for this task.")
        reqs.append(teacher.make_request(f"q-{s['seed_id']}", f"{system}\n\n{task_guide(s['task'])}",
                                         "\n\n".join(user), "medium", QUESTION_SCHEMA))
    return reqs


def build_answers(seeds, chunks, q_results) -> list[dict]:
    base = _prompt("teacher/answer.txt").replace("{STUDENT_SYSTEM_PROMPT}", system_prompt_v1())
    reqs = []
    for s in seeds:
        for i, q in enumerate(questions_for(s, q_results)):
            user = "\n\n".join([passages_block(s, chunks), f"<task>{s['task']}</task>",
                                f"<student_message>\n{student_message(s, q)}\n</student_message>",
                                "Write the assistant's reply to the student message."])
            effort = "high" if s["task"] in HIGH_EFFORT_TASKS else "medium"
            reqs.append(teacher.make_request(f"a-{s['seed_id']}-{i}", f"{base}\n\n{task_guide(s['task'])}", user, effort))
    return reqs


def build_factchecks(seeds, chunks, q_results, a_results) -> list[dict]:
    system = _prompt("teacher/factcheck.txt")
    reqs = []
    for s in seeds:
        for i, q in enumerate(questions_for(s, q_results)):
            a = a_results.get(f"a-{s['seed_id']}-{i}")
            if not a:
                continue
            user = "\n\n".join([passages_block(s, chunks),
                                f"<student_message>\n{student_message(s, q)}\n</student_message>",
                                f"<reply>\n{a['text']}\n</reply>"])
            reqs.append(teacher.make_request(f"f-{s['seed_id']}-{i}", system, user, "medium", FACTCHECK_SCHEMA))
    return reqs


def build(stage: str, seeds: list[dict]) -> list[dict]:
    chunks = load_chunks({cid for s in seeds for cid in s["chunk_ids"]})
    q = teacher.results("questions")
    if stage == "questions":
        return build_questions(seeds, chunks)
    if stage == "answers":
        return build_answers(seeds, chunks, q)
    return build_factchecks(seeds, chunks, q, teacher.results("answers"))


def pending(stage: str, reqs: list[dict], include_failed: bool = False) -> list[dict]:
    done = set(teacher.results(stage)) | teacher.in_flight_ids(stage)
    if not include_failed:
        done |= teacher.failed_ids(stage)
    return [r for r in reqs if r["custom_id"] not in done]


# ---------- assemble ----------

def assemble() -> None:
    seeds = {s["seed_id"]: s for s in load_seeds()}
    q, a, f = (teacher.results(st) for st in STAGES)
    system = system_prompt_v1()
    rows, missing_fc = [], 0
    for seed_id, s in seeds.items():
        for i, question in enumerate(questions_for(s, q)):
            ans = a.get(f"a-{seed_id}-{i}")
            if not ans:
                continue
            fc = f.get(f"f-{seed_id}-{i}")
            try:
                fc_json = json.loads(fc["text"]) if fc else None
            except json.JSONDecodeError:
                fc_json = None
            missing_fc += fc_json is None
            rows.append({
                "id": f"{seed_id}-{i}", "seed_id": seed_id, "task": s["task"], "source_chunks": s["chunk_ids"],
                "chart_seed": s.get("chart_seed"),
                "teachers": {"questions": q[f"q-{seed_id}"].get("model", teacher.MODEL),
                             "answers": ans.get("model", teacher.MODEL),
                             "factcheck": fc.get("model", teacher.MODEL) if fc else None},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": student_message(s, question)},
                             {"role": "assistant", "content": ans["text"].strip()}],
                "factcheck": fc_json,
            })
    n = write_jsonl(SFT / "generated.jsonl", rows)
    print(f"assembled {n} examples -> {SFT / 'generated.jsonl'} ({missing_fc} without a fact check yet)")
    print(Counter(r["task"] for r in rows))


def status() -> None:
    seeds = load_seeds()
    q, a, f = (teacher.results(st) for st in STAGES)
    n_q = sum(len(questions_for(s, q)) for s in seeds)
    print(f"seeds: {len(seeds)}; with questions: {sum(bool(questions_for(s, q)) for s in seeds)} ({n_q} questions)")
    print(f"answers: {len(a)}; fact checks: {len(f)}; passed: "
          f"{sum(json.loads(r['text']).get('verdict') == 'pass' for r in f.values())}")
    for st in STAGES:
        bs = teacher.batches(st)
        print(f"[{st}] batches: {len(bs)} ({sum(not b.get('collected') for b in bs)} waiting); "
              f"failed requests: {len(teacher.failed_ids(st))}")
    print(teacher.cost_summary())


def _valid(stage: str, text: str) -> bool:
    """Reject empty or malformed teacher output so it is retried instead of silently kept."""
    try:
        if stage == "questions":
            return any(q["question"].strip() for q in json.loads(text)["questions"])
        if stage == "factcheck":
            return json.loads(text).get("verdict") in ("pass", "fail")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return False
    return len(text.split()) >= 30


def run(stage: str, reqs: list[dict], backend: str, workers: int, model: str | None = None, reverse: bool = False) -> None:
    """Subscription mode: call the CLI back-end for each request; results are appended as they finish."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from src.dataset import backends

    if not reqs:
        print(f"[{stage}] nothing to do")
        return
    if reverse:
        reqs = reqs[::-1]  # lets a second runner (e.g. Gemini) start from the other end without overlapping
    print(f"[{stage}] {len(reqs)} requests via {backend} ({model or 'default model'}) with {workers} worker(s)", flush=True)
    counts: Counter = Counter()

    def work(r: dict) -> dict:
        # another runner may have finished this request since our list was built
        if r["custom_id"] in teacher.results(stage):
            return {"custom_id": r["custom_id"], "type": "skipped"}
        return backends.call_with_wait(backend, r, model)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, r): r["custom_id"] for r in reqs}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                row = fut.result()
            except Exception as e:  # keep going; the request can be retried later
                row = {"custom_id": futs[fut], "backend": backend, "type": "errored", "error": str(e)[:300]}
            if row["type"] == "succeeded" and not _valid(stage, row["text"]):
                row = {**row, "type": "errored", "error": f"invalid {stage} output"}
            if row["type"] != "skipped":
                teacher._append(teacher.RESULTS_DIR / f"{stage}.jsonl", row)  # one append per row
            counts[row["type"]] += 1
            if n % 5 == 0 or n == len(reqs):
                print(f"[{stage}] {n}/{len(reqs)} done {dict(counts)}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "submit", "collect", "retry", "assemble", "status"])
    ap.add_argument("stage", nargs="?", choices=STAGES)
    ap.add_argument("--limit", type=int, help="number of seeds (stratified by task); 40 seeds ~ 100 examples")
    ap.add_argument("--dry-run", action="store_true", help="write the requests to data/sft/requests/ without calling the API")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--backend", choices=["claude", "gemini"], help="run: override the default back-end for this stage")
    ap.add_argument("--model", help="run: override the model (e.g. claude-opus-5-5, claude-sonnet-5-5, gemini-3.1-pro-high)")
    ap.add_argument("--workers", type=int, default=2, help="run: parallel requests (keep low to respect usage limits)")
    ap.add_argument("--retry", action="store_true", help="run: only redo requests whose last attempt failed")
    ap.add_argument("--reverse", action="store_true", help="run: process requests from the end of the list (for a second, parallel runner)")
    args = ap.parse_args()

    if args.command == "assemble":
        return assemble()
    if args.command == "status":
        return status()
    if not args.stage:
        ap.error("stage is required")
    if args.command == "collect":
        return teacher.collect(args.stage, wait=not args.no_wait)
    seeds = select(load_seeds(), args.limit)
    retry = args.command == "retry" or args.retry
    reqs = pending(args.stage, build(args.stage, seeds), include_failed=retry)
    if retry:
        failed = teacher.failed_ids(args.stage)
        reqs = [r for r in reqs if r["custom_id"] in failed]
    if args.command == "run":
        backend = args.backend or DEFAULT_BACKEND[args.stage]
        model = args.model or (DEFAULT_MODEL.get(args.stage) if not args.backend else None)
        return run(args.stage, reqs, backend, args.workers, model, args.reverse)
    if args.command == "retry":
        failed = teacher.failed_ids(args.stage)
        reqs = [r for r in reqs if r["custom_id"] in failed]
    teacher.submit(args.stage, reqs, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
