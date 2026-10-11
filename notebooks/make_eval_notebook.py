"""Builds notebooks/eval_generate.ipynb (Phase 6): answers every evaluation prompt with the base model and with the
LoRA adapter, on Kaggle. Edit this file, then run it, rather than editing the notebook JSON by hand.

Inputs on Kaggle: dataset krishmithlesh0786/astro-eval (test.jsonl, quiz.jsonl, safety_eval.jsonl, system_v1.txt) and
the output of the training notebook krishmithlesh0786/notebookd2e6e39330 (the adapter).
Output: /kaggle/working/eval_outputs.jsonl, one row per (prompt, model).
"""
import json
import pathlib

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("""
# Jyotish LoRA: evaluation answers (Phase 6)

Generates answers from **Qwen3-4B-Instruct-2507** with the LoRA adapter switched **off** (base) and **on** (adapter),
for the 60 held-out test examples, the 100-question quiz and the 50 safety prompts. Same system prompt, greedy decoding.
Scoring happens afterwards on the laptop (`src/eval/judge.py`).
""")

code("""
import os
TWO_GPU_MERGED = False   # True: fp16 base + adapter MERGED, sharded across both T4s (model B of the A/B/C chain); adapter-only answers
if not TWO_GPU_MERGED:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
""")

code("""
!pip install -q -U transformers peft accelerate bitsandbytes
!pip uninstall -y -q torchao
""")

code("""
import contextlib, glob, json, re, time
import torch, transformers, peft
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from transformers import BitsAndBytesConfig

# ---------- settings ----------
BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
QLORA = False                 # True: load the base in 4-bit (for the 8B QLoRA adapter)
ADAPTER_HINT = ""             # substring of the adapter path to pick, when several inputs carry adapters
THINK_CHART = False           # v3 models: thinking on for prompts that carry a chart (they were trained that way), off otherwise
THINK_EXTRA = 700             # extra new tokens allowed for the reasoning block when THINK_CHART is on
PRE_ADAPTER_HINT = ""         # set for a DPO adapter: substring of the SFT adapter that is merged into the base first
OUT = "/kaggle/working/eval_outputs.jsonl"
BATCH = {"test": 6, "quiz": 16, "safety": 8}
MAX_NEW = {"test": 1000, "quiz": 200, "safety": 600}

def find(name):
    hits = glob.glob("/kaggle/input/**/" + name, recursive=True)
    assert hits, name + " not found: attach the astro-eval dataset and the training notebook output"
    return hits[0]

adapters = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
PRE_ADAPTER = None
if PRE_ADAPTER_HINT:
    PRE_ADAPTER = os.path.dirname([a for a in adapters if PRE_ADAPTER_HINT in a][-1])
    adapters = [a for a in adapters if PRE_ADAPTER_HINT not in a]
adapters = [a for a in adapters if ADAPTER_HINT in a] or adapters
final = [a for a in adapters if "/adapter/" in a]
ADAPTER = os.path.dirname((final or sorted(adapters, key=lambda a: int(re.findall(r"checkpoint-(\\d+)", a)[-1]) if "checkpoint-" in a else 0))[-1])
SYSTEM = open(find("system_v1.txt"), encoding="utf-8").read().strip()
load = lambda n: [json.loads(l) for l in open(find(n), encoding="utf-8") if l.strip()]
tests, quiz, safety = load("test.jsonl"), load("quiz.jsonl"), load("safety_eval.jsonl")
print("adapter:", ADAPTER, "| test", len(tests), "quiz", len(quiz), "safety", len(safety))
print({m.__name__: m.__version__ for m in (torch, transformers, peft)})

items = []
for t in tests:
    items.append({"set": "test", "id": t["id"], "task": t["task"], "messages": t["messages"][:-1]})
for q in quiz:
    items.append({"set": "quiz", "id": q["id"], "task": q["category"],
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": q["question"] + "\\n\\nAnswer briefly, in one or two sentences."}]})
for s in safety:
    items.append({"set": "safety", "id": s["id"], "task": s["category"],
                  "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": s["prompt"]}]})
""")

code("""
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
tokenizer.padding_side = "left"
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
if TWO_GPU_MERGED:
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map="auto",
                                                 max_memory={0: "13GiB", 1: "13GiB"})   # no cpu budget: fail instead of offloading
    assert all(str(d) in ("0", "1") for d in model.hf_device_map.values()), model.hf_device_map
elif QLORA:
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb, dtype=torch.float16, device_map={"": 0})
else:
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map={"": 0})
if PRE_ADAPTER:
    model = PeftModel.from_pretrained(model, PRE_ADAPTER).merge_and_unload()   # the DPO adapter sits on the merged SFT model
    print("merged SFT adapter:", PRE_ADAPTER)
model = PeftModel.from_pretrained(model, ADAPTER)
if TWO_GPU_MERGED:
    model = model.merge_and_unload()
    print("merged into the fp16 base; device map:", sorted({str(d) for d in model.hf_device_map.values()}))
MODELS = (("adapter", True),) if TWO_GPU_MERGED else (("adapter", True), ("base", False))
VARIANT = "merged-fp16-2gpu" if TWO_GPU_MERGED else ("qlora-4bit" if QLORA else "fp16")
model.eval()
print("loaded; GPU memory per device (GiB):", [round(torch.cuda.memory_allocated(i) / 2**30, 1) for i in range(torch.cuda.device_count())])
""")

code("""
def generate(batch, max_new, use_adapter):
    thinks = [THINK_CHART and b["messages"][-1]["content"].startswith("Chart:") for b in batch]
    texts = [tokenizer.apply_chat_template(b["messages"], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=t) for b, t in zip(batch, thinks)]  # ignored by non-thinking models
    max_new = max_new + THINK_EXTRA if any(thinks) else max_new
    enc = tokenizer(texts, return_tensors="pt", padding=True).to("cuda")
    ctx = contextlib.nullcontext() if (use_adapter or TWO_GPU_MERGED) else model.disable_adapter()
    with torch.no_grad(), ctx:
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False, repetition_penalty=1.05,
                             pad_token_id=tokenizer.pad_token_id)
    n = enc["input_ids"].shape[1]
    clean = lambda s: re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()
    decoded = [tokenizer.decode(o[n:], skip_special_tokens=True) for o in out]
    for b, d in zip(batch, decoded):
        m = re.search(r"<think>(.*?)</think>", d, flags=re.S)
        raw_think[b["id"]] = m.group(1).strip() if m else None
    return [clean(d) for d in decoded]

raw_think = {}

done = set()
if os.path.exists(OUT):
    done = {(r["set"], r["id"], r["model"]) for r in map(json.loads, open(OUT, encoding="utf-8"))}

t0 = time.time()
for set_name in ("safety", "quiz", "test"):
    group = sorted([it for it in items if it["set"] == set_name], key=lambda it: len(str(it["messages"])))
    for model_name, use_adapter in MODELS:
        todo = [it for it in group if (set_name, it["id"], model_name) not in done]
        for i in range(0, len(todo), BATCH[set_name]):
            batch = todo[i:i + BATCH[set_name]]
            answers = generate(batch, MAX_NEW[set_name], use_adapter)
            with open(OUT, "a", encoding="utf-8") as f:
                for it, a in zip(batch, answers):
                    f.write(json.dumps({"set": set_name, "id": it["id"], "task": it["task"], "model": model_name,
                                        "answer": a, "thinking": raw_think.get(it["id"]), "variant": VARIANT}, ensure_ascii=False) + "\\n")
            torch.cuda.empty_cache()
        print("%s / %s done at %.1f min" % (set_name, model_name, (time.time() - t0) / 60), flush=True)
print("ALL DONE in %.2f h" % ((time.time() - t0) / 3600))
""")

code("""
rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
from collections import Counter
print(Counter((r["set"], r["model"]) for r in rows))
for r in rows[:2]:
    print("=" * 80, "\\n", r["set"], r["id"], r["model"], "\\n", r["answer"][:600])
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
path = pathlib.Path(__file__).with_name("eval_generate.ipynb")
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
for c in cells:
    if c["cell_type"] == "code":
        compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
print("wrote", path, len(cells), "cells; all code cells compile")
