"""Subscription-based teacher back-ends (no API key): Claude Code and the Antigravity CLI.

Both are run as one-shot, non-interactive subprocesses from an empty scratch folder, so no project
context (CLAUDE.md, files) leaks into the prompt. Each call returns a result row in the same format
as the Batches API path in teacher.py, so the rest of the pipeline does not care which back-end ran.

    claude: `claude -p` on your Claude Pro login (Claude Opus 5.5 by default)
    gemini: `agy --print` on your Google login (Gemini 3.1 Pro by default)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_MODEL = "gemini-3.1-pro-high"
AGY_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
TIMEOUT_SECONDS = 900
LIMIT_WAIT_SECONDS = 15 * 60  # usage limit hit: wait, then try again
MAX_LIMIT_WAITS = 40          # give up after ~10 hours of waiting for one request
FLAKY_RETRIES = 2             # extra attempts when a run ends without an answer

# Conditions worth waiting out rather than recording as failures (includes a logged-out CLI, e.g. mid account switch)
_LIMIT = re.compile(r"usage limit|session limit|rate limit|quota|resource.?exhausted|\b429\b|too many requests|limit reached"
                    r"|overloaded|not logged in|please run /login", re.I)
WORKDIR = Path(tempfile.gettempdir()) / "jyotish_teacher"


_RESETS_IN = re.compile(r"resets? in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)


def wait_seconds(message: str) -> int:
    """Seconds to wait after a limit message: the reported reset time ("Resets in 3h10m0s") plus a margin,
    else the default. Capped so a wrong parse cannot park the run for too long."""
    m = _RESETS_IN.search(message)
    if m and any(m.groups()):
        h, mi, s = (int(x or 0) for x in m.groups())
        return min(max(h * 3600 + mi * 60 + s + 45, 60), 6 * 3600)
    return LIMIT_WAIT_SECONDS


class UsageLimit(Exception):
    """The subscription's usage limit was hit; the caller should wait and retry."""


def _row(custom_id: str, backend: str, model: str, **kw) -> dict:
    return {"custom_id": custom_id, "backend": backend, "model": model, **kw}


def _workdir(name: str) -> Path:
    d = WORKDIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def call_claude(custom_id: str, system: str, user: str, effort: str, schema: dict | None,
                model: str = CLAUDE_MODEL) -> dict:
    wd = _workdir("claude")
    sys_file = wd / f"system_{custom_id}.txt"  # one file per request: safe with parallel workers
    sys_file.write_text(system, encoding="utf-8")
    cmd = [shutil.which("claude") or "claude", "-p", "--output-format", "json", "--model", model,
           "--effort", effort, "--tools", "", "--system-prompt-file", str(sys_file),
           "--no-session-persistence", "--strict-mcp-config"]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}  # force the Pro login
    try:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                              cwd=wd, env=env, timeout=TIMEOUT_SECONDS)
    finally:
        sys_file.unlink(missing_ok=True)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        msg = (proc.stdout + proc.stderr)[-500:]
        if _LIMIT.search(msg):
            raise UsageLimit(msg)
        return _row(custom_id, "claude", model, type="errored", error=msg)
    if out.get("is_error"):
        msg = str(out.get("result") or out.get("api_error_status"))
        if _LIMIT.search(msg) or out.get("api_error_status") == 429:
            raise UsageLimit(msg)
        return _row(custom_id, "claude", model, type="errored", error=msg[:500])
    u = out.get("usage", {})
    usage = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
             "cache_write": u.get("cache_creation_input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0)}
    text = json.dumps(out["structured_output"]) if schema and out.get("structured_output") is not None else out.get("result", "")
    stop = out.get("stop_reason")
    kind = "refusal" if stop == "refusal" else "succeeded"
    if schema and out.get("structured_output") is None:
        kind = "errored"
    return _row(custom_id, "claude", model, type=kind, stop_reason=stop, text=text, usage=usage)


def call_gemini(custom_id: str, system: str, user: str, effort: str, schema: dict | None,
                model: str = GEMINI_MODEL) -> dict:
    wd = _workdir(f"gemini/{custom_id}")  # own empty folder per call: parallel agent sessions must not share one
    prompt = (f"<instructions>\n{system}\n</instructions>\n\n{user}\n\n"
              "Respond directly with your answer. Do not use any tools, do not read or write files.")
    message = json.dumps({"event": "user", "message": {"role": "user", "content": prompt}}, ensure_ascii=False)
    cmd = [str(AGY_EXE), "--input-format", "stream-json", "--output-format", "stream-json",
           "--model", model, "--disable-slash-commands"]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    cmd += ["--print="]
    try:
        proc = subprocess.run(cmd, input=message + "\n", capture_output=True, text=True, encoding="utf-8",
                              cwd=wd, timeout=TIMEOUT_SECONDS)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    result = None
    for line in proc.stdout.splitlines():
        if '"event":"result"' in line:
            try:
                result = json.loads(line)["result"]
            except (json.JSONDecodeError, KeyError):
                pass
    if result is None:
        msg = (proc.stdout + proc.stderr)[-500:]
        if _LIMIT.search(msg):
            raise UsageLimit(msg)
        return _row(custom_id, "gemini", model, type="errored", error=msg)
    if result.get("status") != "SUCCESS":
        msg = str(result.get("error") or result.get("response"))
        if _LIMIT.search(msg):
            raise UsageLimit(msg)
        return _row(custom_id, "gemini", model, type="errored", error=msg[:500])
    u = result.get("usage", {})
    usage = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0) + u.get("thinking_tokens", 0),
             "cache_write": 0, "cache_read": u.get("cache_read_tokens", 0)}
    if schema:
        so = result.get("structured_output")
        if not _has_content(so):  # agent sometimes leaves it empty but puts the JSON in its reply
            so = _json_from_text(result.get("response", ""), schema)
        if not _has_content(so):
            return _row(custom_id, "gemini", model, type="errored", usage=usage,
                        error="no structured output; response: " + result.get("response", "")[:300])
        text = json.dumps(so)
    else:
        text = result.get("response", "").strip()
    return _row(custom_id, "gemini", model, type="succeeded", stop_reason="end_turn", text=text, usage=usage)


def _has_content(obj) -> bool:
    """False for None and for objects whose values are all empty (e.g. {"questions": []})."""
    if not isinstance(obj, dict):
        return False
    return any(v not in (None, "", [], {}) for v in obj.values())


def _json_from_text(text: str, schema: dict) -> dict | None:
    """Last JSON object in the text that fits the schema's required keys; a bare array is wrapped
    when the schema has a single array property."""
    required = schema.get("required", [])
    array_keys = [k for k, v in schema.get("properties", {}).items() if v.get("type") == "array"]
    dec = json.JSONDecoder()
    found = None
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list) and len(array_keys) == 1 and len(required) <= 1:
            obj = {array_keys[0]: obj}
        if isinstance(obj, dict) and all(k in obj for k in required) and _has_content(obj):
            found = {k: obj[k] for k in schema.get("properties", obj)}
    return found


BACKENDS = {"claude": call_claude, "gemini": call_gemini}


def call_with_wait(backend: str, req: dict, model: str | None = None, log=print) -> dict:
    """Run one request; on a usage limit, wait and retry so long runs survive limit windows."""
    p = req["params"]
    system = p["system"][0]["text"]
    user = p["messages"][0]["content"]
    effort = p["output_config"]["effort"]
    fmt = p["output_config"].get("format")
    schema = fmt["schema"] if fmt else None
    flaky_left = FLAKY_RETRIES
    for attempt in range(MAX_LIMIT_WAITS + 1):
        try:
            row = BACKENDS[backend](req["custom_id"], system, user, effort, schema, **({"model": model} if model else {}))
            # Antigravity sometimes ends a run without its final answer; trying again usually works
            while row["type"] == "errored" and "no structured output" in row.get("error", "") and flaky_left:
                flaky_left -= 1
                row = BACKENDS[backend](req["custom_id"], system, user, effort, schema, **({"model": model} if model else {}))
            if row["type"] == "errored":
                with open(WORKDIR / "failures.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return row
        except UsageLimit as e:
            if attempt == MAX_LIMIT_WAITS:
                raise
            secs = wait_seconds(str(e))
            log(f"[{backend}] usage limit reached ({str(e)[:120]!r}); waiting {secs // 60} min...", flush=True)
            time.sleep(secs)
        except subprocess.TimeoutExpired:
            return _row(req["custom_id"], backend, "?", type="errored", error="timeout")
    raise RuntimeError("unreachable")
