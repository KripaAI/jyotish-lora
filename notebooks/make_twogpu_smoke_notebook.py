"""Builds notebooks/twogpu_smoke.ipynb: can the merged fp16 Qwen3-8B (model B of the A/B/C chain) be loaded and run in transformers
sharded across Kaggle's two T4s, with no CPU offload?

Steps: list both GPUs and free memory; load the fp16 base with device_map="auto" and a per-GPU memory cap and NO cpu budget (so a
model that does not fit fails instead of silently offloading); apply the v2-8b adapter and merge it; run one greedy answer on a
held-out test question with the exact chat template (thinking off); record the device map, peak memory per GPU and timings.
Output: /kaggle/working/twogpu_smoke.json. Inputs: datasets astro-lora-v2-8b (adapter) and astro-eval-v2 (test.jsonl).
"""
import json
import pathlib

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("# Two-GPU smoke test: merged fp16 Qwen3-8B across two T4s\n\nModel B of the A/B/C artifact chain. Fails loudly instead of offloading to CPU.")

code("""
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"   # both GPUs stay visible (no CUDA_VISIBLE_DEVICES)
""")

code("""
!pip install -q -U transformers peft accelerate
!pip uninstall -y -q torchao
""")

code("""
import glob, json, re, time
import torch, transformers, peft, accelerate
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE_MODEL = "Qwen/Qwen3-8B"
PER_GPU = "13GiB"
VERSIONS = {m.__name__: m.__version__ for m in (torch, transformers, peft, accelerate)}
gpus = [{"index": i, "name": torch.cuda.get_device_name(i),
         "total_gib": round(torch.cuda.get_device_properties(i).total_memory / 2**30, 2),
         "free_gib": round(torch.cuda.mem_get_info(i)[0] / 2**30, 2)} for i in range(torch.cuda.device_count())]
print(VERSIONS); print(gpus)
assert len(gpus) >= 2, "this test needs two GPUs"
def find(name):
    hits = glob.glob("/kaggle/input/**/" + name, recursive=True)
    assert hits, name + " not found"
    return hits[0]
adapters = [a for a in glob.glob("/kaggle/input/**/adapter_config.json", recursive=True)]
ADAPTER = os.path.dirname(([a for a in adapters if "/adapter/" in a] or adapters)[-1])
print("adapter:", ADAPTER)
""")

code("""
result = {"versions": VERSIONS, "gpus": gpus, "base": BASE_MODEL, "adapter": ADAPTER, "per_gpu_cap": PER_GPU}
t0 = time.time()
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
try:
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16, device_map="auto",
                                                 max_memory={0: PER_GPU, 1: PER_GPU})   # no "cpu" key: no offload allowed
    devices = sorted({str(v) for v in model.hf_device_map.values()})
    result["load_seconds"] = round(time.time() - t0, 1)
    result["devices_used"] = devices
    assert all(d in ("0", "1") for d in devices), "parts of the model were placed off-GPU: " + str(devices)
    t1 = time.time()
    model = PeftModel.from_pretrained(model, ADAPTER).merge_and_unload()
    model.eval()
    result["merge_seconds"] = round(time.time() - t1, 1)
    result["params_dtype"] = str(next(model.parameters()).dtype)
    result["ok_load"] = True
except Exception as e:
    result["ok_load"] = False
    result["error"] = repr(e)[:800]
    print("LOAD FAILED:", result["error"])
print({k: v for k, v in result.items() if k != "versions"})
""")

code("""
if result["ok_load"]:
    test = [json.loads(l) for l in open(find("test.jsonl"), encoding="utf-8") if l.strip()]
    item = test[0]
    text = tokenizer.apply_chat_template(item["messages"][:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    enc = tokenizer(text, return_tensors="pt").to(model.device)
    for i in range(len(gpus)):
        torch.cuda.reset_peak_memory_stats(i)
    with torch.no_grad():
        t2 = time.time()
        first = model.generate(**enc, max_new_tokens=1, do_sample=False)
        torch.cuda.synchronize()
        ttft = time.time() - t2
        t3 = time.time()
        out = model.generate(**enc, max_new_tokens=200, do_sample=False, repetition_penalty=1.05, pad_token_id=tokenizer.eos_token_id)
        torch.cuda.synchronize()
        gen_s = time.time() - t3
    new = out[0][enc["input_ids"].shape[1]:]
    answer = tokenizer.decode(new, skip_special_tokens=True)
    result.update({
        "test_id": item["id"], "prompt_tokens": int(enc["input_ids"].shape[1]), "new_tokens": int(len(new)),
        "time_to_first_token_s": round(ttft, 2), "generate_200_s": round(gen_s, 1),
        "tokens_per_s": round(len(new) / gen_s, 2),
        "peak_gib_per_gpu": [round(torch.cuda.max_memory_allocated(i) / 2**30, 2) for i in range(len(gpus))],
        "reserved_gib_per_gpu": [round(torch.cuda.max_memory_reserved(i) / 2**30, 2) for i in range(len(gpus))],
        "answer_head": answer[:600],
        "answer_looks_valid": len(answer.split()) > 30 and "<|im_start|>" not in answer,
    })
    print(answer[:800])
result["verdict"] = "PASS" if result.get("ok_load") and result.get("answer_looks_valid") else "FAIL"
json.dump(result, open("/kaggle/working/twogpu_smoke.json", "w"), indent=2)
print(json.dumps({k: v for k, v in result.items() if k not in ("versions", "answer_head")}, indent=2))
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
for c in cells:
    if c["cell_type"] == "code":
        compile("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")), "cell", "exec")
path = pathlib.Path(__file__).with_name("twogpu_smoke.ipynb")
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", path, "- all code cells compile")
