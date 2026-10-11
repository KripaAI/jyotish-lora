"""Builds two Kaggle notebooks that run the Q4_K_M GGUF on a free T4 with llama.cpp:

  notebooks/gguf_eval.ipynb   speed benchmark + the same evaluation prompts as eval_generate (-> eval_outputs.jsonl, speed.json)
  notebooks/live_demo.ipynb   the full pipeline (chart engine, safety layer, model) behind a Gradio page with a temporary public link

Inputs on Kaggle (kernel_sources / dataset_sources of the pushed kernel):
  the output of astro-export-v2-8b (the .gguf), dataset astro-eval-v2 (gguf_eval), dataset astro-app-code (live_demo).
Edit this file, then run it, rather than editing the notebook JSON by hand.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent


def cell(kind, s):
    base = {"cell_type": kind, "metadata": {}, "source": s.strip("\n")}
    return base if kind == "markdown" else {**base, "execution_count": None, "outputs": []}


def build(name, cells):
    for c in cells:
        if c["cell_type"] == "code":
            compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    (HERE / name).write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", name, "- all code cells compile")


SETTINGS = r"""
import glob, json, os, re, shutil, subprocess, sys, tarfile, time, urllib.request, hashlib
os.environ["CUDA_VISIBLE_DEVICES"] = "0"       # one GPU: llama.cpp would otherwise split the model across both T4s

# ---------- settings ----------
RELEASE = "b11513"
MODEL_FILE = "astro-v2-8b.Q4_K_M.gguf"
PARALLEL = 4                  # simultaneous requests the server handles
CTX_PER_SLOT = 5120           # a chart prompt is about 2,800 tokens and an answer up to 1,000
PORT = 8080
WORK = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp"
# prebuilt Linux CUDA 12.8 build of llama.cpp and its CUDA runtime, with the sha256 GitHub publishes for release b11513
PREBUILT = {
    "llama-b11513-bin-ubuntu-cuda-12.8-x64.tar.gz": "af399b958079ec0a0a002faa5b2432f63269c0bf862e9f4f8add67a38a17aa33",
    "cudart-llama-b11513-bin-ubuntu-cuda-12.8-x64.tar.gz": "bb8ac07d9ae02a9d834d03cd5b2ed7c3b9720f46aea02414d0c304d066fec13c",
}
"""

INSTALL = r"""
def sh(cmd, check=True):
    print("$", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    out = (r.stdout + r.stderr)
    print(out[-2500:], flush=True)
    if check:
        assert r.returncode == 0, "command failed: " + cmd
    return r.returncode, out

print(sh("nvidia-smi")[1][:900])
MODEL = glob.glob("/kaggle/input/**/" + MODEL_FILE, recursive=True)
assert MODEL, MODEL_FILE + " not found: attach the output of the astro-export kernel"
MODEL = MODEL[0]
print("model:", MODEL, os.path.getsize(MODEL), "bytes")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()

def install_prebuilt():
    d = WORK + "/llama_prebuilt"
    os.makedirs(d, exist_ok=True)
    for name, digest in PREBUILT.items():
        path = d + "/" + name
        urllib.request.urlretrieve("https://github.com/ggml-org/llama.cpp/releases/download/%s/%s" % (RELEASE, name), path)
        got = sha256(path)
        assert got == digest, "sha256 mismatch for " + name + ": " + got
        with tarfile.open(path) as t:
            t.extractall(d)
        os.remove(path)
    server = glob.glob(d + "/**/llama-server", recursive=True)[0]
    bench = glob.glob(d + "/**/llama-bench", recursive=True)[0]
    libs = sorted({os.path.dirname(p) for p in glob.glob(d + "/**/*.so*", recursive=True)})
    return server, bench, ":".join(libs)

def build_from_source():
    src = WORK + "/llama.cpp"
    sh("git clone --depth 1 --branch %s https://github.com/ggml-org/llama.cpp %s" % (RELEASE, src))
    sh("cd %s && cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF > /dev/null "
       "&& cmake --build build --target llama-server llama-bench -j4" % src)
    return src + "/build/bin/llama-server", src + "/build/bin/llama-bench", src + "/build/bin"

def works(bench, libs):
    env = "LD_LIBRARY_PATH=%s:$LD_LIBRARY_PATH " % libs
    rc, out = sh(env + "%s -m %s -ngl 99 -p 64 -n 8 -r 1" % (bench, MODEL), check=False)
    return rc == 0 and "CUDA" in out and "tg8" in out

try:
    SERVER, BENCH, LIBS = install_prebuilt()
    ok = works(BENCH, LIBS)
except Exception as e:
    print("prebuilt build failed:", repr(e)[:300])
    ok = False
if not ok:
    print("prebuilt build did not run on this GPU/driver: building llama.cpp from source (about 10 minutes)")
    SERVER, BENCH, LIBS = build_from_source()
    assert works(BENCH, LIBS), "llama.cpp does not run on this machine"
print("llama.cpp ready:", SERVER)
"""

SERVER_CELL = r"""
import requests
os.environ["LD_LIBRARY_PATH"] = LIBS + ":" + os.environ.get("LD_LIBRARY_PATH", "")
server_log = open("/kaggle/working/llama_server.log", "w")
server = subprocess.Popen([SERVER, "-m", MODEL, "-ngl", "99", "-c", str(PARALLEL * CTX_PER_SLOT), "--parallel", str(PARALLEL),
                           "--host", "127.0.0.1", "--port", str(PORT), "-t", "4"], stdout=server_log, stderr=server_log)
BASE = "http://127.0.0.1:%d" % PORT
t0 = time.time()
while True:
    try:
        if requests.get(BASE + "/health", timeout=2).json().get("status") == "ok":
            break
    except Exception:
        pass
    assert server.poll() is None, "llama-server exited: see /kaggle/working/llama_server.log"
    assert time.time() - t0 < 600, "llama-server did not become ready"
    time.sleep(3)
print("server ready after %.0f s" % (time.time() - t0))

def render_qwen(messages, thinking=False):
    # Qwen3 chat format: same text as tokenizer.apply_chat_template(..., enable_thinking=thinking). With thinking off the
    # empty think block is pre-filled; with it on the assistant turn is left open and the model writes <think>...</think> itself.
    text = "".join("<|im_start|>%s\n%s<|im_end|>\n" % (m["role"], m["content"]) for m in messages)
    return text + ("<|im_start|>assistant\n" if thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n")
"""

# ------------------------------------------------------------------ evaluation notebook
E = []
E.append(cell("markdown", "# Jyotish LoRA: GGUF speed and accuracy on a T4\n\nBenchmarks the Q4_K_M model with llama.cpp on the GPU, then answers the same prompts as `eval_generate` (greedy). Judging happens on the laptop."))
E.append(cell("code", SETTINGS + "\nRUN_LIMIT = 0                  # >0: only that many prompts per set (smoke test)\nTHINKING = False               # True: Qwen3 thinking mode at answer time (reasoning before the answer; the model was trained with it off)\nTHINK_BUDGET = 2500            # extra tokens allowed for the reasoning when THINKING is on\nTHINK_PREFIX = \"\"              # with THINKING: text pre-filled at the start of the reasoning block, so the model cannot close it at once\nOUT = \"/kaggle/working/eval_outputs.jsonl\"\nMAX_NEW = {\"test\": 1000, \"quiz\": 200, \"safety\": 600}\nEXTRA_FILE = \"\"               # a file name under /kaggle/input: run ONLY its prompts (rows: set, id, task, messages, max_new, route)\n"))
E.append(cell("code", INSTALL))
E.append(cell("code", r"""
# speed of the model itself: reading a prompt (pp) and writing an answer (tg)
cmd = "LD_LIBRARY_PATH=%s:$LD_LIBRARY_PATH %s -m %s -ngl 99 -p 512,2500 -n 128 -r 3 -o json" % (LIBS, BENCH, MODEL)
print("$", cmd, flush=True)
res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
print(res.stderr[-1500:])
assert res.returncode == 0, "llama-bench failed"
rows = json.loads(res.stdout)          # stdout holds only the JSON; the log lines are on stderr
speed = {("pp%d" % r["n_prompt"]) if r["n_prompt"] else ("tg%d" % r["n_gen"]): round(r["avg_ts"], 1) for r in rows}
print("tokens/second:", speed)
json.dump({"tokens_per_second": speed, "rows": rows}, open("/kaggle/working/speed.json", "w"), indent=2)
"""))
E.append(cell("code", SERVER_CELL))
E.append(cell("code", r"""
from concurrent.futures import ThreadPoolExecutor
def find(name):
    hits = glob.glob("/kaggle/input/**/" + name, recursive=True)
    assert hits, name + " not found: attach the astro-eval dataset"
    return hits[0]
SYSTEM = open(find("system_v1.txt"), encoding="utf-8").read().strip()
load = lambda n: [json.loads(l) for l in open(find(n), encoding="utf-8") if l.strip()]
tests, quiz, safety = load("test.jsonl"), load("quiz.jsonl"), load("safety_eval.jsonl")
items = []
for t in tests:
    items.append({"set": "test", "id": t["id"], "task": t["task"], "messages": t["messages"][:-1]})
for q in quiz:
    items.append({"set": "quiz", "id": q["id"], "task": q["category"],
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": q["question"] + "\n\nAnswer briefly, in one or two sentences."}]})
for s in safety:
    items.append({"set": "safety", "id": s["id"], "task": s["category"],
                  "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": s["prompt"]}]})
if EXTRA_FILE:
    items = load(EXTRA_FILE)
if RUN_LIMIT:
    keep = {k: 0 for k in MAX_NEW}
    items = [it for it in items if (keep.__setitem__(it["set"], keep[it["set"]] + 1) or keep[it["set"]] <= RUN_LIMIT)]
done = set()
if os.path.exists(OUT):
    done = {(r["set"], r["id"]) for r in map(json.loads, open(OUT, encoding="utf-8"))}
todo = [it for it in items if (it["set"], it["id"]) not in done]
print(len(items), "prompts;", len(todo), "to do")

def ask(it):
    if THINKING:   # Qwen's documented settings for thinking mode; greedy decoding is known to loop in this mode
        decode = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "seed": 42}
        n_predict = MAX_NEW[it["set"]] + THINK_BUDGET
    else:
        decode = {"temperature": 0.0, "top_k": 1}
        n_predict = it.get("max_new") or MAX_NEW[it["set"]]
    prompt = render_qwen(it["messages"], THINKING)
    if THINKING and THINK_PREFIX:
        prompt += "<think>\n" + THINK_PREFIX
    r = requests.post(BASE + "/completion", timeout=3600, json={
        "prompt": prompt, "n_predict": n_predict, **decode,
        "repeat_penalty": 1.05, "stop": ["<|im_end|>"], "cache_prompt": False, "stream": False})
    r.raise_for_status()
    j = r.json()
    content = j["content"]
    if THINKING and THINK_PREFIX:
        content = "<think>\n" + THINK_PREFIX + content      # the opening tag and prefix were part of the prompt
    m = re.search(r"<think>(.*?)</think>", content, flags=re.S)
    thinking_text = m.group(1).strip() if m else ("" if not THINKING else content.strip().removeprefix("<think>").strip())
    answer = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip() if (m or not THINKING) else ""
    unfinished = THINKING and not m          # ran out of tokens while still reasoning: no answer was produced
    return {"set": it["set"], "id": it["id"], "task": it["task"], "model": "adapter", "route": it.get("route"),
            "variant": ("gguf-q4_k_m-thinking-forced" if THINK_PREFIX else "gguf-q4_k_m-thinking") if THINKING else "gguf-q4_k_m", "answer": answer,
            "thinking": thinking_text if THINKING else None, "unfinished": unfinished,
            "prompt_tokens": j.get("tokens_evaluated"), "new_tokens": j.get("tokens_predicted"),
            "prompt_tps": (j.get("timings") or {}).get("prompt_per_second"),
            "gen_tps": (j.get("timings") or {}).get("predicted_per_second")}

t0, n = time.time(), 0
with ThreadPoolExecutor(PARALLEL) as ex, open(OUT, "a", encoding="utf-8") as f:
    for row in ex.map(ask, todo):
        f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
        n += 1
        if n % 20 == 0:
            print("%d/%d, %.1f min" % (n, len(todo), (time.time() - t0) / 60), flush=True)
print("ALL DONE in %.1f min" % ((time.time() - t0) / 60))
server.terminate()
"""))
E.append(cell("code", r"""
rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
from collections import Counter
print(Counter(r["set"] for r in rows))
gen = [r["gen_tps"] for r in rows if r.get("gen_tps")]
print("mean single-request writing speed while 4 requests ran together: %.1f tok/s" % (sum(gen) / len(gen)))
if THINKING:
    unf = sum(r.get("unfinished", False) for r in rows)
    th = [len(r["thinking"].split()) for r in rows if r.get("thinking")]
    print("thinking mode: %d/%d ran out of tokens before answering; reasoning length (words) median %d, max %d"
          % (unf, len(rows), sorted(th)[len(th) // 2] if th else 0, max(th) if th else 0))
json.dump({"model": MODEL_FILE, "release": RELEASE, "parallel": PARALLEL, "rows": len(rows), "thinking": THINKING},
          open("/kaggle/working/eval_manifest.json", "w"))
"""))
build("gguf_eval.ipynb", E)

# ------------------------------------------------------------------ live demo notebook
D = []
D.append(cell("markdown", "# Jyotish assistant: live demo on a T4\n\nRuns the GGUF with llama.cpp and the full pipeline behind a Gradio page with a temporary public link and a password. The session ends after `DEMO_HOURS`."))
D.append(cell("code", SETTINGS + "\nDEMO_HOURS = 1.5              # the page stays up this long, then the session ends and stops using GPU quota\n"))
D.append(cell("code", "!pip install -q gradio pyswisseph scikit-learn==1.9.1 scipy==1.17.1 joblib httpx\n"))
D.append(cell("code", INSTALL))
D.append(cell("code", SERVER_CELL))
D.append(cell("code", r"""
# the pipeline code (chart engine, safety layer, prompts) comes from the astro-app-code dataset
hits = glob.glob("/kaggle/input/**/src/app/pipeline.py", recursive=True)
if not hits:                                   # the dataset was uploaded as a zip: unpack it
    import zipfile
    for z in glob.glob("/kaggle/input/**/*.zip", recursive=True):
        zipfile.ZipFile(z).extractall(WORK + "/app_code")
    hits = glob.glob(WORK + "/app_code/**/src/app/pipeline.py", recursive=True)
assert hits, "astro-app-code dataset not found or empty"
root = os.path.dirname(os.path.dirname(os.path.dirname(hits[0])))      # .../src/app/pipeline.py -> the folder holding src/ and prompts/
assert os.path.exists(root + "/prompts/system_v1.txt"), "prompts/system_v1.txt missing from the code bundle"
sys.path.insert(0, root)
os.chdir("/kaggle/working")        # writable; the code folder under /kaggle/input is read-only and Gradio writes .gradio into the cwd
from src.app.pipeline import Pipeline, Birth, DISCLAIMER, llamacpp_llm, find_city
from src.app import safety
v = safety.check_input("I want to end my life")
print("safety layer test:", v.action, v.category, "|", v.reason)
safety._classify("what is the exaltation sign of venus")      # forces the classifier model to load now
print("classifier loaded:", bool(safety._CLF))
import csv
CITIES = sorted(r["city"] for r in csv.DictReader(open(root + "/src/chart/cities.csv", encoding="utf-8")))
pipe = Pipeline(llamacpp_llm(BASE, temperature=0.0, max_tokens=1500))
"""))
D.append(cell("code", r"""
import secrets
from datetime import datetime
import gradio as gr

USER, PASSWORD = "astro", secrets.token_urlsafe(9)

def respond(question, use_chart, date_str, time_str, city):
    t0 = time.time()
    try:
        birth = Birth(when=datetime.fromisoformat("%sT%s" % (date_str.strip(), time_str.strip())), city=city) if use_chart else None
        res = pipe.ask(question, birth)
    except ValueError as e:
        return "Please check the birth details: %s" % e, "input error", "", DISCLAIMER
    return res.reply, res.route, "%.1f s" % (time.time() - t0), DISCLAIMER

with gr.Blocks(title="Jyotish assistant") as demo:
    gr.Markdown("## Jyotish assistant\nAsk a question. To use a birth chart, tick the box and fill in the birth details (local time).")
    q = gr.Textbox(label="Question", lines=3)
    with gr.Row():
        use = gr.Checkbox(label="Use a birth chart", value=False)
        d = gr.Textbox(label="Birth date (YYYY-MM-DD)", value="1990-05-17")
        t = gr.Textbox(label="Birth time (HH:MM, local)", value="06:30")
        c = gr.Dropdown(CITIES, label="Birth city", value="Delhi")
    go = gr.Button("Ask")
    reply = gr.Textbox(label="Reply", lines=14)
    with gr.Row():
        route = gr.Textbox(label="Safety route")
        took = gr.Textbox(label="Time")
    note = gr.Textbox(label="Note", lines=3)
    go.click(respond, [q, use, d, t, c], [reply, route, took, note])

res = demo.launch(share=True, auth=(USER, PASSWORD), prevent_thread_lock=True, quiet=True)
share_url = getattr(demo, "share_url", None) or (res[2] if isinstance(res, (tuple, list)) and len(res) > 2 else None)
if not share_url:
    print("WARNING: no public link was created (Gradio could not open a share tunnel). The page only works inside this notebook.")
print("=" * 70)
print("PUBLIC LINK :", share_url)
print("USER        :", USER)
print("PASSWORD    :", PASSWORD)
print("Ends in %.1f hours. Anyone with the link AND the password can use it." % DEMO_HOURS)
print("=" * 70, flush=True)
end = time.time() + DEMO_HOURS * 3600
while time.time() < end:
    time.sleep(30)
print("demo time is up")
server.terminate()
"""))
build("live_demo.ipynb", D)
