"""Claude Opus 5.5 teacher via the Message Batches API (Tech Spec 5.4.5).

Batches are 50% cheaper and asynchronous. Results arrive in any order, so everything is keyed by
custom_id. Refusal fallbacks are not available on the Batches API: a refused request is recorded
with type "refusal" and skipped.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import anthropic

from src.common import SFT, read_jsonl

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
BATCH_LIMIT = 5000  # requests per batch we submit (API limit is 100,000 / 256 MB)
POLL_SECONDS = 60
# USD per million tokens with the 50% batch discount (list: $4 in / $20 out, cache read $0.20)
PRICE = {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10}

BATCHES_LOG = SFT / "batches.jsonl"
RESULTS_DIR = SFT / "results"
REQUESTS_DIR = SFT / "requests"


def make_request(custom_id: str, system: str, user: str, effort: str, schema: dict | None = None) -> dict:
    output_config: dict = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    return {
        "custom_id": custom_id,
        "params": {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            # stable text first, cached; the variable passage/question goes in the user turn
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        },
    }


def _append(path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def batches(stage: str) -> list[dict]:
    if not BATCHES_LOG.exists():
        return []
    rows: dict[str, dict] = {}
    for r in read_jsonl(BATCHES_LOG):
        if r["stage"] == stage:
            rows[r["batch_id"]] = {**rows.get(r["batch_id"], {}), **r}
    return list(rows.values())


def in_flight_ids(stage: str) -> set[str]:
    ids: set[str] = set()
    for b in batches(stage):
        if not b.get("collected"):
            ids.update(b["custom_ids"])
    return ids


def submit(stage: str, requests: list[dict], dry_run: bool = False) -> None:
    if not requests:
        print(f"[{stage}] nothing to submit")
        return
    if dry_run:
        path = REQUESTS_DIR / f"{stage}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in requests:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[{stage}] dry run: wrote {len(requests)} requests to {path} (nothing sent)")
        return
    client = anthropic.Anthropic()
    for i in range(0, len(requests), BATCH_LIMIT):
        part = requests[i : i + BATCH_LIMIT]
        batch = client.messages.batches.create(requests=part)
        _append(BATCHES_LOG, {"stage": stage, "batch_id": batch.id, "n": len(part),
                              "custom_ids": [r["custom_id"] for r in part],
                              "created": datetime.now(timezone.utc).isoformat(), "collected": False})
        print(f"[{stage}] submitted batch {batch.id} with {len(part)} requests")


def collect(stage: str, wait: bool = True) -> None:
    pending = [b for b in batches(stage) if not b.get("collected")]
    if not pending:
        print(f"[{stage}] no batches waiting")
        return
    client = anthropic.Anthropic()
    for b in pending:
        while True:
            batch = client.messages.batches.retrieve(b["batch_id"])
            if batch.processing_status == "ended":
                break
            c = batch.request_counts
            print(f"[{stage}] {b['batch_id']}: {batch.processing_status} "
                  f"(processing {c.processing}, succeeded {c.succeeded}, errored {c.errored})", flush=True)
            if not wait:
                return
            time.sleep(POLL_SECONDS)
        n = {"succeeded": 0, "refusal": 0, "errored": 0, "canceled": 0, "expired": 0}
        for res in client.messages.batches.results(b["batch_id"]):
            row = {"custom_id": res.custom_id, "type": res.result.type}
            if res.result.type == "succeeded":
                msg = res.result.message
                u = msg.usage
                row.update({
                    "stop_reason": msg.stop_reason,
                    "text": "".join(blk.text for blk in msg.content if blk.type == "text"),
                    "usage": {"input": u.input_tokens, "output": u.output_tokens,
                              "cache_write": u.cache_creation_input_tokens or 0,
                              "cache_read": u.cache_read_input_tokens or 0},
                })
                if msg.stop_reason == "refusal":
                    row["type"] = "refusal"
                    details = getattr(msg, "stop_details", None)
                    row["refusal_category"] = getattr(details, "category", None) if details else None
                elif msg.stop_reason == "max_tokens":
                    row["type"] = "errored"
                    row["error"] = "max_tokens reached"
            elif res.result.type == "errored":
                row["error"] = str(res.result.error)
            n[row["type"]] = n.get(row["type"], 0) + 1
            _append(RESULTS_DIR / f"{stage}.jsonl", row)
        _append(BATCHES_LOG, {"stage": stage, "batch_id": b["batch_id"], "collected": True})
        print(f"[{stage}] collected {b['batch_id']}: {n}")


def results(stage: str) -> dict[str, dict]:
    """Latest successful result per custom_id."""
    path = RESULTS_DIR / f"{stage}.jsonl"
    out: dict[str, dict] = {}
    if path.exists():
        for r in read_jsonl(path):
            if r["type"] == "succeeded":
                out[r["custom_id"]] = r
    return out


def failed_ids(stage: str) -> set[str]:
    """custom_ids whose latest attempt failed (refusal, error, expiry); successes override failures."""
    path = RESULTS_DIR / f"{stage}.jsonl"
    latest: dict[str, str] = {}
    if path.exists():
        for r in read_jsonl(path):
            latest[r["custom_id"]] = r["type"]
    return {k for k, v in latest.items() if v != "succeeded"}


def cost_summary() -> str:
    lines = ["| Stage | Requests | Input | Output | Cache write | Cache read | Cost (USD, batch) |", "|---|---|---|---|---|---|---|"]
    total = 0.0
    for path in sorted(RESULTS_DIR.glob("*.jsonl")) if RESULTS_DIR.exists() else []:
        tok = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        n = 0
        for r in read_jsonl(path):
            if "usage" in r:
                n += 1
                for k in tok:
                    tok[k] += r["usage"][k]
        cost = sum(tok[k] * PRICE[k] for k in tok) / 1e6
        total += cost
        lines.append(f"| {path.stem} | {n} | {tok['input']:,} | {tok['output']:,} | {tok['cache_write']:,} | "
                     f"{tok['cache_read']:,} | ${cost:,.2f} |")
    lines.append(f"| **Total** | | | | | | **${total:,.2f}** |")
    return "\n".join(lines)
