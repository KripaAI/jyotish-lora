"""Serving pipeline: the prompt matches Qwen's own chat template, the chart comes from the engine, the safety layer is wired in."""
import glob
import json
from datetime import datetime

import pytest

from src.app.pipeline import Birth, Pipeline, build_messages, chart_for, render_qwen
from src.chart.render import render_chart_text


def _qwen_template():
    jinja2 = pytest.importorskip("jinja2.sandbox")
    hits = glob.glob(glob.os.path.expanduser("~/.cache/huggingface/hub/models--Qwen--Qwen3-8B/snapshots/*/tokenizer_config.json"))
    if not hits:
        pytest.skip("Qwen3-8B tokenizer_config.json not in the local Hugging Face cache")
    env = jinja2.ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = lambda m: (_ for _ in ()).throw(Exception(m))
    env.filters["tojson"] = lambda x, **k: json.dumps(x, ensure_ascii=False)
    return env.from_string(json.load(open(hits[0], encoding="utf-8"))["chat_template"])


@pytest.mark.parametrize("question,chart,note", [
    ("What is Gajakesari yoga?", None, ""),
    ("Interpret my 10th house.", "Lagna: Leo 12deg\nSun: Aries 3deg", ""),
    ("A sensitive question", "x", "\n\nSAFETY NOTICE: test"),
])
def test_prompt_matches_the_qwen_chat_template(question, chart, note):
    msgs = build_messages(question, chart, note)
    expected = _qwen_template().render(messages=msgs, add_generation_prompt=True, enable_thinking=False, tools=None)
    assert render_qwen(msgs) == expected


def test_prompt_with_thinking_on_matches_the_qwen_chat_template():
    msgs = build_messages("Interpret my 10th house.", "Lagna: Leo 12deg")
    expected = _qwen_template().render(messages=msgs, add_generation_prompt=True, enable_thinking=True, tools=None)
    assert render_qwen(msgs, thinking=True) == expected and expected.endswith("<|im_start|>assistant\n")


def test_v3_pipeline_thinks_for_chart_questions_and_hides_the_working():
    seen = {}

    def llm(msgs, thinking=False):
        seen["thinking"] = thinking
        return "<think>\nThe lagna is Taurus.\n</think>\n\nVenus rules your lagna, in the Parashari view."
    pipe = Pipeline(llm, render_version=3)
    r = pipe.ask("What does my lagna lord say?", Birth(when=datetime(1990, 5, 17, 6, 30), city="Delhi"))
    assert seen["thinking"] is True and "Counted from the Moon" in r.chart_text
    assert "<think>" not in r.reply and r.reply.startswith("Venus rules")
    pipe.ask("What is Gajakesari yoga?")
    assert seen["thinking"] is False


BIRTH = Birth(when=datetime(1990, 5, 17, 6, 30), city="Delhi")


def test_chart_comes_from_the_engine_and_is_in_the_prompt():
    chart_text = render_chart_text(chart_for(BIRTH))
    seen = {}
    pipe = Pipeline(lambda msgs: seen.setdefault("msgs", msgs) and "Saturn gives patience in the Parashari view.")
    result = pipe.ask("What does my Moon sign say about me?", BIRTH)
    assert result.route == "model" and result.chart_text == chart_text
    assert chart_text in seen["msgs"][1]["content"] and seen["msgs"][1]["content"].endswith("Question: What does my Moon sign say about me?")
    assert "SAFETY NOTICE" not in seen["msgs"][0]["content"]


def test_sensitive_question_gets_the_safety_note_and_the_helpline_rule():
    seen = {}
    pipe = Pipeline(lambda msgs: seen.setdefault("msgs", msgs) and "I am sorry you feel this way. Please speak to someone you trust.")
    result = pipe.ask("I want to end my life.")
    assert "SAFETY NOTICE" in seen["msgs"][0]["content"]
    assert "14416" in result.reply and "helpline" in result.route


def test_unsafe_model_output_is_replaced():
    pipe = Pipeline(lambda msgs: "You will die at the age of 60.")
    result = pipe.ask("Tell me about my Mars.")
    assert "die" not in result.reply and result.route.startswith("output block")


def test_unknown_city_is_an_error():
    with pytest.raises(ValueError):
        chart_for(Birth(when=datetime(1990, 1, 1), city="Atlantis"))


def test_llamacpp_client_sends_the_exact_prompt_and_reads_the_reply():
    import http.server
    import threading

    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"content": " A reply. "}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from src.app.pipeline import llamacpp_llm
    msgs = build_messages("What is Gajakesari yoga?")
    assert llamacpp_llm(f"http://127.0.0.1:{srv.server_port}")(msgs) == "A reply."
    srv.shutdown()
    assert seen["path"] == "/completion" and seen["body"]["prompt"] == render_qwen(msgs)
    assert seen["body"]["stop"] == ["<|im_end|>"]
