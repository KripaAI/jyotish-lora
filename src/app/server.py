"""Web API around the pipeline.

    python -m uvicorn src.app.server:app --port 8000

Environment: ASTRO_MODEL (Ollama model name, default astro-v2-8b), OLLAMA_HOST (default http://localhost:11434),
ASTRO_TRACE (path of the JSONL trace file, default runs/traces/requests.jsonl).

Every request is traced to a JSONL file: time, how long it took, which safety route was taken, sizes, and a hash of the
question. The question and the reply text are NOT written unless ASTRO_TRACE_TEXT=1, because they may be personal.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.app.pipeline import DISCLAIMER, Birth, Pipeline, ollama_llm
from src.common import RUNS

TRACE = Path(os.environ.get("ASTRO_TRACE", RUNS / "traces" / "requests.jsonl"))
TRACE_TEXT = os.environ.get("ASTRO_TRACE_TEXT") == "1"


class BirthIn(BaseModel):
    when: datetime = Field(description="Local date and time of birth, e.g. 1990-05-17T06:30:00")
    city: str | None = Field(None, description="A city from the built-in list; or give lat, lon and tz_offset")
    lat: float | None = None
    lon: float | None = None
    tz_offset: float | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    birth: BirthIn | None = None


class AskOut(BaseModel):
    reply: str
    route: str
    disclaimer: str


def make_app(pipeline: Pipeline | None = None) -> FastAPI:
    app = FastAPI(title="Jyotish assistant", version="1.0")
    pipe = pipeline or Pipeline(ollama_llm(os.environ.get("ASTRO_MODEL", "astro-v2-8b"),
                                           os.environ.get("OLLAMA_HOST", "http://localhost:11434")))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/ask", response_model=AskOut)
    def ask(body: AskIn):
        t0 = time.time()
        try:
            result = pipe.ask(body.question, Birth(**body.birth.model_dump()) if body.birth else None)
        except ValueError as e:                      # unknown city, missing coordinates
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:                       # model server down, timeout
            _trace({"event": "error", "error": type(e).__name__, "seconds": round(time.time() - t0, 2)})
            raise HTTPException(status_code=502, detail="The language model is not available right now.")
        row = {"event": "ask", "seconds": round(time.time() - t0, 2), "route": result.route,
               "has_chart": body.birth is not None, "question_chars": len(body.question), "reply_chars": len(result.reply),
               "question_sha256": hashlib.sha256(body.question.encode()).hexdigest()[:16]}
        if TRACE_TEXT:
            row.update(question=body.question, reply=result.reply)
        _trace(row)
        return AskOut(reply=result.reply, route=result.route, disclaimer=DISCLAIMER)

    return app


def _trace(row: dict) -> None:
    TRACE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **row}, ensure_ascii=False) + "\n")


app = make_app() if os.environ.get("ASTRO_NO_AUTOSTART") != "1" else None
