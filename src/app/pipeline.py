"""The serving pipeline: birth details -> chart engine -> prompt -> model -> safety checks -> reply.

    from src.app.pipeline import Pipeline, ollama_llm
    pipe = Pipeline(ollama_llm("astro-v2-8b"))
    result = pipe.ask("What does Saturn in my 10th house mean?", birth=Birth(...))

Training and serving use the same system prompt (prompts/system_v1.txt) and the same chart text
(src/chart/render.py:render_chart_text). The model never calculates a chart: src/chart does.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from src.app.safety import check_input, finalize, fixed_reply, guard_note
from src.chart.engine import compute_chart
from src.chart.render import render_chart_text
from src.common import PROMPTS, ROOT

DISCLAIMER = ("Astrology is a traditional interpretive system, not a science, and this assistant describes tendencies "
              "only. It cannot predict death, diagnose illness, or give legal or financial advice: for those, please "
              "consult a doctor, a lawyer or a registered adviser.")
SYSTEM = (PROMPTS / "system_v1.txt").read_text(encoding="utf-8").strip()
CITIES = ROOT / "src" / "chart" / "cities.csv"


@dataclass
class Birth:
    when: datetime                 # local date and time of birth
    city: str | None = None        # a name from cities.csv, or give lat, lon and tz_offset directly
    lat: float | None = None
    lon: float | None = None
    tz_offset: float | None = None


@dataclass
class Result:
    reply: str
    route: str                     # what the safety layer did: model, guarded (...), output block (...)
    disclaimer: str = DISCLAIMER
    chart_text: str | None = None


def find_city(name: str) -> dict:
    with open(CITIES, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["city"].lower() == name.strip().lower():
                return {"lat": float(row["lat"]), "lon": float(row["lon"]), "tz": float(row["tz"])}
    raise ValueError(f"unknown city {name!r}: give lat, lon and tz_offset instead")


def chart_for(birth: Birth, as_of: date | None = None) -> dict:
    lat, lon, tz = birth.lat, birth.lon, birth.tz_offset
    if None in (lat, lon, tz):
        if not birth.city:
            raise ValueError("give a city, or lat, lon and tz_offset")
        c = find_city(birth.city)
        lat, lon, tz = c["lat"], c["lon"], c["tz"]
    return compute_chart(birth.when, tz, lat, lon, as_of or date.today())


def build_messages(question: str, chart_text: str | None = None, note: str = "") -> list[dict]:
    """System prompt v1 (plus the safety note when the input check fires), then 'Chart: ... Question: ...' or the bare question."""
    user = f"Chart:\n{chart_text}\n\nQuestion: {question}" if chart_text else question
    return [{"role": "system", "content": SYSTEM + note}, {"role": "user", "content": user}]


def render_qwen(messages: list[dict], thinking: bool = False) -> str:
    """Qwen3 chat format, identical to tokenizer.apply_chat_template(..., add_generation_prompt=True, enable_thinking=thinking):
    thinking off pre-fills the empty think block; thinking on leaves the assistant turn open for the model's own <think> block."""
    text = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    return text + ("<|im_start|>assistant\n" if thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def ollama_llm(model: str, host: str = "http://localhost:11434", temperature: float = 0.0, num_ctx: int = 4096,
               max_tokens: int = 1500, timeout: float = 1800) -> Callable[[list[dict]], str]:
    """A function messages -> reply that calls a local Ollama server in raw mode, so the prompt is exactly render_qwen()."""
    import httpx

    def call(messages: list[dict], thinking: bool = False) -> str:
        r = httpx.post(f"{host}/api/generate", timeout=timeout, json={
            "model": model, "prompt": render_qwen(messages, thinking), "raw": True, "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": max_tokens,
                        "repeat_penalty": 1.05, "stop": ["<|im_end|>"]}})
        r.raise_for_status()
        return r.json()["response"].strip()

    return call


def llamacpp_llm(host: str = "http://localhost:8080", temperature: float = 0.0, max_tokens: int = 1500,
                 timeout: float = 1800) -> Callable[[list[dict]], str]:
    """A function messages -> reply that calls a llama.cpp `llama-server` (its /completion endpoint) with the exact
    render_qwen() prompt. `cache_prompt` lets follow-up questions about the same chart reuse the already-read prompt."""
    import httpx

    def call(messages: list[dict], thinking: bool = False) -> str:
        r = httpx.post(f"{host}/completion", timeout=timeout, json={
            "prompt": render_qwen(messages, thinking), "n_predict": max_tokens + (700 if thinking else 0),
            "temperature": temperature, "repeat_penalty": 1.05,
            "stop": ["<|im_end|>"], "cache_prompt": True, "stream": False})
        r.raise_for_status()
        return r.json()["content"].strip()

    return call


class Pipeline:
    """render_version 2: the v2 chart text, thinking off (v1, v2-4b, v2-8b adapters).
    render_version 3: the v3 chart text with counted facts, and thinking on for chart questions (v3 adapters)."""

    def __init__(self, llm: Callable[..., str], render_version: int = 2):
        self.llm, self.render_version = llm, render_version

    def ask(self, question: str, birth: Birth | None = None, as_of: date | None = None) -> Result:
        chart_text = render_chart_text(chart_for(birth, as_of), derived=self.render_version >= 3) if birth else None
        v_in = check_input(question)                      # sensitive request? the model gets a safety note
        fixed = fixed_reply(v_in)                         # a few categories never reach the model
        if fixed is not None:
            return Result(reply=fixed, route=f"fixed ({v_in.category})", chart_text=chart_text)
        messages = build_messages(question, chart_text, guard_note(v_in))
        thinking = self.render_version >= 3 and chart_text is not None
        raw = self.llm(messages, thinking) if thinking else self.llm(messages)
        answer = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()   # the working is not shown to the user
        reply, route = finalize(answer, v_in)             # output rules, helpline rule
        return Result(reply=reply, route=route, chart_text=chart_text)
