"""API: request validation, the safety route is reported, the trace holds no personal text by default."""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRO_NO_AUTOSTART", "1")
    monkeypatch.setenv("ASTRO_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.delenv("ASTRO_TRACE_TEXT", raising=False)
    from src.app import server
    importlib.reload(server)
    from src.app.pipeline import Pipeline
    calls = []
    pipe = Pipeline(lambda msgs: calls.append(msgs) or "Saturn gives patience, in the Parashari view.")
    return TestClient(server.make_app(pipe)), tmp_path / "trace.jsonl", calls


def test_health(client):
    c, _, _ = client
    assert c.get("/health").json() == {"status": "ok"}


def test_ask_returns_reply_route_and_disclaimer(client):
    c, trace, _ = client
    r = c.post("/ask", json={"question": "What does Saturn in the 10th house mean?"})
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "model" and body["reply"] and "not a science" in body["disclaimer"]
    row = json.loads(trace.read_text().splitlines()[-1])
    assert row["event"] == "ask" and "question" not in row and "reply" not in row and len(row["question_sha256"]) == 16


def test_birth_details_make_a_chart_prompt(client):
    c, _, calls = client
    r = c.post("/ask", json={"question": "What does my Moon say?", "birth": {"when": "1990-05-17T06:30:00", "city": "Delhi"}})
    assert r.status_code == 200 and "Chart:" in calls[-1][1]["content"]


def test_unknown_city_is_422(client):
    c, _, _ = client
    r = c.post("/ask", json={"question": "What does my Moon say?", "birth": {"when": "1990-05-17T06:30:00", "city": "Atlantis"}})
    assert r.status_code == 422


def test_too_short_question_is_422(client):
    c, _, _ = client
    assert c.post("/ask", json={"question": "hi"}).status_code == 422


def test_model_down_is_502_and_traced(client):
    c, trace, _ = client
    from src.app import server
    from src.app.pipeline import Pipeline

    def boom(msgs):
        raise ConnectionError("no model")
    c2 = TestClient(server.make_app(Pipeline(boom)))
    assert c2.post("/ask", json={"question": "What is Gajakesari yoga?"}).status_code == 502
    assert json.loads(trace.read_text().splitlines()[-1])["event"] == "error"
